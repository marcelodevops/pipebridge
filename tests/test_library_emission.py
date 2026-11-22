"""Tests for runnable YAML and scripts emission for sh/echo-only library calls."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import pipebridge.cli as cli_mod
from pipebridge.cli import main


def _write_map(base: Path, libraries: dict[str, str]) -> Path:
    for rel in libraries.values():
        (base / rel / "vars").mkdir(parents=True, exist_ok=True)
    map_path = base / "library-map.json"
    map_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "libraries": {
                    name: {"path": rel} for name, rel in libraries.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return map_path


def _write_jf(path: Path, prelude: str, stages_body: str) -> Path:
    path.write_text(
        f"{prelude}"
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        f"{stages_body}"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    return path


def _run_workflow_steps(wf_text: str, cwd: Path) -> subprocess.CompletedProcess:
    data = yaml.safe_load(wf_text)
    job = data["jobs"]["migrated-pipeline"]
    assert "if" not in job
    steps = job["steps"]
    # First step must be actions/checkout before any generated scripts run.
    assert steps[0]["uses"].startswith("actions/checkout@")
    run_scripts = [s["run"] for s in steps[1:] if "run" in s]
    combined = "\n".join(run_scripts)
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", combined],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_emission_executes_with_exact_bytes_ordering_and_repeated_calls(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "record.groovy").write_text(
        'def call(String tag, String payload) {\n'
        '    helper(tag, payload)\n'
        '    echo "done ${tag}"\n'
        '}\n'
        'def helper(String tag, String payload) {\n'
        '    sh "printf \'%s:%s\\n\' \\"${tag}\\" \\"${payload}\\" >> out.log"\n'
        '}\n',
        encoding="utf-8",
    )
    tricky = "a'b \"c\"  $HOME $(id) `uname` ${{ secrets.EXAMPLE }}\nline2"
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Run') {\n"
        "            steps {\n"
        "                sh 'printf \"start\\n\" >> out.log'\n"
        "                record('first', '''" + tricky + "''')\n"
        "                record('second', 'plain')\n"
        "                sh 'printf \"end\\n\" >> out.log'\n"
        "            }\n"
        "        }\n",
    )
    out_dir = Path("migration")
    rc = main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)])
    assert rc == 0
    capsys.readouterr()

    wf_path = out_dir / "workflow.yml"
    wf_text = wf_path.read_text(encoding="utf-8")
    assert "if: false" not in wf_text

    # Script reuse: helper-1.sh and call-1.sh exist once and are reused by both calls.
    helper_script = out_dir / "scripts" / "build-lib" / "record" / "helper-1.sh"
    echo_script = out_dir / "scripts" / "build-lib" / "record" / "call-1.sh"
    assert helper_script.is_file()
    assert echo_script.is_file()
    helper_body = helper_script.read_text(encoding="utf-8")
    assert "${1}" in helper_body and "${2}" in helper_body
    assert "secrets.EXAMPLE" not in helper_body
    assert "first" not in helper_body
    assert "second" not in helper_body

    # actionlint check when available.
    if shutil.which("actionlint") is not None:
        report = json.loads((out_dir / "migration-report.json").read_text(encoding="utf-8"))
        assert report["validation"]["actionlint"]["ok"] is True

    # Execute generated steps in disposable workspace (tmp_path has migration/).
    proc = _run_workflow_steps(wf_text, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "done first\ndone second\n"
    log = (tmp_path / "out.log").read_text(encoding="utf-8")
    assert log == (
        "start\n"
        f"first:{tricky}\n"
        "second:plain\n"
        "end\n"
    )


def test_emission_failure_propagates_and_stops_later_steps(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "failStep.groovy").write_text(
        "def call() { sh 'exit 7' }\n",
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Fail') {\n"
        "            steps {\n"
        "                failStep()\n"
        "                sh 'touch should_not_exist.txt'\n"
        "            }\n"
        "        }\n",
    )
    out_dir = Path("migration")
    assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)]) == 0
    capsys.readouterr()

    wf_text = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    proc = _run_workflow_steps(wf_text, tmp_path)
    assert proc.returncode == 7
    assert not (tmp_path / "should_not_exist.txt").exists()


def test_blocked_stage_emits_no_executable_library_scripts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "okStep.groovy").write_text(
        "def call() { sh 'echo should-not-emit' }\n",
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Mixed') {\n"
        "            steps {\n"
        "                okStep()\n"
        "                script { println 'blocker' }\n"
        "            }\n"
        "        }\n",
    )
    out_dir = Path("migration")
    rc = main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)])
    assert rc == 2
    capsys.readouterr()
    assert "if: false" in (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert not (out_dir / "scripts").exists()


def test_pending_credentials_without_secrets_ready_retain_disabled_draft_and_exit_2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fixture_dir = Path(__file__).resolve().parent.parent / "examples" / "shared-library" / "success"
    out_dir = Path("migration")
    rc = main([
        "convert",
        str(fixture_dir / "Jenkinsfile"),
        "--output",
        str(out_dir),
        "--library-map",
        str(fixture_dir / "library-map.json"),
    ])
    assert rc == 2
    capsys.readouterr()
    assert "if: false" in (out_dir / "workflow.yml").read_text(encoding="utf-8")
    # Publish stage is blocked by PB-CRED-MAP; Restore stage is blocked by missing earlier stash 'dist'.
    assert not (out_dir / "scripts").exists()


def test_overwrite_refusal_force_and_unrelated_files_preserved(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { sh 'echo v1' }\n",
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Greet') {\n"
        "            steps {\n"
        "                greet()\n"
        "            }\n"
        "        }\n",
    )
    out_dir = Path("migration")
    assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)]) == 0
    capsys.readouterr()

    unrelated = out_dir / "scripts" / "keep-me.txt"
    unrelated.write_text("do not touch\n", encoding="utf-8")
    script_path = out_dir / "scripts" / "build-lib" / "greet" / "call-1.sh"

    # Update library and convert without --force -> refused, exit 1, old bytes preserved.
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { sh 'echo v2' }\n",
        encoding="utf-8",
    )
    assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err
    assert script_path.read_text(encoding="utf-8") == "echo v1\n"

    # With --force -> updated, unrelated file preserved.
    assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path), "--force"]) == 0
    capsys.readouterr()
    assert script_path.read_text(encoding="utf-8") == "echo v2\n"
    assert unrelated.read_text(encoding="utf-8") == "do not touch\n"


def test_output_path_containment_for_library_scripts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { sh 'echo ok' }\n",
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Greet') {\n"
        "            steps {\n"
        "                greet()\n"
        "            }\n"
        "        }\n",
    )
    abs_out = tmp_path / "abs-out"
    assert main(["convert", str(jf), "--output", str(abs_out), "--library-map", str(map_path)]) == 1
    assert "--output must be a relative path" in capsys.readouterr().err
    assert not abs_out.exists()

    assert main(["convert", str(jf), "--output", "../escape-out", "--library-map", str(map_path)]) == 1
    assert "--output must be a relative path" in capsys.readouterr().err


def test_rollback_restores_workflow_reports_and_scripts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { sh 'echo original' }\n",
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Greet') {\n"
        "            steps {\n"
        "                greet()\n"
        "            }\n"
        "        }\n",
    )
    out_dir = Path("migration")
    assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)]) == 0
    capsys.readouterr()

    wf_path = out_dir / "workflow.yml"
    script_path = out_dir / "scripts" / "build-lib" / "greet" / "call-1.sh"
    orig_wf = wf_path.read_text(encoding="utf-8")
    orig_script = script_path.read_text(encoding="utf-8")

    # Update library and add a second script, then fail os.replace on the 4th item (first script).
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { sh 'echo updated'; sh 'echo second' }\n",
        encoding="utf-8",
    )
    real_replace = os.replace
    calls = 0

    def failing_replace(src, dst):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("simulated disk error")
        return real_replace(src, dst)

    monkeypatch.setattr(cli_mod.os, "replace", failing_replace)
    rc = main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path), "--force"])
    assert rc == 1
    assert "rolled back completely" in capsys.readouterr().err
    assert wf_path.read_text(encoding="utf-8") == orig_wf
    assert script_path.read_text(encoding="utf-8") == orig_script
    assert not (out_dir / "scripts" / "build-lib" / "greet" / "call-2.sh").exists()


def test_sh_param_multiword_and_failing_command_execution(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "runCmd.groovy").write_text(
        "def call(String cmd) { sh(cmd) }\n",
        encoding="utf-8",
    )
    multi_cmd = "printf 'ran:%s' 'ok' > multi.txt && printf 'done\\n'"
    jf_ok = _write_jf(
        tmp_path / "Jenkinsfile.ok",
        "@Library('build-lib') _\n",
        "        stage('Multi') {\n"
        "            steps {\n"
        f'                runCmd("{multi_cmd}")\n'
        "            }\n"
        "        }\n",
    )
    out_ok = Path("mig-ok")
    assert main(["convert", str(jf_ok), "--output", str(out_ok), "--library-map", str(map_path)]) == 0
    capsys.readouterr()

    script_text = (out_ok / "scripts" / "build-lib" / "runCmd" / "call-1.sh").read_text(encoding="utf-8")
    assert "multi.txt" not in script_text
    assert 'bash --noprofile --norc -eo pipefail -c "${1}"' in script_text

    proc_ok = _run_workflow_steps((out_ok / "workflow.yml").read_text(encoding="utf-8"), tmp_path)
    assert proc_ok.returncode == 0, proc_ok.stderr
    assert proc_ok.stdout == "done\n"
    assert (tmp_path / "multi.txt").read_text(encoding="utf-8") == "ran:ok"

    jf_fail = _write_jf(
        tmp_path / "Jenkinsfile.fail",
        "@Library('build-lib') _\n",
        "        stage('Fail') {\n"
        "            steps {\n"
        "                runCmd('exit 9')\n"
        "                sh 'touch should_not_exist.txt'\n"
        "            }\n"
        "        }\n",
    )
    out_fail = Path("mig-fail")
    assert main(["convert", str(jf_fail), "--output", str(out_fail), "--library-map", str(map_path)]) == 0
    capsys.readouterr()
    proc_fail = _run_workflow_steps((out_fail / "workflow.yml").read_text(encoding="utf-8"), tmp_path)
    assert proc_fail.returncode == 9
    assert not (tmp_path / "should_not_exist.txt").exists()


def test_ten_plus_distinct_interpolated_parameters_execution(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    params_sig = ", ".join(f"String p{i}" for i in range(1, 12))
    interp_body = "|".join(f"${{p{i}}}" for i in range(1, 12))
    (tmp_path / "build-lib" / "vars" / "many.groovy").write_text(
        f'def call({params_sig}) {{ sh "printf \'%s\\\\n\' \\"{interp_body}\\"" }}\n',
        encoding="utf-8",
    )
    call_args = ", ".join(f"'v{i}'" for i in range(1, 12))
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Many') {\n"
        "            steps {\n"
        f"                many({call_args})\n"
        "            }\n"
        "        }\n",
    )
    out_dir = Path("mig-many")
    assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)]) == 0
    capsys.readouterr()

    script_text = (out_dir / "scripts" / "build-lib" / "many" / "call-1.sh").read_text(encoding="utf-8")
    assert "${10}" in script_text and "${11}" in script_text

    proc = _run_workflow_steps((out_dir / "workflow.yml").read_text(encoding="utf-8"), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "|".join(f"v{i}" for i in range(1, 12)) + "\n"


def test_echo_preserves_literal_dollar_digits_alongside_param(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "say.groovy").write_text(
        'def call(String msg) { echo "lit=\\$1 braced=\\${1} param=${msg}" }\n',
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Say') {\n"
        "            steps {\n"
        "                say('VALUE')\n"
        "            }\n"
        "        }\n",
    )
    out_dir = Path("mig-say")
    assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)]) == 0
    capsys.readouterr()

    script_text = (out_dir / "scripts" / "build-lib" / "say" / "call-1.sh").read_text(encoding="utf-8")
    assert script_text == 'printf \'%s\\n\' "lit=\\$1 braced=\\${1} param=${1}"\n'

    proc = _run_workflow_steps((out_dir / "workflow.yml").read_text(encoding="utf-8"), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "lit=$1 braced=${1} param=VALUE\n"


def test_generated_script_enforces_errexit_and_pipefail_inside_child_shell(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "failEarly.groovy").write_text(
        "def call() { sh 'false; printf SHOULD_NOT_RUN' }\n",
        encoding="utf-8",
    )
    (tmp_path / "build-lib" / "vars" / "failPipe.groovy").write_text(
        "def call() { sh 'false | true; printf SHOULD_NOT_RUN_PIPE' }\n",
        encoding="utf-8",
    )

    for var_name, marker in (("failEarly", "SHOULD_NOT_RUN"), ("failPipe", "SHOULD_NOT_RUN_PIPE")):
        jf = _write_jf(
            tmp_path / f"Jenkinsfile.{var_name}",
            "@Library('build-lib') _\n",
            f"        stage('{var_name}') {{\n"
            "            steps {\n"
            f"                {var_name}()\n"
            "                sh 'touch should_not_exist.txt'\n"
            "            }\n"
            "        }\n",
        )
        out_dir = Path(f"mig-{var_name}")
        assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)]) == 0
        capsys.readouterr()

        data = yaml.safe_load((out_dir / "workflow.yml").read_text(encoding="utf-8"))
        run_steps = [s["run"] for s in data["jobs"]["migrated-pipeline"]["steps"][1:] if "run" in s]
        # Execute the actual generated run command in plain bash (without outer -eo pipefail)
        # to prove the generated `bash --noprofile --norc -eo pipefail ...` enforces errexit/pipefail.
        proc = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", run_steps[0]],
            cwd=tmp_path, capture_output=True, text=True, check=False,
        )
        assert proc.returncode != 0
        assert marker not in proc.stdout
        assert not (tmp_path / "should_not_exist.txt").exists()


def test_unbraced_dotted_property_interpolation_rejected_with_pb_interp(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "badEcho.groovy").write_text(
        'def call(String x) { echo "$x.length" }\n', encoding="utf-8"
    )
    (tmp_path / "build-lib" / "vars" / "badSh.groovy").write_text(
        'def call(String x) { sh "echo $x.foo.bar" }\n', encoding="utf-8"
    )
    (tmp_path / "build-lib" / "vars" / "good.groovy").write_text(
        'def call(String x) {\n'
        '    echo "$x"\n'
        '    echo "${x}.length"\n'
        '    echo "Hello $x."\n'
        '    echo "\\$x.length"\n'
        '}\n',
        encoding="utf-8",
    )

    for bad in ("badEcho", "badSh"):
        jf = _write_jf(
            tmp_path / f"Jenkinsfile.{bad}",
            "@Library('build-lib') _\n",
            "        stage('Bad') {\n"
            "            steps {\n"
            f"                {bad}('abc')\n"
            "            }\n"
            "        }\n",
        )
        out_dir = Path(f"mig-{bad}")
        rc = main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)])
        assert rc == 2
        capsys.readouterr()
        assert "if: false" in (out_dir / "workflow.yml").read_text(encoding="utf-8")
        assert not (out_dir / "scripts").exists()
        report = json.loads((out_dir / "migration-report.json").read_text(encoding="utf-8"))
        interp = [f for f in report["findings"] if f["code"] == "PB-INTERP"]
        assert len(interp) == 1
        assert interp[0]["source_path"].endswith(f"{bad}.groovy")
        assert interp[0]["call_chain"][0].endswith(f"{bad}@7:17")

    # Valid bare parameters, braced property suffix, trailing dot, and escaped dollar work.
    jf_good = _write_jf(
        tmp_path / "Jenkinsfile.good",
        "@Library('build-lib') _\n",
        "        stage('Good') {\n"
        "            steps {\n"
        "                good('abc')\n"
        "            }\n"
        "        }\n",
    )
    out_good = Path("mig-good")
    assert main(["convert", str(jf_good), "--output", str(out_good), "--library-map", str(map_path)]) == 0
    capsys.readouterr()
    proc = _run_workflow_steps((out_good / "workflow.yml").read_text(encoding="utf-8"), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "abc\nabc.length\nHello abc.\n$x.length\n"
