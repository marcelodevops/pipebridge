"""Tests for validation and reporting."""

import json

import pytest
import yaml

from pipebridge.analysis import analyze_source
from pipebridge.reporting import build_report, render_markdown_report
from pipebridge.validation import run_actionlint, validate_yaml_text

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


def make_analysis(source=CLEAN):
    return analyze_source(source)


# ---- validation ---------------------------------------------------------

def test_validate_yaml_text_ok():
    result = validate_yaml_text("name: x\non:\n  workflow_dispatch:\n")
    assert result["ok"] is True
    assert result["error"] is None


def test_validate_yaml_text_rejects_broken_yaml():
    result = validate_yaml_text("foo: [unclosed\n  bar: {")
    assert result["ok"] is False
    assert result["error"]


def test_run_actionlint_when_available(tmp_path):
    import shutil

    if shutil.which("actionlint") is None:
        pytest.skip("actionlint not installed")
    path = tmp_path / "workflow.yml"
    path.write_text(
        "name: t\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  a:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo hi\n"
    )
    result = run_actionlint(path)
    assert result["available"] is True
    assert result["ok"] is True
    assert result["exit_code"] == 0


def test_run_actionlint_reports_lint_failures(tmp_path):
    import shutil

    if shutil.which("actionlint") is None:
        pytest.skip("actionlint not installed")
    path = tmp_path / "workflow.yml"
    path.write_text(
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n      - run: echo hi\n"
    )
    result = run_actionlint(path)
    assert result["available"] is True
    assert result["ok"] is False


# ---- reports ------------------------------------------------------------

def test_json_report_shape_and_no_confidence():
    analysis = make_analysis()
    report = build_report(
        analysis,
        source_path="/repo/Jenkinsfile",
        validation={"yaml_parse": {"ok": True, "error": None}, "actionlint": {"available": False}, "runtime": {"performed": False}},
    )
    text = json.dumps(report)
    data = json.loads(text)
    assert data["tool"]["name"] == "pipebridge"
    assert data["tool"]["version"]
    assert data["source"]["sha256"]
    assert data["source"]["path"] == "/repo/Jenkinsfile"
    assert data["summary"]["blockers"] == 0
    assert data["findings"][0]["code"]
    assert data["findings"][0]["severity"] in ("blocker", "warning", "info")
    assert "confidence" not in text.lower()
    # Runtime honesty: never claim execution.
    assert data["validation"]["runtime"]["performed"] is False


def test_json_report_counts_blockers_and_exit_code():
    source = CLEAN.replace("sh 'make build'", "script {\n                    sh 'x'\n                }")
    analysis = make_analysis(source)
    report = build_report(analysis, source_path="Jenkinsfile", validation=None)
    assert report["summary"]["blockers"] >= 1
    assert report["exit_code"] == 2


def test_json_report_lists_translated_items():
    analysis = make_analysis()
    report = build_report(analysis, source_path="Jenkinsfile", validation=None)
    translated = report["translated"]
    assert translated[0]["stage"] == "Build"
    assert translated[0]["steps"][0]["kind"] in ("sh", "echo", "checkout")


def test_markdown_report_contains_required_sections():
    analysis = make_analysis()
    report = build_report(analysis, source_path="Jenkinsfile", validation=None)
    md = render_markdown_report(report)
    assert "# Migration report" in md
    assert "## Summary" in md
    assert "## Translated items" in md
    assert "## Assumptions" in md
    assert "## Blockers" in md
    assert "## Warnings" in md
    assert "## Validation" in md
    assert "sha256" in md
    assert "NOT performed" in md or "not performed" in md.lower()
    assert "confidence" not in md.lower()


def test_markdown_report_blocker_details():
    source = CLEAN.replace("sh 'make build'", "withCredentials([string(credentialsId: 'c', usernameVariable: 'U')]) {\n                    sh 'push'\n                }")
    analysis = make_analysis(source)
    report = build_report(analysis, source_path="Jenkinsfile", validation=None)
    md = render_markdown_report(report)
    assert "PB-CRED" in md
    assert "line 6" in md
    assert "Next action" in md


def test_report_validation_section_distinguishes_levels():
    analysis = make_analysis()
    report = build_report(
        analysis,
        source_path="Jenkinsfile",
        validation={
            "yaml_parse": {"ok": True, "error": None},
            "actionlint": {"available": True, "ok": True, "exit_code": 0, "output": ""},
            "runtime": {"performed": False},
        },
    )
    md = render_markdown_report(report)
    assert "YAML parse" in md
    assert "actionlint" in md
    # Runtime validation is explicitly NOT claimed.
    assert "not performed" in md.lower()


def test_analyze_style_report_has_no_workflow_validation():
    analysis = make_analysis()
    report = build_report(analysis, source_path="Jenkinsfile", validation=None)
    assert report["validation"]["runtime"]["performed"] is False
