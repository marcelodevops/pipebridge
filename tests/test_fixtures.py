"""End-to-end tests over the synthetic fixture pipelines (real CLI path)."""

import hashlib
import json

import pytest
import yaml

from pipebridge.cli import main

FIXTURES = {
    "build-and-test": 0,
    "no-explicit-checkout": 0,
    "container-credentials": 2,
    "terraform-approval": 2,
    "k8s-custom-agent": 2,
    # Surrounding Groovy (v0.2.0): imports-only prelude is info-level and
    # does not block; every executable surrounding form blocks.
    "prelude-imports-only": 0,
    "prelude-decl-literal": 2,
    "prelude-decl-side-effect": 2,
    "postlude-functions": 2,
    "prelude-postlude-combined": 2,
    "surrounding-annotations": 2,
    "calls-to-helper": 2,
    "scripted-node": 2,
}


@pytest.fixture
def fixture_path(request):
    from pathlib import Path

    return Path(__file__).parent / "fixtures" / request.param / "Jenkinsfile"


@pytest.mark.parametrize("fixture_path", list(FIXTURES), indirect=True)
def test_fixture_exit_codes(fixture_path, tmp_path):
    out = tmp_path / "migration"
    code = main(["convert", str(fixture_path), "--output", str(out)])
    assert code == FIXTURES[fixture_path.parent.name]
    assert (out / "workflow.yml").exists()
    assert (out / "migration-report.md").exists()
    assert (out / "migration-report.json").exists()


def test_build_and_test_conversion(tmp_path):
    jf = f"{__import__('pathlib').Path(__file__).parent}/fixtures/build-and-test/Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", jf, "--output", str(out)]) == 0

    workflow_text = (out / "workflow.yml").read_text()
    parsed = yaml.safe_load(workflow_text)
    job = parsed["jobs"]["migrated-pipeline"]

    # Single job = shared workspace across sequential stages.
    assert list(parsed["jobs"]) == ["migrated-pipeline"]
    assert job["runs-on"] == "ubuntu-latest"
    names = [s["name"] for s in job["steps"]]
    assert names == [
        "Checkout source (implicit)",
        "Checkout",
        "Build",
        "Build (step 2)",
        "Build (step 3)",
        "Test",
        "Report",
    ]
    # Jenkins' default checkout is modeled before the first translated step;
    # the explicit 'checkout scm' is preserved (a later checkout can change
    # workspace state, so no deduplication).
    assert job["steps"][0]["uses"].startswith("actions/checkout@")

    # Pipeline env at job level; stage env only on that stage's steps.
    assert job["env"] == {"APP_ENV": "ci", "VERSION": "1.0.0"}
    for step in job["steps"]:
        if step["name"].startswith("Build"):
            assert step.get("env") == {"BUILD_DIR": "dist"}
        else:
            assert "env" not in step

    # Shell variables preserved verbatim, including inside multiline strings.
    test_run = next(s["run"] for s in job["steps"] if s["name"] == "Test")
    assert "export REPORTS_DIR=$PWD/reports" in test_run
    assert '"$REPORTS_DIR"' in test_run
    assert "# braces { and comments # inside the string are shell data" in test_run
    build_run = next(s["run"] for s in job["steps"] if s["name"] == "Build (step 2)")
    assert 'make build VERSION=$VERSION' in build_run

    # The Jenkins variable is preserved but flagged.
    report = json.loads((out / "migration-report.json").read_text())
    codes = [f["code"] for f in report["findings"]]
    assert "PB-JENV" in codes
    assert not report["blockers"]
    jenv = next(f for f in report["findings"] if f["code"] == "PB-JENV")
    assert "BUILD_NUMBER" in jenv["message"]
    assert (jenv["line"], jenv["col"]) == (36, 33)

    # Source hash matches the file on disk.
    on_disk = hashlib.sha256(open(jf, "rb").read()).hexdigest()
    assert report["source"]["sha256"] == on_disk

    # Validation was performed and is honest about runtime — and about
    # optional tooling: actionlint may be absent locally.
    assert report["validation"]["yaml_parse"]["ok"] is True
    actionlint = report["validation"]["actionlint"]
    if actionlint["available"]:
        assert actionlint["ok"] is True
    else:
        assert actionlint["ok"] is None
        assert "not installed" in actionlint["output"]
    assert report["validation"]["runtime"]["performed"] is False


def test_no_explicit_checkout_still_checks_out_source(tmp_path):
    """Issue 2: a pipeline with 'agent any' and no explicit 'checkout scm'
    must still get a source checkout before the build commands, and the
    report must disclose the assumption."""
    jf = f"{__import__('pathlib').Path(__file__).parent}/fixtures/no-explicit-checkout/Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", jf, "--output", str(out)]) == 0

    parsed = yaml.safe_load((out / "workflow.yml").read_text())
    steps = parsed["jobs"]["migrated-pipeline"]["steps"]
    names = [s["name"] for s in steps]
    assert names[0] == "Checkout source (implicit)"
    assert names.index("Checkout source (implicit)") < names.index("Build")
    assert steps[0]["uses"].startswith("actions/checkout@")
    assert len(steps[0]["uses"].split("@")[1].split()[0]) == 40  # full SHA

    report = json.loads((out / "migration-report.json").read_text())
    checkout = next(
        f for f in report["findings"] if f["code"] == "PB-ASSUME-CHECKOUT" and "implicit" in f["message"]
    )
    assert checkout["severity"] == "info"


def test_container_credentials_conversion(tmp_path):
    jf = f"{__import__('pathlib').Path(__file__).parent}/fixtures/container-credentials/Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", jf, "--output", str(out)]) == 2

    workflow_text = (out / "workflow.yml").read_text()
    parsed = yaml.safe_load(workflow_text)
    job = parsed["jobs"]["migrated-pipeline"]

    # Pipeline-level blocker: skeleton only, nothing extracted, job disabled.
    assert job["if"] is False
    runs = [s.get("run", "") for s in job["steps"]]
    joined = "\n".join(runs)
    assert "npm ci" not in joined
    assert "docker push" not in joined
    assert "$NPM_TOKEN" not in joined
    assert "exit 1" in joined

    report = json.loads((out / "migration-report.json").read_text())
    codes = {f["code"] for f in report["findings"] if f["severity"] == "blocker"}
    assert {"PB-AGENT", "PB-CRED"} <= codes


def test_terraform_approval_conversion(tmp_path):
    jf = f"{__import__('pathlib').Path(__file__).parent}/fixtures/terraform-approval/Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", jf, "--output", str(out)]) == 2

    parsed = yaml.safe_load((out / "workflow.yml").read_text())
    job = parsed["jobs"]["migrated-pipeline"]
    assert job["if"] is False
    assert job["env"] == {"TF_IN_AUTOMATION": "true"}
    assert isinstance(job["env"]["TF_IN_AUTOMATION"], str)

    names = [s["name"] for s in job["steps"]]
    assert names == [
        "Checkout source (implicit)",
        "Init",
        "Init (step 2)",
        "Plan",
        "Plan (step 2)",
        "[NOT MIGRATED] Deploy",
    ]

    # Translated stages keep their commands; the blocked stage does not.
    init_run = job["steps"][2]["run"]
    assert init_run == "terraform init -input=false"
    deploy_run = job["steps"][5]["run"]
    assert "terraform apply" not in deploy_run
    assert "exit 1" in deploy_run

    report = json.loads((out / "migration-report.json").read_text())
    blockers = {f["code"] for f in report["findings"] if f["severity"] == "blocker"}
    # The input gate blocks the whole Deploy stage: its steps (including the
    # interpolated echo) are never traversed, so PB-INPUT is the only blocker.
    assert blockers == {"PB-INPUT"}
    by_code = {f["code"]: f for f in report["findings"]}
    assert (by_code["PB-INPUT"]["line"], by_code["PB-INPUT"]["col"]) == (20, 13)
    jenv = next(f for f in report["findings"] if f["code"] == "PB-JENV")
    assert (jenv["line"], jenv["col"]) == (16, 42)

    assert report["exit_code"] == 2
    assert "# Stage \"Deploy\" (line 19) was NOT migrated" in (out / "workflow.yml").read_text()


def test_k8s_custom_agent_conversion(tmp_path):
    jf = f"{__import__('pathlib').Path(__file__).parent}/fixtures/k8s-custom-agent/Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", jf, "--output", str(out)]) == 2

    workflow_text = (out / "workflow.yml").read_text()
    parsed = yaml.safe_load(workflow_text)
    job = parsed["jobs"]["migrated-pipeline"]
    assert job["if"] is False

    # Nothing from the kubernetes pod template or the script block leaks.
    joined = "\n".join(s.get("run", "") for s in job["steps"])
    assert "kubectl" not in joined
    assert "bitnami" not in workflow_text
    assert "k8s/" not in joined

    report = json.loads((out / "migration-report.json").read_text())
    codes = {f["code"] for f in report["findings"] if f["severity"] == "blocker"}
    # The custom agent blocks the whole pipeline: stage bodies (including the
    # script block) are never traversed, so PB-AGENT is the only blocker.
    assert codes == {"PB-AGENT"}
    # The report says the contents were not analyzed.
    md = (out / "migration-report.md").read_text()
    assert "not analyzed" in md or "NOT migrated" in md


def test_github_expression_injection_end_to_end(tmp_path):
    jf = tmp_path / "Jenkinsfile"
    jf.write_text(
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Deploy') {\n"
        "            steps {\n"
        "                sh './deploy ${{ secrets.DEPLOY_TOKEN }}'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 0  # warning, not blocker

    workflow_text = (out / "workflow.yml").read_text()
    assert "${{ '${{' }}" in workflow_text  # neutralized in the YAML source
    parsed = yaml.safe_load(workflow_text)
    steps = parsed["jobs"]["migrated-pipeline"]["steps"]
    run = next(s["run"] for s in steps if s["name"] == "Deploy")
    # After GitHub's own substitution the shell sees the original literal.
    assert run.replace("${{ '${{' }}", "${{") == "./deploy ${{ secrets.DEPLOY_TOKEN }}"

    report = json.loads((out / "migration-report.json").read_text())
    assert "PB-GHEXPR" in [f["code"] for f in report["findings"]]
