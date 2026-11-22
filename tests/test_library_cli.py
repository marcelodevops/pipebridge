"""CLI tests for --library-map on analyze and convert."""

import json
from pathlib import Path

from pipebridge.cli import main


def _write_map(tmp_path: Path, libraries: dict[str, str]) -> Path:
    for rel in libraries.values():
        (tmp_path / rel / "vars").mkdir(parents=True, exist_ok=True)
    map_path = tmp_path / "library-map.json"
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


def test_cli_analyze_and_convert_mapped_resolution_and_emission(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "publish.groovy").write_text(
        'def call(String label) { packageSources(label) }\n'
        'def packageSources(String label) { sh "echo ${label}" }\n',
        encoding="utf-8",
    )
    (tmp_path / "build-lib" / "vars" / "unusedVar.groovy").write_text(
        "def call() { echo 'unused' }\n",
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        '@Library("build-lib@v1") _\n',
        "        stage('Publish') {\n"
        "            steps {\n"
        "                publish('packaged')\n"
        "            }\n"
        "        }\n",
    )

    rc = main(["analyze", str(jf), "--format", "json", "--library-map", str(map_path)])
    assert rc == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["exit_code"] == 0
    assert report["summary"]["blockers"] == 0
    libs = report["libraries"]
    assert libs["map_supplied"] is True
    assert libs["conversion_deferred"] is False
    assert libs["loaded"] == [
        {
            "name": "build-lib",
            "path": "build-lib",
            "revision": "v1",
            "discovered_vars": ["publish", "unusedVar"],
            "vars": ["publish"],
        }
    ]
    assert len(libs["calls"]) == 1
    call = libs["calls"][0]
    assert call["name"] == "publish"
    assert call["status"] == "resolved"
    assert call["source_path"] == str(jf)
    assert call["line"] == 7
    assert call["col"] == 17
    assert call["chain"][0] == f"{jf}:publish@7:17"
    assert "publish.groovy:packageSources@" in call["chain"][1]

    out_dir = Path("migration")
    rc_conv = main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)])
    assert rc_conv == 0
    capsys.readouterr()
    wf = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    assert "if: false" not in wf
    assert "bash 'migration/scripts/build-lib/publish/packageSources-1.sh' 'packaged'" in wf
    script_file = out_dir / "scripts" / "build-lib" / "publish" / "packageSources-1.sh"
    assert script_file.read_text(encoding="utf-8") == "echo ${1}\n"
    md = (out_dir / "migration-report.md").read_text(encoding="utf-8")
    assert "## Libraries" in md
    assert "did not fetch repositories or execute Groovy" in md
    assert "build-lib" in md
    assert "v1" in md


def test_cli_undeclared_library_isolation(tmp_path, capsys):
    map_path = _write_map(tmp_path, {"build-lib": "build-lib", "unused-lib": "unused-lib"})
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { echo 'hi' }\n",
        encoding="utf-8",
    )
    (tmp_path / "unused-lib" / "vars" / "sh.groovy").write_text(
        "def call() { echo 'shadow' }\n",
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Build') {\n"
        "            steps {\n"
        "                greet()\n"
        "                sh 'make'\n"
        "            }\n"
        "        }\n",
    )
    rc = main(["analyze", str(jf), "--format", "json", "--library-map", str(map_path)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert [lib["name"] for lib in report["libraries"]["loaded"]] == ["build-lib"]
    assert any(
        f["code"] == "PB-LIB-MAP-UNUSED" and "unused-lib" in f["message"]
        for f in report["findings"]
    )
    assert not any(
        f["code"] == "PB-LIB-CALL" and "shadows" in f["message"]
        for f in report["findings"]
    )


def test_cli_invalid_library_map_exits_1_without_artifacts(tmp_path, capsys):
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('A') {\n"
        "            steps {\n"
        "                echo 'ok'\n"
        "            }\n"
        "        }\n",
    )
    missing_map = tmp_path / "missing.json"
    out_dir = tmp_path / "out-missing"
    assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(missing_map)]) == 1
    assert "pipebridge: error:" in capsys.readouterr().err
    assert not out_dir.exists()

    bad_map = tmp_path / "bad-map.json"
    bad_map.write_text(
        json.dumps({"schema_version": 1, "libraries": {"build-lib": {"path": "../outside"}}}),
        encoding="utf-8",
    )
    out_dir2 = tmp_path / "out-bad"
    assert main(["convert", str(jf), "--output", str(out_dir2), "--library-map", str(bad_map)]) == 1
    assert "pipebridge: error:" in capsys.readouterr().err
    assert not out_dir2.exists()


def test_cli_containment_failure_exits_1_without_artifacts(tmp_path, tmp_path_factory, capsys):
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.groovy").write_text("def call() { sh 'id' }\n", encoding="utf-8")
    (tmp_path / "build-lib" / "vars" / "escape.groovy").symlink_to(outside / "secret.groovy")

    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Escape') {\n"
        "            steps {\n"
        "                escape()\n"
        "            }\n"
        "        }\n",
    )
    out_dir = tmp_path / "out-escape"
    assert main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)]) == 1
    assert "pipebridge: error:" in capsys.readouterr().err
    assert not out_dir.exists()


def test_cli_provenance_serialized_in_json_and_markdown_reports(tmp_path, capsys):
    map_path = _write_map(tmp_path, {"build-lib": "build-lib"})
    var_file = tmp_path / "build-lib" / "vars" / "publish.groovy"
    var_file.write_text(
        "def call() { helper() }\n"
        "def helper() { nope() }\n",
        encoding="utf-8",
    )
    jf = _write_jf(
        tmp_path / "Jenkinsfile",
        "@Library('build-lib') _\n",
        "        stage('Fail') {\n"
        "            steps {\n"
        "                publish()\n"
        "            }\n"
        "        }\n",
    )
    out_dir = tmp_path / "out-prov"
    rc = main(["convert", str(jf), "--output", str(out_dir), "--library-map", str(map_path)])
    assert rc == 2
    capsys.readouterr()

    report = json.loads((out_dir / "migration-report.json").read_text(encoding="utf-8"))
    lib_finding = next(f for f in report["findings"] if f["code"] == "PB-LIB-CALL")
    assert lib_finding["source_path"] == str(var_file.resolve())
    assert lib_finding["call_chain"][0] == f"{jf}:publish@7:17"
    assert any("publish.groovy:helper@" in frame for frame in lib_finding["call_chain"])

    # Non-library findings keep existing key set (no source_path / call_chain).
    assume_shell = next(f for f in report["findings"] if f["code"] == "PB-ASSUME-SHELL")
    assert "source_path" not in assume_shell
    assert "call_chain" not in assume_shell

    md = (out_dir / "migration-report.md").read_text(encoding="utf-8")
    assert "**Call chain:**" in md
    assert str(var_file.resolve()) in md
    assert f"{jf}:publish@7:17" in md


def test_cli_convert_non_library_python_build_workflow_bytes_unchanged(tmp_path, capsys):
    example = Path(__file__).resolve().parent.parent / "examples" / "python-build"
    out_dir = tmp_path / "migration"
    rc = main(["convert", str(example / "Jenkinsfile"), "--output", str(out_dir)])
    assert rc == 0
    capsys.readouterr()
    actual = (out_dir / "workflow.yml").read_text(encoding="utf-8")
    expected = (example / "migration" / "workflow.yml").read_text(encoding="utf-8")
    assert actual == expected
