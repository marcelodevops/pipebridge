"""Regression tests for GitHub expression safety in generated artifacts.

GitHub Actions evaluates ``${{ ... }}`` in workflow fields (run scripts,
names, env values) BEFORE the shell runs; shell quoting does not prevent
evaluation. These tests verify literal preservation of source text that
contains expression syntax — by simulating GitHub's substitution and, for
commands, actually running the result under bash.
"""

import subprocess

import yaml

from pipebridge.analysis import analyze_source
from pipebridge.workflow import generate_workflow

# The documented escaping idiom: pipebridge emits EMITTED_IDIOM for each
# literal ``${{`` in text placed in GitHub-evaluated fields, and GitHub
# evaluates it back to LITERAL_EXPRESSION. Built by concatenation so this
# module has exactly one unambiguous spelling of each.
LITERAL_EXPRESSION = "$" + "{{"
EMITTED_IDIOM = "${{ '" + LITERAL_EXPRESSION + "' }}"

SOURCE = (
    "pipeline {\n"
    "    agent any\n"
    "    stages {\n"
    "        stage('Build') {\n"
    "            steps {\n"
    "                echo '${{ secrets.DEMO }}'\n"
    "            }\n"
    "        }\n"
    "    }\n"
    "}\n"
)


def gen(source=SOURCE, **kwargs):
    return generate_workflow(analyze_source(source), **kwargs)


def steps_of(text):
    parsed = yaml.safe_load(text)
    return parsed["jobs"]["migrated-pipeline"]["steps"]


def build_step_of(text, name="Build"):
    return next(s for s in steps_of(text) if s["name"].startswith(name))


def simulate_github_substitution(text: str) -> str:
    """Simulate GitHub's evaluation of the documented escaping idiom."""
    return text.replace(EMITTED_IDIOM, LITERAL_EXPRESSION)


def run_bash(script: str) -> str:
    """Run a generated run-script under bash, exactly as the runner would."""
    result = subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_echo_script_contains_no_expression_syntax_at_all():
    """The echo path must not rely on the idiom at all: the raw generated
    script must contain no ``${{`` sequence, so GitHub has nothing to
    evaluate regardless of quoting."""
    text = gen()
    step = build_step_of(text)
    assert step["run"].startswith("printf")
    assert LITERAL_EXPRESSION not in step["run"]
    assert "secrets.DEMO" in step["run"]


def test_echo_prints_the_literal_when_run_under_bash():
    """End-to-end literal preservation: execute the generated command under
    bash and check the output is the source message, byte for byte."""
    text = gen()
    step = build_step_of(text)
    stdout = run_bash(step["run"])
    assert stdout == LITERAL_EXPRESSION + " secrets.DEMO }}\n"


def test_echo_with_quotes_and_newlines_roundtrips_through_bash():
    """A multi-line message containing quotes and expression syntax must be
    preserved byte-for-byte when the generated command is executed."""
    message = (
        "line1\n"
        "say '" + LITERAL_EXPRESSION + " secrets.TOKEN }}' and \"double\" quoted"
    )
    # Embed as a Groovy triple-single-quoted string: literal newlines and
    # quotes without escape processing.
    source = SOURCE.replace("echo '${{ secrets.DEMO }}'", "echo '''" + message + "'''")
    text = gen(source)
    step = build_step_of(text)
    assert LITERAL_EXPRESSION not in step["run"]
    stdout = run_bash(step["run"])
    assert stdout == message + "\n"


def test_sh_run_block_preserves_literal_after_substitution():
    source = SOURCE.replace(
        "echo '${{ secrets.DEMO }}'",
        "sh './deploy --token ${{ secrets.DEPLOY_TOKEN }}'",
    )
    text = gen(source)
    step = build_step_of(text)
    script = simulate_github_substitution(step["run"])
    assert "./deploy --token ${{ secrets.DEPLOY_TOKEN }}" in script


def test_step_name_with_expression_displays_literally():
    source = SOURCE.replace("stage('Build')", "stage('Build ${{ github.ref }}')")
    text = gen(source)
    step = build_step_of(text)
    name = simulate_github_substitution(step["name"])
    assert name == "Build ${{ github.ref }}"


def test_env_value_with_expression_preserved_after_substitution():
    source = SOURCE.replace(
        "    agent any\n",
        "    agent any\n    environment {\n"
        "        ENDPOINT = 'https://${{ env.HOST }}'\n    }\n",
    )
    text = gen(source)
    parsed = yaml.safe_load(text)
    raw = parsed["jobs"]["migrated-pipeline"]["env"]["ENDPOINT"]
    assert simulate_github_substitution(raw) == "https://${{ env.HOST }}"


def test_placeholder_name_with_expression_is_escaped():
    """A blocked stage's placeholder embeds the source stage name; GitHub
    must not evaluate expression syntax inside the step name."""
    source = SOURCE.replace(
        "stage('Build')",
        "stage('Deploy ${{ secrets.LEAK }}')",
    ).replace(
        "echo '${{ secrets.DEMO }}'",
        "script {\n                    sh 'x'\n                }",
    )
    text = gen(source)
    parsed = yaml.safe_load(text)  # must remain structurally intact YAML
    steps = parsed["jobs"]["migrated-pipeline"]["steps"]
    assert len(steps) == 1
    placeholder = steps[0]
    assert placeholder["name"].startswith("[NOT MIGRATED]")
    # Escaping must actually be applied (not vacuously absent).
    assert EMITTED_IDIOM in placeholder["name"]
    name = simulate_github_substitution(placeholder["name"])
    assert "${{ secrets.LEAK }}" in name


def test_stage_name_with_newline_cannot_inject_into_comments():
    """A stage name with embedded newlines reaches generated '#' comments;
    every embedded newline must be re-prefixed so it cannot introduce a
    non-comment line (workflow structure)."""
    evil_name = "Deploy\n    injected: true\n" + LITERAL_EXPRESSION + " secrets.LEAK }}"
    source = SOURCE.replace(
        "stage('Build')",
        "stage('''" + evil_name + "''')",
    ).replace(
        "echo '${{ secrets.DEMO }}'",
        "script {\n                    sh 'x'\n                }",
    )
    text = gen(source)
    parsed = yaml.safe_load(text)  # injection would have broken the YAML
    steps = parsed["jobs"]["migrated-pipeline"]["steps"]
    assert len(steps) == 1
    assert steps[0]["name"].startswith("[NOT MIGRATED]")


def test_source_name_with_newline_cannot_inject_into_header_comment():
    text = gen(source_name="weird\nname  EVIL: true")
    parsed = yaml.safe_load(text)  # must not raise / must stay a workflow
    assert "migrated-pipeline" in parsed["jobs"]
    # No line outside comments may be introduced by the source name.
    for line in text.splitlines():
        if "name  EVIL" in line or "weird" in line:
            assert line.lstrip().startswith("#")
