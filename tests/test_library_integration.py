"""Parser and analyzer integration tests for shared-library resolution."""

import json
from pathlib import Path

import pytest

from pipebridge import findings as F
from pipebridge.analysis import analyze_source
from pipebridge.errors import PipebridgeError
from pipebridge.librarybody import LibraryResolutionError
from pipebridge.librarymap import load_library_map
from pipebridge.parser import parse
from pipebridge.workflow import generate_workflow


def _write_map(tmp_path: Path, libraries: dict[str, str]):
    for _, rel in libraries.items():
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
    return load_library_map(map_path)


def _pipeline(prelude: str, stages_body: str) -> str:
    return (
        f"{prelude}"
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        f"{stages_body}"
        "    }\n"
        "}\n"
    )


def test_successful_resolution_and_forwarding(tmp_path):
    lm = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "publish.groovy").write_text(
        'def call(String label) { packageSources(label) }\n'
        'def packageSources(String label) { sh "echo ${label}" }\n',
        encoding="utf-8",
    )
    source = _pipeline(
        "@Library('build-lib') _\n",
        "        stage('Publish') {\n"
        "            steps {\n"
        "                publish('packaged')\n"
        "            }\n"
        "        }\n",
    )
    result = analyze_source(source, library_map=lm, source_path="ci/Jenkinsfile")
    assert not result.has_blockers
    assert not result.pipeline.blocked
    assert not result.pipeline.stages[0].blocked

    assume = [f for f in result.findings if f.code == F.PB_ASSUME_LIBRARY]
    assert len(assume) == 1
    assert "build-lib" in assume[0].message
    assert "Jenkins library resolution was not run." in assume[0].message

    inv = result.library_inventory
    assert inv.map_supplied is True
    assert [lib.name for lib in inv.libraries] == ["build-lib"]
    assert inv.libraries[0].vars == ["publish"]
    assert len(inv.calls) == 1
    assert inv.calls[0].status == "resolved"
    assert inv.calls[0].source_path == "ci/Jenkinsfile"
    assert len(inv.operations) == 1
    assert inv.operations[0].kind == "sh"
    assert inv.operations[0].bindings == {"label": "packaged"}
    assert inv.operations[0].call_chain[0] == "ci/Jenkinsfile:publish@7:17"
    assert "publish.groovy:packageSources@" in inv.operations[0].call_chain[1]

    # Conversion remains blocked until script emission exists.
    wf = generate_workflow(result, source_name="ci/Jenkinsfile")
    assert "if: false" in wf


def test_eligible_revision_recorded_in_inventory_and_assumption(tmp_path):
    lm = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { echo 'hi' }\n",
        encoding="utf-8",
    )
    source = _pipeline(
        '@Library("build-lib@v1.2") _\n',
        "        stage('Greet') {\n"
        "            steps {\n"
        "                greet()\n"
        "            }\n"
        "        }\n",
    )
    result = analyze_source(source, library_map=lm)
    assert not result.has_blockers
    assert result.library_inventory.libraries[0].revision == "v1.2"
    assume = [f for f in result.findings if f.code == F.PB_ASSUME_LIBRARY]
    assert len(assume) == 1
    assert "Annotated revision 'v1.2' was not fetched or checked." in assume[0].message


def test_undeclared_mapped_library_is_not_loaded_or_resolved(tmp_path):
    lm = _write_map(tmp_path, {"build-lib": "build-lib", "unused-lib": "unused-lib"})
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { echo 'hi' }\n",
        encoding="utf-8",
    )
    # Shadowing and var in unused-lib must not affect declared build-lib.
    (tmp_path / "unused-lib" / "vars" / "sh.groovy").write_text(
        "def call() { echo 'shadow' }\n",
        encoding="utf-8",
    )
    (tmp_path / "unused-lib" / "vars" / "secretStep.groovy").write_text(
        "def call() { echo 'nope' }\n",
        encoding="utf-8",
    )
    source = _pipeline(
        "@Library('build-lib') _\n",
        "        stage('Build') {\n"
        "            steps {\n"
        "                greet()\n"
        "                sh 'make'\n"
        "            }\n"
        "        }\n"
        "        stage('Unknown') {\n"
        "            steps {\n"
        "                secretStep()\n"
        "            }\n"
        "        }\n",
    )
    result = analyze_source(source, library_map=lm)
    unused = [f for f in result.findings if f.code == F.PB_LIB_MAP_UNUSED]
    assert len(unused) == 1
    assert "unused-lib" in unused[0].message
    assert not result.pipeline.stages[0].blocked
    assert result.pipeline.stages[1].blocked
    assert any(
        f.code == F.PB_LIB_CALL and "no vars/secretStep.groovy" in f.message
        for f in result.findings
    )


def test_legacy_pb_lib_without_map_or_unresolved_declaration(tmp_path):
    lm = _write_map(tmp_path, {"build-lib": "build-lib"})
    source = _pipeline(
        "@Library('other-lib@v2') _\n",
        "        stage('A') {\n"
        "            steps {\n"
        "                echo 'x'\n"
        "            }\n"
        "        }\n",
    )
    # Without a map: legacy PB-LIB, stage steps preserved.
    no_map = parse(source)
    assert [f.code for f in no_map.findings if f.is_blocker] == [F.PB_LIB]
    assert len(no_map.pipeline.stages[0].steps) == 1

    # With a map missing 'other-lib': legacy PB-LIB, unused map entry reported.
    unmapped = parse(source, library_map=lm)
    assert [f.code for f in unmapped.findings if f.is_blocker] == [F.PB_LIB]
    assert any(f.code == F.PB_LIB_MAP_UNUSED for f in unmapped.findings)
    assert len(unmapped.pipeline.stages[0].steps) == 1


def test_ineligible_library_annotation_keeps_legacy_pb_lib(tmp_path):
    lm = _write_map(tmp_path, {"build-lib": "build-lib"})
    for prelude in (
        "@Library('build-lib') def x = 1\n",
        "@Library('build-lib@') _\n",
        "@Library(['build-lib']) _\n",
    ):
        source = _pipeline(
            prelude,
            "        stage('A') {\n"
            "            steps {\n"
            "                echo 'x'\n"
            "            }\n"
            "        }\n",
        )
        res = parse(source, library_map=lm)
        assert F.PB_LIB in [f.code for f in res.findings if f.is_blocker]
        assert res.library_inventory.libraries == []


def test_duplicate_library_declaration_blocks_pipeline(tmp_path):
    lm = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { echo 'hi' }\n",
        encoding="utf-8",
    )
    source = _pipeline(
        "@Library('build-lib') _\n@Library('build-lib@v1') _\n",
        "        stage('A') {\n"
        "            steps {\n"
        "                sh 'make'\n"
        "            }\n"
        "        }\n",
    )
    result = analyze_source(source, library_map=lm)
    assert result.pipeline.blocked
    assert result.pipeline.stages[0].blocked
    assert result.pipeline.stages[0].steps == []
    dup = [f for f in result.findings if f.code == F.PB_LIB_CALL]
    assert len(dup) == 1
    assert "declared more than once" in dup[0].message
    assert (dup[0].line, dup[0].col) == (2, 1)


def test_missing_call_clears_stage_and_preserves_provenance(tmp_path):
    lm = _write_map(tmp_path, {"build-lib": "build-lib"})
    source = _pipeline(
        "@Library('build-lib') _\n",
        "        stage('Broken') {\n"
        "            steps {\n"
        "                sh 'before'\n"
        "                missing()\n"
        "            }\n"
        "        }\n"
        "        stage('Healthy') {\n"
        "            steps {\n"
        "                sh 'after'\n"
        "            }\n"
        "        }\n",
    )
    result = analyze_source(source, library_map=lm, source_path="pipelines/Jenkinsfile")
    assert result.has_blockers
    assert result.pipeline.stages[0].blocked
    assert result.pipeline.stages[0].steps == []
    assert not result.pipeline.stages[1].blocked
    assert len(result.pipeline.stages[1].steps) == 1

    calls = result.library_inventory.calls
    assert len(calls) == 1
    assert calls[0].status == "blocked"
    assert calls[0].chain == ("pipelines/Jenkinsfile:missing@8:17",)
    lib_findings = [f for f in result.findings if f.code == F.PB_LIB_CALL]
    assert len(lib_findings) == 1
    assert lib_findings[0].call_chain == ("pipelines/Jenkinsfile:missing@8:17",)


def test_pending_operations_clear_stage_and_retain_inventory(tmp_path):
    fixture_dir = Path(__file__).resolve().parent.parent / "examples" / "shared-library" / "success"
    lm = load_library_map(fixture_dir / "library-map.json")
    jf_path = fixture_dir / "Jenkinsfile"
    source = jf_path.read_text(encoding="utf-8")

    result = analyze_source(source, library_map=lm, source_path=str(jf_path))
    assert result.has_blockers
    publish_stage = result.pipeline.stages[0]
    assert publish_stage.name == "Publish"
    assert publish_stage.blocked
    assert publish_stage.steps == []

    inv = result.library_inventory
    assert len(inv.calls) == 2
    assert inv.calls[0].name == "publish"
    assert inv.calls[0].status == "pending"
    assert inv.calls[0].chain[0] == f"{jf_path}:publish@7:17"
    assert inv.calls[1].name == "unstash"
    assert inv.calls[1].status == "blocked"
    assert [op.kind for op in inv.operations] == ["sh", "with-credentials", "stash"]
    assert any(f.code == F.PB_LIB_CALL and "pending operation" in f.message for f in result.findings)


def test_unrelated_blocker_clears_stage_preserving_library_inventory(tmp_path):
    lm = _write_map(tmp_path, {"build-lib": "build-lib"})
    (tmp_path / "build-lib" / "vars" / "greet.groovy").write_text(
        "def call() { echo 'hi' }\n",
        encoding="utf-8",
    )
    source = _pipeline(
        "@Library('build-lib') _\n",
        "        stage('Mixed') {\n"
        "            steps {\n"
        "                greet()\n"
        "                script { println 'nope' }\n"
        "            }\n"
        "        }\n",
    )
    result = analyze_source(source, library_map=lm, source_path="Jenkinsfile")
    stage = result.pipeline.stages[0]
    assert stage.blocked
    assert stage.steps == []
    assert [f.code for f in result.findings if f.is_blocker] == [F.PB_SCRIPT]
    assert any(f.code == F.PB_ASSUME_LIBRARY for f in result.findings)
    assert len(result.library_inventory.calls) == 1
    assert result.library_inventory.calls[0].status == "resolved"
    assert [op.kind for op in result.library_inventory.operations] == ["echo"]


def test_containment_failure_propagates_as_tool_error(tmp_path, tmp_path_factory):
    lm = _write_map(tmp_path, {"build-lib": "build-lib"})
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.groovy").write_text("def call() { sh 'id' }\n", encoding="utf-8")
    (tmp_path / "build-lib" / "vars" / "escape.groovy").symlink_to(outside / "secret.groovy")

    source = _pipeline(
        "@Library('build-lib') _\n",
        "        stage('Escape') {\n"
        "            steps {\n"
        "                escape()\n"
        "            }\n"
        "        }\n",
    )
    with pytest.raises(LibraryResolutionError) as exc_info:
        analyze_source(source, library_map=lm)
    assert isinstance(exc_info.value, PipebridgeError)


def test_non_library_python_build_workflow_bytes_unchanged():
    example = Path(__file__).resolve().parent.parent / "examples" / "python-build"
    source = (example / "Jenkinsfile").read_text(encoding="utf-8")
    expected = (example / "migration" / "workflow.yml").read_text(encoding="utf-8")
    result = analyze_source(source)
    actual = generate_workflow(result, source_name="Jenkinsfile")
    assert actual == expected
