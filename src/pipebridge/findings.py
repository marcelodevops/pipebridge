"""Findings: stable codes, severities, and the registry."""

from __future__ import annotations

from dataclasses import dataclass

SEVERITY_BLOCKER = "blocker"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

# Stable finding codes. Never renumber or rename: they appear in reports
# and JSON consumed by other tooling.
PB_SCRIPT = "PB-SCRIPT"
PB_LIB = "PB-LIB"
PB_LIB_CALL = "PB-LIB-CALL"
PB_LIB_MAP_UNUSED = "PB-LIB-MAP-UNUSED"
PB_CRED = "PB-CRED"
PB_CRED_MAP = "PB-CRED-MAP"
PB_CRED_SETUP = "PB-CRED-SETUP"
PB_CRED_MAP_UNUSED = "PB-CRED-MAP-UNUSED"
PB_ASSUME_CREDENTIALS = "PB-ASSUME-CREDENTIALS"
PB_PARALLEL = "PB-PARALLEL"
PB_MATRIX = "PB-MATRIX"
PB_AGENT = "PB-AGENT"
PB_TOOLS = "PB-TOOLS"
PB_WHEN = "PB-WHEN"
PB_PARAM = "PB-PARAM"
PB_TRIGGER = "PB-TRIGGER"
PB_INPUT = "PB-INPUT"
PB_POST = "PB-POST"
PB_INTERP = "PB-INTERP"
PB_ENVVAL = "PB-ENVVAL"
PB_SYNTAX = "PB-SYNTAX"
PB_JENV = "PB-JENV"
PB_GHEXPR = "PB-GHEXPR"
PB_SHELLCHECK = "PB-SHELLCHECK"
PB_ASSUME_RUNNER = "PB-ASSUME-RUNNER"
PB_ASSUME_RUNNER_LABEL = "PB-ASSUME-RUNNER-LABEL"
PB_ASSUME_CHECKOUT = "PB-ASSUME-CHECKOUT"
PB_ASSUME_SHELL = "PB-ASSUME-SHELL"
PB_TRIGGER_MANUAL = "PB-TRIGGER-MANUAL"
PB_SINGLE_JOB = "PB-SINGLE-JOB"
PB_GROOVY_IMPORT = "PB-GROOVY-IMPORT"
PB_GROOVY_PRELUDE = "PB-GROOVY-PRELUDE"
PB_GROOVY_POSTLUDE = "PB-GROOVY-POSTLUDE"

REGISTRY: dict[str, tuple[str, str]] = {
    PB_SCRIPT: (SEVERITY_BLOCKER, "Scripted pipeline syntax or script block"),
    PB_LIB: (SEVERITY_BLOCKER, "Shared library usage"),
    PB_CRED: (SEVERITY_BLOCKER, "Credentials or credential bindings"),
    PB_CRED_MAP: (SEVERITY_BLOCKER, "Credential ID has no valid explicit secret mapping"),
    PB_CRED_SETUP: (SEVERITY_BLOCKER, "Mapped secrets have not been acknowledged"),
    PB_CRED_MAP_UNUSED: (SEVERITY_INFO, "Credential map entry is not referenced"),
    PB_ASSUME_CREDENTIALS: (SEVERITY_INFO, "User acknowledged mapped secrets; values were not verified"),
    PB_PARALLEL: (SEVERITY_BLOCKER, "Parallel execution"),
    PB_MATRIX: (SEVERITY_BLOCKER, "Matrix execution"),
    PB_AGENT: (SEVERITY_BLOCKER, "Unsupported agent declaration"),
    PB_TOOLS: (SEVERITY_BLOCKER, "Tools declaration"),
    PB_WHEN: (SEVERITY_BLOCKER, "Stage conditions (when)"),
    PB_PARAM: (SEVERITY_BLOCKER, "Parameters directive"),
    PB_TRIGGER: (SEVERITY_BLOCKER, "Triggers directive"),
    PB_INPUT: (SEVERITY_BLOCKER, "Input approval gate"),
    PB_POST: (SEVERITY_BLOCKER, "Post actions"),
    PB_INTERP: (SEVERITY_BLOCKER, "Groovy interpolation or dynamic expression"),
    PB_ENVVAL: (SEVERITY_BLOCKER, "Non-literal environment value"),
    PB_SYNTAX: (SEVERITY_BLOCKER, "Unknown or unsupported syntax"),
    PB_JENV: (SEVERITY_WARNING, "Jenkins-specific variable reference in shell text"),
    PB_GHEXPR: (SEVERITY_WARNING, "GitHub expression syntax in source literal"),
    PB_SHELLCHECK: (SEVERITY_WARNING, "shellcheck note about the migrated shell script"),
    PB_ASSUME_RUNNER: (SEVERITY_INFO, "Runner assumed ubuntu-latest"),
    PB_ASSUME_RUNNER_LABEL: (SEVERITY_INFO, "Jenkins agent label mapped to a self-hosted runner label"),
    PB_ASSUME_CHECKOUT: (SEVERITY_INFO, "checkout scm assumed to run in the migrated repository"),
    PB_ASSUME_SHELL: (SEVERITY_INFO, "Shell and execution-environment differences"),
    PB_TRIGGER_MANUAL: (SEVERITY_INFO, "Workflow triggers on workflow_dispatch only"),
    PB_SINGLE_JOB: (SEVERITY_INFO, "Sequential stages kept in one job to preserve workspace state"),
    PB_GROOVY_IMPORT: (SEVERITY_INFO, "Ordinary Groovy import statement before the pipeline block"),
    PB_GROOVY_PRELUDE: (SEVERITY_BLOCKER, "Executable Groovy before the pipeline block"),
    PB_GROOVY_POSTLUDE: (SEVERITY_BLOCKER, "Executable Groovy after the pipeline block"),
}

ALL_CODES = frozenset(REGISTRY)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    construct: str
    message: str
    line: int
    col: int
    suggestion: str

    @property
    def is_blocker(self) -> bool:
        return self.severity == SEVERITY_BLOCKER
