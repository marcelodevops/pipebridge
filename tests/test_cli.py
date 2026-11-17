"""CLI tests: exit codes, overwrite protection, output contract."""

import json

import pytest
import yaml

from pipebridge.cli import main

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

BLOCKED = (
    "pipeline {\n"
    "    agent any\n"
    "    stages {\n"
    "        stage('Deploy') {\n"
    "            steps {\n"
    "                script {\n"
    "                    sh 'x'\n"
    "                }\n"
    "            }\n"
    "        }\n"
    "    }\n"
    "}\n"
)


@pytest.fixture
def jenkinsfile(tmp_path):
    path = tmp_path / "Jenkinsfile"
    path.write_text(CLEAN)
    return path


# ---- version ------------------------------------------------------------

def test_version_flag(capsys):
    code = main(["--version"])
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("pipebridge ")


# ---- analyze ------------------------------------------------------------

def test_analyze_clean_exit_zero(jenkinsfile, capsys):
    assert main(["analyze", str(jenkinsfile)]) == 0
    out = capsys.readouterr().out
    assert "converted without blockers" in out or "assumption" in out.lower()


def test_analyze_blocked_exit_two(tmp_path):
    path = tmp_path / "Jenkinsfile"
    path.write_text(BLOCKED)
    assert main(["analyze", str(path)]) == 2


def test_analyze_json_format(jenkinsfile, capsys):
    assert main(["analyze", str(jenkinsfile), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tool"]["name"] == "pipebridge"
    assert data["source"]["sha256"]
    assert "confidence" not in json.dumps(data).lower()


def test_analyze_missing_file_exit_one(tmp_path, capsys):
    code = main(["analyze", str(tmp_path / "nope")])
    assert code == 1


def test_analyze_malformed_exit_one(tmp_path):
    path = tmp_path / "Jenkinsfile"
    path.write_text("sh 'unterminated")
    assert main(["analyze", str(path)]) == 1


def test_analyze_text_format_mentions_findings(jenkinsfile, capsys):
    assert main(["analyze", str(jenkinsfile)]) == 0
    out = capsys.readouterr().out
    assert "PB-" in out


# ---- convert ------------------------------------------------------------

def test_convert_generates_all_outputs(jenkinsfile, tmp_path):
    out = tmp_path / "migration"
    code = main(["convert", str(jenkinsfile), "--output", str(out)])
    assert code == 0
    assert (out / "workflow.yml").exists()
    assert (out / "migration-report.md").exists()
    assert (out / "migration-report.json").exists()
    import yaml

    parsed = yaml.safe_load((out / "workflow.yml").read_text())
    assert "migrated-pipeline" in parsed["jobs"]


def test_convert_blocked_exit_two_but_writes_outputs(tmp_path):
    jf = tmp_path / "Jenkinsfile"
    jf.write_text(BLOCKED)
    out = tmp_path / "migration"
    code = main(["convert", str(jf), "--output", str(out)])
    assert code == 2
    assert (out / "workflow.yml").exists()
    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 2
    import yaml

    parsed = yaml.safe_load((out / "workflow.yml").read_text())
    assert parsed["jobs"]["migrated-pipeline"]["if"] is False


def test_convert_never_overwrites_by_default(jenkinsfile, tmp_path):
    out = tmp_path / "migration"
    assert main(["convert", str(jenkinsfile), "--output", str(out)]) == 0
    guard = out / "workflow.yml"
    guard.write_text("user content")
    code = main(["convert", str(jenkinsfile), "--output", str(out)])
    assert code == 1
    assert guard.read_text() == "user content"  # untouched
    # The user's unrelated files are left alone too.
    (out / "keep.txt").write_text("precious")
    assert (out / "keep.txt").read_text() == "precious"


def test_convert_force_replaces_outputs(jenkinsfile, tmp_path):
    out = tmp_path / "migration"
    assert main(["convert", str(jenkinsfile), "--output", str(out)]) == 0
    (out / "workflow.yml").write_text("stale")
    code = main(["convert", str(jenkinsfile), "--output", str(out), "--force"])
    assert code == 0
    assert "stale" not in (out / "workflow.yml").read_text()


def test_convert_malformed_writes_nothing(tmp_path):
    jf = tmp_path / "Jenkinsfile"
    jf.write_text("sh 'unterminated")
    out = tmp_path / "migration"
    code = main(["convert", str(jf), "--output", str(out)])
    assert code == 1
    assert not (out / "workflow.yml").exists()
    assert not out.exists() or not any(out.iterdir())


def test_convert_output_path_is_a_file_fails(jenkinsfile, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    code = main(["convert", str(jenkinsfile), "--output", str(blocker)])
    assert code == 1


def test_convert_blocked_pipeline_skeleton_writes_no_steps(tmp_path):
    jf = tmp_path / "Jenkinsfile"
    jf.write_text(
        "pipeline {\n"
        "    agent {\n"
        "        docker {\n"
        "            image 'node:20'\n"
        "        }\n"
        "    }\n"
        "    stages {\n"
        "        stage('Build') {\n"
        "            steps {\n"
        "                sh 'make secret-sauce'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    out = tmp_path / "migration"
    code = main(["convert", str(jf), "--output", str(out)])
    assert code == 2
    workflow = (out / "workflow.yml").read_text()
    assert "make secret-sauce" not in workflow  # never extracted


def test_usage_error_exits_one(capsys):
    code = main(["analyze"])  # missing required argument
    assert code == 1


def test_unknown_command_exits_one(capsys):
    assert main(["frobnicate"]) == 1


# ---- required structure: malformed (1) vs valid-but-unsupported (2) ------

MALFORMED_CASES = {
    "missing-stages": "pipeline {\n    agent any\n}\n",
    "empty-stages": "pipeline {\n    agent any\n    stages {\n    }\n}\n",
    "stage-without-steps": (
        "pipeline {\n    agent any\n    stages {\n        stage('A') {\n"
        "            environment {\n                X = 'y'\n            }\n"
        "        }\n    }\n}\n"
    ),
    "empty-steps": (
        "pipeline {\n    agent any\n    stages {\n        stage('A') {\n"
        "            steps {\n            }\n        }\n    }\n}\n"
    ),
    "empty-file": "",
}


@pytest.mark.parametrize("label", sorted(MALFORMED_CASES))
def test_malformed_structure_exits_one_and_writes_nothing(tmp_path, label):
    jf = tmp_path / "Jenkinsfile"
    jf.write_text(MALFORMED_CASES[label])
    out = tmp_path / "migration"
    assert main(["analyze", str(jf)]) == 1
    assert main(["convert", str(jf), "--output", str(out)]) == 1
    assert not out.exists() or not any(out.iterdir())


def test_scripted_pipeline_converts_to_valid_disabled_draft(tmp_path):
    """Scripted pipelines are valid but unsupported: exit 2, and the
    generated draft must remain a structurally valid, disabled workflow."""
    jf = tmp_path / "Jenkinsfile"
    jf.write_text("node {\n    sh 'deploy-to-production'\n}\n")
    out = tmp_path / "migration"
    assert main(["analyze", str(jf)]) == 2
    assert main(["convert", str(jf), "--output", str(out)]) == 2

    workflow = (out / "workflow.yml").read_text()
    parsed = yaml.safe_load(workflow)
    job = parsed["jobs"]["migrated-pipeline"]
    assert job["if"] is False  # disabled
    assert job["steps"], "draft must contain a steps section"
    joined = "\n".join(s.get("run", "") for s in job["steps"])
    assert "exit 1" in joined  # placeholder fails loudly
    assert "deploy-to-production" not in joined  # never extracted

    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 2


# ---- safe staged writes with rollback (issue 4) --------------------------

import os
import uuid as _uuid

from pipebridge.cli import _write_all
from pipebridge.errors import PipebridgeError

ITEMS_CONTENT = {"workflow.yml": "WF-V2", "migration-report.md": "MD-V2", "migration-report.json": "JS-V2"}
PREVIOUS = {"workflow.yml": "PRECIOUS-WF-V1", "migration-report.md": "PRECIOUS-MD-V1"}


def _make_items(out):
    return [(out / name, content) for name, content in ITEMS_CONTENT.items()]


def _assert_no_temp_files(out):
    leftovers = [p.name for p in out.iterdir() if ".tmp" in p.name or ".bak" in p.name]
    assert leftovers == [], f"temporary files not cleaned: {leftovers}"


def test_write_all_rejects_targets_equal_to_input(tmp_path):
    jf = tmp_path / "Jenkinsfile"
    jf.write_text("pipeline {}")
    with pytest.raises(PipebridgeError, match="input Jenkinsfile"):
        _write_all([(jf, "EVIL")], protected=jf)


def test_write_all_rejects_symlink_target_pointing_at_input(tmp_path):
    jf = tmp_path / "Jenkinsfile"
    jf.write_text("pipeline {}")
    out = tmp_path / "out"
    out.mkdir()
    (out / "workflow.yml").symlink_to(jf)
    with pytest.raises(PipebridgeError, match="input Jenkinsfile"):
        _write_all(_make_items(out), protected=jf)
    assert jf.read_text() == "pipeline {}"


def test_write_all_success_replaces_and_cleans_backups(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "unrelated.txt").write_text("keep me")
    (out / "workflow.yml").write_text(PREVIOUS["workflow.yml"])
    _write_all(_make_items(out), protected=tmp_path / "Jenkinsfile")
    assert (out / "workflow.yml").read_text() == "WF-V2"
    assert (out / "migration-report.md").read_text() == "MD-V2"
    assert (out / "unrelated.txt").read_text() == "keep me"
    _assert_no_temp_files(out)


def test_write_all_commit_failure_restores_previous_bytes(tmp_path, monkeypatch):
    """A handled rename failure at any commit position must restore the
    previous output set byte-for-byte, remove newly introduced outputs,
    clean temp files, and leave unrelated files alone."""
    out = tmp_path / "out"
    for position in (1, 2, 3):
        out.mkdir(exist_ok=True)
        for name, content in PREVIOUS.items():
            (out / name).write_text(content)
        (out / "unrelated.txt").write_text("keep me")
        (out / "migration-report.json").unlink(missing_ok=True)

        real_replace = os.replace
        calls = {"n": 0}

        def flaky(src, dst, _pos=position, _real=real_replace):
            calls["n"] += 1
            if calls["n"] == _pos:
                raise OSError(f"simulated failure at commit #{_pos}")
            return _real(src, dst)

        monkeypatch.setattr(os, "replace", flaky)
        with pytest.raises(PipebridgeError):
            _write_all(_make_items(out), protected=tmp_path / "Jenkinsfile")
        monkeypatch.undo()

        assert (out / "workflow.yml").read_text() == PREVIOUS["workflow.yml"]
        assert (out / "migration-report.md").read_text() == PREVIOUS["migration-report.md"]
        assert not (out / "migration-report.json").exists()
        assert (out / "unrelated.txt").read_text() == "keep me"
        _assert_no_temp_files(out)


def test_write_all_commit_failure_without_existing_outputs_leaves_nothing(tmp_path, monkeypatch):
    out = tmp_path / "out"
    for position in (1, 2, 3):
        out.mkdir(exist_ok=True)
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(src, dst, _pos=position, _real=real_replace):
            calls["n"] += 1
            if calls["n"] == _pos:
                raise OSError(f"simulated failure at commit #{_pos}")
            return _real(src, dst)

        monkeypatch.setattr(os, "replace", flaky)
        with pytest.raises(PipebridgeError):
            _write_all(_make_items(out), protected=tmp_path / "Jenkinsfile")
        monkeypatch.undo()

        assert not any(out.iterdir()), "no artifacts may survive a failed run"


def test_write_all_staging_failure_touches_nothing(tmp_path, monkeypatch):
    """A failure while STAGING (before any commit) must leave existing
    outputs byte-for-byte and create no partial files."""
    out = tmp_path / "out"
    out.mkdir()
    for name, content in PREVIOUS.items():
        (out / name).write_text(content)

    real_write = __import__("pathlib").Path.write_text
    calls = {"n": 0}

    def flaky_write(self, data, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:  # second staged file fails
            raise OSError("simulated staging failure")
        return real_write(self, data, *a, **kw)

    monkeypatch.setattr("pathlib.Path.write_text", flaky_write)
    with pytest.raises(PipebridgeError):
        _write_all(_make_items(out), protected=tmp_path / "Jenkinsfile")
    monkeypatch.undo()

    for name, content in PREVIOUS.items():
        assert (out / name).read_text() == content
    assert not (out / "migration-report.json").exists()
    _assert_no_temp_files(out)
