"""CLI tests: exit codes, overwrite protection, output contract."""

import json

import pytest

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
