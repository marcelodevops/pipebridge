"""Portability tests: optional lint tooling must be handled honestly.

actionlint is an OPTIONAL local tool. The suite must pass without it, and
every availability state — present, absent, failing, unable to execute —
must be reported honestly instead of being silently treated as success.
"""

import shutil

import pytest

from pipebridge.errors import ValidationError
from pipebridge.validation import run_actionlint, validate_generated_workflow

VALID_WORKFLOW = (
    "name: valid\n"
    "on: workflow_dispatch\n"
    "permissions:\n"
    "  contents: read\n"
    "jobs:\n"
    "  job:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - run: echo 'ok'\n"
)

# Structural failure: the job has no steps section (actionlint's
# syntax-check kind — detected without shellcheck).
BROKEN_WORKFLOW = (
    "name: broken\n"
    "on: workflow_dispatch\n"
    "jobs:\n"
    "  job:\n"
    "    runs-on: ubuntu-latest\n"
)

ACTIONLINT_AVAILABLE = shutil.which("actionlint") is not None


def test_actionlint_absent_is_reported_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr("pipebridge.validation.shutil.which", lambda name: None)
    result = run_actionlint(tmp_path / "workflow.yml")
    assert result["available"] is False
    assert result["ok"] is None
    assert "not installed" in result["output"]
    assert "skipped" in result["output"]


def test_validate_generated_workflow_succeeds_without_actionlint(tmp_path, monkeypatch):
    monkeypatch.setattr("pipebridge.validation.shutil.which", lambda name: None)
    path = tmp_path / "workflow.yml"
    path.write_text(VALID_WORKFLOW)
    result = validate_generated_workflow(VALID_WORKFLOW, path)
    assert result["yaml_parse"]["ok"] is True
    assert result["actionlint"]["available"] is False
    assert result["actionlint"]["ok"] is None  # not silently treated as ok


def test_actionlint_unexecutable_is_reported_honestly(tmp_path, monkeypatch):
    """The tool exists on PATH but cannot be executed (e.g. permissions,
    broken install): the check does not run and this is reported."""
    monkeypatch.setattr(
        "pipebridge.validation.shutil.which",
        lambda name: "/nonexistent/actionlint",
    )
    result = run_actionlint(tmp_path / "workflow.yml")
    assert result["available"] is True
    assert result["ok"] is None
    assert "could not be executed" in result["output"]


@pytest.mark.skipif(
    not ACTIONLINT_AVAILABLE,
    reason="actionlint is not installed locally; absent/unexecutable cases "
    "are covered above without it",
)
def test_actionlint_present_reports_version_and_ok():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        workflow = Path(td) / "workflow.yml"
        workflow.write_text(VALID_WORKFLOW)
        result = run_actionlint(workflow)
    assert result["available"] is True
    assert result["ok"] is True
    assert result.get("version", "").startswith("1.")


@pytest.mark.skipif(
    not ACTIONLINT_AVAILABLE,
    reason="actionlint is not installed locally; the real-failure case "
    "requires the real tool",
)
def test_actionlint_reports_real_structural_failure(tmp_path):
    path = tmp_path / "broken.yml"
    path.write_text(BROKEN_WORKFLOW)
    result = run_actionlint(path)
    assert result["available"] is True
    assert result["ok"] is False
    assert result.get("structural_errors"), "a structural failure must be classified"


LABELED_WORKFLOW = VALID_WORKFLOW.replace(
    "runs-on: ubuntu-latest",
    "runs-on: [self-hosted, nodejs]",
)
BROKEN_LABELED_WORKFLOW = BROKEN_WORKFLOW.replace(
    "runs-on: ubuntu-latest",
    "runs-on: [self-hosted, nodejs]",
)


@pytest.mark.skipif(
    not ACTIONLINT_AVAILABLE,
    reason="actionlint is not installed locally; the custom-label suppression "
    "is only observable with the real tool",
)
def test_custom_self_hosted_label_is_disclosed_not_a_generation_failure(tmp_path):
    result = validate_generated_workflow(LABELED_WORKFLOW, tmp_path / "workflow.yml")
    ignored = result["actionlint"]["ignored_rules"]
    assert result["actionlint"]["ok"] is True
    assert 'label ".+" is unknown' in ignored
    assert "constant expression" not in " ".join(ignored)


@pytest.mark.skipif(
    not ACTIONLINT_AVAILABLE,
    reason="actionlint is not installed locally; the structural-failure case "
    "requires the real tool",
)
def test_self_hosted_label_does_not_hide_structural_lint_errors(tmp_path):
    with pytest.raises(ValidationError, match="failed actionlint"):
        validate_generated_workflow(BROKEN_LABELED_WORKFLOW, tmp_path / "workflow.yml")
