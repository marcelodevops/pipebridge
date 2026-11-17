"""Tokenizer for the limited Jenkins declarative pipeline grammar.

Produces tokens with 1-based line and column tracking. Braces, comments,
and Groovy escapes inside string literals never produce structural tokens,
so the parser cannot be confused by them.

A ``NEWLINE`` token is emitted for every line break so the parser can
separate successive step statements.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LexError

IDENT = "IDENT"
STRING_SQ = "STRING_SQ"  # '…'
STRING_DQ = "STRING_DQ"  # "…"
STRING_TS = "STRING_TS"  # '''…'''
STRING_TD = "STRING_TD"  # """…"""
NUMBER = "NUMBER"
LBRACE = "LBRACE"
RBRACE = "RBRACE"
LPAREN = "LPAREN"
RPAREN = "RPAREN"
LBRACKET = "LBRACKET"
RBRACKET = "RBRACKET"
COMMA = "COMMA"
DOT = "DOT"
EQUALS = "EQUALS"
COLON = "COLON"
SEMI = "SEMI"
NEWLINE = "NEWLINE"
ANNOTATION = "ANNOTATION"
OTHER = "OTHER"
EOF = "EOF"

PUNCT = {
    "{": LBRACE,
    "}": RBRACE,
    "(": LPAREN,
    ")": RPAREN,
    "[": LBRACKET,
    "]": RBRACKET,
    ",": COMMA,
    ".": DOT,
    "=": EQUALS,
    ":": COLON,
    ";": SEMI,
}

_SINGLE_CHAR_ESCAPES = ("\\", "'")


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    col: int


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_"


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    line = 1
    col = 1
    n = len(source)

    def advance_over(text: str) -> None:
        nonlocal pos, line, col
        for ch in text:
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1
        pos += len(text)

    def emit(kind: str, value: str, tok_line: int, tok_col: int) -> None:
        tokens.append(Token(kind, value, tok_line, tok_col))

    # Tolerate a Jenkinsfile shebang line (including its newline).
    if source.startswith("#!"):
        nl = source.find("\n", pos)
        if nl == -1:
            nl = n
        else:
            nl += 1
        advance_over(source[pos:nl])

    while pos < n:
        ch = source[pos]

        if ch == "\n":
            tok_line, tok_col = line, col
            emit(NEWLINE, "\n", tok_line, tok_col)
            advance_over(ch)
            continue

        if ch in (" ", "\t", "\r"):
            advance_over(ch)
            continue

        if source.startswith("//", pos):
            end = source.find("\n", pos)
            if end == -1:
                end = n
            advance_over(source[pos:end])
            continue

        if source.startswith("/*", pos):
            end = source.find("*/", pos + 2)
            if end == -1:
                raise LexError("unterminated block comment", line, col)
            tok_line, tok_col = line, col
            advance_over(source[pos : end + 2])
            continue

        tok_line, tok_col = line, col

        if source.startswith("'''", pos):
            raw = _scan_string(source, pos, "'''", _SINGLE_CHAR_ESCAPES, line, col)
            emit(STRING_TS, raw, tok_line, tok_col)
            advance_over(raw)
            continue

        if source.startswith('"""', pos):
            raw = _scan_string(source, pos, '"""', None, line, col)
            emit(STRING_TD, raw, tok_line, tok_col)
            advance_over(raw)
            continue

        if ch == "'":
            raw = _scan_string(source, pos, "'", _SINGLE_CHAR_ESCAPES, line, col)
            emit(STRING_SQ, raw, tok_line, tok_col)
            advance_over(raw)
            continue

        if ch == '"':
            raw = _scan_string(source, pos, '"', None, line, col)
            emit(STRING_DQ, raw, tok_line, tok_col)
            advance_over(raw)
            continue

        if ch == "@" and pos + 1 < n and _is_ident_start(source[pos + 1]):
            end = pos + 1
            while end < n and _is_ident_char(source[end]):
                end += 1
            emit(ANNOTATION, source[pos:end], tok_line, tok_col)
            advance_over(source[pos:end])
            continue

        if _is_ident_start(ch):
            end = pos
            while end < n and _is_ident_char(source[end]):
                end += 1
            emit(IDENT, source[pos:end], tok_line, tok_col)
            advance_over(source[pos:end])
            continue

        if ch.isdigit():
            end = pos
            while end < n and (source[end].isalnum() or source[end] == "."):
                end += 1
            emit(NUMBER, source[pos:end], tok_line, tok_col)
            advance_over(source[pos:end])
            continue

        if ch in PUNCT:
            emit(PUNCT[ch], ch, tok_line, tok_col)
            advance_over(ch)
            continue

        emit(OTHER, ch, tok_line, tok_col)
        advance_over(ch)

    tokens.append(Token(EOF, "", line, col))
    return tokens


def _scan_string(
    source: str,
    start: int,
    delimiter: str,
    escape_chars: tuple[str, ...] | None,
    line: int,
    col: int,
) -> str:
    """Return the raw text of a string literal starting at ``start``.

    ``escape_chars`` restricts which characters a backslash may escape
    (Groovy single-quote family); ``None`` means all escapes are consumed
    (Groovy double-quote family). Raises :class:`LexError` when the string
    is never closed.
    """
    triple = len(delimiter) == 3
    pos = start + len(delimiter)
    n = len(source)
    while pos < n:
        ch = source[pos]
        if ch == "\\":
            if escape_chars is None:
                if pos + 1 >= n:
                    raise LexError("unterminated string", line, col)
                pos += 2
            else:
                # Only \\ and \' are escapes in single-quote family strings.
                if pos + 1 < n and source[pos + 1] in escape_chars:
                    pos += 2
                else:
                    pos += 1
            continue
        if source.startswith(delimiter, pos):
            return source[start : pos + len(delimiter)]
        if ch == "\n" and not triple:
            raise LexError(
                "unterminated string (use a triple-quoted string for multiline values)",
                line,
                col,
            )
        pos += 1
    raise LexError("unterminated string", line, col)
