"""Validation of generated workflows.

Validation has honest, separate levels that are reported distinctly:

- YAML parse: is the file well-formed YAML?
- actionlint: static workflow linting, only when installed locally.
- Runtime: NEVER performed and never claimed — pipebridge does not
  execute generated workflows.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from .errors import ValidationError

_ACTIONLINT_TIMEOUT_SECONDS = 60
# actionlint's hosted-runner catalog cannot know a user-defined self-hosted
# label. Suppress only that message when we emitted a self-hosted list; every
# other lint failure still rejects the conversion. The suppression is stored
# on the actionlint result as ``ignored_rules``.
_UNKNOWN_SELF_HOSTED_LABEL = 'label ".+" is unknown'
_SELF_HOSTED_RUNS_ON = "runs-on: [self-hosted,"


def validate_yaml_text(text: str) -> dict:
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {"ok": False, "error": str(exc), "note": "yaml.safe_load"}
    return {"ok": True, "error": None, "note": "yaml.safe_load"}


def run_actionlint(path, ignore: list[str] | None = None) -> dict:
    """Run actionlint on a file; ok=None means the check did not run.

    ``ignore`` lists actionlint error-message regexps to suppress (each
    suppression must be disclosed in reports).
    """
    executable = shutil.which("actionlint")
    if executable is None:
        return {
            "available": False,
            "ok": None,
            "exit_code": None,
            "output": "actionlint is not installed; workflow linting was skipped.",
        }
    try:
        version = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=_ACTIONLINT_TIMEOUT_SECONDS,
            check=False,
        )
        command = [executable, "-no-color", "-format", "{{json .}}"]
        for pattern in ignore or []:
            command.extend(["-ignore", pattern])
        command.append(str(path))
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_ACTIONLINT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": True,
            "ok": None,
            "exit_code": None,
            "output": f"actionlint could not be executed: {exc}",
        }
    version_first = version.stdout.strip().splitlines()[0] if version.stdout.strip() else "unknown"
    if proc.returncode not in (0, 1):
        output = (proc.stdout + proc.stderr).strip()
        return {
            "available": True,
            "ok": None,
            "exit_code": proc.returncode,
            "output": f"actionlint exited unexpectedly ({proc.returncode}): {output}",
            "version": version_first,
        }
    entries = _parse_actionlint_json(proc.stdout)
    if entries is None:
        # Unexpected output shape: report the raw text honestly rather than
        # guessing at a classification.
        output = (proc.stdout + proc.stderr).strip()
        return {
            "available": True,
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": output or "(no output)",
            "version": version_first,
        }
    # Classify via the structured `kind` field: shellcheck notes are about
    # the user's faithfully-migrated script (report warnings, not generation
    # failures); every other kind is a structural workflow problem.
    shellcheck = [e for e in entries if e.get("kind") == "shellcheck"]
    structural = [e for e in entries if e.get("kind") != "shellcheck"]
    ok = proc.returncode == 0 or (bool(shellcheck) and not structural)
    result = {
        "available": True,
        "ok": ok,
        "exit_code": proc.returncode,
        "output": json.dumps(entries, ensure_ascii=False) if entries else "",
        "version": version_first,
        "shellcheck_notes": [_fmt_actionlint_entry(e) for e in shellcheck] or None,
        "structural_errors": [_fmt_actionlint_entry(e) for e in structural] or None,
    }
    if ignore:
        result["ignored_rules"] = list(ignore)
    return result


def _parse_actionlint_json(text: str) -> list[dict] | None:
    """Parse actionlint's `-format '{{json .}}'` output; None if unexpected."""
    if not text.strip():
        return []
    try:
        entries = json.loads(text)
    except json.JSONDecodeError:
        return None
    return entries if isinstance(entries, list) else None


def _fmt_actionlint_entry(entry: dict) -> str:
    location = entry.get("file", "")
    if entry.get("line"):
        location += f":{entry['line']}:{entry.get('column', 0)}"
    return f"{location}: {entry.get('message', '')}".strip(": ")


def validate_generated_workflow(workflow_text: str, workflow_path, disabled: bool = False) -> dict:
    """Validate a generated workflow before anything is written.

    Raises :class:`ValidationError` when the generated workflow is not
    valid, so a failed conversion never leaves artifacts behind. When
    ``disabled`` (blockers exist), the deliberate constant-false job
    condition is disclosed as a suppressed lint rule. A generated
    ``runs-on: [self-hosted, label]`` list also suppresses actionlint's
    unknown-hosted-label message: that catalog cannot know a Jenkins label,
    and the suppression is disclosed the same way. It does not mean the
    runner exists.
    """
    yaml_result = validate_yaml_text(workflow_text)
    if not yaml_result["ok"]:
        raise ValidationError(f"generated workflow is not valid YAML: {yaml_result['error']}")

    # Lint from a temp file in the system temp directory: this runs BEFORE
    # any output directory is created, so a failed validation leaves nothing.
    ignore = ['constant expression "false" in condition'] if disabled else []
    if _SELF_HOSTED_RUNS_ON in workflow_text:
        ignore.append(_UNKNOWN_SELF_HOSTED_LABEL)
    temp_path = Path(tempfile.gettempdir()) / f"pipebridge-actionlint-{os.getpid()}.yml"
    temp_path.write_text(workflow_text, encoding="utf-8")
    try:
        lint_result = run_actionlint(temp_path, ignore=ignore)
    finally:
        temp_path.unlink(missing_ok=True)
    if lint_result.get("available") and lint_result.get("ok") is False:
        raise ValidationError(
            "generated workflow failed actionlint:\n" + (lint_result.get("output") or "")
        )

    return {
        "yaml_parse": yaml_result,
        "actionlint": lint_result,
        "runtime": {
            "performed": False,
            "note": (
                "Not performed: pipebridge does not execute generated workflows. "
                "YAML parsing and actionlint are static checks only; validate at "
                "runtime by dispatching the workflow manually."
            ),
        },
    }
