"""Static parsing and resolution of supported shared-library function bodies.

This module never executes Groovy or generated shell. It expands calls
depth-first in source order and returns structured operations plus
findings with source paths and call chains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .findings import PB_INTERP, PB_LIB_CALL, Finding
from .groovystrings import decode_string
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
from .libraryresolver import Definition, LibraryVar, load_var
from .model import Span

LIBRARY_CALL_DEPTH_CAP = 20

STRING_KINDS = (STRING_SQ, STRING_DQ, STRING_TS, STRING_TD)


class LibraryResolutionError(Exception):
    """Containment or read failure for a reached file (tool error, exit 1)."""


@dataclass(frozen=True)
class Operation:
    kind: str
    text: str | None = None
    args: tuple[str, ...] = ()
    bindings: dict[str, str] = field(default_factory=dict)
    span: Span | None = None
    path: Path | None = None
    pending: bool = False


@dataclass
class Resolution:
    operations: list[Operation] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    blocked: bool = False


def _finding(code, message, line, col, severity="blocker", construct="library body"):
    return Finding(
        code=code,
        severity=severity,
        construct=construct,
        message=message,
        line=line,
        col=col,
        suggestion="Inline the library steps or provide a supported local library.",
    )


class Resolver:
    def __init__(self, library_map: LibraryMap):
        self.map = library_map
        self.vars: dict[Path, LibraryVar] = {}

    def _var_for_name(self, name: str) -> LibraryVar | None:
        for entry in self.map.entries.values():
            path = entry.root / "vars" / f"{name}.groovy"
            if path.exists():
                try:
                    return self._load(path, entry.root)
                except LibraryResolutionError:
                    raise
        return None

    def _load(self, path: Path, root: Path) -> LibraryVar:
        try:
            var = load_var(path, root)
        except Exception as exc:  # containment/read tool error
            raise LibraryResolutionError(str(exc)) from exc
        self.vars[var.path] = var
        return var

    def resolve(self, lib_name: str, var_name: str, args: list[str]) -> Resolution:
        entry = self.map.entries.get(lib_name)
        if entry is None:
            return Resolution(blocked=True, findings=[_finding(PB_LIB_CALL, f"Library '{lib_name}' is not in the library map.", 1, 1)])
        path = entry.root / "vars" / f"{var_name}.groovy"
        try:
            var = self._load(path, entry.root)
        except LibraryResolutionError as exc:
            return Resolution(blocked=True, findings=[_finding(PB_LIB_CALL, f"Library file '{path}' cannot be read: {exc}", 1, 1)])
        res = Resolution()
        for f in var.findings:
            res.findings.append(f)
            if f.is_blocker:
                res.blocked = True
        call = var.call
        if call is None:
            if not res.blocked:
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library file '{path}' has no call().", 1, 1))
            return res
        if len(args) != len(call.params):
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"Library call '{var_name}' passed {len(args)} argument(s); call() requires {len(call.params)}.", call.span.line, call.span.col))
            return res
        self._expand(var, call, args, [], res)
        return res

    def _expand(self, var, defn, arg_values, stack, res):
        if len(stack) >= LIBRARY_CALL_DEPTH_CAP:
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"Library call depth exceeded {LIBRARY_CALL_DEPTH_CAP} at '{defn.name}'.", defn.span.line, defn.span.col))
            return
        for (p, d) in stack:
            if p == var.path and d.name == defn.name:
                chain = " -> ".join([d.name for _, d in stack] + [defn.name])
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call cycle: {chain}.", defn.span.line, defn.span.col))
                return
        params = {p.name: v for p, v in zip(defn.params, arg_values)}
        self._expand_body(var, defn, params, stack + [(var.path, defn)], res)

    def _arg_value(self, tok, params):
        if tok.kind in STRING_KINDS:
            dec = decode_string(tok.value, tok.kind, tok.line, tok.col)
            if dec.value is None:
                return None
            return dec.value
        if tok.kind == IDENT and tok.value in params:
            return params[tok.value]
        return None

    def _expand_body(self, var, defn, params, stack, res):
        body = defn.body
        for stmt in _split_statements(body):
            if not stmt:
                continue
            first = stmt[0]
            if first.kind == IDENT and first.value in ("sh", "echo"):
                self._do_sh_echo(first.value, stmt, params, res)
            elif first.kind == IDENT and first.value == "withCredentials":
                res.operations.append(Operation(kind="with-credentials", span=Span(first.line, first.col), path=var.path, pending=True))
            elif first.kind == IDENT and first.value == "stash":
                res.operations.append(Operation(kind="stash", span=Span(first.line, first.col), path=var.path, pending=True))
            elif first.kind == IDENT and first.value == "unstash":
                res.operations.append(Operation(kind="unstash", span=Span(first.line, first.col), path=var.path, pending=True))
            elif first.kind == IDENT and len(stmt) >= 2 and stmt[1].kind == LPAREN:
                self._do_invocation(first, stmt, var, defn, params, stack, res)
            else:
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Unsupported library statement at line {first.line}: '{first.value}'.", first.line, first.col))

    def _do_sh_echo(self, which, stmt, params, res):
        # Forms: sh 'cmd' | sh "cmd" | sh('cmd') | sh("cmd")
        tok = stmt[0]
        idx = 1
        if idx < len(stmt) and stmt[idx].kind == LPAREN:
            idx += 1
        if idx >= len(stmt) or stmt[idx].kind not in STRING_KINDS:
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"{which} requires a string argument in the supported subset.", tok.line, tok.col))
            return
        dec = decode_string(stmt[idx].value, stmt[idx].kind, stmt[idx].line, stmt[idx].col)
        bindings: dict[str, str] = {}
        if dec.has_interpolation:
            for interp in dec.interpolations:
                raw = interp.text.strip()
                if raw.startswith("${") and raw.endswith("}"):
                    raw = raw[2:-1].strip()
                name = raw.lstrip("$").strip()
                if name not in params:
                    res.blocked = True
                    res.findings.append(_finding(PB_INTERP, f"Unsupported interpolation in library {which}: '{interp.text}'.", interp.line, interp.col))
                    return
                bindings[name] = params[name]
        res.operations.append(Operation(kind=which, text=dec.value if dec.value is not None else stmt[idx].value, bindings=bindings, span=Span(tok.line, tok.col)))

    def _do_invocation(self, name_tok, stmt, var, defn, params, stack, res):
        args = []
        idx = 2
        # parse args separated by commas until matching RPAREN
        while idx < len(stmt) and stmt[idx].kind != RPAREN:
            tok = stmt[idx]
            val = self._arg_value(tok, params)
            if val is None:
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' argument is not a literal string or in-scope parameter.", tok.line, tok.col))
                return
            args.append(val)
            idx += 1
            if idx < len(stmt) and stmt[idx].kind == COMMA:
                idx += 1
        # helper in same file?
        helper = next((d for d in var.definitions if d.name == name_tok.value), None)
        var_for_name = self._var_for_name(name_tok.value)
        if helper is not None and var_for_name is not None:
            res.blocked = True
            res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' is ambiguous: a helper and a vars file both define it.", name_tok.line, name_tok.col))
            return
        if helper is not None:
            if len(args) != len(helper.params):
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' passed {len(args)} argument(s); requires {len(helper.params)}.", name_tok.line, name_tok.col))
                return
            self._expand(var, helper, args, stack, res)
            return
        if var_for_name is not None:
            call = var_for_name.call
            if call is None:
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library file '{var_for_name.path}' has no call().", name_tok.line, name_tok.col))
                return
            if len(args) != len(call.params):
                res.blocked = True
                res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' passed {len(args)} argument(s); call() requires {len(call.params)}.", name_tok.line, name_tok.col))
                return
            self._expand(var_for_name, call, args, stack, res)
            return
        res.blocked = True
        res.findings.append(_finding(PB_LIB_CALL, f"Library call '{name_tok.value}' has no definition.", name_tok.line, name_tok.col))


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
