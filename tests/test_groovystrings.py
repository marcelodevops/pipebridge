"""Tests for Groovy string semantics: escapes, interpolation detection."""

from pipebridge.groovystrings import decode_string


def test_single_quoted_only_two_escapes():
    d = decode_string("'a\\'b\\\\c\\nd'", "STRING_SQ", 1, 1)
    # \' -> ' ; \\ -> \ ; \n stays literal backslash+n in single quotes
    assert d.value == "a'b\\c\\nd"
    assert d.interpolations == []


def test_double_quoted_full_escapes():
    d = decode_string('"a\\nb\\tc\\"d"', "STRING_DQ", 1, 1)
    assert d.value == "a\nb\tc\"d"


def test_double_quoted_dollar_escape_suppresses_interpolation():
    d = decode_string('"\\$BUILD_DIR"', "STRING_DQ", 1, 1)
    assert d.value == "$BUILD_DIR"
    assert d.interpolations == []


def test_double_quoted_brace_interpolation_detected():
    d = decode_string('"hello ${BUILD_NUMBER}!"', "STRING_DQ", 3, 8)
    assert d.value is None  # not decodable without evaluation
    assert len(d.interpolations) == 1
    interp = d.interpolations[0]
    assert interp.text == "${BUILD_NUMBER}"
    # column of the `$` within the source line
    assert (interp.line, interp.col) == (3, 8 + 7)  # "hello " is 6 chars + opening quote


def test_double_quoted_bare_dollar_interpolation_detected():
    d = decode_string('"$var and text"', "STRING_DQ", 1, 1)
    assert d.value is None
    assert [i.text for i in d.interpolations] == ["$var"]


def test_dollar_followed_by_digit_is_not_interpolation():
    d = decode_string('"cost $5 and $10"', "STRING_DQ", 1, 1)
    assert d.value == "cost $5 and $10"
    assert d.interpolations == []


def test_single_quoted_dollar_is_literal():
    d = decode_string("'${FOO} $BAR'", "STRING_SQ", 1, 1)
    assert d.value == "${FOO} $BAR"
    assert d.interpolations == []


def test_triple_single_multiline_value():
    d = decode_string("'''line one\nline two\n'''", "STRING_TS", 1, 1)
    assert d.value == "line one\nline two\n"
    assert d.interpolations == []


def test_triple_double_multiline_with_interpolation_positions():
    raw = '"""\nmkdir ${DIR}\nls\n"""'
    d = decode_string(raw, "STRING_TD", 7, 10)
    assert d.value is None
    assert len(d.interpolations) == 1
    # `${DIR}` is on source line 8 (7 + 1), col 6 ("mkdir " is 6 chars)
    assert (d.interpolations[0].line, d.interpolations[0].col) == (8, 7)


def test_double_quoted_thirty_two_bit_unicode_escape():
    d = decode_string('"\\u0041"', "STRING_DQ", 1, 1)
    assert d.value == "A"


def test_unknown_escape_kept_verbatim_in_double_quotes():
    d = decode_string('"\\q"', "STRING_DQ", 1, 1)
    assert d.value == "\\q"
