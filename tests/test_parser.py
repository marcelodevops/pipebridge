"""Parser tests: limited grammar, blockers without traversal, positions."""

import pytest

from pipebridge import findings as F
from pipebridge.errors import LexError, MalformedPipelineError
from pipebridge.parser import parse


def codes(result):
    return [f.code for f in result.findings]


def blocker_codes(result):
    return [f.code for f in result.findings if f.is_blocker]


SIMPLE = (
    "pipeline {\n"
    "    agent any\n"
    "    stages {\n"
    "        stage('Build') {\n"
    "            steps {\n"
    "                echo 'building'\n"
    "                sh 'make build'\n"
    "            }\n"
    "        }\n"
    "    }\n"
    "}\n"
)


def test_supported_pipeline_parses_without_blockers():
    result = parse(SIMPLE)
    assert result.findings == []
    p = result.pipeline
    assert p is not None and p.has_agent_any and not p.blocked
    assert [s.name for s in p.stages] == ["Build"]
    assert [(s.kind, s.text) for s in p.stages[0].steps] == [
        ("echo", "building"),
        ("sh", "make build"),
    ]


def test_step_spans_point_at_source():
    result = parse(SIMPLE)
    echo = result.pipeline.stages[0].steps[0]
    assert (echo.span.line, echo.span.col) == (6, 17)
    sh = result.pipeline.stages[0].steps[1]
    assert (sh.span.line, sh.span.col) == (7, 17)


def test_scripted_pipeline_is_one_blocker_and_not_traversed():
    source = "node {\n    sh 'rm -rf /tmp/thing'\n    echo 'oops'\n}\n"
    result = parse(source)
    assert result.pipeline is None
    assert blocker_codes(result) == [F.PB_SCRIPT]
    f = result.findings[0]
    assert (f.line, f.col) == (1, 1)
    assert "rm -rf" not in "".join(x.message for x in result.findings)


def test_script_block_blocks_stage_and_is_not_traversed():
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Test') {\n"
        "            steps {\n"
        "                echo 'before'\n"
        "                script {\n"
        "                    sh 'evil-command'\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    assert blocker_codes(result) == [F.PB_SCRIPT]
    stage = result.pipeline.stages[0]
    assert stage.blocked is True
    assert stage.steps == []  # 'echo before' is NOT translated either
    # The enclosed command must not be extracted anywhere.
    all_text = str(result.pipeline.stages[0])
    assert "evil-command" not in all_text


def test_blocker_position_inside_second_stage():
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Build') {\n"
        "            steps {\n"
        "                echo 'ok'\n"
        "            }\n"
        "        }\n"
        "        stage('Test') {\n"
        "            steps {\n"
        "                script {\n"
        "                    sh 'x'\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    assert result.findings[0].code == F.PB_SCRIPT
    assert (result.findings[0].line, result.findings[0].col) == (11, 17)


def test_agent_none_is_blocker():
    source = "pipeline {\n    agent none\n    stages {\n        stage('A') {\n            steps {\n                sh 'x'\n            }\n        }\n    }\n}\n"
    result = parse(source)
    assert blocker_codes(result) == [F.PB_AGENT]
    assert result.pipeline.blocked is True


def test_docker_agent_is_blocker_with_position():
    source = (
        "pipeline {\n"
        "    agent {\n"
        "        docker {\n"
        "            image 'node:20'\n"
        "        }\n"
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
    result = parse(source)
    assert blocker_codes(result) == [F.PB_AGENT]
    assert (result.findings[0].line, result.findings[0].col) == (2, 5)
    assert result.pipeline.blocked is True


def test_pipeline_label_agent_is_accepted():
    source = "pipeline {\n    agent { label 'linux' }\n    stages {\n        stage('A') {\n            steps {\n                echo 'x'\n            }\n        }\n    }\n}\n"
    result = parse(source)
    assert blocker_codes(result) == []
    assert result.pipeline.agent_label == "linux"
    assert result.pipeline.blocked is False


def test_stage_level_docker_agent_blocks_only_that_stage():
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Build') {\n"
        "            steps {\n"
        "                echo 'ok'\n"
        "            }\n"
        "        }\n"
        "        stage('Publish') {\n"
        "            agent {\n"
        "                docker 'alpine'\n"
        "            }\n"
        "            steps {\n"
        "                sh 'push'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    stages = result.pipeline.stages
    assert [s.blocked for s in stages] == [False, True]
    assert [len(s.steps) for s in stages] == [1, 0]


def test_environment_pipeline_and_stage_scope():
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    environment {\n"
        "        APP_ENV = 'production'\n"
        "    }\n"
        "    stages {\n"
        "        stage('Build') {\n"
        "            environment {\n"
        "                BUILD_DIR = 'target'\n"
        "            }\n"
        "            steps {\n"
        "                sh 'make'\n"
        "            }\n"
        "        }\n"
        "        stage('Test') {\n"
        "            steps {\n"
        "                sh 'make test'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    p = result.pipeline
    assert [v.name for v in p.env] == ["APP_ENV"]
    build, test = p.stages
    assert [(v.name, v.value) for v in build.env] == [("BUILD_DIR", "target")]
    assert test.env == []  # stage env does not leak to later stages


def test_env_credentials_is_credential_blocker():
    source = "pipeline {\n    agent any\n    stages {\n        stage('A') {\n            environment {\n                NPM_TOKEN = credentials('npm-id')\n            }\n            steps {\n                sh 'x'\n            }\n        }\n    }\n}\n"
    result = parse(source)
    assert blocker_codes(result) == [F.PB_CRED]
    assert result.findings[0].line == 6
    assert result.pipeline.stages[0].blocked is True


def test_env_interpolation_is_blocker():
    source = 'pipeline {\n    agent any\n    environment {\n        GREETING = "Hello ${NAME}"\n    }\n    stages {\n        stage(\'A\') {\n            steps {\n                echo \'x\'\n            }\n        }\n    }\n}\n'
    result = parse(source)
    assert blocker_codes(result) == [F.PB_INTERP]
    assert result.pipeline.env == []


def test_env_nonliteral_value_is_blocker():
    source = "pipeline {\n    agent any\n    environment {\n        PORT = serverPort\n    }\n    stages {\n        stage('A') {\n            steps {\n                echo 'x'\n            }\n        }\n    }\n}\n"
    result = parse(source)
    assert blocker_codes(result) == [F.PB_ENVVAL]
    assert result.pipeline.blocked is True
    assert result.pipeline.stages[0].steps == []


def test_env_numeric_and_boolean_literals_supported():
    source = "pipeline {\n    agent any\n    environment {\n        PORT = 8080\n        DEBUG = true\n    }\n    stages {\n        stage('A') {\n            steps {\n                echo 'x'\n            }\n        }\n    }\n}\n"
    result = parse(source)
    assert result.findings == []
    values = {v.name: v.value for v in result.pipeline.env}
    assert values == {"PORT": "8080", "DEBUG": "true"}


def test_unknown_step_blocks_stage_without_traversal():
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('A') {\n"
        "            steps {\n"
        "                mysteryStep 'payload'\n"
        "                sh 'later'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    assert blocker_codes(result) == [F.PB_SYNTAX]
    assert "mysteryStep" in result.findings[0].message
    stage = result.pipeline.stages[0]
    assert stage.blocked is True
    assert stage.steps == []


def test_unsupported_directives_map_to_specific_codes():
    cases = {
        "when": F.PB_WHEN,
        "input": F.PB_INPUT,
        "post": F.PB_POST,
        "parallel": F.PB_PARALLEL,
        "matrix": F.PB_MATRIX,
    }
    for directive, code in cases.items():
        source = (
            "pipeline {\n"
            "    agent any\n"
            "    stages {\n"
            "        stage('A') {\n"
            f"            {directive} {{\n"
            "                something 'inner'\n"
            "            }\n"
            "            steps {\n"
            "                echo 'x'\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        result = parse(source)
        expected = [code]
        if directive in ("parallel", "matrix"):
            # The triggering construct's body is diagnosed too, so the
            # unrecognized inner step is reported at its own boundary.
            expected.append(F.PB_SYNTAX)
        assert blocker_codes(result) == expected, f"directive {directive}"
        assert result.pipeline.stages[0].blocked is True


def test_parameters_triggers_tools_options_block_pipeline():
    for directive, code in [
        ("parameters", F.PB_PARAM),
        ("triggers", F.PB_TRIGGER),
        ("tools", F.PB_TOOLS),
        ("post", F.PB_POST),
        ("options", F.PB_SYNTAX),
    ]:
        source = (
            "pipeline {\n"
            "    agent any\n"
            f"    {directive} {{\n"
            "                whatever 'x'\n"
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
        result = parse(source)
        assert blocker_codes(result) == [code], f"directive {directive}"
        assert result.pipeline.blocked is True
        # Pipeline-level blocker: no steps are translated at all.
        assert result.pipeline.stages[0].steps == []


def test_library_annotation_is_blocker_and_pipeline_still_parses():
    source = (
        "@Library('my-shared-lib@v2') _\n"
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('A') {\n"
        "            steps {\n"
        "                echo 'x'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    assert blocker_codes(result) == [F.PB_LIB]
    assert (result.findings[0].line, result.findings[0].col) == (1, 1)
    assert len(result.pipeline.stages[0].steps) == 1


def test_checkout_scm_parses_and_other_checkout_is_blocker():
    source = "pipeline {\n    agent any\n    stages {\n        stage('A') {\n            steps {\n                checkout scm\n            }\n        }\n    }\n}\n"
    result = parse(source)
    assert result.findings == []
    assert result.pipeline.stages[0].steps[0].kind == "checkout"

    source2 = source.replace("checkout scm", "checkout([$class: 'GitSCM'])")
    result2 = parse(source2)
    assert blocker_codes(result2) == [F.PB_SYNTAX]


def test_sh_named_args_blocker():
    source = "pipeline {\n    agent any\n    stages {\n        stage('A') {\n            steps {\n                sh label: 'build', script: 'make'\n            }\n        }\n    }\n}\n"
    result = parse(source)
    assert blocker_codes(result) == [F.PB_SYNTAX]
    assert result.pipeline.stages[0].blocked is True


def test_multiline_sh_preserves_shell_variables():
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Test') {\n"
        "            steps {\n"
        "                sh '''\n"
        "                    export REPORTS_DIR=$PWD/reports\n"
        "                    ./run-tests.sh --dir \"$REPORTS_DIR\"\n"
        "                '''\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    assert result.findings == []
    step = result.pipeline.stages[0].steps[0]
    assert step.kind == "sh"
    assert "export REPORTS_DIR=$PWD/reports" in step.text
    assert './run-tests.sh --dir "$REPORTS_DIR"' in step.text


def test_double_quoted_string_without_interpolation_supported():
    source = 'pipeline {\n    agent any\n    stages {\n        stage(\'A\') {\n            steps {\n                echo "hello world"\n                sh "make all"\n            }\n        }\n    }\n}\n'
    result = parse(source)
    assert result.findings == []
    assert [(s.kind, s.text) for s in result.pipeline.stages[0].steps] == [
        ("echo", "hello world"),
        ("sh", "make all"),
    ]


def test_interpolated_sh_blocks_stage():
    source = 'pipeline {\n    agent any\n    stages {\n        stage(\'A\') {\n            steps {\n                sh "echo ${BUILD_NUMBER}"\n            }\n        }\n    }\n}\n'
    result = parse(source)
    assert blocker_codes(result) == [F.PB_INTERP]
    assert result.findings[0].line == 6
    assert result.pipeline.stages[0].steps == []


def test_comments_inside_steps_are_ignored():
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('A') {\n"
        "            steps {\n"
        "                // a comment\n"
        "                /* block\n"
        "                   comment */\n"
        "                echo 'x'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    assert result.findings == []
    assert len(result.pipeline.stages[0].steps) == 1


def test_malformed_input_raises_lex_error():
    with pytest.raises(LexError):
        parse("sh 'unterminated")


MALFORMED_SOURCES = {
    "missing stages section": "pipeline {\n    agent any\n}\n",
    "empty stages section": (
        "pipeline {\n    agent any\n    stages {\n    }\n}\n"
    ),
    "stage without steps section": (
        "pipeline {\n    agent any\n    stages {\n"
        "        stage('A') {\n            environment {\n"
        "                X = 'y'\n            }\n        }\n    }\n}\n"
    ),
    "empty steps section": (
        "pipeline {\n    agent any\n    stages {\n        stage('A') {\n"
        "            steps {\n            }\n        }\n    }\n}\n"
    ),
    "empty file": "",
    "comments-only file": "// nothing here\n",
}


@pytest.mark.parametrize("label", sorted(MALFORMED_SOURCES))
def test_missing_required_structure_raises_malformed(label):
    """Required declarative structure (per official Jenkins syntax docs:
    'stages' with at least one stage, and a non-empty 'steps' section per
    stage) is malformed input, distinct from valid-but-unsupported."""
    with pytest.raises(MalformedPipelineError):
        parse(MALFORMED_SOURCES[label])


def test_empty_file_is_malformed():
    with pytest.raises(MalformedPipelineError):
        parse("")


def test_scripted_pipeline_is_not_malformed():
    """A scripted pipeline is valid-but-unsupported: parsed result carries
    the PB-SCRIPT blocker; no malformed-pipeline exception."""
    result = parse("node {\n    sh 'deploy'\n}\n")
    assert result.pipeline is None
    assert blocker_codes(result) == [F.PB_SCRIPT]


def test_stage_names_preserved_verbatim():
    source = "pipeline {\n    agent any\n    stages {\n        stage('Build & Test \"v2\"') {\n            steps {\n                echo 'x'\n            }\n        }\n    }\n}\n"
    result = parse(source)
    assert result.pipeline.stages[0].name == 'Build & Test "v2"'
