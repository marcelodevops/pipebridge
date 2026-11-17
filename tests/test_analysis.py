"""Tests for the analysis pass: assumptions, warnings, deterministic order."""

from pipebridge import findings as F
from pipebridge.analysis import analyze_source


def codes(result):
    return [f.code for f in result.findings]


CLEAN = (
    "pipeline {\n"
    "    agent any\n"
    "    stages {\n"
    "        stage('Build') {\n"
    "            steps {\n"
    "                sh 'make build'\n"
    "            }\n"
    "        }\n"
    "    }\n"
    "}\n"
)


def test_clean_pipeline_has_assumption_findings_only():
    result = analyze_source(CLEAN)
    assert not result.has_blockers
    assert codes(result) == [
        F.PB_ASSUME_SHELL,
        F.PB_SINGLE_JOB,
        F.PB_TRIGGER_MANUAL,
        F.PB_ASSUME_RUNNER,
    ]
    runner = next(f for f in result.findings if f.code == F.PB_ASSUME_RUNNER)
    assert (runner.line, runner.col) == (2, 5)
    assert "ubuntu-latest" in runner.message
    assert "does not establish" in runner.message


def test_checkout_scm_adds_checkout_assumption():
    result = analyze_source(CLEAN.replace("sh 'make build'", "checkout scm"))
    assert F.PB_ASSUME_CHECKOUT in codes(result)
    checkout = next(f for f in result.findings if f.code == F.PB_ASSUME_CHECKOUT)
    assert (checkout.line, checkout.col) == (6, 17)


def test_jenkins_variable_reference_is_reported_once_per_variable():
    source = CLEAN.replace(
        "sh 'make build'",
        "sh 'echo $BUILD_NUMBER'\n                sh 'ls $BUILD_NUMBER $WORKSPACE'",
    )
    result = analyze_source(source)
    jenv = [f for f in result.findings if f.code == F.PB_JENV]
    assert {f.message for f in jenv} == {
        "Jenkins-specific variable 'BUILD_NUMBER' is referenced in shell text.",
        "Jenkins-specific variable 'WORKSPACE' is referenced in shell text.",
    }
    bn = next(f for f in jenv if "BUILD_NUMBER" in f.message)
    assert (bn.line, bn.col) == (6, 26)


def test_jenkins_var_detection_covers_braced_form_and_echo():
    source = CLEAN.replace(
        "sh 'make build'",
        "sh 'echo ${BUILD_URL}'\n                echo 'done $NODE_NAME'",
    )
    result = analyze_source(source)
    jenv = [f for f in result.findings if f.code == F.PB_JENV]
    assert len(jenv) == 2
    assert any("BUILD_URL" in f.message for f in jenv)
    assert any("NODE_NAME" in f.message for f in jenv)


def test_shell_variables_that_are_not_jenkins_vars_are_not_flagged():
    source = CLEAN.replace("sh 'make build'", "sh 'echo $PWD ${HOME} $1'")
    result = analyze_source(source)
    assert not any(f.code == F.PB_JENV for f in result.findings)


def test_github_expression_syntax_is_flagged_with_position():
    source = CLEAN.replace(
        "sh 'make build'",
        "sh 'deploy ${{ secrets.TOKEN }}'",
    )
    result = analyze_source(source)
    ghex = [f for f in result.findings if f.code == F.PB_GHEXPR]
    assert len(ghex) == 1
    assert (ghex[0].line, ghex[0].col) == (6, 28)


def test_github_expression_in_env_value_is_flagged():
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    environment {\n"
        "        ODD = 'x ${{ github }} y'\n"
        "    }\n"
        "    stages {\n"
        "        stage('A') {\n"
        "            steps {\n"
        "                echo 'x'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = analyze_source(source)
    ghex = [f for f in result.findings if f.code == F.PB_GHEXPR]
    assert len(ghex) == 1
    assert (ghex[0].line, ghex[0].col) == (4, 18)


def test_findings_are_sorted_by_position_and_deduplicated():
    source = CLEAN.replace(
        "sh 'make build'",
        "sh 'echo $BUILD_NUMBER'\n                script {\n                    echo '$WORKSPACE'\n                }",
    )
    result = analyze_source(source)
    positions = [(f.line, f.col, f.code) for f in result.findings]
    assert positions == sorted(positions, key=lambda t: (t[0], t[1], t[2]))
    assert len(positions) == len(set(positions))


def test_source_sha256_is_computed():
    result = analyze_source(CLEAN)
    import hashlib

    assert result.source_sha256 == hashlib.sha256(CLEAN.encode()).hexdigest()


def test_lex_error_propagates_from_analysis():
    import pytest

    from pipebridge.errors import LexError

    with pytest.raises(LexError):
        analyze_source("sh 'unterminated")
