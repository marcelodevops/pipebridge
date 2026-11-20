"""Explicit Jenkins credential-ID → GitHub secret-name mapping.

The mapping file contains names only. This module never reads a secret
value, invokes ``gh``, or contacts GitHub.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import PipebridgeError
from .findings import (
    Finding,
    PB_ASSUME_CREDENTIALS,
    PB_CRED_MAP,
    PB_CRED_MAP_UNUSED,
    PB_CRED_SETUP,
)
from .model import (
    STATUS_COLLISION,
    STATUS_INVALID_SECRET_NAME,
    STATUS_MISSING_MAPPING,
    STATUS_PENDING,
    STATUS_RESOLVED,
    CredentialInventory,
    Pipeline,
    Span,
)

_VARIABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SECRET_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
_RESERVED_PREFIXES = ("GITHUB_", "RUNNER_")
_MAP_SUGGESTION = (
    "Add an explicit credential-ID to secret-name mapping. pipebridge does "
    "not guess, trim, or case-fold credential IDs."
)


class CredentialMapError(PipebridgeError):
    """The mapping file is missing, unreadable, or structurally invalid."""


@dataclass(frozen=True)
class MappedSecret:
    secret: str


@dataclass(frozen=True)
class CredentialMap:
    entries: dict[str, MappedSecret]


def valid_credential_id(value: str) -> bool:
    """Exact Jenkins credential ID: non-empty, no surrounding whitespace, no controls."""
    if value == "" or value != value.strip():
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def valid_variable(name: str) -> bool:
    """POSIX environment name, excluding GitHub-reserved prefixes."""
    if _VARIABLE_RE.fullmatch(name) is None:
        return False
    upper = name.upper()
    return not upper.startswith(_RESERVED_PREFIXES)


def valid_secret_name(name: str) -> bool:
    """Uppercase GitHub secret name. Case-folding then equals exact comparison."""
    if _SECRET_RE.fullmatch(name) is None:
        return False
    return not name.startswith(_RESERVED_PREFIXES)


def load_credential_map(path: Path) -> CredentialMap:
    """Load a strict schema_version 1 mapping file. Raises CredentialMapError."""
    if not path.exists():
        raise CredentialMapError(f"credential map not found: {path}")
    if not path.is_file():
        raise CredentialMapError(f"credential map path is not a file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CredentialMapError(f"cannot read credential map {path}: {exc}") from exc
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except CredentialMapError:
        raise
    except json.JSONDecodeError as exc:
        raise CredentialMapError(f"credential map is not valid JSON: {exc}") from exc
    return _validate_map(data)


def resolve_credentials(
    inventory: CredentialInventory,
    pipeline: Pipeline | None,
    credential_map: CredentialMap | None,
    secrets_ready: bool,
) -> list[Finding]:
    """Finalize pending inventory entries. Never removes an entry.

    Unresolved mappings block only the stages named by those entries and
    clear their steps. A resolved entry keeps its steps unless that stage
    is blocked for another reason. ``pending`` is never left behind.
    """
    findings: list[Finding] = []
    referenced = {
        entry.credential_id
        for entry in inventory.entries
        if entry.credential_id is not None
    }
    colliding = _colliding_ids(credential_map)
    resolved: list = []
    stages_to_block: list[str] = []

    for entry in list(inventory.entries):
        if entry.status != STATUS_PENDING:
            continue
        updated, finding = _resolve_one(entry, credential_map, colliding, inventory)
        if finding is not None:
            findings.append(finding)
        if updated.status != STATUS_RESOLVED:
            stages_to_block.append(updated.stage_name)
        else:
            resolved.append(updated)

    if pipeline is not None and stages_to_block:
        blocked_names = set(stages_to_block)
        for stage in pipeline.stages:
            if stage.name in blocked_names:
                stage.blocked = True
                stage.steps.clear()

    if resolved:
        anchor = resolved[0]
        if secrets_ready:
            findings.append(
                Finding(
                    code=PB_ASSUME_CREDENTIALS,
                    severity="info",
                    construct="credential setup acknowledgement",
                    message=(
                        "The user acknowledged that every secret named in the "
                        "credential checklist exists in the target repository. "
                        "pipebridge did not verify that and never reads secret values."
                    ),
                    line=anchor.span.line,
                    col=anchor.span.col,
                    suggestion=(
                        "Confirm each secret name matches the checklist exactly "
                        "before enabling the workflow."
                    ),
                )
            )
        else:
            findings.append(
                Finding(
                    code=PB_CRED_SETUP,
                    severity="blocker",
                    construct="credential setup acknowledgement",
                    message=(
                        "The credential mapping is resolved, but secret setup has "
                        "not been acknowledged. Re-run with --secrets-ready after "
                        "creating each required secret. pipebridge does not verify values."
                    ),
                    line=anchor.span.line,
                    col=anchor.span.col,
                    suggestion=(
                        "Create the secrets listed in the report, then re-run with "
                        "the same --credential-map and --secrets-ready."
                    ),
                )
            )

    if credential_map is not None:
        span = pipeline.span if pipeline is not None else Span(1, 1)
        for cred_id, mapped in credential_map.entries.items():
            if cred_id in referenced:
                continue
            if valid_secret_name(mapped.secret):
                findings.append(
                    Finding(
                        code=PB_CRED_MAP_UNUSED,
                        severity="info",
                        construct="credential map",
                        message=(
                            f"Credential map entry '{cred_id}' is not referenced "
                            "by this Jenkinsfile."
                        ),
                        line=span.line,
                        col=span.col,
                        suggestion="Remove the unused mapping entry or keep it deliberately.",
                    )
                )
            else:
                findings.append(
                    _map_finding(
                        span,
                        (
                            f"Unused credential map entry '{cred_id}' has secret name "
                            f"{mapped.secret!r}, which is not a valid GitHub Actions "
                            "secret name."
                        ),
                    )
                )
    return findings


def _resolve_one(entry, credential_map, colliding, inventory):
    cred_id = entry.credential_id
    if credential_map is None or cred_id is None or cred_id not in credential_map.entries:
        shown = cred_id if cred_id is not None else ""
        reason = f"no mapping for credential ID `{shown}`"
        updated = inventory.replace(
            entry.binding_id,
            status=STATUS_MISSING_MAPPING,
            secret_name=None,
            reason=reason,
        )
        return updated, _map_finding(entry.span, reason)

    mapped = credential_map.entries[cred_id]
    if not valid_secret_name(mapped.secret):
        reason = (
            f"secret name for credential ID `{cred_id}` is not a valid "
            f"GitHub Actions secret name ({mapped.secret!r})"
        )
        updated = inventory.replace(
            entry.binding_id,
            status=STATUS_INVALID_SECRET_NAME,
            secret_name=None,
            reason=reason,
        )
        return updated, _map_finding(entry.span, reason)

    if cred_id in colliding:
        reason = (
            f"credential ID `{cred_id}` collides with another mapping on "
            f"secret name `{mapped.secret}`"
        )
        updated = inventory.replace(
            entry.binding_id,
            status=STATUS_COLLISION,
            secret_name=None,
            reason=reason,
        )
        return updated, _map_finding(entry.span, reason)

    updated = inventory.replace(
        entry.binding_id,
        status=STATUS_RESOLVED,
        secret_name=mapped.secret,
        reason=None,
    )
    return updated, None


def _colliding_ids(credential_map: CredentialMap | None) -> set[str]:
    if credential_map is None:
        return set()
    folded: dict[str, list[str]] = {}
    for cred_id, mapped in credential_map.entries.items():
        # Invalid names are their own finding; they do not collide with a
        # valid name that merely case-folds to the same text.
        if not valid_secret_name(mapped.secret):
            continue
        folded.setdefault(mapped.secret.casefold(), []).append(cred_id)
    colliding: set[str] = set()
    for ids in folded.values():
        if len(ids) > 1:
            colliding.update(ids)
    return colliding


def _map_finding(span: Span, message: str) -> Finding:
    return Finding(
        code=PB_CRED_MAP,
        severity="blocker",
        construct="credential mapping",
        message=message,
        line=span.line,
        col=span.col,
        suggestion=_MAP_SUGGESTION,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise CredentialMapError(f"duplicate JSON member '{key}'")
        seen[key] = value
    return seen


def _validate_map(data: object) -> CredentialMap:
    if not isinstance(data, dict):
        raise CredentialMapError("credential map must be a JSON object")
    if set(data) != {"schema_version", "credentials"}:
        raise CredentialMapError(
            "credential map must contain exactly schema_version and credentials"
        )
    version = data["schema_version"]
    if type(version) is not int or version != 1:
        raise CredentialMapError("credential map schema_version must be the integer 1")
    raw_credentials = data["credentials"]
    if not isinstance(raw_credentials, dict):
        raise CredentialMapError("credential map credentials must be an object")
    entries: dict[str, MappedSecret] = {}
    for cred_id, spec in raw_credentials.items():
        if not isinstance(cred_id, str) or not valid_credential_id(cred_id):
            raise CredentialMapError(
                f"credential map key {cred_id!r} is not a valid credential ID"
            )
        if not isinstance(spec, dict) or set(spec) != {"secret"}:
            raise CredentialMapError(
                f"credential map entry {cred_id!r} must be an object with exactly 'secret'"
            )
        secret = spec["secret"]
        if not isinstance(secret, str):
            raise CredentialMapError(
                f"credential map secret for {cred_id!r} must be a string"
            )
        entries[cred_id] = MappedSecret(secret=secret)
    return CredentialMap(entries=entries)
