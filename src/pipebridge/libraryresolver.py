"""Resolve and parse a bounded subset of vars/*.groovy shared-library files.

This module never executes Groovy, fetches repositories, or reads secrets.
It reads only reached files, after containment and regular-file checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PipebridgeError
from .findings import (
    PB_LIB_CALL,
    PB_LIB_MAP_UNUSED,
    PB_SYNTAX,
    Finding,
)
from .lexer import (
    COLON,
    COMMA,
    DOT,
    EQUALS,
    EOF,
    IDENT,
    LBRACE,
    LPAREN,
    NEWLINE,
    RBRACE,
    RPAREN,
    SEMI,
    STRING_DQ,
    STRING_SQ,
    Token,
    tokenize,
)
from .librarymap import LibraryMap
from .model import Span

VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

BUILTIN_STEPS = {"sh", "echo", "checkout", "withCredentials", "stash", "unstash"}


class LibraryParseError(PipebridgeError):
    """A reached vars file escapes containment or cannot be read."""


@dataclass(frozen=True)
class Parameter:
    name: str
    span: Span


@dataclass(frozen=True)
class Definition:
    name: str
    params: tuple[Parameter, ...]
    span: Span


@dataclass
class LibraryVar:
    name: str
    path: Path
    definitions: list[Definition] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def call(self) -> Definition | None:
        for d in self.definitions:
            if d.name == "call":
                return d
        return None


@dataclass(frozen=True)
class DiscoveredVar:
    library: str
    name: str
    path: Path


def _finding(code, message, line, col, severity="blocker", construct="shared library"):
    return Finding(
        code=code,
        severity=severity,
        construct=construct,
        message=message,
        line=line,
        col=col,
        suggestion="Inline the library steps or provide a supported local library.",
    )


def discover_vars(library_map: LibraryMap) -> tuple[list[DiscoveredVar], list[Finding]]:
    """Deterministically discover vars/<name>.groovy across loaded libraries."""
    discovered: list[DiscoveredVar] = []
    findings: list[Finding] = []
    seen: dict[str, list[Path]] = {}

    for lib_name, entry in sorted(library_map.entries.items()):
        vars_dir = entry.root / "vars"
        if not vars_dir.is_dir():
            continue
        for path in sorted(vars_dir.iterdir(), key=lambda p: p.name):
            if not path.is_file() or path.suffix != ".groovy":
                continue
            name = path.stem
            discovered.append(DiscoveredVar(lib_name, name, path))
            seen.setdefault(name, []).append(path)

    for name, paths in sorted(seen.items()):
        if name in BUILTIN_STEPS:
            first = paths[0]
            findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library var '{name}' shadows a built-in step.",
                    line=1,
                    col=1,
                    construct="library var",
                )
            )
            continue
        if len(paths) > 1:
            sorted_paths = sorted(str(p) for p in paths)
            findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library var '{name}' is defined in more than one loaded library: {sorted_paths[0]}, {sorted_paths[1]}.",
                    line=1,
                    col=1,
                    construct="library var",
                )
            )
    return discovered, findings


def _resolve_reached(path: Path, root: Path) -> Path:
    """Containment and regular-file check before any read."""
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise LibraryParseError(f"library file escapes the library root: {path}") from exc
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise LibraryParseError(f"library file escapes the library root: {path}")
    if not resolved.is_file():
        raise LibraryParseError(f"library file escapes the library root: {path}")
    return resolved


def _parse_params(tokens, i, depth, end_line, end_col):
    params: list[Parameter] = []
    seen: set[str] = set()
    if i < len(tokens) and tokens[i].kind == RPAREN:
        return params, i
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == IDENT and tok.value == "String":
            i += 1
            if i >= len(tokens) or tokens[i].kind != IDENT:
                break
            tok = tokens[i]
        if tok.kind != IDENT:
            break
        name = tok.value
        if name in seen:
            params.append(Parameter(name, Span(tok.line, tok.col)))
            break
        seen.add(name)
        params.append(Parameter(name, Span(tok.line, tok.col)))
        i += 1
        if i < len(tokens) and tokens[i].kind == COMMA:
            i += 1
            continue
        break
    return params, i


def _parse_definitions(tokens: list[Token], path: Path) -> tuple[list[Definition], list[Finding]]:
    definitions: list[Definition] = []
    findings: list[Finding] = []
    i = 0
    n = len(tokens)
    call_count = 0

    while i < n:
        tok = tokens[i]
        if tok.kind in (NEWLINE, EOF):
            i += 1
            continue
        if tok.kind != IDENT or tok.value != "def":
            findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library file '{path}' has unsupported top-level syntax at line {tok.line}: '{tok.value}'.",
                    tok.line,
                    tok.col,
                    construct="library definition",
                )
            )
            # skip to next newline
            while i < n and tokens[i].kind != NEWLINE:
                i += 1
            continue
        def_line, def_col = tok.line, tok.col
        i += 1
        if i >= n or tokens[i].kind != IDENT:
            findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library file '{path}' is malformed: expected a definition name.",
                    def_line,
                    def_col,
                )
            )
            continue
        name_tok = tokens[i]
        name = name_tok.value
        if VAR_NAME_RE.fullmatch(name) is None:
            findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library file '{path}' is malformed: invalid definition name '{name}'.",
                    name_tok.line,
                    name_tok.col,
                )
            )
            i += 1
            continue
        i += 1
        if i >= n or tokens[i].kind != LPAREN:
            findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library file '{path}' is malformed: expected '(' after '{name}'.",
                    name_tok.line,
                    name_tok.col,
                )
            )
            continue
        i += 1
        params, i = _parse_params(tokens, i, 1, name_tok.line, name_tok.col)
        # find matching close paren
        while i < n and tokens[i].kind != RPAREN:
            i += 1
        if i < n:
            i += 1
        if i >= n or tokens[i].kind != LBRACE:
            findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library file '{path}' is malformed: expected '{{' to start '{name}' body.",
                    name_tok.line,
                    name_tok.col,
                )
            )
            continue
        # skip body by brace depth (token-level; braces in strings already hidden)
        depth = 0
        body_start = i
        while i < n:
            k = tokens[i].kind
            if k == LBRACE:
                depth += 1
            elif k == RBRACE:
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body_end = i
        if depth != 0:
            findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library file '{path}' is malformed: unterminated body for '{name}'.",
                    name_tok.line,
                    name_tok.col,
                )
            )
            break
        # duplicate parameter names
        names = [p.name for p in params]
        dup = next((x for x in set(names) if names.count(x) > 1), None)
        if dup is not None:
            findings.append(
                _finding(
                    PB_LIB_CALL,
                    f"Library file '{path}' definition '{name}' has duplicate parameter '{dup}'.",
                    name_tok.line,
                    name_tok.col,
                )
            )
        defn = Definition(name=name, params=tuple(params), span=Span(name_tok.line, name_tok.col))
        definitions.append(defn)
        if name == "call":
            call_count += 1
        i = body_end + 1

    if call_count == 0:
        findings.append(
            _finding(
                PB_LIB_CALL,
                f"Library file '{path}' has no call().",
                1,
                1,
                construct="library definition",
            )
        )
    elif call_count > 1:
        findings.append(
            _finding(
                PB_LIB_CALL,
                f"Library file '{path}' has more than one call().",
                1,
                1,
                construct="library definition",
            )
        )
    return definitions, findings


def load_var(path: Path, root: Path, name: str | None = None) -> LibraryVar:
    resolved = _resolve_reached(path, root)
    var = LibraryVar(name=name or resolved.stem, path=resolved)
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        var.findings.append(
            _finding(
                PB_LIB_CALL,
                f"Library file '{resolved}' cannot be read: {exc}",
                1,
                1,
                construct="library file",
            )
        )
        return var
    tokens = tokenize(text)
    defs, findings = _parse_definitions(tokens, resolved)
    var.definitions = defs
    var.findings = findings
    return var


def unused_library_findings(library_map: LibraryMap, resolved_names: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for name in sorted(library_map.entries.keys()):
        if name not in resolved_names:
            findings.append(
                _finding(
                    PB_LIB_MAP_UNUSED,
                    f"Library '{name}' was not declared by any resolved @Library annotation.",
                    1,
                    1,
                    severity="info",
                    construct="library map",
                )
            )
    return findings
