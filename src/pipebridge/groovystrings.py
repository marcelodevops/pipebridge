"""Groovy string semantics for the supported subset.

Only string forms whose meaning can be preserved are decoded:

- single-quoted ``'...'`` and triple-single ``'''...'''``: literal text, no
  interpolation, only ``\\'`` and ``\\\\`` escapes;
- double-quoted ``"..."`` and triple-double (three double quotes): full
  Groovy/Java escapes, **no** Groovy interpolation (``${...}`` / ``$ident``).

Interpolated strings are flagged instead of decoded: Groovy would
substitute the expression at pipeline runtime, and pipebridge refuses to
guess at that behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_ESCAPE_MAP = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "b": "\b",
    "f": "\f",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "$": "$",
}

_DELIMITERS = {
    "STRING_SQ": ("'", "'"),
    "STRING_DQ": ('"', '"'),
    "STRING_TS": ("'''", "'''"),
    "STRING_TD": ('"""', '"""'),
}

_SINGLE_QUOTE_KINDS = ("STRING_SQ", "STRING_TS")


@dataclass(frozen=True)
class Interpolation:
    text: str
    line: int
    col: int


@dataclass(frozen=True)
class Decoded:
    raw: str
    kind: str
    value: str | None
    interpolations: list[Interpolation] = field(default_factory=list)
    # (offset_in_value, line, col) of every literal '$' that reached the
    # decoded value; used to report Jenkins variable references precisely.
    dollar_spans: list[tuple[int, int, int]] = field(default_factory=list)

    @property
    def has_interpolation(self) -> bool:
        return bool(self.interpolations)


def decode_string(raw: str, kind: str, line: int, col: int) -> Decoded:
    """Decode a raw string literal token into its runtime value.

    ``line``/``col`` are the source position of the opening quote and are
    used to report absolute positions of interpolations. When Groovy
    interpolation is present, ``value`` is ``None`` (the runtime value is
    dynamic) and ``interpolations`` lists each detected expression.
    """
    open_d, _close = _DELIMITERS[kind]
    body = raw[len(open_d) : len(raw) - len(open_d)]
    single_quote_family = kind in _SINGLE_QUOTE_KINDS

    out: list[str] = []
    interpolations: list[Interpolation] = []
    dollar_spans: list[tuple[int, int, int]] = []
    # cur_line/cur_col track the source position of the current body char;
    # the opening delimiter occupies `len(open_d)` columns after (line, col).
    cur_line, cur_col = line, col + len(open_d)
    pos = 0
    n = len(body)

    while pos < n:
        ch = body[pos]

        if ch == "\\":
            pos += 1
            if pos >= n:
                # Should not happen: the lexer guarantees closed literals.
                out.append("\\")
                break
            esc = body[pos]
            cur_col += 1
            if single_quote_family:
                if esc in ("\\", "'"):
                    out.append(esc)
                else:
                    out.append("\\" + esc)
            else:
                if esc == "u" and pos + 4 < n and _is_hex4(body[pos + 1 : pos + 5]):
                    out.append(chr(int(body[pos + 1 : pos + 5], 16)))
                    cur_col += 4
                    pos += 4
                elif esc == "\n":
                    pass  # line continuation contributes nothing
                elif esc in _ESCAPE_MAP:
                    out.append(_ESCAPE_MAP[esc])
                    if _ESCAPE_MAP[esc] == "$":
                        dollar_spans.append((len(out) - 1, cur_line, cur_col + 1))
                else:
                    out.append("\\" + esc)
            pos += 1
            cur_col += 1
            continue

        if ch == "\n":
            out.append(ch)
            pos += 1
            cur_line += 1
            cur_col = 1
            continue

        if ch == "$" and not single_quote_family:
            interp = _match_interpolation(body, pos)
            if interp is not None:
                text, end = interp
                interpolations.append(Interpolation(text, cur_line, cur_col))
                # Advance the cursor over the raw expression text.
                for c in body[pos:end]:
                    if c == "\n":
                        cur_line += 1
                        cur_col = 1
                    else:
                        cur_col += 1
                pos = end
                continue
            out.append(ch)
            pos += 1
            cur_col += 1
            continue

        out.append(ch)
        if ch == "$":
            dollar_spans.append((len(out) - 1, cur_line, cur_col))
        pos += 1
        cur_col += 1

    if interpolations:
        return Decoded(
            raw=raw, kind=kind, value=None, interpolations=interpolations, dollar_spans=dollar_spans
        )
    return Decoded(raw=raw, kind=kind, value="".join(out), dollar_spans=dollar_spans)


def decode_template_parts(
    raw: str,
    kind: str,
    line: int,
    col: int,
    allowed_params: set[str] | frozenset[str] | dict[str, str],
) -> tuple[tuple[tuple[str, str | int], ...] | None, tuple[str, ...], list[Interpolation]]:
    """Decode a Groovy string into structured ``('lit', str)`` and ``('param', int)`` parts.

    Preserves the structural distinction between literal source text (including
    escaped ``\\$``) and parameter placeholders (1-based positional index).
    """
    open_d, _close = _DELIMITERS[kind]
    body = raw[len(open_d) : len(raw) - len(open_d)]
    single_quote_family = kind in _SINGLE_QUOTE_KINDS

    parts: list[tuple[str, str | int]] = []
    lit_buf: list[str] = []
    param_order: list[str] = []
    param_index: dict[str, int] = {}
    invalid: list[Interpolation] = []
    cur_line, cur_col = line, col + len(open_d)
    pos = 0
    n = len(body)

    def flush_lit() -> None:
        if lit_buf:
            parts.append(("lit", "".join(lit_buf)))
            lit_buf.clear()

    while pos < n:
        ch = body[pos]

        if ch == "\\":
            pos += 1
            if pos >= n:
                lit_buf.append("\\")
                break
            esc = body[pos]
            cur_col += 1
            if single_quote_family:
                if esc in ("\\", "'"):
                    lit_buf.append(esc)
                else:
                    lit_buf.append("\\" + esc)
            else:
                if esc == "u" and pos + 4 < n and _is_hex4(body[pos + 1 : pos + 5]):
                    lit_buf.append(chr(int(body[pos + 1 : pos + 5], 16)))
                    cur_col += 4
                    pos += 4
                elif esc == "\n":
                    pass
                elif esc in _ESCAPE_MAP:
                    lit_buf.append(_ESCAPE_MAP[esc])
                else:
                    lit_buf.append("\\" + esc)
            pos += 1
            cur_col += 1
            continue

        if ch == "\n":
            lit_buf.append(ch)
            pos += 1
            cur_line += 1
            cur_col = 1
            continue

        if ch == "$" and not single_quote_family:
            interp = _match_interpolation(body, pos)
            if interp is not None:
                interp_text, end = interp
                if interp_text.startswith("${") and interp_text.endswith("}"):
                    name = interp_text[2:-1].strip()
                else:
                    name = interp_text[1:]
                if name not in allowed_params:
                    invalid.append(Interpolation(interp_text, cur_line, cur_col))
                else:
                    flush_lit()
                    if name not in param_index:
                        param_order.append(name)
                        param_index[name] = len(param_order)
                    parts.append(("param", param_index[name]))
                for c in body[pos:end]:
                    if c == "\n":
                        cur_line += 1
                        cur_col = 1
                    else:
                        cur_col += 1
                pos = end
                continue
            lit_buf.append(ch)
            pos += 1
            cur_col += 1
            continue

        lit_buf.append(ch)
        pos += 1
        cur_col += 1

    flush_lit()
    if invalid:
        return None, (), invalid
    return tuple(parts), tuple(param_order), []


def decode_template(
    raw: str,
    kind: str,
    line: int,
    col: int,
    allowed_params: set[str] | frozenset[str] | dict[str, str],
) -> tuple[str | None, tuple[str, ...], list[Interpolation]]:
    """Decode a Groovy string, replacing bare allowed-parameter interpolations with ``${1}``, ``${2}``, ..."""
    parts, param_order, invalid = decode_template_parts(
        raw, kind, line, col, allowed_params
    )
    if parts is None:
        return None, (), invalid
    rendered = "".join(
        str(val) if kind_tag == "lit" else f"${{{val}}}"
        for kind_tag, val in parts
    )
    return rendered, param_order, []


def _is_hex4(s: str) -> bool:
    return all(c in "0123456789abcdefABCDEF" for c in s)


def _match_interpolation(body: str, pos: int) -> tuple[str, int] | None:
    """Match ``${…}`` or ``$ident`` at ``pos``; return (text, end) or None."""
    n = len(body)
    next_ch = body[pos + 1] if pos + 1 < n else ""
    if next_ch == "{":
        depth = 1
        end = pos + 2
        while end < n and depth:
            if body[end] == "{":
                depth += 1
            elif body[end] == "}":
                depth -= 1
            end += 1
        return body[pos:end], end
    if next_ch.isalpha() or next_ch == "_":
        end = pos + 1
        while end < n and (body[end].isalnum() or body[end] == "_"):
            end += 1
        return body[pos:end], end
    return None
