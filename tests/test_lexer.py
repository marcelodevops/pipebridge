"""Tests for the source tokenizer: positions, strings, comments, nesting."""

import pytest

from pipebridge.errors import LexError
from pipebridge.lexer import tokenize


def kinds(source):
    return [t.kind for t in tokenize(source)]


def test_basic_pipeline_tokens_and_positions():
    source = "pipeline {\n    agent any\n}\n"
    tokens = tokenize(source)
    by_kind = {}
    for tok in tokens:
        by_kind.setdefault(tok.kind, []).append(tok)

    assert "LBRACE" in by_kind and "RBRACE" in by_kind
    # 'pipeline' starts at 1:1
    first = tokens[0]
    assert (first.kind, first.value, first.line, first.col) == ("IDENT", "pipeline", 1, 1)
    # 'agent' is on line 2, column 5
    agent = next(t for t in tokens if t.value == "agent")
    assert (agent.line, agent.col) == (2, 5)
    # '}' closes at line 3, column 1
    close = by_kind["RBRACE"][0]
    assert (close.line, close.col) == (3, 1)
    assert tokens[-1].kind == "EOF"


def test_strings_are_single_tokens():
    source = "sh 'make build'\n"
    tokens = tokenize(source)
    string_tokens = [t for t in tokens if t.kind == "STRING_SQ"]
    assert len(string_tokens) == 1
    assert string_tokens[0].value == "'make build'"
    assert (string_tokens[0].line, string_tokens[0].col) == (1, 4)


def test_braces_and_comments_inside_strings_are_not_tokens():
    source = (
        "sh 'echo \"# not a comment\" { keep braces } // still in string'\n"
        "echo 'done'\n"
    )
    tokens = tokenize(source)
    assert not any(t.kind in ("LBRACE", "RBRACE") for t in tokens)
    strings = [t for t in tokens if t.kind.startswith("STRING")]
    assert len(strings) == 2
    assert "{ keep braces } // still in string" in strings[0].value


def test_multiline_string_token_and_subsequent_position():
    source = "sh '''\nline one\nline two\n'''\necho 'next'\n"
    tokens = tokenize(source)
    triple = next(t for t in tokens if t.kind == "STRING_TS")
    assert triple.line == 1
    echo = next(t for t in tokens if t.value == "echo")
    assert (echo.line, echo.col) == (5, 1)


def test_line_comment_and_block_comment_skipped():
    source = (
        "// a line comment\n"
        "/* a block\n"
        "   comment */\n"
        "echo 'hi'\n"
    )
    tokens = tokenize(source)
    assert all(t.kind != "OTHER" or t.value not in ("a", "comment") for t in tokens)
    echo = next(t for t in tokens if t.value == "echo")
    assert (echo.line, echo.col) == (4, 1)


def test_shebang_first_line_is_skipped():
    source = "#!/usr/bin/env groovy\npipeline {\n}\n"
    tokens = tokenize(source)
    pipeline_tok = tokens[0]
    assert (pipeline_tok.kind, pipeline_tok.value, pipeline_tok.line, pipeline_tok.col) == (
        "IDENT", "pipeline", 2, 1,
    )


def test_unterminated_string_raises_with_position():
    with pytest.raises(LexError) as excinfo:
        tokenize("sh 'oops\n")
    assert excinfo.value.line == 1
    assert excinfo.value.col == 4


def test_unterminated_multiline_string_raises_with_position():
    with pytest.raises(LexError):
        tokenize("sh '''\nnever closed\n")


def test_annotation_token():
    tokens = tokenize("@Library('mylib@v1') _\npipeline {\n}\n")
    assert tokens[0].kind == "ANNOTATION"
    assert tokens[0].value == "@Library"
    assert (tokens[0].line, tokens[0].col) == (1, 1)


def test_structural_punctuation():
    tokens = tokenize("stage('A') { steps { sh 'x' } }")
    kinds_ = [t.kind for t in tokens]
    for expected in ("IDENT", "LPAREN", "STRING_SQ", "RPAREN", "LBRACE", "RBRACE"):
        assert expected in kinds_


def test_newlines_are_tokens():
    tokens = tokenize("a\nb\nc")
    newlines = [t for t in tokens if t.kind == "NEWLINE"]
    assert len(newlines) == 2


def test_column_counts_tabs_as_one_column():
    source = "\tsh 'x'"
    tokens = tokenize(source)
    sh_tok = next(t for t in tokens if t.value == "sh")
    assert sh_tok.col == 2
