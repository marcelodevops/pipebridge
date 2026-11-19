"""Migration analysis: assumptions, warnings, and finding assembly."""

from __future__ import annotations

import hashlib
import re

from .findings import (
    Finding,
    PB_ASSUME_CHECKOUT,
    PB_ASSUME_RUNNER,
    PB_ASSUME_RUNNER_LABEL,
    PB_ASSUME_SHELL,
    PB_GHEXPR,
    PB_JENV,
    PB_SINGLE_JOB,
    PB_TRIGGER_MANUAL,
)
from .model import Pipeline, Span
from .parser import parse

# Jenkins-specific environment variables that have no value on GitHub
# Actions runners. Referenced shell variables are preserved as-is but
# reported so a human can map them deliberately.
JENKINS_VARIABLES = (
    "BRANCH_NAME",
    "BUILD_DISPLAY_NAME",
    "BUILD_ID",
    "BUILD_NUMBER",
    "BUILD_TAG",
    "BUILD_URL",
    "CHANGE_AUTHOR",
    "CHANGE_BRANCH",
    "CHANGE_ID",
    "CHANGE_TARGET",
    "CHANGE_TITLE",
    "EXECUTOR_NUMBER",
    "GIT_BRANCH",
    "GIT_COMMIT",
    "GIT_URL",
    "JENKINS_HOME",
    "JENKINS_URL",
    "JOB_BASE_NAME",
    "JOB_NAME",
    "NODE_LABELS",
    "NODE_NAME",
    "TAG_NAME",
    "WORKSPACE",
)

_JENKINS_VAR_RE = re.compile(
    r"\$[({]?(" + "|".join(JENKINS_VARIABLES) + r")\b\}?"
)
_GH_EXPR = "${{"


class AnalysisResult:
    def __init__(self, findings: list[Finding], pipeline: Pipeline | None, source_sha256: str) -> None:
        self.findings = findings
        self.pipeline = pipeline
        self.source_sha256 = source_sha256

    @property
    def has_blockers(self) -> bool:
        return any(f.is_blocker for f in self.findings)


def analyze_source(source_text: str) -> AnalysisResult:
    """Parse and analyze a Jenkinsfile, producing ordered findings."""
    sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    parsed = parse(source_text)
    findings = list(parsed.findings)
    pipeline = parsed.pipeline

    if pipeline is not None:
        findings.extend(_standard_assumptions(pipeline))
        findings.extend(_scan_translated(pipeline))

    findings = _dedupe(findings)
    findings.sort(key=lambda f: (f.line, f.col, f.code))
    return AnalysisResult(findings=findings, pipeline=pipeline, source_sha256=sha)


def models_implicit_checkout(pipeline: Pipeline) -> bool:
    """True when pipebridge models Jenkins' default SCM checkout.

    Jenkins checks out source from SCM when the agent is allocated, before
    the first stage runs (the 'Default Checkout' behavior, suppressed only
    by ``skipDefaultCheckout`` — an option the MVP keeps blocked, so it is
    never in scope here). The checkout is modeled whenever the pipeline was
    actually translated: not blocked and at least one step translated.
    Explicit ``checkout scm`` steps are preserved as-is and never
    deduplicated against it (a later checkout can change workspace state).
    """
    if pipeline.blocked or not pipeline.stages:
        return False
    return any(stage.steps for stage in pipeline.stages)


def _standard_assumptions(pipeline: Pipeline) -> list[Finding]:
    base = pipeline.span
    out = [
        Finding(
            code=PB_ASSUME_SHELL,
            severity="info",
            construct="shell execution environment",
            message=(
                "Steps run under 'bash --noprofile --norc -eo pipefail' on GitHub "
                "Actions; Jenkins 'sh' uses '/bin/sh -xe'. Shell differences "
                "(pipefail, tracing, tool availability) may change behavior."
            ),
            line=base.line,
            col=base.col,
            suggestion="Review each command under 'set -eo pipefail' bash semantics.",
        ),
        Finding(
            code=PB_TRIGGER_MANUAL,
            severity="info",
            construct="workflow trigger",
            message="The generated workflow triggers on workflow_dispatch only.",
            line=base.line,
            col=base.col,
            suggestion="Add push/pull_request/schedule triggers deliberately after review.",
        ),
    ]
    if pipeline.stages:
        out.append(
            Finding(
                code=PB_SINGLE_JOB,
                severity="info",
                construct="sequential stages",
                message=(
                    "All sequential stages are kept in a single GitHub Actions job "
                    "so filesystem state (the Jenkins executor workspace) is "
                    "preserved between stages."
                ),
                line=base.line,
                col=base.col,
                suggestion="Split into multiple jobs only with explicit needs/ and artifact passing.",
            )
        )
    if pipeline.has_agent_any:
        span = pipeline.agent_span or base
        out.append(
            Finding(
                code=PB_ASSUME_RUNNER,
                severity="info",
                construct="agent any",
                message=(
                    "'agent any' does not establish the required OS, installed "
                    "tools, or network access; the generated workflow assumes the "
                    "'ubuntu-latest' runner."
                ),
                line=span.line,
                col=span.col,
                suggestion="Verify the runner image provides every tool the commands need.",
            )
        )
    if pipeline.agent_label is not None:
        span = pipeline.agent_label_span or base
        label = pipeline.agent_label
        out.append(
            Finding(
                code=PB_ASSUME_RUNNER_LABEL,
                severity="info",
                construct="agent label",
                message=(
                    f"Jenkins agent label '{label}' was mapped to "
                    f"runs-on: [self-hosted, {label}]. This assumes a "
                    f"self-hosted GitHub Actions runner with label '{label}' "
                    "exists and provides the same OS, installed tools, network "
                    "access, permissions, and workspace behavior as the Jenkins "
                    "agent. Jenkins label expressions, variables, and stage-level "
                    "agents are not mapped."
                ),
                line=span.line,
                col=span.col,
                suggestion=(
                    "Verify a self-hosted runner with this label exists and "
                    "matches the Jenkins agent before enabling the workflow."
                ),
            )
        )
    return out


def _scan_translated(pipeline: Pipeline) -> list[Finding]:
    """Scan translated text for Jenkins variables and GitHub expressions."""
    findings: list[Finding] = []
    if models_implicit_checkout(pipeline):
        first = pipeline.stages[0]
        findings.append(
            Finding(
                code=PB_ASSUME_CHECKOUT,
                severity="info",
                construct="default SCM checkout (implicit)",
                message=(
                    "Jenkins checks out source from SCM before the first stage "
                    "(default checkout). An implicit 'Checkout source (implicit)' "
                    "step was inserted before the first translated step, in "
                    "addition to any explicit 'checkout scm' steps (Jenkins "
                    "performs both; checkouts are not deduplicated). This "
                    "assumes the workflow runs in the migrated source repository."
                ),
                line=first.span.line,
                col=first.span.col,
                suggestion=(
                    "If the Jenkins job did not check out source (e.g. it only "
                    "used artifacts), remove the implicit checkout step."
                ),
            )
        )
    for stage in pipeline.stages:
        findings.extend(_scan_github_expressions(stage.name, stage.dollar_spans, "stage name"))
        for step in stage.steps:
            if step.kind == "checkout":
                findings.append(
                    Finding(
                        code=PB_ASSUME_CHECKOUT,
                        severity="info",
                        construct="checkout scm",
                        message=(
                            "'checkout scm' is translated to the pinned "
                            "actions/checkout step; the workflow is assumed to run "
                            "in the migrated source repository."
                        ),
                        line=step.span.line,
                        col=step.span.col,
                        suggestion="Confirm the workflow's repository matches the Jenkins SCM.",
                    )
                )
                continue
            label = "sh command" if step.kind == "sh" else "echo message"
            for offset, line, col in step.dollar_spans:
                match = _JENKINS_VAR_RE.match(step.text, offset)
                if match:
                    findings.append(
                        Finding(
                            code=PB_JENV,
                            severity="warning",
                            construct=label,
                            message=(
                                f"Jenkins-specific variable '{match.group(1)}' is "
                                "referenced in shell text."
                            ),
                            line=line,
                            col=col,
                            suggestion=(
                                "Map it to a GitHub Actions equivalent "
                                "(e.g. github.run_number) or remove it, deliberately."
                            ),
                        )
                    )
            findings.extend(
                _scan_github_expressions(step.text, step.dollar_spans, label)
            )
        for env_var in stage.env:
            findings.extend(_scan_env_value(env_var, f"stage '{stage.name}' environment"))
    for env_var in pipeline.env:
        findings.extend(_scan_env_value(env_var, "pipeline environment"))
    return findings


def _scan_env_value(env_var, context: str) -> list[Finding]:
    findings: list[Finding] = []
    for offset, line, col in env_var.dollar_spans:
        match = _JENKINS_VAR_RE.match(env_var.value, offset)
        if match:
            findings.append(
                Finding(
                    code=PB_JENV,
                    severity="warning",
                    construct=context,
                    message=(
                        f"Environment variable '{env_var.name}' contains a literal "
                        f"reference to Jenkins variable '{match.group(1)}'; it is "
                        "exported verbatim and will not be expanded."
                    ),
                    line=line,
                    col=col,
                    suggestion="Set the intended value explicitly in the workflow.",
                )
            )
    findings.extend(_scan_github_expressions(env_var.value, env_var.dollar_spans, context))
    return findings


def _scan_github_expressions(text: str, dollar_spans, label: str) -> list[Finding]:
    findings: list[Finding] = []
    for offset, line, col in dollar_spans:
        if text.startswith(_GH_EXPR, offset):
            findings.append(
                Finding(
                    code=PB_GHEXPR,
                    severity="warning",
                    construct=label,
                    message=(
                        "Source text contains GitHub expression syntax '${{ ... }}'. "
                        "It is escaped in the generated workflow so GitHub Actions "
                        "does not evaluate Jenkins source text unintentionally."
                    ),
                    line=line,
                    col=col,
                    suggestion="If the expression is intended, rewrite it against the github context deliberately.",
                )
            )
    return findings


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple] = set()
    out: list[Finding] = []
    for f in findings:
        key = (f.code, f.line, f.col, f.message)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
