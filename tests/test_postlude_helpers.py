"""Tests for Jenkinsfile postlude helper translation via shared-library lowering."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from pipebridge import findings as F
from pipebridge.analysis import analyze_source
from pipebridge.cli import main
from pipebridge.librarymap import load_library_map
from pipebridge.workflow import generate_workflow

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPERS_DIR = REPO_ROOT / "examples" / "jenkinsfile-helpers"


def _run_workflow_steps(
    wf_text: str,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    data = yaml.safe_load(wf_text)
    job = data["jobs"]["migrated-pipeline"]
    assert "if" not in job
    steps = job["steps"]
    assert steps[0]["uses"].startswith("actions/checkout@")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
        "GITHUB_WORKSPACE": str(cwd),
        "RUNNER_TEMP": str(cwd / ".runner_temp"),
    }
    if extra_env:
        env.update(extra_env)
    (cwd / ".runner_temp").mkdir(exist_ok=True)

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    rc = 0
    for step in steps[1:]:
        if "run" not in step:
            continue
        is_always = step.get("if") == "always()"
        if rc != 0 and not is_always:
            continue
        step_env = dict(env)
        for k, v in (step.get("env") or {}).items():
            # Resolve synthetic ${{ secrets.NAME }} from extra_env when testing locally.
            if isinstance(v, str) and v.startswith("${{ secrets.") and v.endswith(" }}"):
                sec_name = v[len("${{ secrets.") : -len(" }}")].strip()
                step_env[k] = (extra_env or {}).get(sec_name, "")
            else:
                step_env[k] = str(v)
        proc = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
            cwd=cwd,
            env=step_env,
            capture_output=True,
            text=True,
            check=False,
        )
        stdout_parts.append(proc.stdout)
        stderr_parts.append(proc.stderr)
        if proc.returncode != 0 and not step.get("continue-on-error"):
            if rc == 0:
                rc = proc.returncode
    return subprocess.CompletedProcess(
        args=["workflow"],
        returncode=rc,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
    )


def test_success_fixture_converts_reuses_scripts_and_executes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src_jf = HELPERS_DIR / "success" / "Jenkinsfile"
    local_jf = tmp_path / "Jenkinsfile"
    shutil.copy2(src_jf, local_jf)

    out_dir = Path("migration")
    rc = main(["convert", str(local_jf), "--output", str(out_dir)])
    assert rc == 0
    capsys.readouterr()

    wf_text = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert "if: false" not in wf_text

    marker_script = out_dir / "scripts" / "_jenkinsfile" / "writeReleaseMarker-1.sh"
    echo_script = out_dir / "scripts" / "_jenkinsfile" / "publishChannel-1.sh"
    assert marker_script.is_file()
    assert echo_script.is_file()

    marker_body = marker_script.read_text(encoding="utf-8")
    echo_body = echo_script.read_text(encoding="utf-8")
    assert "${1}" in marker_body and "${2}" in marker_body
    assert "${1}" in echo_body and "${2}" in echo_body
    for literal in ("alpha", "beta", "build-1", "build-2"):
        assert literal not in marker_body
        assert literal not in echo_body

    # Both calls in workflow.yml reuse the same two generated script paths.
    assert wf_text.count("migration/scripts/_jenkinsfile/writeReleaseMarker-1.sh") == 2
    assert wf_text.count("migration/scripts/_jenkinsfile/publishChannel-1.sh") == 2

    report = json.loads((out_dir / "migration-report.json").read_text(encoding="utf-8"))
    assert report["exit_code"] == 0
    assert report["summary"]["blockers"] == 0
    assert len(report["libraries"]["calls"]) == 2
    assert all(c["status"] == "resolved" for c in report["libraries"]["calls"])
    assert report["libraries"]["calls"][0]["chain"] == [
        f"{local_jf}:publishChannel@6:17",
    ]
    assert report["translated"][0]["steps"][0]["script_path"] == "scripts/_jenkinsfile/writeReleaseMarker-1.sh"
    assert report["translated"][0]["steps"][0]["args"] == ["alpha", "build-1"]
    if shutil.which("actionlint") is not None:
        assert report["validation"]["actionlint"]["ok"] is True

    proc = _run_workflow_steps(wf_text, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "published alpha:build-1\npublished beta:build-2\n"
    assert (tmp_path / "dist" / "alpha.txt").read_text(encoding="utf-8") == "alpha:build-1"
    assert (tmp_path / "dist" / "beta.txt").read_text(encoding="utf-8") == "beta:build-2"


@pytest.mark.parametrize(
    "fixture_name,expected_codes,expected_substring,needs_lib_map",
    [
        (
            "unsupported-body.Jenkinsfile",
            ["PB-LIB-CALL"],
            "Unsupported library statement at line 13: 'script'.",
            False,
        ),
        (
            "captured-variable.Jenkinsfile",
            ["PB-GROOVY-PRELUDE", "PB-INTERP"],
            "Unsupported interpolation in library sh: '${GLOBAL_ENV}'.",
            False,
        ),
        (
            "recursion.Jenkinsfile",
            ["PB-LIB-CALL"],
            "Library call cycle:",
            False,
        ),
        (
            "collision-builtin.Jenkinsfile",
            ["PB-LIB-CALL"],
            "Postlude helper 'sh' shadows a built-in step.",
            False,
        ),
        (
            "collision-library-var.Jenkinsfile",
            ["PB-LIB-CALL"],
            "Postlude helper 'publish' collides with library var",
            True,
        ),
        (
            "collision-duplicate-helper.Jenkinsfile",
            ["PB-LIB-CALL"],
            "Postlude helper 'deploy' is defined more than once.",
            False,
        ),
        (
            "mixed-executable-postlude.Jenkinsfile",
            ["PB-GROOVY-POSTLUDE", "PB-GROOVY-POSTLUDE"],
            "executable; pipebridge does not evaluate or translate it",
            False,
        ),
    ],
)
def test_negative_fixtures_exit_2_without_spurious_unused_helper_findings(
    fixture_name,
    expected_codes,
    expected_substring,
    needs_lib_map,
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    jf = HELPERS_DIR / "negative" / fixture_name
    out_dir = Path("migration")
    argv = ["convert", str(jf), "--output", str(out_dir)]
    if needs_lib_map:
        lib_map = REPO_ROOT / "examples" / "shared-library" / "success" / "library-map.json"
        argv.extend(["--library-map", str(lib_map)])

    rc = main(argv)
    assert rc == 2
    capsys.readouterr()

    wf_text = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert "if: false" in wf_text
    assert not (out_dir / "scripts").exists()

    report = json.loads((out_dir / "migration-report.json").read_text(encoding="utf-8"))
    blockers = [f for f in report["findings"] if f["severity"] == "blocker"]
    assert [f["code"] for f in blockers] == expected_codes
    assert any(expected_substring in f["message"] for f in blockers)


def test_transitive_failing_helper_and_cleared_stage_produce_no_spurious_unused_finding():
    # Case 1: helperA calls helperB, and helperB fails internally.
    # Both helperA and helperB were visited and must not emit PB-GROOVY-POSTLUDE.
    source_failing_callee = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Run') {\n"
        "            steps {\n"
        "                outerHelper('val')\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def outerHelper(String x) {\n"
        "    innerHelper(x)\n"
        "}\n"
        "def innerHelper(String x) {\n"
        "    script { echo \"${x}\" }\n"
        "}\n"
    )
    res1 = analyze_source(source_failing_callee, source_path="Jenkinsfile")
    blockers1 = [f for f in res1.findings if f.is_blocker]
    assert [f.code for f in blockers1] == [F.PB_LIB_CALL]
    assert blockers1[0].call_chain == (
        "Jenkinsfile:outerHelper@6:17",
        "Jenkinsfile:innerHelper@12:5",
    )

    # Case 2: outerHelper -> innerHelper succeeds, then an unrelated step in the
    # same stage blocks and clears the stage. Neither helper is reported unused.
    source_cleared_stage = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Run') {\n"
        "            steps {\n"
        "                outerHelper('val')\n"
        "                script { println 'block stage' }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def outerHelper(String x) {\n"
        "    innerHelper(x)\n"
        "}\n"
        "def innerHelper(String x) {\n"
        "    sh \"printf '%s' \\\"${x}\\\"\"\n"
        "}\n"
    )
    res2 = analyze_source(source_cleared_stage, source_path="Jenkinsfile")
    blockers2 = [f for f in res2.findings if f.is_blocker]
    assert [f.code for f in blockers2] == [F.PB_SCRIPT]
    assert res2.pipeline.stages[0].blocked is True
    assert res2.pipeline.stages[0].steps == []

    # Case 3: helper called ONLY after a stage is already blocked (diagnostic walk)
    # is NOT visited by Resolver and must emit PB-GROOVY-POSTLUDE.
    source_diag_only = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('BlockedFirst') {\n"
        "            steps {\n"
        "                script { println 'blocks before helper' }\n"
        "                diagOnlyHelper('val')\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def diagOnlyHelper(String x) {\n"
        "    sh \"printf '%s' \\\"${x}\\\"\"\n"
        "}\n"
    )
    res3 = analyze_source(source_diag_only, source_path="Jenkinsfile")
    codes3 = [f.code for f in res3.findings if f.is_blocker]
    assert F.PB_SCRIPT in codes3
    assert F.PB_GROOVY_POSTLUDE in codes3


def test_depth_cap_reserved_call_and_bare_captured_argument_rejected():
    # Reserved 'def call()' in a Jenkinsfile postlude is rejected with PB-LIB-CALL.
    reserved_call = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('A') {\n"
        "            steps {\n"
        "                echo 'hi'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def call() {\n"
        "    sh 'echo reserved'\n"
        "}\n"
    )
    res_call = analyze_source(reserved_call, source_path="Jenkinsfile")
    call_blockers = [f for f in res_call.findings if f.is_blocker]
    assert [f.code for f in call_blockers] == [F.PB_LIB_CALL]
    assert "reserved for shared-library" in call_blockers[0].message

    # Bare non-parameter identifier passed to sh(GLOBAL) or another helper is PB-LIB-CALL.
    bare_capture = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('A') {\n"
        "            steps {\n"
        "                runCaptured()\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def runCaptured() {\n"
        "    sh(GLOBAL_CMD)\n"
        "}\n"
    )
    res_cap = analyze_source(bare_capture, source_path="Jenkinsfile")
    assert [f.code for f in res_cap.findings if f.is_blocker] == [F.PB_LIB_CALL]

    # Call chain of depth 21 exceeds LIBRARY_CALL_DEPTH_CAP (20).
    helpers = "\n".join(
        f"def h{i}(String x) {{ h{i + 1}(x) }}" for i in range(1, 21)
    ) + "\ndef h21(String x) { sh \"echo ${x}\" }\n"
    deep_source = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Deep') {\n"
        "            steps {\n"
        "                h1('ok')\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        + helpers
    )
    res_deep = analyze_source(deep_source, source_path="Jenkinsfile")
    deep_blockers = [f for f in res_deep.findings if f.is_blocker]
    assert [f.code for f in deep_blockers] == [F.PB_LIB_CALL]
    assert "depth exceeded 20 at 'h21'" in deep_blockers[0].message
    assert len(deep_blockers[0].call_chain) == 21


def test_quoting_expression_neutralization_and_failure_propagation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    tricky = "a'b \"c\"  $HOME $(id) `uname` ${{ secrets.EXAMPLE }}\nline2"
    jf = tmp_path / "Jenkinsfile"
    jf.write_text(
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Quote') {\n"
        "            steps {\n"
        "                writeTricky('''" + tricky + "''')\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def writeTricky(String payload) {\n"
        "    sh 'printf \"%s\" \"${1}\" > tricky.txt'\n"
        "    sh \"printf '%s' \\\"${payload}\\\" > tricky.txt\"\n"
        "}\n",
        encoding="utf-8",
    )
    out_dir = Path("migration")
    assert main(["convert", str(jf), "--output", str(out_dir)]) == 0
    capsys.readouterr()

    wf_text = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert "${{" not in wf_text
    script_body = (out_dir / "scripts" / "_jenkinsfile" / "writeTricky-2.sh").read_text(encoding="utf-8")
    assert "${{" not in script_body

    report = json.loads((out_dir / "migration-report.json").read_text(encoding="utf-8"))
    assert "PB-GHEXPR" in [f["code"] for f in report["findings"]]

    proc = _run_workflow_steps(wf_text, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "tricky.txt").read_text(encoding="utf-8") == tricky

    # Failure propagation: false; printf SHOULD_NOT_RUN and failing pipeline.
    fail_jf = tmp_path / "Fail.Jenkinsfile"
    fail_jf.write_text(
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Fail') {\n"
        "            steps {\n"
        "                failPipeline()\n"
        "                sh 'printf SHOULD_NOT_RUN_STEP > after.txt'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def failPipeline() {\n"
        "    sh 'exit 9 | cat; printf SHOULD_NOT_RUN_CMD > inside.txt'\n"
        "}\n",
        encoding="utf-8",
    )
    fail_out = Path("fail-migration")
    assert main(["convert", str(fail_jf), "--output", str(fail_out)]) == 0
    capsys.readouterr()
    fail_wf = (fail_out / "workflow.yml").read_text(encoding="utf-8")
    fail_proc = _run_workflow_steps(fail_wf, tmp_path)
    assert fail_proc.returncode == 9
    assert not (tmp_path / "inside.txt").exists()
    assert not (tmp_path / "after.txt").exists()


def test_postlude_helper_credentials_stash_and_stage_clearing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cred_map = tmp_path / "credential-map.json"
    cred_map.write_text(
        json.dumps({"schema_version": 1, "credentials": {"api-token": {"secret": "API_TOKEN_GH"}}}),
        encoding="utf-8",
    )
    jf = tmp_path / "Jenkinsfile"
    jf.write_text(
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Build') {\n"
        "            steps {\n"
        "                buildAndStash('v1')\n"
        "            }\n"
        "        }\n"
        "        stage('Restore') {\n"
        "            steps {\n"
        "                sh 'rm -rf dist'\n"
        "                restoreAndCheck('v1')\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def buildAndStash(String ver) {\n"
        "    sh \"mkdir -p dist && printf '%s' \\\"${ver}\\\" > dist/version.txt\"\n"
        "    withCredentials([string(credentialsId: 'api-token', variable: 'API_TOKEN')]) {\n"
        "        sh 'test -n \"$API_TOKEN\" && printf ok > dist/auth.txt'\n"
        "    }\n"
        "    stash name: 'bundle', includes: 'dist/**'\n"
        "}\n"
        "def restoreAndCheck(String ver) {\n"
        "    unstash 'bundle'\n"
        "    sh \"test \\\"\\$(cat dist/version.txt)\\\" = \\\"${ver}\\\" && test \\\"\\$(cat dist/auth.txt)\\\" = ok\"\n"
        "}\n",
        encoding="utf-8",
    )
    out_dir = Path("migration")

    # Without --secrets-ready: exit 2, PB-CRED-SETUP, disabled draft, scripts still reviewable.
    rc_unready = main([
        "convert",
        str(jf),
        "--output",
        str(out_dir),
        "--credential-map",
        str(cred_map),
    ])
    assert rc_unready == 2
    capsys.readouterr()
    wf_unready = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert "if: false" in wf_unready
    assert (out_dir / "scripts" / "_jenkinsfile" / "buildAndStash-1.sh").is_file()
    assert (out_dir / "scripts" / "_jenkinsfile" / "buildAndStash-2.sh").is_file()
    assert (out_dir / "scripts" / "pipebridge_stash.py").is_file()
    assert (out_dir / "scripts" / "pipebridge_unstash.py").is_file()

    # With --secrets-ready and --force: exit 0, enabled workflow, credential scoped to step 2 only.
    rc_ready = main([
        "convert",
        str(jf),
        "--output",
        str(out_dir),
        "--credential-map",
        str(cred_map),
        "--secrets-ready",
        "--force",
    ])
    assert rc_ready == 0
    capsys.readouterr()
    wf_ready = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert "if: false" not in wf_ready
    parsed_wf = yaml.safe_load(wf_ready)
    steps = parsed_wf["jobs"]["migrated-pipeline"]["steps"]
    env_steps = [s for s in steps if "env" in s]
    assert len(env_steps) == 1
    assert env_steps[0]["env"] == {"API_TOKEN": "${{ secrets.API_TOKEN_GH }}"}
    assert "buildAndStash-2.sh" in env_steps[0]["run"]
    assert steps[-1]["name"] == "Remove pipebridge stash"
    assert steps[-1]["if"] == "always()"

    proc = _run_workflow_steps(wf_ready, tmp_path, extra_env={"API_TOKEN_GH": "synthetic-secret"})
    assert proc.returncode == 0, proc.stderr
    assert "synthetic-secret" not in proc.stdout
    assert "synthetic-secret" not in proc.stderr
    assert (tmp_path / "dist" / "version.txt").read_text(encoding="utf-8") == "v1"
    assert (tmp_path / "dist" / "auth.txt").read_text(encoding="utf-8") == "ok"
    assert not (tmp_path / ".runner_temp" / "pipebridge-stash").exists()


def test_overwrite_refusal_containment_and_rollback_for_postlude_scripts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    jf = tmp_path / "Jenkinsfile"
    jf.write_text(
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Build') {\n"
        "            steps {\n"
        "                runHelper('v1')\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def runHelper(String v) {\n"
        "    sh \"echo ${v}\"\n"
        "}\n",
        encoding="utf-8",
    )

    # Containment: absolute --output or '..' segment must fail with exit 1.
    for bad_out in (str(tmp_path / "abs-out"), "../escape"):
        assert main(["convert", str(jf), "--output", bad_out]) == 1
        assert "--output must be a relative path" in capsys.readouterr().err

    out_dir = Path("migration")
    assert main(["convert", str(jf), "--output", str(out_dir)]) == 0
    capsys.readouterr()

    script_file = out_dir / "scripts" / "_jenkinsfile" / "runHelper-1.sh"
    assert script_file.read_text(encoding="utf-8") == "echo ${1}\n"

    # Without --force: refused (exit 1), existing bytes untouched.
    jf.write_text(jf.read_text(encoding="utf-8").replace("echo ${v}", "printf '%s\\n' ${v}"), encoding="utf-8")
    assert main(["convert", str(jf), "--output", str(out_dir)]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err
    assert script_file.read_text(encoding="utf-8") == "echo ${1}\n"

    # Rollback on injected commit failure during --force replacement.
    real_replace = os.replace

    def fail_on_script_replace(src, dst):
        if str(dst).endswith("runHelper-1.sh") and ".pb-backup-" not in str(src):
            raise OSError("injected script commit failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_on_script_replace)
    assert main(["convert", str(jf), "--output", str(out_dir), "--force"]) == 1
    err = capsys.readouterr().err
    assert "rolled back completely" in err
    assert script_file.read_text(encoding="utf-8") == "echo ${1}\n"


def test_stage_blocker_attribution_via_root_call_chain_and_compatibility(tmp_path):
    # 1. Multi-stage postlude helper blocker in Stage 1 (whose helper body is at line 18,
    # after Stage 2 at line 11) must attribute PB-LIB-CALL to Stage 1, leaving Stage 2 clean.
    postlude_multi = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('First') {\n"
        "            steps {\n"
        "                badHelper()\n"
        "            }\n"
        "        }\n"
        "        stage('Second') {\n"
        "            steps {\n"
        "                sh 'echo second stage survives'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "def badHelper() {\n"
        "    script { println 'bad' }\n"
        "}\n"
    )
    res_post = analyze_source(postlude_multi, source_path="Jenkinsfile")
    wf_post = generate_workflow(res_post, source_name="Jenkinsfile")
    assert '# Stage "First" (line 4) was NOT migrated: it contains\n      # unsupported constructs (PB-LIB-CALL).' in wf_post
    assert "echo second stage survives" in wf_post

    # 2. Multi-stage shared-library blocker in Stage 2 (where vars/fail.groovy line 1
    # is < Stage 1 line 5) must attribute PB-LIB-CALL to Stage 2, not Stage 1 or 'see report'.
    (tmp_path / "build-lib" / "vars").mkdir(parents=True)
    (tmp_path / "build-lib" / "vars" / "failVar.groovy").write_text(
        "def call() { script { println 'oops' } }\n",
        encoding="utf-8",
    )
    map_path = tmp_path / "library-map.json"
    map_path.write_text(
        json.dumps({"schema_version": 1, "libraries": {"build-lib": {"path": "build-lib"}}}),
        encoding="utf-8",
    )
    lm = load_library_map(map_path)
    lib_multi = (
        "@Library('build-lib') _\n"
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('First') {\n"
        "            steps {\n"
        "                sh 'echo first ok'\n"
        "            }\n"
        "        }\n"
        "        stage('Second') {\n"
        "            steps {\n"
        "                failVar()\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    res_lib = analyze_source(lib_multi, library_map=lm, source_path="Jenkinsfile")
    wf_lib = generate_workflow(res_lib, source_name="Jenkinsfile")
    assert "echo first ok" in wf_lib
    assert '# Stage "Second" (line 10) was NOT migrated: it contains\n      # unsupported constructs (PB-LIB-CALL).' in wf_lib

    # 3. Byte-for-byte preservation of committed example workflows without postlude helpers.
    py_build = REPO_ROOT / "examples" / "python-build"
    res_py = analyze_source((py_build / "Jenkinsfile").read_text(encoding="utf-8"), source_path=str(py_build / "Jenkinsfile"))
    assert generate_workflow(res_py, source_name="Jenkinsfile") == (py_build / "migration" / "workflow.yml").read_text(encoding="utf-8")

