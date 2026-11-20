"""D2: diagnostic traversal inside blocked scopes.

These tests enforce the contract in
``docs/d2-nested-diagnostics-design.md``:

- diagnosis never expands translation eligibility and never creates steps;
- the triggering construct's body and the remaining siblings are both
  diagnosed;
- only the documented declarative grammar and step-wrapper allowlist are
  entered, and every stopping point is stated in the finding text;
- findings keep source positions, parent scope, source order, and dedupe;
- exit codes, disabled drafts, supported clean output, and finding JSON keys
  are unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipebridge.cli import main
from pipebridge.parser import parse

from tests.d2_support import (
    assert_structurally_equal,
    load_workflow,
    normalize_blocked_workflow,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = REPO_ROOT / "docs" / "compatibility-study" / "synthetic"
BASELINES = REPO_ROOT / "tests" / "baselines" / "d2"


def blocker_codes(result):
    return [f.code for f in result.findings if f.is_blocker]


def convert(tmp_path: Path, source: str, name: str = "Jenkinsfile") -> tuple[int, dict, str]:
    jf = tmp_path / name
    jf.write_text(source)
    out = tmp_path / "migration"
    code = main(["convert", str(jf), "--output", str(out)])
    report = json.loads((out / "migration-report.json").read_text())
    workflow = (out / "workflow.yml").read_text()
    return code, report, workflow


def find(report: dict, code: str, line: int) -> list[dict]:
    return [
        finding
        for finding in report["findings"]
        if finding["code"] == code and finding["line"] == line
    ]


# ---- Jetty-like fixture matches the design -----------------------------


def test_jetty_like_nested_findings_match_design(tmp_path):
    jf = SYNTHETIC / "java-maven-jetty-like.Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 2
    workflow = (out / "workflow.yml").read_text()
    report = json.loads((out / "migration-report.json").read_text())

    assert "if: false" in workflow
    assert [(e["stage"], e["blocked"], e["steps"]) for e in report["translated"]] == [
        ("Parallel Stage", True, [])
    ]
    assert report["exit_code"] == 2

    expected = {
        ("PB-PARALLEL", 16),
        ("PB-AGENT", 18),
        ("PB-WHEN", 19),
        ("PB-SYNTAX", 21),  # timeout (wrapper body still diagnosed)
        ("PB-SCRIPT", 22),
        ("PB-SYNTAX", 26),  # mavenBuild
        ("PB-AGENT", 31),
        ("PB-WHEN", 32),
        ("PB-SYNTAX", 34),  # timeout
        ("PB-SYNTAX", 35),  # mavenBuild
    }
    found = {(f["code"], f["line"]) for f in report["findings"] if f["severity"] == "blocker"}
    assert expected <= found
    # The supported checkout step inside the timeout produces no finding and
    # is never translated.
    assert not any(f["construct"] == "step 'scm'" for f in report["findings"])

    parallel = find(report, "PB-PARALLEL", 16)[0]
    assert "Build / Test - JDK21" in parallel["message"]
    assert "Build / Test - JDK25" in parallel["message"]

    branch_agent = find(report, "PB-AGENT", 18)[0]
    assert (
        "In stage 'Parallel Stage' → parallel branch 'Build / Test - JDK21'"
        in branch_agent["message"]
    )

    keys = {tuple(sorted(f)) for f in report["findings"]}
    assert keys == {
        ("code", "col", "construct", "line", "message", "severity", "suggestion")
    }


def test_jetty_workflow_is_structurally_unchanged(tmp_path):
    baseline = (BASELINES / "java-maven-jetty-like.workflow.yml").read_text()
    jf = SYNTHETIC / "java-maven-jetty-like.Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 2
    generated = (out / "workflow.yml").read_text()

    # Raw parsed documents differ only because diagnostic counts/codes are
    # embedded in the placeholder command.
    assert load_workflow(baseline) != load_workflow(generated)
    assert_structurally_equal(baseline, generated)
    assert load_workflow(baseline)["jobs"]["migrated-pipeline"]["if"] is False


def test_normalization_does_not_hide_executable_changes():
    baseline = (BASELINES / "build-and-test.workflow.yml").read_text()
    changed = baseline.replace(
        "make build VERSION=$VERSION", "make build VERSION=$VERSION --fast"
    )
    assert changed != baseline
    with pytest.raises(AssertionError):
        assert_structurally_equal(baseline, changed)


def test_clean_example_is_byte_identical_and_exits_zero(tmp_path):
    baseline = (BASELINES / "build-and-test.workflow.yml").read_text()
    jf = REPO_ROOT / "tests" / "fixtures" / "build-and-test" / "Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 0
    assert (out / "workflow.yml").read_text() == baseline


@pytest.mark.parametrize(
    "name",
    ["python-gpu-kymatio-like"],
)
def test_blocked_synthetics_keep_exit_2_and_structure(name, tmp_path):
    baseline = (BASELINES / f"{name}.workflow.yml").read_text()
    jf = SYNTHETIC / f"{name}.Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 2
    workflow = (out / "workflow.yml").read_text()
    assert "if: false" in workflow
    assert_structurally_equal(baseline, workflow)
    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 2
    assert report["summary"]["blockers"] > 0


def test_kymatio_gains_hidden_stage_diagnostics(tmp_path):
    jf = SYNTHETIC / "python-gpu-kymatio-like.Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 2
    report = json.loads((out / "migration-report.json").read_text())
    codes = {(f["code"], f["line"]) for f in report["findings"]}
    # Previously invisible inside the pipeline-blocked stage.
    assert ("PB-AGENT", 17) in codes
    assert ("PB-INTERP", 24) in codes


# ---- triggering body and remaining siblings ----------------------------


TRIGGER_SOURCE = """pipeline {
    agent any
    stages {
        stage('Outer') {
            parallel {
                stage('A') {
                    agent { label 'linux' }
                    when { branch 'main' }
                    steps {
                        script {
                            echo 'inside script'
                        }
                    }
                }
                stage('B') {
                    agent { label 'linux' }
                    steps {
                        echo 'ok'
                    }
                }
            }
            post {
                always {
                    echo 'sibling after parallel'
                }
            }
        }
    }
}
"""


def test_triggering_parallel_body_and_later_siblings_are_diagnosed():
    result = parse(TRIGGER_SOURCE)
    codes = blocker_codes(result)
    assert codes.count("PB-PARALLEL") == 1
    assert codes.count("PB-AGENT") == 2
    assert codes.count("PB-WHEN") == 1
    assert codes.count("PB-SCRIPT") == 1
    # The post section after the parallel block is a remaining sibling.
    assert codes.count("PB-POST") == 1

    stages = [stage.name for stage in result.pipeline.stages]
    assert stages == ["Outer"]
    assert result.pipeline.stages[0].steps == []
    assert result.pipeline.stages[0].blocked


def test_pipeline_blocked_trigger_body_is_diagnosed():
    source = """pipeline {
    agent none
    stages {
        stage('Outer') {
            parallel {
                stage('A') {
                    agent { label 'linux' }
                    steps {
                        script { echo 'x' }
                    }
                }
            }
        }
    }
}
"""
    result = parse(source)
    codes = blocker_codes(result)
    assert "PB-PARALLEL" in codes
    assert "PB-AGENT" in codes
    assert "PB-SCRIPT" in codes
    assert [stage.name for stage in result.pipeline.stages] == ["Outer"]


def test_matrix_axis_names_and_nested_stage_diagnostics():
    source = """pipeline {
    agent none
    stages {
        stage('M') {
            matrix {
                axes {
                    axis { name 'OS'; values 'linux', 'mac' }
                }
                stages {
                    stage('build') {
                        agent { label 'linux' }
                        steps { sh 'make' }
                    }
                }
            }
        }
    }
}
"""
    result = parse(source)
    matrix = [f for f in result.findings if f.code == "PB-MATRIX"]
    assert len(matrix) == 1
    assert "Axes: 'OS'." in matrix[0].message
    branch_agents = [
        f for f in result.findings if f.code == "PB-AGENT" and f.line == 11
    ]
    assert len(branch_agents) == 1
    assert "nested stage 'build'" in branch_agents[0].message


# ---- opaque boundaries -------------------------------------------------


OPAQUE_SOURCE = """pipeline {
    agent none
    stages {
        stage('A') {
            steps {
                script {
                    echo 'inside script'
                    sh 'rm -rf /tmp/do-not-report'
                }
                withCredentials([string(credentialsId: 'x', variable: 'T')]) {
                    sh 'use $T'
                }
                deployPlugin(env: 'prod') {
                    sh 'nested-command-do-not-report'
                }
                echo 'ok'
            }
            post {
                always {
                    junit 'x'
                }
            }
        }
    }
}
"""


def test_opaque_bodies_are_reported_once_and_never_traversed():
    result = parse(OPAQUE_SOURCE)
    codes = blocker_codes(result)
    assert "PB-SCRIPT" in codes
    assert "PB-CRED" in codes
    assert "PB-SYNTAX" in codes
    assert "PB-POST" in codes
    # The unknown closure and the script are each reported once.
    assert codes.count("PB-SCRIPT") == 1
    assert codes.count("PB-CRED") == 1
    assert codes.count("PB-POST") == 1

    all_text = "\n".join(f.message + f.construct for f in result.findings)
    assert "rm -rf" not in all_text
    assert "nested-command-do-not-report" not in all_text
    assert "inside script" not in all_text
    # junit inside post is not enumerated.
    assert not any(f.construct == "step 'junit'" for f in result.findings)
    cred = [f for f in result.findings if f.code == "PB-CRED"]
    assert len(cred) == 1
    assert "not analyzed" in cred[0].message
    assert not any("use $T" in f.message for f in result.findings)


def test_withcredentials_and_wrap_bodies_are_not_entered():
    source = """pipeline {
    agent any
    stages {
        stage('A') {
            steps {
                withCredentials([string(credentialsId: 'x', variable: 'T')]) {
                    sh 'secret-command-do-not-report'
                    timeout(time: 1) { sh 'also-hidden' }
                }
                wrap([$class: 'AnsiColorBuildWrapper']) {
                    sh 'wrap-body-do-not-report'
                }
                echo 'after'
            }
        }
    }
}
"""
    result = parse(source)
    text = "\n".join(f.message + f.construct for f in result.findings)
    assert "secret-command-do-not-report" not in text
    assert "also-hidden" not in text
    assert "wrap-body-do-not-report" not in text
    assert blocker_codes(result).count("PB-CRED") == 1
    assert any(f.construct == "step 'wrap'" for f in result.findings)
    assert result.pipeline.stages[0].steps == []


def _pos(source: str, needle: str) -> tuple[int, int]:
    index = source.index(needle)
    line = source[:index].count("\n") + 1
    col = index - source.rfind("\n", 0, index)
    return line, col


def _argument_source(prefix: str) -> str:
    return prefix + """
                script {
                    sh "echo ${env.DO_NOT_REPORT}"
                    checkout([$class: 'GitSCM'])
                }
                sh 'make'
                echo 'plain'
                checkout scm
                sh "echo ${env.BUILD_NUMBER}"
                echo "build ${env.BUILD_NUMBER}"
                echo env.JOB_NAME
                sh "echo " + env.BUILD_NUMBER
                checkout([$class: 'GitSCM'])
                mavenBuild 'later'
            }
        }
    }
}
"""


PIPELINE_ARGUMENT_SOURCE = _argument_source("""pipeline {
    agent none
    stages {
        stage('Hidden') {
            steps {""")


STAGE_ARGUMENT_SOURCE = _argument_source("""pipeline {
    agent any
    stages {
        stage('Build') {
            steps {""")


def _assert_argument_diagnostics(result, source: str, stage_name: str) -> None:
    text = "\n".join(f.message + f.construct for f in result.findings)
    assert "DO_NOT_REPORT" not in text
    # The map form is unsupported, but its class name is not extracted.
    assert not any("GitSCM" in (f.message + f.construct) for f in result.findings)

    literal_lines = {
        _pos(source, "sh 'make'")[0],
        _pos(source, "echo 'plain'")[0],
        _pos(source, "checkout scm")[0],
    }
    assert not any(f.line in literal_lines for f in result.findings)

    sh_interp = _pos(source, "${env.BUILD_NUMBER}")
    echo_at = source.index("${env.BUILD_NUMBER}", source.index("${env.BUILD_NUMBER}") + 1)
    echo_interp = (
        source[:echo_at].count("\n") + 1,
        echo_at - source.rfind("\n", 0, echo_at),
    )

    interps = [f for f in result.findings if f.code == "PB-INTERP"]
    interp_pos = {(f.line, f.col) for f in interps}
    assert sh_interp in interp_pos
    assert echo_interp in interp_pos
    concat_at = source.index('+ env.BUILD_NUMBER')
    concat_pos = (
        source[:concat_at].count("\n") + 1,
        concat_at - source.rfind("\n", 0, concat_at),
    )
    assert concat_pos in interp_pos
    assert all(f"stage '{stage_name}'" in f.message for f in interps)
    assert any("${env.BUILD_NUMBER}" in f.message for f in interps)
    assert any("dynamic Groovy expression" in f.message for f in interps)

    checkout_at = source.rindex("checkout([")
    line_start = source.rfind("\n", 0, checkout_at) + 1
    checkout_pos = (
        source[:checkout_at].count("\n") + 1,
        source.index("(", checkout_at) - line_start + 1,
    )
    checkouts = [
        f for f in result.findings
        if f.code == "PB-SYNTAX" and f.construct == "checkout step"
    ]
    assert len(checkouts) == 1
    assert (checkouts[0].line, checkouts[0].col) == checkout_pos
    assert "checkout scm" in checkouts[0].message
    assert f"stage '{stage_name}'" in checkouts[0].message

    dynamic = [
        f for f in result.findings
        if f.construct == "echo step" and "requires a string" in f.message
    ]
    assert len(dynamic) == 1
    assert (dynamic[0].line, dynamic[0].col) == _pos(source, "env.JOB_NAME")

    sibling = [f for f in result.findings if f.construct == "step 'mavenBuild'"]
    assert len(sibling) == 1
    assert sibling[0].line > checkouts[0].line
    assert all(stage.steps == [] for stage in result.pipeline.stages)
    keys = [(f.code, f.line, f.col) for f in result.findings]
    assert len(keys) == len(set(keys))
    assert [(f.line, f.col, f.code) for f in result.findings] == sorted(
        (f.line, f.col, f.code) for f in result.findings
    )


def test_pipeline_blocked_scope_validates_step_arguments():
    result = parse(PIPELINE_ARGUMENT_SOURCE)
    assert result.pipeline.blocked is True
    _assert_argument_diagnostics(result, PIPELINE_ARGUMENT_SOURCE, "Hidden")
    assert blocker_codes(result).count("PB-SCRIPT") == 1
    assert blocker_codes(result).count("PB-AGENT") == 1


def test_stage_blocked_scope_validates_step_arguments_and_later_sibling():
    result = parse(STAGE_ARGUMENT_SOURCE)
    assert result.pipeline.blocked is False
    assert result.pipeline.stages[0].blocked is True
    _assert_argument_diagnostics(result, STAGE_ARGUMENT_SOURCE, "Build")
    assert blocker_codes(result).count("PB-SCRIPT") == 1
    assert "PB-AGENT" not in blocker_codes(result)


_SEMICOLON_STEPS = """
                echo env.JOB_NAME; mavenBuild 'job'
                sh "echo " + env.BUILD_NUMBER; mavenBuild 'concat'
                sh "echo " + "x; y"; mavenBuild 'concat-string'
                echo "keep; this"; mavenBuild 'string-semi'
                sh 'cmd; still one'; mavenBuild 'literal-semi'
                echo call(env.JOB_NAME; 'nested'); mavenBuild 'nested-paren'
                echo items[0; 1]; mavenBuild 'nested-bracket'
                echo closure { def x = 1; x }; mavenBuild 'nested-brace'
                sh("echo " + env.BUILD_NUMBER); mavenBuild 'paren-form'
"""

_SEMICOLON_SIBLINGS = (
    "mavenBuild 'job'",
    "mavenBuild 'concat'",
    "mavenBuild 'concat-string'",
    "mavenBuild 'string-semi'",
    "mavenBuild 'literal-semi'",
    "mavenBuild 'nested-paren'",
    "mavenBuild 'nested-bracket'",
    "mavenBuild 'nested-brace'",
    "mavenBuild 'paren-form'",
)


def _semicolon_source(prefix: str, *, opaque: str = "") -> str:
    return prefix + opaque + _SEMICOLON_STEPS + """
            }
        }
    }
}
"""


def _assert_semicolon_recovery(result, source: str, stage_name: str) -> None:
    text = "\n".join(f.message + f.construct for f in result.findings)
    assert "DO_NOT_REPORT" not in text
    assert "hidden" not in text
    assert "Expected ')'" not in text
    assert all(stage.steps == [] for stage in result.pipeline.stages)

    siblings = [f for f in result.findings if f.construct == "step 'mavenBuild'"]
    assert [(f.line, f.col) for f in siblings] == [
        _pos(source, needle) for needle in _SEMICOLON_SIBLINGS
    ]
    assert all(f"stage '{stage_name}'" in f.message for f in siblings)

    echo_dynamic = [
        f for f in result.findings
        if f.construct == "echo step" and "requires a string" in f.message
    ]
    assert [(f.line, f.col) for f in echo_dynamic] == [
        _pos(source, "env.JOB_NAME"),
        _pos(source, "call(env.JOB_NAME"),
        _pos(source, "items[0; 1]"),
        _pos(source, "closure {"),
    ]
    assert all(f"stage '{stage_name}'" in f.message for f in echo_dynamic)

    interps = [f for f in result.findings if "dynamic Groovy expression" in f.message]
    assert [(f.line, f.col) for f in interps] == [
        _pos(source, "+ env.BUILD_NUMBER"),
        _pos(source, '+ "x; y"'),
        _pos(source, "+ env.BUILD_NUMBER)"),
    ]
    assert all(f"stage '{stage_name}'" in f.message for f in interps)

    # A semicolon inside a literal is not a split, and the opaque script's
    # sibling must stay unreported. The visible mavenBuild on those lines is
    # a separate finding.
    assert not any(
        f.line == _pos(source, 'echo "keep; this"')[0] and f.construct == "echo step"
        for f in result.findings
    )
    assert not any(
        f.line == _pos(source, "sh 'cmd; still one'")[0] and f.construct == "sh step"
        for f in result.findings
    )
    if "mavenBuild 'hidden'" in source:
        hidden = _pos(source, "mavenBuild 'hidden'")
        assert not any((f.line, f.col) == hidden for f in result.findings)

    keys = [(f.code, f.line, f.col) for f in result.findings]
    assert len(keys) == len(set(keys))
    assert [(f.line, f.col, f.code) for f in result.findings] == sorted(
        (f.line, f.col, f.code) for f in result.findings
    )


def test_pipeline_blocked_scope_recovers_at_top_level_semicolons():
    source = _semicolon_source("""pipeline {
    agent none
    stages {
        stage('Hidden') {
            steps {""")
    result = parse(source)
    assert result.pipeline.blocked is True
    _assert_semicolon_recovery(result, source, "Hidden")
    assert blocker_codes(result).count("PB-AGENT") == 1


def test_stage_blocked_scope_recovers_at_top_level_semicolons():
    source = _semicolon_source(
        """pipeline {
    agent any
    stages {
        stage('Build') {
            steps {""",
        opaque="""
                script {
                    sh "echo ${env.DO_NOT_REPORT}; mavenBuild 'hidden'"
                }
""",
    )
    result = parse(source)
    assert result.pipeline.blocked is False
    assert result.pipeline.stages[0].blocked is True
    _assert_semicolon_recovery(result, source, "Build")
    assert blocker_codes(result).count("PB-SCRIPT") == 1
    assert "PB-AGENT" not in blocker_codes(result)


def test_eligible_semicolon_separated_literals_stay_translated():
    source = """pipeline {
    agent any
    stages {
        stage('A') {
            steps {
                sh 'make; not a split'; echo "plain; still one"
                checkout scm
            }
        }
    }
}
"""
    result = parse(source)
    assert blocker_codes(result) == []
    assert [step.kind for step in result.pipeline.stages[0].steps] == [
        "sh",
        "echo",
        "checkout",
    ]
    assert result.pipeline.stages[0].steps[0].text == "make; not a split"
    assert result.pipeline.stages[0].steps[1].text == "plain; still one"


def test_eligible_literal_steps_are_not_false_blockers():
    source = """pipeline {
    agent any
    stages {
        stage('A') {
            steps {
                sh 'make'
                echo 'plain'
                sh "make all"
                checkout scm
            }
        }
    }
}
"""
    result = parse(source)
    assert blocker_codes(result) == []
    assert [step.kind for step in result.pipeline.stages[0].steps] == [
        "sh",
        "echo",
        "sh",
        "checkout",
    ]


def test_when_expression_and_agent_internals_are_opaque():
    source = """pipeline {
    agent none
    stages {
        stage('A') {
            agent { dockerfile { additionalBuildArgs '--x' } }
            when { expression { echo 'do-not-report' } }
            steps { sh 'make' }
        }
    }
}
"""
    result = parse(source)
    text = "\n".join(f.message for f in result.findings)
    assert "do-not-report" not in text
    # One pipeline-level ('agent none') and one stage-level custom agent.
    agents = [f for f in result.findings if f.code == "PB-AGENT"]
    assert sorted(f.line for f in agents) == [2, 5]
    assert blocker_codes(result).count("PB-WHEN") == 1


# ---- grammar robustness ------------------------------------------------


def test_braces_in_strings_and_comments_do_not_confuse_diagnostics():
    source = """pipeline {
    agent none
    stages {
        stage('A') {
            // } stage('Fake') {
            options { timeout(time: 1, unit: 'HOURS') }
            steps {
                sh 'echo }'
                echo 'text } stage("fake") {'
            }
        }
    }
}
"""
    result = parse(source)
    assert blocker_codes(result) == ["PB-AGENT", "PB-SYNTAX"]
    assert not any("Fake" in f.construct for f in result.findings)


def test_unterminated_blocked_scope_reports_one_syntax_finding():
    source = "pipeline {\n    agent none\n    stages {\n        stage('A') {\n            steps {\n                echo 'x'\n"
    result = parse(source)
    syntax = [f for f in result.findings if f.code == "PB-SYNTAX"]
    assert len(syntax) == 1
    assert "Unterminated" in syntax[0].message


def test_depth_limit_is_explicit_and_bounded():
    depth = 30
    source = "pipeline {\n    agent none\n    stages {\n"
    indent = "        "
    for index in range(depth):
        source += f"{indent}stage('s{index}') {{\n"
        indent += "    "
        source += f"{indent}stages {{\n"
        indent += "    "
    source += f"{indent}stage('leaf') {{\n{indent}    steps {{ echo 'x' }}\n{indent}}}\n"
    for _ in range(depth):
        indent = indent[:-4]
        source += f"{indent}}}\n"
        indent = indent[:-4]
        source += f"{indent}}}\n"
    source += "    }\n}\n"

    result = parse(source)
    limited = [
        f for f in result.findings if f.construct == "diagnostic traversal limit"
    ]
    assert len(limited) == 1
    assert "depth limit (20)" in limited[0].message
    assert "deeper content was not analyzed" in limited[0].message


# ---- ordering, dedupe, model and schema --------------------------------


def test_findings_are_source_ordered_and_deduplicated():
    result = parse(OPAQUE_SOURCE)
    positions = [(f.line, f.col) for f in result.findings]
    assert positions == sorted(positions)
    keys = [(f.code, f.line, f.col) for f in result.findings]
    assert len(keys) == len(set(keys))


def test_diagnostics_create_no_steps_or_nested_model_stages():
    result = parse(TRIGGER_SOURCE)
    pipeline = result.pipeline
    assert [stage.name for stage in pipeline.stages] == ["Outer"]
    assert all(stage.steps == [] for stage in pipeline.stages)
    assert pipeline.blocked is False  # only the stage is blocked
    assert pipeline.stages[0].blocked is True


def test_environment_diagnostics_are_read_only():
    source = """pipeline {
    agent none
    stages {
        stage('A') {
            environment {
                LITERAL = 'ok'
                DYNAMIC = "$WORKSPACE/build"
            }
            steps { sh 'make' }
        }
    }
}
"""
    result = parse(source)
    interp = [f for f in result.findings if f.code == "PB-INTERP"]
    assert len(interp) == 1
    assert "DYNAMIC" in interp[0].message
    # Nothing from diagnostics is carried into the model.
    assert all(not stage.env for stage in result.pipeline.stages)


def test_report_schema_and_exit_contract_unchanged(tmp_path):
    jf = SYNTHETIC / "java-maven-jetty-like.Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 2
    report = json.loads((out / "migration-report.json").read_text())

    assert set(report) == {
        "tool",
        "generated_at",
        "source",
        "exit_code",
        "summary",
        "findings",
        "blockers",
        "assumptions",
        "translated",
        "credentials",
        "validation",
    }
    assert all(isinstance(code, str) for code in report["blockers"])
    assert all(
        set(entry) == {"stage", "source_line", "blocked", "steps"}
        for entry in report["translated"]
    )
    assert set(report["summary"]) == {
        "blockers",
        "warnings",
        "info",
        "translated_stages",
        "translated_steps",
    }
