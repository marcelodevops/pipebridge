"""Pipeline-level literal agent labels.

Contract: docs/v0.3.0-agent-label-design.md. A label is a runner selector,
not a claim that the GitHub runner matches the Jenkins agent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pipebridge.analysis import analyze_source
from pipebridge.cli import main
from pipebridge.parser import parse
from pipebridge.reporting import build_report
from pipebridge.workflow import generate_workflow

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = REPO_ROOT / "docs" / "compatibility-study" / "synthetic"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "agent-label" / "Jenkinsfile"
DO400 = SYNTHETIC / "node-minimal-do400-like.Jenkinsfile"
GOLDEN = REPO_ROOT / "tests" / "goldens" / "pure-declarative" / "node-minimal-do400-like.workflow.yml"

REPORT_KEYS = {
    "tool",
    "generated_at",
    "source",
    "exit_code",
    "summary",
    "findings",
    "blockers",
    "assumptions",
    "translated",
    "validation",
}
FINDING_KEYS = {"code", "severity", "construct", "message", "line", "col", "suggestion"}


def _pipeline(agent: str, steps: str = "sh 'true'") -> str:
    return (
        "pipeline {\n"
        f"    {agent}\n"
        "    stages {\n"
        "        stage('A') {\n"
        "            steps {\n"
        f"                {steps}\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _pos(source: str, needle: str) -> tuple[int, int]:
    index = source.index(needle)
    line = source[:index].count("\n") + 1
    col = index - source.rfind("\n", 0, index)
    return line, col


def _job(source: str) -> dict:
    parsed = yaml.safe_load(generate_workflow(analyze_source(source)))
    return parsed["jobs"]["migrated-pipeline"]


def _convert(source: str, tmp_path: Path) -> tuple[int, Path]:
    jf = tmp_path / "Jenkinsfile"
    jf.write_text(source)
    out = tmp_path / "migration"
    code = main(["convert", str(jf), "--output", str(out)])
    return code, out


# ---- parser -------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["nodejs", "big-fleet", "node.js_20", "NodeJS", "a" * 64, "true", "null", "123", "1.2"],
)
@pytest.mark.parametrize("quote", ["'", '"'])
def test_accepted_literal_labels_are_stored_unchanged(label, quote):
    source = _pipeline(f"agent {{ label {quote}{label}{quote} }}")
    result = parse(source)
    assert result.pipeline.agent_label == label
    assert result.pipeline.blocked is False
    assert result.pipeline.has_agent_any is False
    assert blocker_codes(result) == []
    assert (result.pipeline.agent_label_span.line, result.pipeline.agent_label_span.col) == (
        2,
        5,
    )


def blocker_codes(result):
    return [f.code for f in result.findings if f.is_blocker]


@pytest.mark.parametrize(
    "label",
    [
        "",
        "a" * 65,
        "linux&&docker",
        "linux||docker",
        "not linux",
        "a b",
        "has:colon",
        "star*label",
        "what?",
        "path/label",
        "path\\label",
        "bang!",
        "dollar$",
        "paren()",
        "brace{}",
        "self-hosted",
        "SELF-HOSTED",
        "Self-Hosted",
        "sElF-hOsTeD",
    ],
)
def test_rejected_labels_stay_blocked_and_unmapped(label):
    source = _pipeline("agent { label '" + label.replace("'", "\\'") + "' }")
    result = parse(source)
    assert result.pipeline.agent_label is None
    assert result.pipeline.blocked is True
    assert blocker_codes(result) == ["PB-AGENT"]
    assert "PB-ASSUME-RUNNER-LABEL" not in [f.code for f in analyze_source(source).findings]


@pytest.mark.parametrize(
    "literal",
    [
        r'"\n"',
        r'"\t"',
        r'"\r"',
        r'"nodejs\n"',
        r'"nodejs\t"',
        r'"nodejs\r"',
    ],
)
def test_double_quoted_control_escapes_stay_blocked(literal, tmp_path):
    source = _pipeline(f"agent {{ label {literal} }}")
    result = parse(source)
    assert result.pipeline.agent_label is None
    assert result.pipeline.blocked is True
    assert blocker_codes(result) == ["PB-AGENT"]
    assert "PB-ASSUME-RUNNER-LABEL" not in [f.code for f in analyze_source(source).findings]

    code, out = _convert(source, tmp_path)
    assert code == 2
    workflow = (out / "workflow.yml").read_text()
    parsed = yaml.safe_load(workflow)
    job = parsed["jobs"]["migrated-pipeline"]
    assert job["if"] is False
    assert job["runs-on"] == "ubuntu-latest"
    assert "runs-on: [self-hosted," not in workflow
    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 2
    assert "PB-AGENT" in report["blockers"]
    assert "PB-ASSUME-RUNNER-LABEL" not in report["assumptions"]


def test_escaped_quote_backslash_and_control_are_rejected_after_decode():
    cases = [
        r"agent { label 'a\'b' }",
        r"agent { label 'a\\b' }",
        r'agent { label "a\nb" }',
        r'agent { label "a\tb" }',
        r'agent { label "a\$b" }',
    ]
    for agent in cases:
        result = parse(_pipeline(agent))
        assert result.pipeline.agent_label is None, agent
        assert result.pipeline.blocked is True
        assert blocker_codes(result) == ["PB-AGENT"]


def test_interpolated_label_reports_interp_at_the_expression_and_agent():
    source = _pipeline('agent { label "${AGENT}" }')
    result = parse(source)
    assert result.pipeline.agent_label is None
    interps = [f for f in result.findings if f.code == "PB-INTERP"]
    assert len(interps) == 1
    assert (interps[0].line, interps[0].col) == _pos(source, "${AGENT}")
    assert "${AGENT}" in interps[0].message
    agents = [f for f in result.findings if f.code == "PB-AGENT"]
    assert len(agents) == 1
    assert (agents[0].line, agents[0].col) == (2, 5)


def test_dollar_name_interpolation_is_not_mapped():
    source = _pipeline('agent { label "$AGENT" }')
    result = parse(source)
    assert result.pipeline.agent_label is None
    assert {f.code for f in result.findings if f.is_blocker} == {"PB-INTERP", "PB-AGENT"}


@pytest.mark.parametrize(
    "agent",
    [
        "agent none",
        "agent { node { label 'linux' } }",
        "agent { docker { image 'node:20' } }",
        "agent { dockerfile { filename 'Dockerfile' } }",
        "agent { kubernetes { label 'linux' } }",
        "agent { label 'linux' customWorkspace '/tmp' }",
        "agent { label('linux') }",
        "agent { label 'a' + 'b' }",
        "agent { label AGENT }",
        "agent { label '''nodejs''' }",
    ],
)
def test_unsupported_agent_shapes_remain_blockers(agent):
    result = parse(_pipeline(agent))
    assert result.pipeline.agent_label is None
    assert result.pipeline.blocked is True
    assert "PB-AGENT" in blocker_codes(result)
    assert "self-hosted" not in generate_workflow(analyze_source(_pipeline(agent)))


def test_stage_level_label_blocks_only_that_stage():
    source = """pipeline {
    agent any
    stages {
        stage('Build') {
            steps { sh 'make' }
        }
        stage('Pack') {
            agent { label 'linux' }
            steps { sh 'pack' }
        }
    }
}
"""
    result = parse(source)
    assert result.pipeline.agent_label is None
    assert result.pipeline.has_agent_any is True
    assert result.pipeline.blocked is False
    assert result.pipeline.stages[0].blocked is False
    assert result.pipeline.stages[0].steps[0].text == "make"
    assert result.pipeline.stages[1].blocked is True
    assert result.pipeline.stages[1].steps == []
    agents = [f for f in result.findings if f.code == "PB-AGENT"]
    assert len(agents) == 1
    assert (agents[0].line, agents[0].col) == (8, 13)


def test_stage_level_agent_any_stays_a_noop():
    source = """pipeline {
    agent { label 'nodejs' }
    stages {
        stage('A') {
            agent any
            steps { sh 'make' }
        }
    }
}
"""
    result = parse(source)
    assert result.pipeline.agent_label == "nodejs"
    assert result.pipeline.blocked is False
    assert result.pipeline.stages[0].blocked is False
    assert blocker_codes(result) == []


def test_duplicate_pipeline_agents_are_syntax_and_select_no_runner():
    source = """pipeline {
    agent { label 'nodejs' }
    agent any
    stages {
        stage('A') { steps { sh 'make' } }
    }
}
"""
    result = parse(source)
    assert result.pipeline.blocked is True
    assert result.pipeline.agent_label is None
    assert result.pipeline.has_agent_any is False
    assert blocker_codes(result) == ["PB-SYNTAX"]
    analyzed = analyze_source(source)
    codes = [f.code for f in analyzed.findings]
    assert "PB-ASSUME-RUNNER-LABEL" not in codes
    assert "PB-ASSUME-RUNNER" not in codes
    text = generate_workflow(analyzed)
    assert "runs-on: ubuntu-latest" in text
    assert "self-hosted" not in text


def test_accepted_label_does_not_repair_missing_structure():
    source = "pipeline {\n    agent { label 'nodejs' }\n}\n"
    with pytest.raises(Exception) as exc:
        parse(source)
    assert "stages" in str(exc.value)


# ---- workflow -----------------------------------------------------------


def test_accepted_label_emits_self_hosted_list_and_preserves_spelling():
    job = _job(_pipeline("agent { label 'NodeJS' }"))
    assert job["runs-on"] == ["self-hosted", "NodeJS"]
    assert all(isinstance(part, str) for part in job["runs-on"])
    assert "if" not in job
    text = generate_workflow(analyze_source(_pipeline("agent { label 'NodeJS' }")))
    assert "runs-on: [self-hosted, NodeJS]" in text
    assert "NodeJS" in next(
        f.message for f in analyze_source(_pipeline("agent { label 'NodeJS' }")).findings
        if f.code == "PB-ASSUME-RUNNER-LABEL"
    )


@pytest.mark.parametrize("label", ["true", "null", "123", "1.2"])
def test_scalar_looking_labels_round_trip_as_strings(label):
    text = generate_workflow(analyze_source(_pipeline(f"agent {{ label '{label}' }}")))
    parsed = yaml.safe_load(text)
    runs_on = parsed["jobs"]["migrated-pipeline"]["runs-on"]
    assert runs_on == ["self-hosted", label]
    assert all(isinstance(part, str) for part in runs_on)
    assert not any(part is True or part is None or isinstance(part, (int, float)) for part in runs_on)


def test_hosted_looking_label_is_still_self_hosted():
    text = generate_workflow(analyze_source(_pipeline("agent { label 'ubuntu-latest' }")))
    assert "runs-on: [self-hosted, ubuntu-latest]" in text
    assert "runs-on: ubuntu-latest\n" not in text


def test_label_plus_checkout_and_env_keeps_both_checkouts():
    source = """pipeline {
    agent { label 'nodejs' }
    environment { APP_ENV = 'ci' }
    stages {
        stage('Build') {
            steps {
                checkout scm
                sh 'npm ci'
            }
        }
    }
}
"""
    job = _job(source)
    assert job["runs-on"] == ["self-hosted", "nodejs"]
    assert job["env"] == {"APP_ENV": "ci"}
    assert isinstance(job["env"]["APP_ENV"], str)
    names = [step["name"] for step in job["steps"]]
    assert names == ["Checkout source (implicit)", "Build", "Build (step 2)"]
    assert job["steps"][0]["uses"].startswith("actions/checkout@")
    assert job["steps"][1]["uses"].startswith("actions/checkout@")
    assert job["steps"][2]["run"] == "npm ci"


def test_label_with_another_blocker_stays_disabled_but_mapped():
    source = _pipeline("agent { label 'big-fleet' }", "script { sh 'make' }")
    analyzed = analyze_source(source)
    text = generate_workflow(analyzed)
    job = yaml.safe_load(text)["jobs"]["migrated-pipeline"]
    assert job["if"] is False
    assert job["runs-on"] == ["self-hosted", "big-fleet"]
    codes = [f.code for f in analyzed.findings]
    assert "PB-AGENT" not in codes
    assert "PB-SCRIPT" in codes
    assert "PB-ASSUME-RUNNER-LABEL" in codes
    assert "PB-ASSUME-RUNNER" not in codes


def test_rejected_label_keeps_ubuntu_skeleton_and_disabled_job():
    source = _pipeline("agent { label 'self-hosted' }")
    text = generate_workflow(analyze_source(source))
    job = yaml.safe_load(text)["jobs"]["migrated-pipeline"]
    assert job["if"] is False
    assert job["runs-on"] == "ubuntu-latest"
    assert "self-hosted" not in text.split("runs-on:", 1)[1].splitlines()[0]
    assert "PB-ASSUME-RUNNER-LABEL" not in text


# ---- report -------------------------------------------------------------


def test_label_assumption_is_info_and_does_not_replace_agent_any():
    labeled = analyze_source(_pipeline("agent { label 'nodejs' }"))
    plain = analyze_source(_pipeline("agent any"))
    label_finding = next(f for f in labeled.findings if f.code == "PB-ASSUME-RUNNER-LABEL")
    assert label_finding.severity == "info"
    assert (label_finding.line, label_finding.col) == (2, 5)
    assert "runs-on: [self-hosted, nodejs]" in label_finding.message
    assert "label 'nodejs'" in label_finding.message
    assert "same OS" in label_finding.message
    assert "not mapped" in label_finding.message
    assert "PB-ASSUME-RUNNER" not in [f.code for f in labeled.findings]
    assert "PB-ASSUME-RUNNER-LABEL" not in [f.code for f in plain.findings]
    assert "PB-ASSUME-RUNNER" in [f.code for f in plain.findings]

    labeled_report = build_report(labeled, source_path="Jenkinsfile", validation=None)
    plain_report = build_report(plain, source_path="Jenkinsfile", validation=None)
    assert set(labeled_report) == REPORT_KEYS == set(plain_report)
    assert set(labeled_report["findings"][0]) == FINDING_KEYS
    assert "PB-ASSUME-RUNNER-LABEL" in labeled_report["assumptions"]
    assert "PB-ASSUME-RUNNER" not in labeled_report["assumptions"]
    assert labeled_report["blockers"] == []
    assert labeled_report["exit_code"] == 0


# ---- CLI ----------------------------------------------------------------


def test_agent_label_fixture_converts_cleanly(tmp_path):
    out = tmp_path / "migration"
    assert main(["convert", str(FIXTURE), "--output", str(out)]) == 0
    workflow = (out / "workflow.yml").read_text()
    parsed = yaml.safe_load(workflow)
    job = parsed["jobs"]["migrated-pipeline"]
    assert "if" not in job
    assert job["runs-on"] == ["self-hosted", "nodejs"]
    assert [step["name"] for step in job["steps"]] == [
        "Checkout source (implicit)",
        "Install dependencies",
        "Check Style",
        "Test",
    ]
    assert [step["run"] for step in job["steps"][1:]] == [
        "npm ci",
        "npm run lint",
        "npm test",
    ]
    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 0
    assert report["summary"] == {
        "blockers": 0,
        "warnings": 0,
        "info": 5,
        "translated_stages": 3,
        "translated_steps": 3,
    }
    assert "PB-AGENT" not in [f["code"] for f in report["findings"]]
    assert "PB-ASSUME-RUNNER" not in report["assumptions"]
    assert "PB-ASSUME-RUNNER-LABEL" in report["assumptions"]
    assert set(report["assumptions"]) == {
        "PB-ASSUME-SHELL",
        "PB-SINGLE-JOB",
        "PB-TRIGGER-MANUAL",
        "PB-ASSUME-RUNNER-LABEL",
        "PB-ASSUME-CHECKOUT",
    }
    markdown = (out / "migration-report.md").read_text()
    assumptions = markdown.split("## Assumptions", 1)[1].split("## Validation", 1)[0]
    assert "### PB-ASSUME-RUNNER-LABEL —" in assumptions
    assert "### PB-ASSUME-RUNNER —" not in assumptions
    assert report["validation"]["runtime"]["performed"] is False
    assert report["translated"][0]["steps"][0]["detail"] == "npm ci"
    lint = report["validation"]["actionlint"]
    if lint["available"]:
        assert lint["ok"] is True
        assert 'label ".+" is unknown' in lint["ignored_rules"]
    else:
        assert lint["ok"] is None


@pytest.mark.parametrize(
    "label",
    ["self-hosted", "SELF-HOSTED", "Self-Hosted", "sElF-hOsTeD"],
)
def test_reserved_label_cli_keeps_disabled_ubuntu_skeleton(label, tmp_path):
    code, out = _convert(_pipeline(f"agent {{ label '{label}' }}"), tmp_path)
    assert code == 2
    workflow = (out / "workflow.yml").read_text()
    parsed = yaml.safe_load(workflow)
    job = parsed["jobs"]["migrated-pipeline"]
    assert job["if"] is False
    assert job["runs-on"] == "ubuntu-latest"
    assert "runs-on: [self-hosted," not in workflow
    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 2
    assert "PB-AGENT" in report["blockers"]
    assert "PB-ASSUME-RUNNER-LABEL" not in report["assumptions"]


def test_malformed_labeled_pipeline_exits_1_and_writes_nothing(tmp_path, capsys):
    jf = tmp_path / "Jenkinsfile"
    jf.write_text("pipeline {\n    agent { label 'nodejs' }\n}\n")
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 1
    assert not out.exists()
    assert "stages" in capsys.readouterr().err


# ---- deliberate sample transitions --------------------------------------


def test_do400_becomes_enabled_labeled_and_translated(tmp_path):
    out = tmp_path / "migration"
    assert main(["convert", str(DO400), "--output", str(out)]) == 0
    workflow = (out / "workflow.yml").read_text()
    assert workflow == GOLDEN.read_text()
    parsed = yaml.safe_load(workflow)
    job = parsed["jobs"]["migrated-pipeline"]
    assert "if" not in job
    assert job["runs-on"] == ["self-hosted", "nodejs"]
    assert [step["name"] for step in job["steps"]] == [
        "Checkout source (implicit)",
        "Install dependencies",
        "Check Style",
        "Test",
    ]
    assert [step.get("run") for step in job["steps"][1:]] == [
        "npm ci",
        "npm run lint",
        "npm test",
    ]
    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 0
    assert report["summary"]["translated_stages"] == 3
    assert report["summary"]["translated_steps"] == 3
    assert "PB-AGENT" not in report["blockers"]
    assert "PB-ASSUME-RUNNER-LABEL" in report["assumptions"]
    assert "PB-ASSUME-RUNNER" not in report["assumptions"]


def test_simple_label_synthetics_map_runner_and_keep_unrelated_blockers(tmp_path):
    expected = {
        "container-k8s-memphis-like": ("big-fleet", False),
        "infra-deploy-hmrc-like": ("docker", True),
        "node-release-tutanota-like": ("main", True),
    }
    for name, (label, keeps_stage_agent) in expected.items():
        out = tmp_path / name
        code = main(["convert", str(SYNTHETIC / f"{name}.Jenkinsfile"), "--output", str(out)])
        assert code == 2, name
        workflow = (out / "workflow.yml").read_text()
        job = yaml.safe_load(workflow)["jobs"]["migrated-pipeline"]
        assert job["if"] is False, name
        assert job["runs-on"] == ["self-hosted", label], name
        report = json.loads((out / "migration-report.json").read_text())
        agents = [f for f in report["findings"] if f["code"] == "PB-AGENT"]
        if keeps_stage_agent:
            assert agents, name
            assert all(f["line"] != _pipeline_agent_line(name) for f in agents)
        else:
            assert agents == [], name
        assert "PB-ASSUME-RUNNER-LABEL" in report["assumptions"], name
        assert report["blockers"], name


def _pipeline_agent_line(name: str) -> int:
    text = (SYNTHETIC / f"{name}.Jenkinsfile").read_text()
    return text[: text.index("agent")].count("\n") + 1


def test_expression_label_and_agent_none_are_not_relabeled(tmp_path):
    cases = {
        "python-app-couchbase-cli-like": True,
        "java-maven-jetty-like": True,
        "python-gpu-kymatio-like": True,
    }
    for name in cases:
        out = tmp_path / name
        assert main(["convert", str(SYNTHETIC / f"{name}.Jenkinsfile"), "--output", str(out)]) == 2
        workflow = (out / "workflow.yml").read_text()
        job = yaml.safe_load(workflow)["jobs"]["migrated-pipeline"]
        assert job["if"] is False
        assert job["runs-on"] == "ubuntu-latest"
        assert "runs-on: [self-hosted," not in workflow
        report = json.loads((out / "migration-report.json").read_text())
        assert "PB-AGENT" in report["blockers"]
        assert "PB-ASSUME-RUNNER-LABEL" not in report["assumptions"]
