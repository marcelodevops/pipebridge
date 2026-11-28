"""Static parsing and resolution of supported shared-library function bodies.

This module never executes Groovy or generated shell. It expands calls
depth-first in source order and returns structured operations plus
findings with source paths and call chains.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .credentials import match_credential_header
from .errors import PipebridgeError
from .findings import PB_CRED, PB_INTERP, PB_LIB_CALL, Finding
from .groovystrings import decode_string, decode_template_parts
from .lexer import (
    COMMA,
    IDENT,
    LBRACE,
    LPAREN,
    NEWLINE,
    RPAREN,
    RBRACE,
    SEMI,
    STRING_DQ,
    STRING_SQ,
    STRING_TD,
    STRING_TS,
    Token,
)
from .librarymap import LibraryMap
from .libraryresolver import (
    DiscoveredVar,
    Definition,
    LibraryVar,
    discover_vars,
    load_var,
)
from .model import STATUS_PENDING, STATUS_UNSUPPORTED, Span
from .stash import parse_stash_tokens, parse_unstash_tokens

LIBRARY_CALL_DEPTH_CAP = 20

STRING_KINDS = (STRING_SQ, STRING_DQ, STRING_TS, STRING_TD)


class LibraryResolutionError(PipebridgeError):
    """Containment or read failure for a reached file (tool error, exit 1)."""


@dataclass(frozen=True)
class LibraryCredential:
    binding_type: str
    credential_id: str | None
    variable: str | None
    status: str
    reason: str | None
    span: Span
    source_path: str
    call_chain: tuple[str, ...] = ()


@dataclass(frozen=True)
class Operation:
    kind: str
    text: str | None = None
    args: tuple[str, ...] = ()
    bindings: dict[str, str] = field(default_factory=dict)
    span: Span | None = None
    path: Path | None = None
    pending: bool = False
    call_chain: tuple[str, ...] = ()
    library: str | None = None
    var_name: str | None = None
    func_name: str | None = None
    step_index: int = 0
    credential_refs: tuple[int, ...] = ()


@dataclass
class Resolution:
    operations: list[Operation] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    credentials: list[LibraryCredential] = field(default_factory=list)
    visited_local_helpers: set[str] = field(default_factory=set)
    blocked: bool = False
    pending: bool = False

    @property
    def executable(self) -> bool:
        return not self.blocked and not self.pending


def _finding(code, message, line, col, severity="blocker", construct="library body", path=None, chain=()):
    return Finding(
        code=code,
        severity=severity,
        construct=construct,
        message=message,
        line=line,
        col=col,
        suggestion="Inline the library steps or provide a supported local library.",
        source_path=str(path) if path is not None else None,
        call_chain=chain,
    )


def _label(path: Path, defn: Definition) -> str:
    return f"{path}:{defn.name}@{defn.span.line}:{defn.span.col}"


def _frame(caller_path: Path | None, line: int, col: int, name: str) -> str:
    base = str(caller_path) if caller_path is not None else "<root>"
    return f"{base}:{name}@{line}:{col}"


class Resolver:
    def __init__(
        self,
        library_map: LibraryMap | None = None,
        discovered: list[DiscoveredVar] | None = None,
        local_var: LibraryVar | None = None,
    ):
        self.map = library_map if library_map is not None else LibraryMap(entries={})
        self.discovered = (
            discovered
            if discovered is not None
            else (discover_vars(self.map)[0] if library_map is not None else [])
        )
        self.by_name: dict[str, list[DiscoveredVar]] = {}
        for d in self.discovered:
            self.by_name.setdefault(d.name, []).append(d)
        self.vars: dict[Path, LibraryVar] = {}
        self.local_var = local_var

    def _candidates(self, name: str) -> list[DiscoveredVar]:
        return self.by_name.get(name, [])

    def _load(self, path: Path, root: Path) -> LibraryVar:
        # Containment/read failures must stay tool errors (LibraryResolutionError).
        try:
            var = load_var(path, root)
        except LibraryResolutionError:
            raise
        except Exception as exc:
            raise LibraryResolutionError(str(exc)) from exc
        self.vars[var.path] = var
        return var

    def resolve(self, lib_name: str, var_name: str, args: list[str], caller=None) -> Resolution:
        root_frame = _frame(*(caller if caller is not None else (None, 1, 1, var_name)))
        all_candidates = self._candidates(var_name)
        if len(all_candidates) > 1:
            paths = sorted(str(d.path) for d in all_candidates)
            return Resolution(blocked=True, findings=[_finding(PB_LIB_CALL, f"Library var '{var_name}' is defined in more than one loaded library: {paths[0]}, {paths[1]}.", 1, 1, path=all_candidates[0].path, chain=(root_frame,))])
        candidates = [d for d in all_candidates if d.library == lib_name]
        if not candidates:
            return Resolution(blocked=True, findings=[_finding(PB_LIB_CALL, f"Library '{lib_name}' has no vars/{var_name}.groovy.", 1, 1, chain=(root_frame,))])
        if len(candidates) > 1:
            paths = sorted(str(d.path) for d in candidates)
            return Resolution(blocked=True, findings=[_finding(PB_LIB_CALL, f"Library var '{var_name}' is defined in more than one loaded library: {paths[0]}, {paths[1]}.", 1, 1, path=all_candidates[0].path, chain=(root_frame,))])
        disc = candidates[0]
        var = self._load(disc.path, self.map.entries[disc.library].root)  # may raise LibraryResolutionError
        res = Resolution()
        self._merge_findings(var, res, (root_frame,))
        if res.blocked:
            res.operations = []
            return res
        call = var.call
        if call is None:
            res.blocked = True
            res.operations = []
            res.findings.append(_finding(PB_LIB_CALL, f"Library file '{var.path}' has no call().", 1, 1, path=var.path, chain=(root_frame, f"{var.path}:call@1:1")))
            return res
        if len(args) != len(call.params):
            res.blocked = True
            res.operations = []
            res.findings.append(_finding(PB_LIB_CALL, f"Library call '{var_name}' passed {len(args)} argument(s); call() requires {len(call.params)}.", call.span.line, call.span.col, path=var.path, chain=(root_frame, _label(var.path, call))))
            return res
        self._expand(var, call, args, [], (root_frame,), res, lib_name=disc.library)
        if res.blocked:
            res.operations = []
        return res

    def resolve_local(self, helper_name: str, args: list[str], caller=None) -> Resolution:
        """Resolve a Jenkinsfile postlude helper call."""
        root_frame = _frame(*(caller if caller is not None else (None, 1, 1, helper_name)))
        res = Resolution(visited_local_helpers={helper_name})
        if self.local_var is None:
            res.blocked = True
            res.findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Postlude helper '{helper_name}' has no definition.",
                    1,
                    1,
                    chain=(root_frame,),
                )
            )
            return res
        defn = next((d for d in self.local_var.definitions if d.name == helper_name), None)
        if defn is None:
            res.blocked = True
            res.findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Postlude helper '{helper_name}' has no definition.",
                    1,
                    1,
                    path=self.local_var.path,
                    chain=(root_frame,),
                )
            )
            return res
        if len(args) != len(defn.params):
            res.blocked = True
            res.operations = []
            res.findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library call '{helper_name}' passed {len(args)} argument(s); {helper_name}() requires {len(defn.params)}.",
                    defn.span.line,
                    defn.span.col,
                    path=self.local_var.path,
                    chain=(root_frame, _label(self.local_var.path, defn)),
                )
            )
            return res
        self._expand(self.local_var, defn, args, [], (root_frame,), res, lib_name=None)
        if res.blocked:
            res.operations = []
        return res

    def _merge_findings(self, var: LibraryVar, res: Resolution, frames=()) -> None:
        for f in var.findings:
            merged = replace(f, call_chain=frames) if f.call_chain != frames else f
            res.findings.append(merged)
            if f.is_blocker:
                res.blocked = True

    def _expand(self, var, defn, arg_values, stack, frames, res, lib_name: str | None = None, cred_refs: tuple[int, ...] = ()):
        if lib_name is None:
            res.visited_local_helpers.add(defn.name)
        if len(stack) >= LIBRARY_CALL_DEPTH_CAP:
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"Library call depth exceeded {LIBRARY_CALL_DEPTH_CAP} at '{defn.name}'.", defn.span.line, defn.span.col, path=var.path, chain=frames))
            return
        for (p, d) in stack:
            if p == var.path and d.name == defn.name:
                chain = " -> ".join(frames)
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call cycle: {chain}.", defn.span.line, defn.span.col, path=var.path, chain=frames))
                return
        params = {p.name: v for p, v in zip(defn.params, arg_values)}
        self._expand_body(var, defn, params, stack + [(var.path, defn)], res, frames, lib_name=lib_name, cred_refs=cred_refs)

    def _arg_value(self, tok, params):
        if tok.kind in STRING_KINDS:
            dec = decode_string(tok.value, tok.kind, tok.line, tok.col)
            if dec.value is None:
                return None
            return dec.value
        if tok.kind == IDENT and tok.value in params:
            return params[tok.value]
        return None

    def _expand_body(self, var, defn, params, stack, res, chain, lib_name: str | None = None, cred_refs: tuple[int, ...] = ()):
        self._expand_statements(
            defn.body, var, defn, params, stack, res, chain, lib_name, 0, cred_refs
        )

    def _expand_statements(
        self,
        tokens,
        var,
        defn,
        params,
        stack,
        res,
        chain,
        lib_name: str | None,
        step_counter: int,
        cred_refs: tuple[int, ...],
    ) -> int:
        for stmt in _split_statements(tokens):
            if not stmt:
                continue
            first = stmt[0]
            if first.kind == IDENT and first.value in ("sh", "echo"):
                step_counter = self._do_sh_echo(
                    first.value, stmt, params, res, var, defn, chain, lib_name, step_counter, cred_refs
                )
            elif first.kind == IDENT and first.value == "withCredentials":
                step_counter = self._do_with_credentials(
                    stmt, var, defn, params, stack, res, chain, lib_name, step_counter, cred_refs
                )
            elif first.kind == IDENT and first.value == "stash":
                parsed_stash, next_pos, err = parse_stash_tokens(stmt, 1)
                if err is not None or parsed_stash is None:
                    res.blocked = True
                    res.findings.append(_finding(PB_LIB_CALL, err or "Invalid stash statement.", first.line, first.col, construct="stash step", path=var.path, chain=chain))
                elif next_pos != len(stmt):
                    res.blocked = True
                    res.findings.append(_finding(PB_LIB_CALL, "stash has unsupported trailing tokens.", stmt[next_pos].line, stmt[next_pos].col, construct="stash step", path=var.path, chain=chain))
                else:
                    s_name, s_inc, s_exc = parsed_stash
                    s_args = (s_inc, s_exc) if s_exc is not None else (s_inc,)
                    res.operations.append(Operation(kind="stash", text=s_name, args=s_args, span=Span(first.line, first.col), path=var.path, pending=False, call_chain=chain, library=lib_name, var_name=var.name, func_name=defn.name, credential_refs=cred_refs))
            elif first.kind == IDENT and first.value == "unstash":
                u_name, next_pos, err = parse_unstash_tokens(stmt, 1)
                if err is not None or u_name is None:
                    res.blocked = True
                    res.findings.append(_finding(PB_LIB_CALL, err or "Invalid unstash statement.", first.line, first.col, construct="unstash step", path=var.path, chain=chain))
                elif next_pos != len(stmt):
                    res.blocked = True
                    res.findings.append(_finding(PB_LIB_CALL, "unstash has unsupported trailing tokens.", stmt[next_pos].line, stmt[next_pos].col, construct="unstash step", path=var.path, chain=chain))
                else:
                    res.operations.append(Operation(kind="unstash", text=u_name, span=Span(first.line, first.col), path=var.path, pending=False, call_chain=chain, library=lib_name, var_name=var.name, func_name=defn.name, credential_refs=cred_refs))
            elif first.kind == IDENT and len(stmt) >= 2 and stmt[1].kind == LPAREN:
                self._do_invocation(first, stmt, var, defn, params, stack, res, chain, lib_name, cred_refs)
            else:
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Unsupported library statement at line {first.line}: '{first.value}'.", first.line, first.col, path=var.path, chain=chain))
        return step_counter

    def _do_with_credentials(
        self,
        stmt,
        var,
        defn,
        params,
        stack,
        res,
        chain,
        lib_name: str | None,
        step_counter: int,
        cred_refs: tuple[int, ...],
    ) -> int:
        first = stmt[0]
        if cred_refs:
            res.blocked = True
            res.findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Nested withCredentials is not supported in '{var.path}'.",
                    first.line,
                    first.col,
                    construct="withCredentials binding",
                    path=var.path,
                    chain=chain,
                )
            )
            return step_counter

        header = match_credential_header(stmt, 1)
        if not header.accepted or header.body_pos is None or header.variable is None:
            res.credentials.append(
                LibraryCredential(
                    binding_type=header.binding_type,
                    credential_id=None,
                    variable=None,
                    status=STATUS_UNSUPPORTED,
                    reason=header.reason,
                    span=Span(first.line, first.col),
                    source_path=str(var.path),
                    call_chain=chain,
                )
            )
            res.blocked = True
            res.findings.append(
                _finding(
                    PB_CRED,
                    f"Library '{var.name}' binds credentials; {header.reason}.",
                    first.line,
                    first.col,
                    construct="withCredentials binding",
                    path=var.path,
                    chain=chain,
                )
            )
            return step_counter

        # Locate matching '}' for header.body_pos.
        depth = 0
        body_end = None
        for idx in range(header.body_pos, len(stmt)):
            k = stmt[idx].kind
            if k == LBRACE:
                depth += 1
            elif k == RBRACE:
                depth -= 1
                if depth == 0:
                    body_end = idx
                    break
        if body_end is None or body_end + 1 != len(stmt):
            reason = "withCredentials body is unterminated" if body_end is None else "withCredentials has unsupported trailing tokens"
            res.credentials.append(
                LibraryCredential(
                    binding_type=header.binding_type,
                    credential_id=header.credential_id,
                    variable=header.variable,
                    status=STATUS_UNSUPPORTED,
                    reason=reason,
                    span=Span(first.line, first.col),
                    source_path=str(var.path),
                    call_chain=chain,
                )
            )
            res.blocked = True
            res.findings.append(
                _finding(
                    PB_CRED,
                    f"Library '{var.name}' binds credentials; {reason}.",
                    first.line,
                    first.col,
                    construct="withCredentials binding",
                    path=var.path,
                    chain=chain,
                )
            )
            return step_counter

        body_tokens = stmt[header.body_pos + 1 : body_end]
        if not _split_statements(body_tokens):
            res.credentials.append(
                LibraryCredential(
                    binding_type="string",
                    credential_id=header.credential_id,
                    variable=header.variable,
                    status=STATUS_UNSUPPORTED,
                    reason="body is empty",
                    span=Span(first.line, first.col),
                    source_path=str(var.path),
                    call_chain=chain,
                )
            )
            res.blocked = True
            res.findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"withCredentials body in '{var.path}' is empty.",
                    first.line,
                    first.col,
                    construct="withCredentials binding",
                    path=var.path,
                    chain=chain,
                )
            )
            return step_counter

        cred_idx = len(res.credentials)
        res.credentials.append(
            LibraryCredential(
                binding_type="string",
                credential_id=header.credential_id,
                variable=header.variable,
                status=STATUS_PENDING,
                reason=None,
                span=Span(first.line, first.col),
                source_path=str(var.path),
                call_chain=chain,
            )
        )
        return self._expand_statements(
            body_tokens,
            var,
            defn,
            params,
            stack,
            res,
            chain,
            lib_name,
            step_counter,
            (cred_idx,),
        )

    def _do_sh_echo(self, which, stmt, params, res, var, defn, chain, lib_name: str | None, step_counter: int, cred_refs: tuple[int, ...] = ()) -> int:
        path = var.path
        tok = stmt[0]
        idx = 1
        paren = False
        if idx < len(stmt) and stmt[idx].kind == LPAREN:
            paren = True
            idx += 1
        if idx >= len(stmt) or (
            stmt[idx].kind not in STRING_KINDS
            and not (stmt[idx].kind == IDENT and stmt[idx].value in params)
        ):
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"{which} requires a string argument in the supported subset.", tok.line, tok.col, path=path, chain=chain))
            return step_counter
        arg_tok = stmt[idx]
        if paren:
            idx += 1
            if idx >= len(stmt) or stmt[idx].kind != RPAREN:
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"{which} requires a closing ')' in the supported subset.", tok.line, tok.col, path=path, chain=chain))
                return step_counter
            idx += 1
        else:
            idx += 1
        if idx != len(stmt):
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"{which} has unsupported trailing tokens in the supported subset.", tok.line, tok.col, path=path, chain=chain))
            return step_counter

        if arg_tok.kind == IDENT:
            param_name = arg_tok.value
            arg_values = (params[param_name],)
            bindings = {param_name: params[param_name]}
            step_counter += 1
            if which == "echo":
                script_text = 'printf \'%s\\n\' "${1}"'
            else:
                # Execute parameter-supplied shell text via argv; assumes bash -eo pipefail.
                script_text = (
                    "# Parameter-supplied shell command passed via argv (assumes bash -eo pipefail).\n"
                    'bash --noprofile --norc -eo pipefail -c "${1}"'
                )
            res.operations.append(
                Operation(
                    kind=which,
                    text=script_text,
                    args=arg_values,
                    bindings=bindings,
                    span=Span(tok.line, tok.col),
                    path=path,
                    call_chain=chain,
                    library=lib_name,
                    var_name=var.name,
                    func_name=defn.name,
                    step_index=step_counter,
                    credential_refs=cred_refs,
                )
            )
            return step_counter

        parts, param_order, invalid = decode_template_parts(
            arg_tok.value, arg_tok.kind, arg_tok.line, arg_tok.col, params
        )
        if parts is None:
            first_bad = invalid[0]
            res.blocked = True
            res.findings.append(_finding(PB_INTERP, f"Unsupported interpolation in library {which}: '{first_bad.text}'.", first_bad.line, first_bad.col, path=path, chain=chain))
            return step_counter

        arg_values = tuple(params[name] for name in param_order)
        bindings = {name: params[name] for name in param_order}
        if which == "sh" or param_order:
            step_counter += 1
            step_idx = step_counter
            if which == "echo":
                template = _echo_template_script(parts)
            else:
                template = "".join(
                    str(val) if tag == "lit" else f"${{{val}}}"
                    for tag, val in parts
                )
        else:
            step_idx = 0
            template = "".join(str(val) for _tag, val in parts)
        res.operations.append(
            Operation(
                kind=which,
                text=template,
                args=arg_values,
                bindings=bindings,
                span=Span(tok.line, tok.col),
                path=path,
                call_chain=chain,
                library=lib_name,
                var_name=var.name,
                func_name=defn.name,
                step_index=step_idx,
                credential_refs=cred_refs,
            )
        )
        return step_counter

    def _do_invocation(self, name_tok, stmt, var, defn, params, stack, res, chain, lib_name: str | None = None, cred_refs: tuple[int, ...] = ()):
        if lib_name is None and any(d.name == name_tok.value for d in var.definitions):
            res.visited_local_helpers.add(name_tok.value)
        chain = chain + (_frame(var.path, name_tok.line, name_tok.col, name_tok.value),)
        args = []
        idx = 2
        while True:
            if idx >= len(stmt):
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' is missing a closing ')'.", name_tok.line, name_tok.col, path=var.path, chain=chain))
                return
            if stmt[idx].kind == RPAREN:
                if args:
                    res.blocked = True
                    res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' has a trailing comma.", name_tok.line, name_tok.col, path=var.path, chain=chain))
                idx += 1
                break
            val = self._arg_value(stmt[idx], params)
            if val is None:
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' argument is not a literal string or in-scope parameter.", stmt[idx].line, stmt[idx].col, path=var.path, chain=chain))
                return
            args.append(val)
            idx += 1
            if idx >= len(stmt):
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' is missing a closing ')'.", name_tok.line, name_tok.col, path=var.path, chain=chain))
                return
            if stmt[idx].kind == COMMA:
                idx += 1
                continue
            if stmt[idx].kind == RPAREN:
                idx += 1
                break
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' is missing a comma between arguments.", stmt[idx].line, stmt[idx].col, path=var.path, chain=chain))
            return
        if idx != len(stmt):
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' has unsupported trailing tokens.", name_tok.line, name_tok.col, path=var.path, chain=chain))
            return

        helper = next((d for d in var.definitions if d.name == name_tok.value), None)
        candidates = self._candidates(name_tok.value)
        if helper is not None and candidates:
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' is ambiguous: a helper and a vars file both define it.", name_tok.line, name_tok.col, path=var.path, chain=chain))
            return
        if helper is not None:
            if len(args) != len(helper.params):
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' passed {len(args)} argument(s); requires {len(helper.params)}.", name_tok.line, name_tok.col, path=var.path, chain=chain))
                return
            self._expand(var, helper, args, stack, chain, res, lib_name=lib_name, cred_refs=cred_refs)
            return
        if candidates:
            if len(candidates) > 1:
                paths = sorted(str(d.path) for d in candidates)
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library var '{name_tok.value}' is defined in more than one loaded library: {paths[0]}, {paths[1]}.", name_tok.line, name_tok.col, path=var.path, chain=chain))
                return
            disc = candidates[0]
            nested = self._load(disc.path, self.map.entries[disc.library].root)  # may raise LibraryResolutionError
            self._merge_findings(nested, res, chain)
            if res.blocked:
                return
            call = nested.call
            if call is None:
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library file '{nested.path}' has no call().", name_tok.line, name_tok.col, path=nested.path, chain=chain))
                return
            if len(args) != len(call.params):
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' passed {len(args)} argument(s); call() requires {len(call.params)}.", name_tok.line, name_tok.col, path=var.path, chain=chain))
                return
            self._expand(nested, call, args, stack, chain, res, lib_name=disc.library, cred_refs=cred_refs)
            return
        res.blocked = True
        res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' has no definition.", name_tok.line, name_tok.col, path=var.path, chain=chain))


def _echo_template_script(parts: tuple[tuple[str, str | int], ...]) -> str:
    """Wrap structured ``('lit', str)`` / ``('param', int)`` parts in ``printf '%s\\n' "..."``."""
    out: list[str] = ['printf \'%s\\n\' "']
    for tag, val in parts:
        if tag == "param":
            out.append(f"${{{val}}}")
        else:
            for ch in str(val):
                if ch in ('\\', '"', '`', '$'):
                    out.append("\\" + ch)
                else:
                    out.append(ch)
    out.append('"')
    return "".join(out)


def _split_statements(tokens):
    stmts = []
    cur = []
    depth = 0
    for tok in tokens:
        if tok.kind in (NEWLINE, SEMI) and depth == 0:
            if cur:
                stmts.append(cur)
                cur = []
            continue
        if tok.kind in (LPAREN, LBRACE):
            depth += 1
        elif tok.kind in (RPAREN, RBRACE):
            depth = max(0, depth - 1)
        cur.append(tok)
    if cur:
        stmts.append(cur)
    return stmts
