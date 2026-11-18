"""Surrounding Groovy (v0.2.0): prelude and postlude around a top-level
declarative pipeline block.

Specification: docs/compatibility-study.md §7 (v0.2.0 recommendation) with
the classification rules as merged in PR #10:

- The single top-level ``pipeline {}`` block is extracted and analyzed as
  usual; every top-level stage is listed.
- Ordinary imports are reported at info level (PB-GROOVY-IMPORT) and do not
  block; every other surrounding form is executable Groovy and blocks
  (PB-GROOVY-PRELUDE / PB-GROOVY-POSTLUDE). Groovy is never evaluated and no
  initializer is ever classified as harmless.
- Any blocker means exit 2 and a disabled draft (``if: false``).
- Genuinely scripted files keep the unchanged PB-SCRIPT classification.
- Multiple or ambiguous ``pipeline`` occurrences are rejected
  (MalformedPipelineError); one is never selected silently.
"""

import json
from pathlib import Path

import pytest

from pipebridge.errors import MalformedPipelineError
from pipebridge.parser import parse

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = REPO_ROOT / "docs" / "compatibility-study" / "synthetic"


def blocker_codes(result):
    return [f.code for f in result.findings if f.severity == "blocker"]


def codes(result):
    return [f.code for f in result.findings]


PIPELINE = "pipeline {\n    agent any\n    stages {\n        stage('A') {\n            steps {\n                echo 'x'\n            }\n        }\n    }\n}\n"


# ---- recognized prelude forms ---------------------------------------


def test_imports_only_prelude_is_info_and_structure_is_extracted():
    source = (
        "import hudson.model.Result\n"
        "import static com.example.Foo.*\n"
        "\n" + PIPELINE
    )
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    # Imports are info-level only: no blocker, draft stays enabled.
    assert blocker_codes(result) == []
    import_infos = [f for f in result.findings if f.code == "PB-GROOVY-IMPORT"]
    assert len(import_infos) == 2
    assert import_infos[0].severity == "info"
    assert (import_infos[0].line, import_infos[0].col) == (1, 1)
    assert "hudson.model.Result" in import_infos[0].message
    assert "static com.example.Foo.*" in import_infos[1].message


def test_wildcard_and_static_import_forms_are_supported():
    source = "import a.b.C\nimport static a.b.C.*\nimport a.b.*\n" + PIPELINE
    result = parse(source)
    assert blocker_codes(result) == []
    assert len([f for f in result.findings if f.code == "PB-GROOVY-IMPORT"]) == 3


def test_import_as_aliasing_is_not_supported_and_blocks():
    source = "import a.b.C as Foo\n" + PIPELINE
    result = parse(source)
    assert result.pipeline is not None  # structure still extracted
    assert blocker_codes(result) == ["PB-GROOVY-PRELUDE"]
    prelude = result.findings[0]
    assert (prelude.line, prelude.col) == (1, 1)
    assert "as" in prelude.message


def test_literal_initializer_is_blocked():
    source = "String release_tag = 'v1.2.3'\n" + PIPELINE
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    assert blocker_codes(result) == ["PB-GROOVY-PRELUDE"]
    f = result.findings[0]
    assert (f.line, f.col) == (1, 1)
    # The message must never claim the initializer is harmless.
    assert "harmless" not in f.message.lower()


def test_side_effecting_initializer_is_blocked():
    source = (
        "String build_id = org.apache.commons.lang.RandomStringUtils.random(4, false, true)\n"
        + PIPELINE
    )
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    assert blocker_codes(result) == ["PB-GROOVY-PRELUDE"]


def test_def_declaration_is_blocked_and_structure_extracted():
    source = "def releaseNotes\n\n" + PIPELINE
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    assert blocker_codes(result) == ["PB-GROOVY-PRELUDE"]
    f = result.findings[0]
    assert (f.line, f.col) == (1, 1)


def test_multiline_initializer_with_braces_is_skipped_whole():
    source = (
        "def config = [\n"
        "    a: 1,\n"
        "    b: 'value { with braces }',\n"
        "]\n"
        "def closure = { incoming ->\n"
        "    incoming + 1\n"
        "}\n" + PIPELINE
    )
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    assert blocker_codes(result) == ["PB-GROOVY-PRELUDE", "PB-GROOVY-PRELUDE"]
    assert (result.findings[0].line, result.findings[0].col) == (1, 1)
    assert (result.findings[1].line, result.findings[1].col) == (5, 1)


# ---- recognized postlude forms ---------------------------------------


def test_trailing_helper_functions_block_and_structure_is_extracted():
    source = (
        PIPELINE
        + "\n"
        + "def helper() {\n"
        + "    echo 'after'\n"
        + "}\n"
        + "\n"
        + "def helper2(String a) {\n"
        + "    echo \"{ with braces } ${a}\"\n"
        + "}\n"
    )
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    postludes = [f for f in result.findings if f.code == "PB-GROOVY-POSTLUDE"]
    assert len(postludes) == 2
    assert all(f.severity == "blocker" for f in postludes)
    assert (postludes[0].line, postludes[0].col) == (12, 1)
    assert (postludes[1].line, postludes[1].col) == (16, 1)


def test_combined_prelude_and_postlude():
    source = (
        "import a.b.C\n"
        "def x = 'side effect'\n"
        + PIPELINE
        + "\n"
        + "def helper() {\n"
        + "    echo 'after'\n"
        + "}\n"
    )
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    assert blocker_codes(result) == ["PB-GROOVY-PRELUDE", "PB-GROOVY-POSTLUDE"]
    assert len([f for f in result.findings if f.code == "PB-GROOVY-IMPORT"]) == 1


# ---- calls to imported symbols and helper functions --------------------


def test_step_calling_helper_function_still_blocked_by_existing_rules():
    source = (
        PIPELINE.replace("echo 'x'", "helper('arg')")
        + "\n"
        + "def helper() {\n"
        + "    echo 'after'\n"
        + "}\n"
    )
    result = parse(source)
    assert result.pipeline is not None
    # Existing unsupported-step blocker fires; the call was not translated.
    assert "PB-SYNTAX" in blocker_codes(result)
    assert "PB-GROOVY-POSTLUDE" in blocker_codes(result)
    stage = result.pipeline.stages[0]
    assert stage.blocked is True
    assert stage.steps == []


def test_step_referencing_imported_symbol_still_blocked():
    source = (
        "import hudson.model.Result\n"
        + PIPELINE.replace("echo 'x'", "Result.dump()")
    )
    result = parse(source)
    assert result.pipeline is not None
    # The import is info-level, but the call keeps its existing blocker.
    assert "PB-SYNTAX" in blocker_codes(result)
    assert "PB-GROOVY-IMPORT" in codes(result)


# ---- strings and comments never read as structure ----------------------


def test_pipeline_text_and_braces_inside_strings_and_comments():
    source = (
        "// pipeline { in a comment\n"
        "/* pipeline { another } */\n"
        "def s = 'pipeline { not real }'\n"
        "def t = \"also { not real }\"\n"
        + PIPELINE.replace("echo 'x'", "echo 'pipeline { inside step string }'")
        + "\n"
        + "// postlude comment with pipeline {\n"
        + "def helper() {\n"
        + "    echo 'brace } and pipeline { inside'\n"
        + "}\n"
    )
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    assert blocker_codes(result) == ["PB-GROOVY-PRELUDE", "PB-GROOVY-PRELUDE", "PB-GROOVY-POSTLUDE"]


# ---- positions after a prelude ----------------------------------------


def test_positions_after_prelude_point_at_original_source():
    source = (
        "#!/usr/bin/env groovy\n"
        "\n"
        "// a comment line\n"
        "import a.b.C\n"
        "\n"
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Build') {\n"
        "            steps {\n"
        "                echo 'hello'\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    assert result.pipeline is not None
    stage = result.pipeline.stages[0]
    assert (stage.span.line, stage.span.col) == (9, 9)
    step = stage.steps[0]
    assert (step.span.line, step.span.col) == (11, 17)


# ---- annotations and unsupported surrounding syntax --------------------


def test_library_annotation_keeps_existing_pb_lib_behavior():
    source = "@Library('my-shared-lib@v2') _\n" + PIPELINE
    result = parse(source)
    assert result.pipeline is not None
    assert blocker_codes(result) == ["PB-LIB"]
    assert (result.findings[0].line, result.findings[0].col) == (1, 1)
    # Steps stay translated for the PB-LIB-only case (existing behavior).
    assert len(result.pipeline.stages[0].steps) == 1


def test_other_annotation_is_blocked_as_prelude_groovy():
    source = "@Grab('org.apache.commons:commons-lang3:3.14')\n" + PIPELINE
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    assert blocker_codes(result) == ["PB-GROOVY-PRELUDE"]
    f = result.findings[0]
    assert (f.line, f.col) == (1, 1)
    assert "annotation" in f.construct


def test_unrecognized_prelude_statement_is_scripted_and_discards_buffered():
    source = (
        "import a.b.C\n"
        "def x = 1\n"
        "properties([buildDiscarder(logRotator(numToKeepStr: '5'))])\n"
        + PIPELINE
    )
    result = parse(source)
    # Arbitrary Groovy in the prelude: unchanged scripted classification;
    # the buffered surrounding-Groovy findings are discarded so a scripted
    # file reports exactly one blocker, at the first source token.
    assert result.pipeline is None
    assert blocker_codes(result) == ["PB-SCRIPT"]
    f = result.findings[0]
    assert (f.line, f.col) == (1, 1)
    assert len(result.findings) == 1


def test_conditional_pipeline_in_prelude_without_top_level_is_scripted():
    source = (
        "if (env.BRANCH_NAME == 'main') {\n"
        "    pipeline {\n"
        "        agent any\n"
        "    }\n"
        "}\n"
    )
    result = parse(source)
    assert result.pipeline is None
    assert blocker_codes(result) == ["PB-SCRIPT"]


# ---- multiple / nested / ambiguous pipeline occurrences -----------------


def test_two_top_level_pipeline_blocks_are_rejected():
    source = PIPELINE + "\n" + PIPELINE
    with pytest.raises(MalformedPipelineError):
        parse(source)


def test_pipeline_shape_inside_prelude_statement_is_ambiguous():
    source = (
        "def wrapper() {\n"
        "    pipeline {\n"
        "        agent any\n"
        "    }\n"
        "}\n"
        + PIPELINE
    )
    with pytest.raises(MalformedPipelineError):
        parse(source)


def test_pipeline_shape_inside_postlude_statement_is_rejected():
    source = (
        PIPELINE
        + "\n"
        + "def make() {\n"
        + "    return pipeline {\n"
        + "        agent any\n"
        + "    }\n"
        + "}\n"
    )
    with pytest.raises(MalformedPipelineError):
        parse(source)


# ---- unbalanced syntax --------------------------------------------------


def test_unbalanced_postlude_syntax_is_a_blocker_not_a_crash():
    source = PIPELINE + "\ndef foo() {\n    echo 'unterminated'\n"
    result = parse(source)
    assert result.pipeline is not None
    assert [s.name for s in result.pipeline.stages] == ["A"]
    assert blocker_codes(result) == ["PB-GROOVY-POSTLUDE"]
    f = result.findings[0]
    assert (f.line, f.col) == (12, 1)
    assert "not closed" in f.message


def test_unbalanced_prelude_statement_is_scripted_without_crash():
    source = "def foo() {\n    echo 'unterminated'\n"
    result = parse(source)
    assert result.pipeline is None
    assert blocker_codes(result) == ["PB-SCRIPT"]


# ---- scripted files keep their classification ---------------------------


def test_true_scripted_pipeline_keeps_pb_script_exactly():
    source = "node {\n    checkout scm\n    sh 'make build'\n}\n"
    result = parse(source)
    assert result.pipeline is None
    assert blocker_codes(result) == ["PB-SCRIPT"]
    assert len(result.findings) == 1
    assert (result.findings[0].line, result.findings[0].col) == (1, 1)


def test_scripted_pipeline_with_leading_declarations_still_pb_script():
    # jenkinsci/jenkins-style: declarations then arbitrary Groovy calls.
    source = (
        "#!/usr/bin/env groovy\n"
        "def failFast = false\n"
        "def numBuildToKeep = '50'\n"
        "properties([\n"
        "  buildDiscarder(logRotator(numToKeepStr: numBuildToKeep)),\n"
        "])\n"
        "stage('Build') {\n"
        "    echo 'building'\n"
        "}\n"
    )
    result = parse(source)
    assert result.pipeline is None
    assert blocker_codes(result) == ["PB-SCRIPT"]
    assert len(result.findings) == 1
    assert (result.findings[0].line, result.findings[0].col) == (2, 1)


# ---- empty file behavior (unchanged) ------------------------------------


def test_comments_only_file_is_still_malformed():
    with pytest.raises(MalformedPipelineError):
        parse("#!/usr/bin/env groovy\n// only comments\n/* block comment */\n")


# ---- CLI and fixture level ----------------------------------------------


EXECUTABLE_GROOVY_FIXTURES = [
    "prelude-decl-literal",
    "prelude-decl-side-effect",
    "postlude-functions",
    "prelude-postlude-combined",
    "surrounding-annotations",
    "calls-to-helper",
    "scripted-node",
]


@pytest.mark.parametrize("name", EXECUTABLE_GROOVY_FIXTURES)
def test_every_executable_groovy_fixture_yields_exit_2_and_disabled_draft(name, tmp_path):
    from pipebridge.cli import main

    jf = REPO_ROOT / "tests" / "fixtures" / name / "Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 2
    workflow_text = (out / "workflow.yml").read_text()
    assert "if: false" in workflow_text
    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 2
    assert report["summary"]["blockers"] > 0


def test_imports_only_fixture_yields_exit_0_and_enabled_draft(tmp_path):
    from pipebridge.cli import main

    jf = REPO_ROOT / "tests" / "fixtures" / "prelude-imports-only" / "Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 0
    workflow_text = (out / "workflow.yml").read_text()
    assert "if: false" not in workflow_text
    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 0
    import_infos = [f for f in report["findings"] if f["code"] == "PB-GROOVY-IMPORT"]
    assert len(import_infos) == 3
    assert all(f["severity"] == "info" for f in import_infos)
    # Real steps are translated (imports do not block translation).
    assert report["summary"]["translated_steps"] > 0
    assert all(entry["steps"] for entry in report["translated"])


def test_surrounding_groovy_produces_skeleton_not_translated_steps(tmp_path):
    from pipebridge.cli import main

    jf = REPO_ROOT / "tests" / "fixtures" / "postlude-functions" / "Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 2
    workflow_text = (out / "workflow.yml").read_text()
    report = json.loads((out / "migration-report.json").read_text())
    # The executable surrounding Groovy is a pipeline-level blocker: the
    # draft is a skeleton (stages listed, no steps translated).
    assert report["summary"]["blockers"] >= 1
    assert "if: false" in workflow_text
    assert "[NOT MIGRATED] pipeline" in workflow_text
    assert 'Stages found in the source' in workflow_text
    assert all(not entry["steps"] for entry in report["translated"])


# ---- the study's five affected synthetic fixtures -----------------------


EXPECTED_SYNTHETIC_STAGES = {
    "java-maven-jetty-like": ["Parallel Stage"],
    "python-app-couchbase-cli-like": ["Run tests", "Lint"],
    "node-release-tutanota-like": ["Prepare", "Desktop build", "Release approval", "Publish"],
    "container-k8s-memphis-like": ["Pre Build", "Build", "Deploy test env"],
    "infra-deploy-hmrc-like": [
        "Set build details",
        "Build artefact",
        "Run tests",
        "Generate sha256",
        "Deploy",
    ],
}


EXPECTED_SYNTHETIC_NEW_CODES = {
    "java-maven-jetty-like": {"PB-GROOVY-POSTLUDE"},
    "python-app-couchbase-cli-like": {"PB-GROOVY-IMPORT"},
    "node-release-tutanota-like": {"PB-GROOVY-PRELUDE", "PB-GROOVY-POSTLUDE"},
    "container-k8s-memphis-like": {"PB-GROOVY-PRELUDE", "PB-GROOVY-POSTLUDE"},
    "infra-deploy-hmrc-like": {"PB-GROOVY-PRELUDE"},
}


@pytest.mark.parametrize("name", sorted(EXPECTED_SYNTHETIC_STAGES))
def test_affected_synthetic_lists_every_top_level_stage_and_disables_draft(name, tmp_path):
    from pipebridge.cli import main

    jf = SYNTHETIC / f"{name}.Jenkinsfile"
    out = tmp_path / "migration"
    assert main(["convert", str(jf), "--output", str(out)]) == 2
    workflow_text = (out / "workflow.yml").read_text()
    assert "if: false" in workflow_text
    report = json.loads((out / "migration-report.json").read_text())
    listed = [entry["stage"] for entry in report["translated"]]
    assert listed == EXPECTED_SYNTHETIC_STAGES[name]
    found = {f["code"] for f in report["findings"]}
    for code in EXPECTED_SYNTHETIC_NEW_CODES[name]:
        assert code in found, f"{name}: missing {code}"


# ---- byte-identical pure declarative outputs ----------------------------


@pytest.mark.parametrize(
    "name",
    ["python-gpu-kymatio-like", "node-minimal-do400-like"],
)
def test_pure_declarative_synthetics_remain_byte_identical(name, tmp_path):
    from pipebridge.cli import main

    golden = REPO_ROOT / "tests" / "goldens" / "pure-declarative" / f"{name}.workflow.yml"
    jf = SYNTHETIC / f"{name}.Jenkinsfile"
    out = tmp_path / "migration"
    main(["convert", str(jf), "--output", str(out)])
    generated = (out / "workflow.yml").read_text()
    assert generated == golden.read_text(), (
        "pure declarative output changed — regeneration must be deliberate"
    )
