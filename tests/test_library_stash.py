"""Acceptance and regression tests for bounded single-job stash/unstash."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

import pipebridge.cli as cli_mod
from pipebridge import findings as F
from pipebridge.analysis import analyze_source
from pipebridge.cli import main
from pipebridge.librarymap import load_library_map
from pipebridge.stash import STASH_HELPER_SOURCE, UNSTASH_HELPER_SOURCE


def _write_lib_map(base: Path, libraries: dict[str, str]) -> Path:
    for rel in libraries.values():
        (base / rel / "vars").mkdir(parents=True, exist_ok=True)
    p = base / "library-map.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "libraries": {k: {"path": v} for k, v in libraries.items()},
            }
        ),
        encoding="utf-8",
    )
    return p


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


def _execute_workflow(wf_text: str, workspace: Path, runner_temp: Path, secret_val: str | None = None):
    data = yaml.safe_load(wf_text)
    steps = data["jobs"]["migrated-pipeline"]["steps"]
    assert steps[0]["uses"].startswith("actions/checkout@")
    cleanup = steps[-1]
    assert cleanup["name"] == "Remove pipebridge stash"
    assert cleanup["if"] == "always()"
    assert cleanup["continue-on-error"] is True

    run_steps = steps[1:-1]
    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GITHUB_WORKSPACE": str(workspace),
        "RUNNER_TEMP": str(runner_temp),
    }
    failed_rc = 0
    executed_names: list[str] = []
    for s in run_steps:
        step_env = dict(base_env)
        if "env" in s and secret_val is not None:
            for var_name in s["env"]:
                step_env[var_name] = secret_val
        proc = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", s["run"]],
            cwd=workspace,
            env=step_env,
            capture_output=True,
            text=True,
            check=False,
        )
        executed_names.append(s["name"])
        if proc.returncode != 0:
            failed_rc = proc.returncode
            break

    # always() cleanup runs even after failure.
    clean_proc = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", cleanup["run"]],
        cwd=workspace,
        env=base_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert clean_proc.returncode == 0
    return failed_rc, executed_names


def test_success_fixture_conversion_and_local_execution(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fixture_dir = Path(__file__).resolve().parent.parent / "examples" / "shared-library" / "success"
    out_dir = Path("migration")

    rc = main([
        "convert",
        str(fixture_dir / "Jenkinsfile"),
        "--output", str(out_dir),
        "--library-map", str(fixture_dir / "library-map.json"),
        "--credential-map", str(fixture_dir / "credential-map.json"),
        "--secrets-ready",
    ])
    assert rc == 0
    capsys.readouterr()

    wf_text = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert "if: false" not in wf_text
    assert (out_dir / "scripts" / "pipebridge_stash.py").is_file()
    assert (out_dir / "scripts" / "pipebridge_unstash.py").is_file()
    assert (out_dir / "scripts" / "build-lib" / "publish" / "packageSources-1.sh").is_file()
    assert (out_dir / "scripts" / "build-lib" / "publish" / "call-1.sh").is_file()

    if shutil.which("actionlint") is not None:
        report = json.loads((out_dir / "migration-report.json").read_text(encoding="utf-8"))
        assert report["validation"]["actionlint"]["ok"] is True

    # Verify credential env only on bound step.
    data = yaml.safe_load(wf_text)
    steps = data["jobs"]["migrated-pipeline"]["steps"]
    env_steps = [s for s in steps if "env" in s]
    assert len(env_steps) == 1
    assert env_steps[0]["env"] == {"NPM_TOKEN": "${{ secrets.NPM_TOKEN_GH }}"}

    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    failed_rc, _ = _execute_workflow(wf_text, tmp_path, runner_temp, secret_val="SYNTHETIC_NPM")
    assert failed_rc == 0
    assert (tmp_path / "dist" / "marker.txt").read_text(encoding="utf-8") == "packaged"
    assert (tmp_path / "dist" / "seen.txt").read_text(encoding="utf-8") == "ok"
    assert not (runner_temp / "pipebridge-stash").exists()


def test_failure_fixture_conversion_and_skips_restored(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fixture_dir = Path(__file__).resolve().parent.parent / "examples" / "shared-library" / "failure"
    out_dir = Path("migration")

    rc = main([
        "convert",
        str(fixture_dir / "Jenkinsfile"),
        "--output", str(out_dir),
        "--library-map", str(fixture_dir / "library-map.json"),
    ])
    assert rc == 0
    capsys.readouterr()

    wf_text = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert "if: false" not in wf_text

    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    failed_rc, executed = _execute_workflow(wf_text, tmp_path, runner_temp)
    assert failed_rc != 0
    assert "Restore" not in executed
    assert not (runner_temp / "pipebridge-stash").exists()


def test_stash_exclusions_and_empty_match(tmp_path):
    ws = tmp_path / "ws"
    rt = tmp_path / "rt"
    (ws / "dist" / "sub").mkdir(parents=True)
    (ws / "dist" / "keep.txt").write_text("keep-bytes\n", encoding="utf-8")
    (ws / "dist" / "secret.txt").write_text("exclude-me\n", encoding="utf-8")
    (ws / "dist" / "sub" / "nested.txt").write_text("nested-bytes\n", encoding="utf-8")
    rt.mkdir()

    stash_py = tmp_path / "pipebridge_stash.py"
    unstash_py = tmp_path / "pipebridge_unstash.py"
    stash_py.write_text(STASH_HELPER_SOURCE, encoding="utf-8")
    unstash_py.write_text(UNSTASH_HELPER_SOURCE, encoding="utf-8")

    env = {"GITHUB_WORKSPACE": str(ws), "RUNNER_TEMP": str(rt)}
    p = subprocess.run(
        [sys.executable, str(stash_py), "dist", "dist/**", "dist/secret.txt"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert p.returncode == 0, p.stderr

    shutil.rmtree(ws / "dist")
    u = subprocess.run(
        [sys.executable, str(unstash_py), "dist"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert u.returncode == 0, u.stderr
    assert (ws / "dist" / "keep.txt").read_text(encoding="utf-8") == "keep-bytes\n"
    assert (ws / "dist" / "sub" / "nested.txt").read_text(encoding="utf-8") == "nested-bytes\n"
    assert not (ws / "dist" / "secret.txt").exists()

    # Empty match exits 1 and removes any stash directory.
    empty = subprocess.run(
        [sys.executable, str(stash_py), "empty", "missing/**"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert empty.returncode == 1
    assert "no files matched" in empty.stderr
    assert not (rt / "pipebridge-stash" / "empty").exists()


def test_duplicate_stash_missing_stash_and_blocked_stage_stash(tmp_path):
    # Duplicate stash name
    dup_jf = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('One') { steps { stash name: 'dist', includes: 'dist/**' } }\n"
        "        stage('Two') { steps { stash name: 'dist', includes: 'dist/**' } }\n"
        "    }\n"
        "}\n"
    )
    res_dup = analyze_source(dup_jf)
    assert res_dup.has_blockers
    assert not res_dup.pipeline.stages[0].blocked
    assert res_dup.pipeline.stages[1].blocked
    assert any(f.code == F.PB_LIB_CALL and "already used" in f.message for f in res_dup.findings)

    # Unstash without earlier stash
    miss_jf = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Restore') { steps { unstash 'dist' } }\n"
        "    }\n"
        "}\n"
    )
    res_miss = analyze_source(miss_jf)
    assert res_miss.has_blockers
    assert res_miss.pipeline.stages[0].blocked
    assert any(f.code == F.PB_LIB_CALL and "no earlier stash" in f.message for f in res_miss.findings)

    # Stash in a blocked stage does not count for a later unstash.
    blocked_stash_jf = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Build') {\n"
        "            steps {\n"
        "                stash name: 'dist', includes: 'dist/**'\n"
        "                script { println 'nope' }\n"
        "            }\n"
        "        }\n"
        "        stage('Restore') { steps { unstash 'dist' } }\n"
        "    }\n"
        "}\n"
    )
    res_blk = analyze_source(blocked_stash_jf)
    assert res_blk.pipeline.stages[0].blocked
    assert res_blk.pipeline.stages[0].steps == []
    assert res_blk.pipeline.stages[1].blocked
    assert any(f.code == F.PB_LIB_CALL and "no earlier stash" in f.message for f in res_blk.findings)


def test_stash_and_unstash_reject_symlinks_and_leave_outside_sentinels_untouched(tmp_path):
    ws = tmp_path / "ws"
    rt = tmp_path / "rt"
    outside = tmp_path / "outside"
    ws.mkdir()
    rt.mkdir()
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("OUTSIDE_ORIGINAL", encoding="utf-8")

    stash_py = tmp_path / "pipebridge_stash.py"
    unstash_py = tmp_path / "pipebridge_unstash.py"
    stash_py.write_text(STASH_HELPER_SOURCE, encoding="utf-8")
    unstash_py.write_text(UNSTASH_HELPER_SOURCE, encoding="utf-8")
    env = {"GITHUB_WORKSPACE": str(ws), "RUNNER_TEMP": str(rt)}

    # 1. Symlink inside workspace escaping outside -> stash exits 2, copies nothing.
    (ws / "dist").mkdir()
    (ws / "dist" / "leak.txt").symlink_to(sentinel)
    p1 = subprocess.run(
        [sys.executable, str(stash_py), "s1", "dist/**"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert p1.returncode == 2
    assert not (rt / "pipebridge-stash" / "s1").exists()
    assert sentinel.read_text(encoding="utf-8") == "OUTSIDE_ORIGINAL"

    # 2. Symlink inside stash -> unstash exits 2, copies nothing.
    stash_s2 = rt / "pipebridge-stash" / "s2"
    stash_s2.mkdir(parents=True)
    (stash_s2 / "good.txt").write_text("GOOD", encoding="utf-8")
    (stash_s2 / "bad.txt").symlink_to(sentinel)
    p2 = subprocess.run(
        [sys.executable, str(unstash_py), "s2"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert p2.returncode == 2
    assert not (ws / "good.txt").exists()
    assert sentinel.read_text(encoding="utf-8") == "OUTSIDE_ORIGINAL"

    # 3. Destination-parent symlink in workspace + valid sibling in same stash:
    # pre-validation must reject BEFORE copying anything, leaving sibling & sentinel untouched!
    stash_s3 = rt / "pipebridge-stash" / "s3"
    (stash_s3 / "escape_dir").mkdir(parents=True)
    (stash_s3 / "aaa_sibling.txt").write_text("OVERWRITTEN", encoding="utf-8")
    (stash_s3 / "escape_dir" / "sentinel.txt").write_text("PWNED", encoding="utf-8")
    (ws / "aaa_sibling.txt").write_text("SIBLING_ORIGINAL", encoding="utf-8")
    (ws / "escape_dir").symlink_to(outside)
    p3 = subprocess.run(
        [sys.executable, str(unstash_py), "s3"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert p3.returncode == 2
    assert sentinel.read_text(encoding="utf-8") == "OUTSIDE_ORIGINAL"
    assert (ws / "aaa_sibling.txt").read_text(encoding="utf-8") == "SIBLING_ORIGINAL"


def test_stash_helpers_overwrite_refusal_force_and_rollback(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "",
        "        stage('S') {\n"
        "            steps {\n"
        "                sh 'mkdir -p dist && echo hi > dist/a.txt'\n"
        "                stash name: 'd', includes: 'dist/**'\n"
        "                unstash 'd'\n"
        "            }\n"
        "        }\n",
    )
    out_dir = Path("migration")
    assert main(["convert", str(jf), "--output", str(out_dir)]) == 0
    capsys.readouterr()

    stash_helper = out_dir / "scripts" / "pipebridge_stash.py"
    stash_helper.write_text("# modified\n", encoding="utf-8")

    # Overwrite refusal without --force.
    assert main(["convert", str(jf), "--output", str(out_dir)]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err
    assert stash_helper.read_text(encoding="utf-8") == "# modified\n"

    # Rollback on simulated failure restores helper.
    real_replace = os.replace
    calls = 0

    def failing_replace(src, dst):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(cli_mod.os, "replace", failing_replace)
    assert main(["convert", str(jf), "--output", str(out_dir), "--force"]) == 1
    assert "rolled back completely" in capsys.readouterr().err
    assert stash_helper.read_text(encoding="utf-8") == "# modified\n"


def test_unstash_prevalidation_rejects_dir_leaf_file_parent_and_special_files(tmp_path):
    unstash_py = tmp_path / "pipebridge_unstash.py"
    unstash_py.write_text(UNSTASH_HELPER_SOURCE, encoding="utf-8")

    # 1. Destination leaf is a directory (with valid sibling sorted before it).
    ws1 = tmp_path / "ws1"
    rt1 = tmp_path / "rt1"
    ws1.mkdir()
    (ws1 / "aaa_sibling.txt").write_text("SIBLING_ORIGINAL", encoding="utf-8")
    (ws1 / "dir_leaf").mkdir()
    s1 = rt1 / "pipebridge-stash" / "s1"
    s1.mkdir(parents=True)
    (s1 / "aaa_sibling.txt").write_text("OVERWRITTEN", encoding="utf-8")
    (s1 / "dir_leaf").write_text("FILE_OVER_DIR", encoding="utf-8")

    p1 = subprocess.run(
        [sys.executable, str(unstash_py), "s1"],
        env={"GITHUB_WORKSPACE": str(ws1), "RUNNER_TEMP": str(rt1)},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert p1.returncode == 2
    assert (ws1 / "aaa_sibling.txt").read_text(encoding="utf-8") == "SIBLING_ORIGINAL"
    assert (ws1 / "dir_leaf").is_dir()
    assert list((ws1 / "dir_leaf").iterdir()) == []

    # 2. Destination parent is a regular file (with valid sibling sorted before it).
    ws2 = tmp_path / "ws2"
    rt2 = tmp_path / "rt2"
    ws2.mkdir()
    (ws2 / "aaa_sibling.txt").write_text("SIBLING_ORIGINAL", encoding="utf-8")
    (ws2 / "parent_file").write_text("PARENT_ORIGINAL", encoding="utf-8")
    s2 = rt2 / "pipebridge-stash" / "s2"
    (s2 / "parent_file").mkdir(parents=True)
    (s2 / "aaa_sibling.txt").write_text("OVERWRITTEN", encoding="utf-8")
    (s2 / "parent_file" / "child.txt").write_text("CHILD", encoding="utf-8")

    p2 = subprocess.run(
        [sys.executable, str(unstash_py), "s2"],
        env={"GITHUB_WORKSPACE": str(ws2), "RUNNER_TEMP": str(rt2)},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert p2.returncode == 2
    assert (ws2 / "aaa_sibling.txt").read_text(encoding="utf-8") == "SIBLING_ORIGINAL"
    assert (ws2 / "parent_file").read_text(encoding="utf-8") == "PARENT_ORIGINAL"

    # 3. Source entry is a FIFO (with valid sibling sorted before it).
    if hasattr(os, "mkfifo"):
        ws3 = tmp_path / "ws3"
        rt3 = tmp_path / "rt3"
        ws3.mkdir()
        (ws3 / "aaa_sibling.txt").write_text("SIBLING_ORIGINAL", encoding="utf-8")
        s3 = rt3 / "pipebridge-stash" / "s3"
        s3.mkdir(parents=True)
        (s3 / "aaa_sibling.txt").write_text("OVERWRITTEN", encoding="utf-8")
        os.mkfifo(s3 / "zzz_fifo")

        p3 = subprocess.run(
            [sys.executable, str(unstash_py), "s3"],
            env={"GITHUB_WORKSPACE": str(ws3), "RUNNER_TEMP": str(rt3)},
            capture_output=True, text=True, timeout=5, check=False,
        )
        assert p3.returncode == 2
        assert "non-regular" in p3.stderr
        assert (ws3 / "aaa_sibling.txt").read_text(encoding="utf-8") == "SIBLING_ORIGINAL"

        # 4. Destination leaf is a special file (FIFO) with valid sibling sorted before it.
        ws4 = tmp_path / "ws4"
        rt4 = tmp_path / "rt4"
        ws4.mkdir()
        (ws4 / "aaa_sibling.txt").write_text("SIBLING_ORIGINAL", encoding="utf-8")
        os.mkfifo(ws4 / "zzz_fifo")
        s4 = rt4 / "pipebridge-stash" / "s4"
        s4.mkdir(parents=True)
        (s4 / "aaa_sibling.txt").write_text("OVERWRITTEN", encoding="utf-8")
        (s4 / "zzz_fifo").write_text("OVERWRITE_FIFO", encoding="utf-8")

        p4 = subprocess.run(
            [sys.executable, str(unstash_py), "s4"],
            env={"GITHUB_WORKSPACE": str(ws4), "RUNNER_TEMP": str(rt4)},
            capture_output=True, text=True, timeout=5, check=False,
        )
        assert p4.returncode == 2
        assert (ws4 / "aaa_sibling.txt").read_text(encoding="utf-8") == "SIBLING_ORIGINAL"


def test_unstash_copy_oserror_reports_diagnostic_and_exits_nonzero(tmp_path):
    if os.geteuid() == 0:
        return
    unstash_py = tmp_path / "pipebridge_unstash.py"
    unstash_py.write_text(UNSTASH_HELPER_SOURCE, encoding="utf-8")
    ws = tmp_path / "ws"
    rt = tmp_path / "rt"
    ws.mkdir()
    target_dir = ws / "locked"
    target_dir.mkdir()
    target_dir.chmod(0o555)
    s = rt / "pipebridge-stash" / "s"
    (s / "locked").mkdir(parents=True)
    (s / "locked" / "file.txt").write_text("DATA", encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(unstash_py), "s"],
            env={"GITHUB_WORKSPACE": str(ws), "RUNNER_TEMP": str(rt)},
            capture_output=True, text=True, timeout=5, check=False,
        )
        assert proc.returncode == 1
        assert "failed restoring" in proc.stderr
    finally:
        target_dir.chmod(0o755)


def test_stash_symlink_directory_descendant_detection_and_exclusions(tmp_path):
    stash_py = tmp_path / "pipebridge_stash.py"
    stash_py.write_text(STASH_HELPER_SOURCE, encoding="utf-8")

    ws = tmp_path / "ws"
    rt = tmp_path / "rt"
    outside = tmp_path / "outside"
    (ws / "dist" / "real").mkdir(parents=True)
    (ws / "dist" / "real" / "file").write_text("REAL_BYTES", encoding="utf-8")
    outside.mkdir()
    (outside / "secret.txt").write_text("OUTSIDE_SECRET", encoding="utf-8")
    (ws / "dist" / "link").symlink_to(outside)
    rt.mkdir()
    env = {"GITHUB_WORKSPACE": str(ws), "RUNNER_TEMP": str(rt)}

    # 1. Exact repro: includes 'dist/*/*' must reject symlinked dir 'dist/link' before creating stash.
    p_repro = subprocess.run(
        [sys.executable, str(stash_py), "s_repro", "dist/*/*"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert p_repro.returncode == 2
    assert "symlink matched" in p_repro.stderr
    assert not (rt / "pipebridge-stash" / "s_repro").exists()
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "OUTSIDE_SECRET"

    # 2. Unrelated symlink dir ('dist/real/*' does not match 'dist/link') -> succeeds.
    p_unrel = subprocess.run(
        [sys.executable, str(stash_py), "s_unrel", "dist/real/*"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert p_unrel.returncode == 0, p_unrel.stderr
    assert (rt / "pipebridge-stash" / "s_unrel" / "dist" / "real" / "file").read_text(encoding="utf-8") == "REAL_BYTES"
    assert not (rt / "pipebridge-stash" / "s_unrel" / "dist" / "link").exists()

    # 3. Excluded symlink dir ('dist/link/**' excludes all descendants of 'dist/link') -> succeeds.
    p_excl = subprocess.run(
        [sys.executable, str(stash_py), "s_excl", "dist/*/*", "dist/link/**"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert p_excl.returncode == 0, p_excl.stderr
    assert (rt / "pipebridge-stash" / "s_excl" / "dist" / "real" / "file").read_text(encoding="utf-8") == "REAL_BYTES"
    assert not (rt / "pipebridge-stash" / "s_excl" / "dist" / "link").exists()
