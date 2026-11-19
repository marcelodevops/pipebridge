"""Shared helpers for D2 diagnostic tests."""

from __future__ import annotations

import copy
import re

import yaml

# The only executable text that depends on the diagnostic finding set: the
# parenthesized blocker-code list inside a [NOT MIGRATED] placeholder command.
_PLACEHOLDER_CODE_LIST = re.compile(r"\(PB-[^)]*\)")


def load_workflow(text: str) -> dict:
    return yaml.safe_load(text)


def normalize_blocked_workflow(document: dict) -> dict:
    """Normalize documented diagnostic text, nothing else.

    YAML comments are dropped by the parser. The only non-comment diagnostic
    text is the parenthesized blocker-code list in a placeholder step's
    ``run`` string. This replaces exactly that list and leaves every other
    run command, job, trigger, permission, runner, and condition untouched.
    """
    document = copy.deepcopy(document)
    for job in (document.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            if not isinstance(step, dict):
                continue
            name = step.get("name")
            if not isinstance(name, str) or not name.startswith("[NOT MIGRATED]"):
                continue
            run = step.get("run")
            if isinstance(run, str):
                step["run"] = _PLACEHOLDER_CODE_LIST.sub("(PB-DIAGNOSTIC)", run)
    return document


def assert_structurally_equal(old_text: str, new_text: str) -> None:
    old = load_workflow(old_text)
    new = load_workflow(new_text)
    assert normalize_blocked_workflow(old) == normalize_blocked_workflow(new)
    # The disabled condition and step count are called out separately so a
    # normalization mistake cannot hide a real behavioral change.
    old_jobs = old.get("jobs") or {}
    new_jobs = new.get("jobs") or {}
    assert list(old_jobs) == list(new_jobs)
    for name, old_job in old_jobs.items():
        new_job = new_jobs[name]
        assert old_job.get("if") == new_job.get("if")
        assert len(old_job.get("steps") or []) == len(new_job.get("steps") or [])
