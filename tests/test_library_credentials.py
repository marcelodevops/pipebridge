"""Integration and CLI tests for withCredentials inside shared-library calls."""

import json
import subprocess
from pathlib import Path

import yaml

from pipebridge import findings as F
from pipebridge.analysis import analyze_source
from pipebridge.cli import main
from pipebridge.credentials import load_credential_map
from pipebridge.librarymap import load_library_map


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


def _write_cred_map(base: Path, mapping: dict[str, str]) -> Path:
    p = base / "credential-map.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "credentials": {k: {"secret": v} for k, v in mapping.items()},
            }
        ),
        encoding="utf-8",
    )
    return p


def _write_jf(path: Path, stages_body: str) -> Path:
    path.write_text(
        "@Library('build-lib') _\n"
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        f"{stages_body}"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    return path


def test_library_with_credentials_scope_setup_gating_and_runtime(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    lib_map = _write_lib_map(tmp_path, {"build-lib": "build-lib"})
    cred_map = _write_cred_map(tmp_path, {"npm-token": "NPM_TOKEN_GH"})
    (tmp_path / "build-lib" / "vars" / "deployPkg.groovy").write_text(
        "def call(String tag) {\n"
        '    sh "printf \'before:%s:%s\\n\' \\"${tag}\\" \\"\\${NPM_TOKEN:-unset}\\" >> trace.log"\n'
        "    withCredentials([string(credentialsId: 'npm-token', variable: 'NPM_TOKEN')]) {\n"
        '        sh "printf \'inside:%s:%s\\n\' \\"${tag}\\" \\"\\${NPM_TOKEN:-unset}\\" >> trace.log"\n'
        "    }\n"
        '    sh "printf \'after:%s:%s\\n\' \\"${tag}\\" \\"\\${NPM_TOKEN:-unset}\\" >> trace.log"\n'
        "}\n",
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "        stage('Deploy') {\n"
        "            steps {\n"
        "                sh 'printf \"jf-before:%s\\\\n\" \"${NPM_TOKEN:-unset}\" >> trace.log'\n"
        "                deployPkg('one')\n"
        "                deployPkg('two')\n"
        "                sh 'printf \"jf-after:%s\\\\n\" \"${NPM_TOKEN:-unset}\" >> trace.log'\n"
        "            }\n"
        "        }\n",
    )

    # Without --secrets-ready: exit 2, disabled draft, steps & scripts still emitted for review.
    out_unready = Path("mig-unready")
    rc_unready = main([
        "convert", str(jf),
        "--output", str(out_unready),
        "--library-map", str(lib_map),
        "--credential-map", str(cred_map),
    ])
    assert rc_unready == 2
    capsys.readouterr()
    wf_unready = (out_unready / "workflow.yml").read_text(encoding="utf-8")
    assert "if: false" in wf_unready
    assert 'NPM_TOKEN: "${{ secrets.NPM_TOKEN_GH }}"' in wf_unready
    assert (out_unready / "scripts" / "build-lib" / "deployPkg" / "call-2.sh").is_file()

    # With --secrets-ready: exit 0, runnable YAML, secret env only on bound steps.
    out_ready = Path("mig-ready")
    rc_ready = main([
        "convert", str(jf),
        "--output", str(out_ready),
        "--library-map", str(lib_map),
        "--credential-map", str(cred_map),
        "--secrets-ready",
    ])
    assert rc_ready == 0
    conv_out = capsys.readouterr().out
    assert "SYNTHETIC" not in conv_out
    wf_text = (out_ready / "workflow.yml").read_text(encoding="utf-8")
    assert "if: false" not in wf_text

    # No secret values anywhere in generated scripts or reports.
    for p in (out_ready / "scripts").rglob("*.sh"):
        assert "NPM_TOKEN_GH" not in p.read_text(encoding="utf-8")

    data = yaml.safe_load(wf_text)
    steps = data["jobs"]["migrated-pipeline"]["steps"]
    assert steps[0]["uses"].startswith("actions/checkout@")
    run_steps = steps[1:]
    # 8 run steps: jf-before, (before, inside, after) x 2, jf-after
    assert len(run_steps) == 8
    bound_indices = [i for i, s in enumerate(run_steps) if "env" in s]
    assert bound_indices == [2, 5]
    for i in bound_indices:
        assert run_steps[i]["env"] == {"NPM_TOKEN": "${{ secrets.NPM_TOKEN_GH }}"}

    # Execute steps locally with synthetic env injected ONLY for steps declaring NPM_TOKEN.
    for s in run_steps:
        step_env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin"}
        if "env" in s:
            step_env["NPM_TOKEN"] = "SYNTHETIC_SECRET_VALUE"
        proc = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", s["run"]],
            cwd=tmp_path,
            env=step_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr

    trace = (tmp_path / "trace.log").read_text(encoding="utf-8").splitlines()
    assert trace == [
        "jf-before:unset",
        "before:one:unset",
        "inside:one:SYNTHETIC_SECRET_VALUE",
        "after:one:unset",
        "before:two:unset",
        "inside:two:SYNTHETIC_SECRET_VALUE",
        "after:two:unset",
        "jf-after:unset",
    ]


def test_library_credentials_missing_invalid_collision_and_env_collision(tmp_path, capsys):
    lib_map = load_library_map(_write_lib_map(tmp_path, {"build-lib": "build-lib"}))
    (tmp_path / "build-lib" / "vars" / "useCred.groovy").write_text(
        "def call() {\n"
        "    withCredentials([string(credentialsId: 'npm-token', variable: 'NPM_TOKEN')]) {\n"
        "        sh 'echo ok'\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    source = (
        "@Library('build-lib') _\n"
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('S') {\n"
        "            steps {\n"
        "                useCred()\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    # Missing mapping
    res_missing = analyze_source(source, library_map=lib_map, source_path="Jenkinsfile")
    assert res_missing.has_blockers
    assert res_missing.pipeline.stages[0].blocked
    assert res_missing.pipeline.stages[0].steps == []
    cred_f = [f for f in res_missing.findings if f.code == F.PB_CRED_MAP]
    assert len(cred_f) == 1
    assert cred_f[0].source_path.endswith("useCred.groovy")
    assert cred_f[0].call_chain == ("Jenkinsfile:useCred@7:17",)

    # Invalid secret name
    bad_map = load_credential_map(_write_cred_map(tmp_path, {"npm-token": "bad-secret"}))
    res_bad = analyze_source(source, credential_map=bad_map, secrets_ready=True, library_map=lib_map)
    assert res_bad.has_blockers
    assert res_bad.pipeline.stages[0].blocked

    # Colliding secret name
    col_map = load_credential_map(_write_cred_map(tmp_path, {"npm-token": "SHARED", "other": "SHARED"}))
    res_col = analyze_source(source, credential_map=col_map, secrets_ready=True, library_map=lib_map)
    assert res_col.has_blockers
    assert res_col.pipeline.stages[0].blocked

    # Stage environment collision
    env_source = source.replace(
        "        stage('S') {\n",
        "        stage('S') {\n            environment { NPM_TOKEN = 'plain' }\n",
    )
    ok_map = load_credential_map(_write_cred_map(tmp_path, {"npm-token": "NPM_TOKEN_GH"}))
    res_env = analyze_source(env_source, credential_map=ok_map, secrets_ready=True, library_map=lib_map)
    assert res_env.has_blockers
    assert res_env.pipeline.stages[0].blocked
    assert any(f.code == F.PB_CRED and "collides" in f.message for f in res_env.findings)


def test_library_credentials_preserved_when_stage_cleared_by_blocker(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fixture_dir = Path(__file__).resolve().parent.parent / "examples" / "shared-library" / "success"
    out_dir = Path("mig-success")
    # With --secrets-ready and both maps, success fixture now exits 0 and emits enabled YAML.
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
    assert "if: false" not in (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert (out_dir / "scripts" / "pipebridge_stash.py").is_file()
    assert (out_dir / "scripts" / "pipebridge_unstash.py").is_file()

    report = json.loads((out_dir / "migration-report.json").read_text(encoding="utf-8"))
    bindings = report["credentials"]["bindings"]
    assert len(bindings) == 1
    assert bindings[0]["credential_id"] == "npm-token"
    assert bindings[0]["secret_name"] == "NPM_TOKEN_GH"
    assert bindings[0]["status"] == "resolved"
    assert bindings[0]["stage"] == "Publish"
    assert bindings[0]["source_path"].endswith("publish.groovy")
    assert bindings[0]["call_chain"][0].endswith("Jenkinsfile:publish@7:17")

    # Unrelated blocker in same stage also preserves credential inventory & provenance.
    lib_map = load_library_map(_write_lib_map(tmp_path, {"build-lib": "build-lib"}))
    cred_map = load_credential_map(_write_cred_map(tmp_path, {"npm-token": "NPM_TOKEN_GH"}))
    (tmp_path / "build-lib" / "vars" / "useCred.groovy").write_text(
        "def call() {\n"
        "    withCredentials([string(credentialsId: 'npm-token', variable: 'NPM_TOKEN')]) {\n"
        "        sh 'echo ok'\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    jf = (
        "@Library('build-lib') _\n"
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Mixed') {\n"
        "            steps {\n"
        "                useCred()\n"
        "                script { println 'nope' }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    res = analyze_source(jf, credential_map=cred_map, secrets_ready=True, library_map=lib_map, source_path="Jenkinsfile")
    assert res.pipeline.stages[0].blocked
    assert res.pipeline.stages[0].steps == []
    assert len(res.credential_inventory.entries) == 1
    assert res.credential_inventory.entries[0].status == "resolved"
    assert res.credential_inventory.entries[0].call_chain == ("Jenkinsfile:useCred@7:17",)


def test_library_with_credentials_malformed_header_and_unsupported_body(tmp_path):
    lib_map = load_library_map(_write_lib_map(tmp_path, {"build-lib": "build-lib"}))

    # Unsupported header: body must not be mined.
    (tmp_path / "build-lib" / "vars" / "badHdr.groovy").write_text(
        "def call() {\n"
        "    withCredentials([usernamePassword(credentialsId: 'c', usernameVariable: 'U', passwordVariable: 'P')]) {\n"
        "        sh 'echo secret'\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    src_hdr = _write_jf(tmp_path / "Jenkinsfile.hdr", "        stage('S') { steps { badHdr() } }\n").read_text()
    res_hdr = analyze_source(src_hdr, library_map=lib_map)
    assert res_hdr.has_blockers
    assert res_hdr.pipeline.stages[0].blocked
    assert any(f.code == F.PB_CRED for f in res_hdr.findings)
    assert res_hdr.library_inventory.operations == []
    assert res_hdr.credential_inventory.entries[0].status == "unsupported"

    # Supported header with unsupported body statement: PB-LIB-CALL, binding still inventoried.
    (tmp_path / "build-lib" / "vars" / "badBody.groovy").write_text(
        "def call() {\n"
        "    withCredentials([string(credentialsId: 'npm-token', variable: 'NPM_TOKEN')]) {\n"
        "        if (true) { sh 'x' }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    src_body = _write_jf(tmp_path / "Jenkinsfile.body", "        stage('S') { steps { badBody() } }\n").read_text()
    res_body = analyze_source(src_body, library_map=lib_map)
    assert res_body.has_blockers
    assert res_body.pipeline.stages[0].blocked
    assert any(f.code == F.PB_LIB_CALL for f in res_body.findings)
    assert len(res_body.credential_inventory.entries) == 1
    assert res_body.credential_inventory.entries[0].credential_id == "npm-token"
