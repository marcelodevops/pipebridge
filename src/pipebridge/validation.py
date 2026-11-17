"""Validation of generated workflows.

Validation has honest, separate levels that are reported distinctly:

- YAML parse: is the file well-formed YAML?
- actionlint: static workflow linting, only when installed locally.
- Runtime: NEVER performed and never claimed — pipebridge does not
  execute generated workflows.
"""

from __future__ import annotations

import shutil
import subprocess

import yaml

from .errors import ValidationError

_ACTIONLINT_TIMEOUT_SECONDS = 60


def validate_yaml_text(text: str) -> dict:
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {"ok": False, "error": str(exc), "note": "yaml.safe_load"}
    return {"ok": True, "error": None, "note": "yaml.safe_load"}


def run_actionlint(path) -> dict:
    """Run actionlint on a file; ok=None means the check did not run."""
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
        proc = subprocess.run(
            [executable, "-no-color", str(path)],
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
    ok = proc.returncode == 0
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode not in (0, 1):
        output = f"actionlint exited unexpectedly ({proc.returncode}): {output}"
    return {
        "available": True,
        "ok": ok,
        "exit_code": proc.returncode,
        "output": output,
        "version": version_first,
    }


def validate_generated_workflow(workflow_text: str, workflow_path) -> dict:
    """Validate a generated workflow before anything is written.

    Raises :class:`ValidationError` when the generated workflow is not
    valid, so a failed conversion never leaves artifacts behind.
    """
    yaml_result = validate_yaml_text(workflow_text)
    if not yaml_result["ok"]:
        raise ValidationError(f"generated workflow is not valid YAML: {yaml_result['error']}")

    temp_path = workflow_path.with_name(workflow_path.name + ".actionlint-tmp")
    temp_path.write_text(workflow_text, encoding="utf-8")
    try:
        lint_result = run_actionlint(temp_path)
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
