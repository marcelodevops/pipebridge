"""Bounded literal string credential bindings.

Contract: docs/v0.4.0-credential-bindings-design.md. Secret values are never
read, and a mapping is never guessed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pipebridge.analysis import analyze_source
from pipebridge.cli import main
from pipebridge.credentials import CredentialMapError, load_credential_map
from pipebridge.errors import PipebridgeError
from pipebridge.parser import parse
from pipebridge.reporting import build_report, render_markdown_report
from pipebridge.workflow import generate_workflow

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pipeline(body: str, extra: str = "") -> str:
    return (
        "pipeline {\n"
        "    agent any\n"
        f"{extra}"
        "    stages {\n"
        "        stage('Publish') {\n"
        "            steps {\n"
        f"{body}\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _binding(body: str, cred_id: str = "npm-registry-token", variable: str = "NPM_TOKEN") -> str:
    return (
        "                withCredentials([string(credentialsId: "
        f"'{cred_id}', variable: '{variable}')]) {{\n"
        f"{body}\n"
        "                }"
    )


def _map(path: Path, credentials: dict) -> Path:
    path.write_text(
        json.dumps({"schema_version": 1, "credentials": credentials}),
        encoding="utf-8",
    )
    return path


def _codes(analysis, code: str) -> list:
    return [f for f in analysis.findings if f.code == code]


def _job(analysis):
    workflow = generate_workflow(analysis, source_name="Jenkinsfile")
    return yaml.safe_load(workflow)["jobs"]["migrated-pipeline"], workflow


# ---- grammar and translation --------------------------------------------


def test_literal_string_binding_translates_body_in_order(tmp_path):
    source = _pipeline(
        "                sh 'echo before'\n"
        + _binding("                    sh 'npm publish'\n                    echo 'done'\n                    checkout scm")
        + "\n                sh 'echo after'"
    )
    cred_map = _map(tmp_path / "map.json", {"npm-registry-token": {"secret": "NPM_TOKEN"}})
    analysis = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    assert analysis.has_blockers is False
    assert [f.code for f in _codes(analysis, "PB-ASSUME-CREDENTIALS")] == ["PB-ASSUME-CREDENTIALS"]
    steps = analysis.pipeline.stages[0].steps
    assert [step.kind for step in steps] == ["sh", "sh", "echo", "checkout", "sh"]
    assert [step.credential_binding_ids for step in steps] == [(), ("cred-1",), ("cred-1",), ("cred-1",), ()]
    job, workflow = _job(analysis)
    assert "if" not in job
    bound = [step for step in job["steps"] if step.get("env")]
    assert len(bound) == 3
    assert all(step["env"]["NPM_TOKEN"] == "${{ secrets.NPM_TOKEN }}" for step in bound)
    assert "secrets.NPM_TOKEN" not in "\n".join(step.get("run", "") for step in job["steps"])
    assert job["steps"][0].get("env") is None
    assert "NPM_TOKEN" not in (job.get("env") or {})
    assert "${{ secrets.NPM_TOKEN }}" in workflow


def test_quote_forms_argument_order_and_comments_are_accepted(tmp_path):
    source = _pipeline(
        """
                withCredentials([
                    // comment between tokens
                    string(variable: "NPM_TOKEN", credentialsId: "npm-registry-token")
                ]) {
                    sh '''npm publish'''
                }
        """
    )
    cred_map = _map(tmp_path / "map.json", {"npm-registry-token": {"secret": "NPM_TOKEN"}})
    analysis = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    assert analysis.has_blockers is False
    assert analysis.pipeline.stages[0].steps[0].text == "npm publish"
    job, _ = _job(analysis)
    assert job["steps"][1]["env"]["NPM_TOKEN"] == "${{ secrets.NPM_TOKEN }}"


def test_source_position_points_at_withcredentials_token():
    source = _pipeline(_binding("                    sh 'npm publish'"))
    result = parse(source)
    entry = result.credential_inventory.entries[0]
    line = source.splitlines()[entry.span.line - 1]
    assert line[entry.span.col - 1 :].startswith("withCredentials")


def test_interpolation_discards_the_body_and_keeps_pb_interp():
    source = _pipeline(_binding('                    sh "echo ${env.BUILD_NUMBER}"\n                    echo \'later\''))
    result = parse(source)
    assert result.pipeline.stages[0].steps == []
    assert result.pipeline.stages[0].blocked is True
    cred = [f for f in result.findings if f.code == "PB-CRED"]
    interp = [f for f in result.findings if f.code == "PB-INTERP"]
    assert len(cred) == 1
    assert "interpolated sh argument" in cred[0].message
    assert len(interp) == 1
    assert result.credential_inventory.entries[0].status == "unsupported"
    assert "BUILD_NUMBER" not in generate_workflow(analyze_source(source), "Jenkinsfile").split("env:", 1)[-1]


# ---- scope, opaque bodies, durability -----------------------------------


def test_environment_name_collision_blocks_before_and_after_steps():
    before = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Publish') {\n"
        "            environment { CHANNEL = 'stable' }\n"
        "            steps {\n"
        + _binding("                    sh 'npm publish'", variable="CHANNEL")
        + "\n            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    after = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Publish') {\n"
        "            steps {\n"
        + _binding("                    sh 'npm publish'", variable="CHANNEL")
        + "\n            }\n"
        "            environment { CHANNEL = 'later' }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    for source in (before, after):
        blocked = analyze_source(source)
        assert any(f.code == "PB-CRED" and "collides" in f.message for f in blocked.findings)
        assert blocked.pipeline.stages[0].steps == []
        assert blocked.credential_inventory.entries[0].status == "unsupported"


def test_stage_env_is_merged_onto_bound_steps_only(tmp_path):
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Publish') {\n"
        "            environment { CHANNEL = 'stable' }\n"
        "            steps {\n"
        "                sh 'echo before'\n"
        + _binding("                    sh 'npm publish'")
        + "\n            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    cred_map = _map(tmp_path / "map.json", {"npm-registry-token": {"secret": "NPM_TOKEN"}})
    analysis = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    job, _ = _job(analysis)
    before, bound = job["steps"][1], job["steps"][2]
    assert before["env"] == {"CHANNEL": "stable"}
    assert bound["env"] == {"CHANNEL": "stable", "NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"}
    assert "NPM_TOKEN" not in analysis.pipeline.env
    assert all(var.name != "NPM_TOKEN" for var in analysis.pipeline.stages[0].env)


def test_sequential_bindings_are_independent_and_nested_is_blocked(tmp_path):
    source = _pipeline(
        _binding("                    sh 'first'", cred_id="one", variable="TOK")
        + "\n"
        + _binding("                    sh 'second'", cred_id="two", variable="TOK")
    )
    cred_map = _map(
        tmp_path / "map.json",
        {"one": {"secret": "ONE_TOKEN"}, "two": {"secret": "TWO_TOKEN"}},
    )
    analysis = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    job, _ = _job(analysis)
    assert job["steps"][1]["env"] == {"TOK": "${{ secrets.ONE_TOKEN }}"}
    assert job["steps"][2]["env"] == {"TOK": "${{ secrets.TWO_TOKEN }}"}

    nested = _pipeline(
        _binding(
            "                    "
            + _binding("                        sh 'inner'", cred_id="two", variable="INNER").strip()
        )
    )
    blocked = parse(nested)
    assert blocked.pipeline.stages[0].steps == []
    assert len([f for f in blocked.findings if f.code == "PB-CRED"]) == 1
    assert "inner" not in "\n".join(f.message for f in blocked.findings)


def test_opaque_body_is_not_mined_and_partial_interpolations_stop():
    opaque = _pipeline(
        _binding(
            "                    script {\n"
            "                        sh \"echo ${env.HIDDEN}\"\n"
            "                    }"
        )
    )
    result = parse(opaque)
    assert not any(f.code == "PB-INTERP" for f in result.findings)
    assert "HIDDEN" not in "\n".join(f.message for f in result.findings)
    assert result.pipeline.stages[0].steps == []

    partial = _pipeline(
        _binding(
            "                    sh 'kept-in-buffer-only'\n"
            "                    echo \"build ${env.BUILD_NUMBER}\"\n"
            "                    timeout(time: 1) { sh \"echo ${env.LATER}\" }"
        )
    )
    result = parse(partial)
    assert result.pipeline.stages[0].steps == []
    interps = [f for f in result.findings if f.code == "PB-INTERP"]
    assert len(interps) == 1
    assert "BUILD_NUMBER" in interps[0].message
    assert "LATER" not in "\n".join(f.message for f in result.findings)
    assert "kept-in-buffer-only" not in "\n".join(f.message for f in result.findings)


def test_newline_before_closure_stays_opaque_and_keeps_later_siblings():
    translated = """
pipeline {
  agent any
  stages {
    stage('A') {
      steps {
        withCredentials([file(credentialsId: 'f', variable: 'F')])
        {
          sh "echo ${SECRET}"
        }
        mavenBuild 'later'
      }
    }
  }
}
"""
    result = parse(translated)
    messages = "\n".join(f.message for f in result.findings)
    assert not any(f.code == "PB-INTERP" for f in result.findings)
    assert "SECRET" not in messages
    assert "'{'" not in messages
    assert any(f.code == "PB-SYNTAX" and "mavenBuild" in f.message for f in result.findings)
    assert result.credential_inventory.entries[0].credential_id is None

    diagnosed = """
pipeline {
  agent none
  stages {
    stage('A') {
      steps {
        withCredentials([string(credentialsId: 'id', variable: 'TOK')])
        {
          sh "echo ${SECRET}"
        }
        mavenBuild 'later'
      }
    }
  }
}
"""
    result = parse(diagnosed)
    messages = "\n".join(f.message for f in result.findings)
    assert not any(f.code == "PB-INTERP" for f in result.findings)
    assert "SECRET" not in messages
    assert "'{'" not in messages
    assert any(f.code == "PB-SYNTAX" and "mavenBuild" in f.message for f in result.findings)
    entry = result.credential_inventory.entries[0]
    assert entry.status == "unsupported"
    assert entry.credential_id == "id"
    assert entry.variable == "TOK"


_SEMICOLON_HEADERS = [
    "withCredentials(; [string(credentialsId: 'id', variable: 'TOK')])",
    "withCredentials([; string(credentialsId: 'id', variable: 'TOK')])",
    "withCredentials([string(; credentialsId: 'id', variable: 'TOK')])",
    "withCredentials([string(credentialsId; : 'id', variable: 'TOK')])",
    "withCredentials([string(credentialsId:; 'id', variable: 'TOK')])",
    "withCredentials([string(credentialsId: 'id'; variable: 'TOK')])",
    "withCredentials([string(credentialsId: 'id',; variable: 'TOK')])",
    "withCredentials([string(credentialsId: 'id', variable: 'TOK'); ])",
    "withCredentials([string(credentialsId: 'id', variable: 'TOK')]; )",
    "withCredentials([string(credentialsId: 'id', variable: 'TOK')]);",
]


def _semicolon_source(header: str, *, agent: str = "any") -> str:
    return (
        "pipeline {\n"
        f"  agent {agent}\n"
        "  stages {\n"
        "    stage('A') {\n"
        "      steps {\n"
        f"        {header} {{\n"
        "          sh 'secret-cmd'\n"
        "        }\n"
        "        mavenBuild 'later'\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )


def _assert_malformed_header_stays_blocked(analysis, workflow: str) -> None:
    stage = analysis.pipeline.stages[0]
    assert stage.blocked is True
    assert stage.steps == []
    assert analysis.credential_inventory.entries
    assert all(entry.status == "unsupported" for entry in analysis.credential_inventory.entries)
    assert any(f.code == "PB-CRED" for f in analysis.findings)
    assert any(f.code == "PB-SYNTAX" and "mavenBuild" in f.message for f in analysis.findings)
    assert not any(f.code == "PB-ASSUME-CREDENTIALS" for f in analysis.findings)
    job, _ = _job(analysis)
    assert job["if"] is False
    assert "secret-cmd" not in workflow
    assert "secrets.THE_SECRET" not in workflow
    assert "TOK:" not in workflow


@pytest.mark.parametrize("header", _SEMICOLON_HEADERS)
def test_semicolon_in_header_stays_blocked_with_ready_map(tmp_path, header):
    cred_map = _map(tmp_path / "map.json", {"id": {"secret": "THE_SECRET"}})
    analysis = analyze_source(
        _semicolon_source(header),
        load_credential_map(cred_map),
        secrets_ready=True,
    )
    _assert_malformed_header_stays_blocked(analysis, generate_workflow(analysis, "Jenkinsfile"))


def test_semicolon_before_body_is_not_translated_from_a_blocked_scope():
    result = parse(_semicolon_source(
        "withCredentials([string(credentialsId: 'id', variable: 'TOK')]);",
        agent="none",
    ))
    messages = "\n".join(f.message for f in result.findings)
    assert "SECRET" not in messages
    assert "secret-cmd" not in messages
    assert result.pipeline.stages[0].steps == []
    entry = result.credential_inventory.entries[0]
    assert entry.status == "unsupported"
    assert any(f.code == "PB-SYNTAX" and "mavenBuild" in f.message for f in result.findings)


def test_body_semicolons_and_newlines_still_translate(tmp_path):
    cred_map = load_credential_map(
        _map(
            tmp_path / "map.json",
            {"id": {"secret": "THE_SECRET"}, "id;still": {"secret": "STILL_SECRET"}},
        )
    )
    body = """
pipeline {
  agent any
  stages {
    stage('A') {
      steps {
        withCredentials([string(credentialsId: 'id', variable: 'TOK')]) {
          sh 'one'; echo 'two'; checkout scm
        }
      }
    }
  }
}
"""
    analysis = analyze_source(body, cred_map, secrets_ready=True)
    steps = analysis.pipeline.stages[0].steps
    assert [step.kind for step in steps] == ["sh", "echo", "checkout"]
    assert all(step.credential_binding_ids == ("cred-1",) for step in steps)
    job, workflow = _job(analysis)
    assert "if" not in job
    assert '${{ secrets.THE_SECRET }}' in workflow

    spaced = """
pipeline {
  agent any
  stages {
    stage('A') {
      steps {
        withCredentials([
          string(
            credentialsId: 'id;still',
            variable: 'TOK'
          )
        ])
        {
          sh 'ok'
        }
      }
    }
  }
}
"""
    analysis = analyze_source(spaced, cred_map, secrets_ready=True)
    assert analysis.pipeline.stages[0].steps[0].text == "ok"
    assert analysis.credential_inventory.entries[0].status == "resolved"
    assert '${{ secrets.STILL_SECRET }}' in generate_workflow(analysis, "Jenkinsfile")


def test_unsupported_variants_keep_the_legacy_message_and_no_inventory_outside_steps():
    source = _pipeline(
        "                withCredentials([string(credentialsId: 'c', usernameVariable: 'U')]) {\n"
        "                    sh 'push'\n"
        "                }"
    )
    result = parse(source)
    cred = [f for f in result.findings if f.code == "PB-CRED"]
    assert len(cred) == 1
    assert "not migrated automatically" in cred[0].message
    assert "not analyzed" in cred[0].message
    assert "push" not in cred[0].message
    assert result.credential_inventory.entries[0].credential_id is None

    outside = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('A') {\n"
        "            withCredentials([string(credentialsId: 'id', variable: 'TOK')]) { sh 'x' }\n"
        "            steps { sh 'ok' }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    result = parse(outside)
    assert result.credential_inventory.entries == []
    assert any(f.code == "PB-SYNTAX" for f in result.findings)


def test_diagnosed_binding_is_unsupported_and_not_resolvable(tmp_path):
    source = (
        "pipeline {\n"
        "    agent none\n"
        "    stages {\n"
        "        stage('A') {\n"
        "            steps {\n"
        "                withCredentials([string(credentialsId: 'id', variable: 'TOK')]) {\n"
        "                    sh 'use $T'\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    cred_map = _map(tmp_path / "map.json", {"id": {"secret": "THE_SECRET"}})
    analysis = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    entry = analysis.credential_inventory.entries[0]
    assert entry.status == "unsupported"
    assert entry.secret_name is None
    assert any("not analyzed" in f.message for f in analysis.findings if f.code == "PB-CRED")
    assert not _codes(analysis, "PB-CRED-MAP")
    assert not _codes(analysis, "PB-ASSUME-CREDENTIALS")
    report = build_report(analysis, "Jenkinsfile", None)
    assert report["credentials"]["required_secrets"] == []


def test_missing_mapping_clears_steps_but_keeps_inventory(tmp_path):
    source = _pipeline(_binding("                    sh 'npm publish'"))
    analysis = analyze_source(source)
    entry = analysis.credential_inventory.entries[0]
    assert entry.status == "missing_mapping"
    assert entry.secret_name is None
    assert analysis.pipeline.stages[0].steps == []
    report = build_report(analysis, "Jenkinsfile", None)
    binding = report["credentials"]["bindings"][0]
    assert binding["source_line"] == entry.span.line
    assert binding["status"] == "missing_mapping"
    assert report["credentials"]["checklist"] == []
    job, workflow = _job(analysis)
    assert job["if"] is False
    assert any("NOT MIGRATED" in step["name"] for step in job["steps"])
    assert "secrets." not in workflow


def test_unrelated_blocker_keeps_resolved_inventory_after_steps_are_cleared(tmp_path):
    source = (
        "pipeline {\n"
        "    agent any\n"
        "    stages {\n"
        "        stage('Publish') {\n"
        "            steps {\n"
        + _binding("                    sh 'npm publish'")
        + "\n            }\n"
        "            post { always { echo 'done' } }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    cred_map = _map(tmp_path / "map.json", {"npm-registry-token": {"secret": "NPM_TOKEN"}})
    analysis = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    assert analysis.pipeline.stages[0].steps == []
    entry = analysis.credential_inventory.entries[0]
    assert entry.status == "resolved"
    assert entry.secret_name == "NPM_TOKEN"
    report = build_report(analysis, "Jenkinsfile", None)
    md = render_markdown_report(report)
    assert report["credentials"]["required_secrets"] == ["NPM_TOKEN"]
    assert md.count("gh secret set NPM_TOKEN") == 1
    assert "--body" not in md
    job, workflow = _job(analysis)
    assert job["if"] is False
    assert "NPM_TOKEN:" not in workflow


def test_later_pipeline_blocker_preserves_a_resolved_binding(tmp_path):
    source = _pipeline(_binding("                    sh 'npm publish'"))
    source = source.rstrip()[:-1] + "    post { always { echo 'done' } }\n}\n"
    cred_map = _map(tmp_path / "map.json", {"npm-registry-token": {"secret": "NPM_TOKEN"}})
    analysis = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    assert any(f.code == "PB-POST" for f in analysis.findings)
    assert analysis.pipeline.stages[0].steps == []
    assert analysis.credential_inventory.entries[0].status == "resolved"
    report = build_report(analysis, "Jenkinsfile", None)
    assert report["credentials"]["checklist"][0]["secret_name"] == "NPM_TOKEN"


def test_parse_is_deterministic_and_does_not_leak_scratch_steps():
    source = _pipeline(_binding("                    timeout(time: 1) { sh 'hidden-command' }"))
    first = parse(source)
    second = parse(source)
    assert [(e.binding_id, e.status, e.reason) for e in first.credential_inventory.entries] == [
        (e.binding_id, e.status, e.reason) for e in second.credential_inventory.entries
    ]
    assert first.pipeline.stages[0].steps == []
    text = "\n".join(f.message for f in first.findings)
    assert "hidden-command" not in text


# ---- mapping, gating, CLI -----------------------------------------------


def test_invalid_secret_name_and_collision_block_without_emitting_a_command(tmp_path):
    source = _pipeline(_binding("                    sh 'npm publish'"))
    bad = _map(tmp_path / "bad.json", {"npm-registry-token": {"secret": "npm_token"}})
    analysis = analyze_source(source, load_credential_map(bad))
    assert analysis.credential_inventory.entries[0].status == "invalid_secret_name"
    assert any(f.code == "PB-CRED-MAP" for f in analysis.findings)
    md = render_markdown_report(build_report(analysis, "Jenkinsfile", None))
    assert "gh secret set" not in md

    colliding = _map(
        tmp_path / "collide.json",
        {
            "npm-registry-token": {"secret": "NPM_TOKEN"},
            "other-id": {"secret": "npm_token".upper()},
        },
    )
    # The second name is the same uppercase secret, so it collides.
    analysis = analyze_source(
        _pipeline(
            _binding("                    sh 'one'", cred_id="npm-registry-token")
            + "\n"
            + _binding("                    sh 'two'", cred_id="other-id", variable="OTHER")
        ),
        load_credential_map(colliding),
    )
    assert {e.status for e in analysis.credential_inventory.entries} == {"collision"}
    md = render_markdown_report(build_report(analysis, "Jenkinsfile", None))
    assert "gh secret set" not in md


def test_setup_gate_emits_steps_until_secrets_ready(tmp_path):
    source = _pipeline(_binding("                    sh 'npm publish'"))
    cred_map = _map(tmp_path / "map.json", {"npm-registry-token": {"secret": "NPM_TOKEN"}})
    held = analyze_source(source, load_credential_map(cred_map), secrets_ready=False)
    assert any(f.code == "PB-CRED-SETUP" for f in held.findings)
    job, _ = _job(held)
    assert job["if"] is False
    assert job["steps"][1]["env"]["NPM_TOKEN"] == "${{ secrets.NPM_TOKEN }}"

    ready = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    assert ready.has_blockers is False
    job, _ = _job(ready)
    assert "if" not in job
    report = build_report(ready, "Jenkinsfile", None)
    assert report["credentials"]["setup_acknowledged"] is True
    assert report["exit_code"] == 0


def test_secrets_ready_does_not_clear_unrelated_or_mapping_blockers(tmp_path):
    source = _pipeline(_binding("                    sh 'npm publish'"))
    missing = _map(tmp_path / "missing.json", {"other": {"secret": "OTHER_TOKEN"}})
    analysis = analyze_source(source, load_credential_map(missing), secrets_ready=True)
    assert any(f.code == "PB-CRED-MAP" for f in analysis.findings)
    assert analysis.has_blockers is True
    assert not _codes(analysis, "PB-ASSUME-CREDENTIALS")


def test_secrets_ready_without_bindings_does_not_change_workflow():
    source = _pipeline("                sh 'make'")
    plain = generate_workflow(analyze_source(source), "Jenkinsfile")
    flagged = generate_workflow(analyze_source(source, secrets_ready=True), "Jenkinsfile")
    assert plain == flagged
    assert not any(f.code.startswith("PB-CRED") for f in analyze_source(source, secrets_ready=True).findings)


def test_structural_map_errors_exit_1_and_write_nothing(tmp_path):
    jenkinsfile = tmp_path / "Jenkinsfile"
    jenkinsfile.write_text(_pipeline(_binding("                    sh 'npm publish'")), encoding="utf-8")
    out = tmp_path / "migration"
    missing = tmp_path / "missing.json"
    assert main(["convert", str(jenkinsfile), "--output", str(out), "--credential-map", str(missing)]) == 1
    assert not out.exists()

    duplicate = tmp_path / "dup.json"
    duplicate.write_text(
        '{"schema_version": 1, "credentials": {"id": {"secret": "TOKEN"}, "id": {"secret": "OTHER"}}}'
    )
    with pytest.raises(CredentialMapError):
        load_credential_map(duplicate)
    assert main(["analyze", str(jenkinsfile), "--credential-map", str(duplicate)]) == 1

    bad_version = tmp_path / "ver.json"
    bad_version.write_text('{"schema_version": true, "credentials": {}}')
    assert main(["convert", str(jenkinsfile), "--output", str(out), "--credential-map", str(bad_version)]) == 1
    assert not out.exists()


def test_source_expression_is_still_escaped_inside_a_bound_step(tmp_path):
    source = _pipeline(_binding("                    sh 'echo ${{ secrets.DEPLOY_TOKEN }}'"))
    cred_map = _map(tmp_path / "map.json", {"npm-registry-token": {"secret": "NPM_TOKEN"}})
    analysis = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    assert any(f.code == "PB-GHEXPR" for f in analysis.findings)
    _job_data, workflow = _job(analysis)
    assert '${{ secrets.DEPLOY_TOKEN }}' not in workflow
    assert '${{ secrets.NPM_TOKEN }}' in workflow


def test_report_escapes_table_delimiters_and_never_prints_a_sentinel(tmp_path, monkeypatch):
    monkeypatch.setenv("NPM_TOKEN", "do-not-leak")
    source = _pipeline(_binding("                    sh 'npm publish'", cred_id="id|with`pipe"))
    cred_map = _map(tmp_path / "map.json", {"id|with`pipe": {"secret": "NPM_TOKEN"}})
    analysis = analyze_source(source, load_credential_map(cred_map), secrets_ready=True)
    report = build_report(analysis, "Jenkinsfile", None)
    md = render_markdown_report(report)
    blob = md + json.dumps(report) + generate_workflow(analysis, "Jenkinsfile")
    assert "do-not-leak" not in blob
    assert "--body" not in md
    assert "id\\|with\\`pipe" in md
    assert report["credentials"]["bindings"][0]["credential_id"] == "id|with`pipe"


def test_cli_convert_ready_binding_and_unused_map_entry(tmp_path):
    jenkinsfile = tmp_path / "Jenkinsfile"
    jenkinsfile.write_text(_pipeline(_binding("                    sh 'npm publish'")), encoding="utf-8")
    cred_map = _map(
        tmp_path / "map.json",
        {
            "npm-registry-token": {"secret": "NPM_TOKEN"},
            "unused-id": {"secret": "UNUSED_TOKEN"},
        },
    )
    out = tmp_path / "migration"
    assert main(
        [
            "convert",
            str(jenkinsfile),
            "--output",
            str(out),
            "--credential-map",
            str(cred_map),
            "--secrets-ready",
        ]
    ) == 0
    report = json.loads((out / "migration-report.json").read_text())
    assert report["exit_code"] == 0
    assert "PB-CRED-MAP-UNUSED" in report["assumptions"]
    assert report["credentials"]["required_secrets"] == ["NPM_TOKEN"]
    parsed = yaml.safe_load((out / "workflow.yml").read_text())
    assert "if" not in parsed["jobs"]["migrated-pipeline"]
    assert "do-not-leak" not in (out / "migration-report.md").read_text()


def test_cli_rejects_semicolon_headers_even_when_secrets_are_ready(tmp_path):
    cred_map = _map(tmp_path / "map.json", {"id": {"secret": "THE_SECRET"}})
    headers = [
        "withCredentials([string(credentialsId: 'id', variable: 'TOK')]);",
        "withCredentials(; [string(credentialsId: 'id', variable: 'TOK')])",
    ]
    for index, header in enumerate(headers):
        jenkinsfile = tmp_path / f"Jenkinsfile-{index}"
        jenkinsfile.write_text(_semicolon_source(header), encoding="utf-8")
        out = tmp_path / f"out-{index}"
        assert main(
            [
                "convert",
                str(jenkinsfile),
                "--output",
                str(out),
                "--credential-map",
                str(cred_map),
                "--secrets-ready",
            ]
        ) == 2
        workflow = (out / "workflow.yml").read_text()
        report = json.loads((out / "migration-report.json").read_text())
        assert report["exit_code"] == 2
        assert report["credentials"]["bindings"]
        assert all(row["status"] == "unsupported" for row in report["credentials"]["bindings"])
        assert report["credentials"]["required_secrets"] == []
        parsed = yaml.safe_load(workflow)
        assert parsed["jobs"]["migrated-pipeline"]["if"] is False
        assert "secret-cmd" not in workflow
        assert "secrets.THE_SECRET" not in workflow
        assert "mavenBuild" not in workflow


def test_internal_unresolved_step_reference_fails_closed():
    source = _pipeline(_binding("                    sh 'npm publish'"))
    parsed = parse(source)
    # A committed step must not be emitted against a still-pending entry.
    from pipebridge.analysis import AnalysisResult
    import hashlib

    analysis = AnalysisResult(
        findings=[],
        pipeline=parsed.pipeline,
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        credential_inventory=parsed.credential_inventory,
    )
    with pytest.raises(PipebridgeError, match="not resolved"):
        generate_workflow(analysis, "Jenkinsfile")
