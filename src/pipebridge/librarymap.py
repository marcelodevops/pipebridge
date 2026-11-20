"""Explicit Jenkins shared-library name -> local directory mapping.

The mapping file contains names and relative paths only. This module never
fetches a repository, invokes ``gh``, reads a secret value, or executes
Groovy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import PipebridgeError

LIBRARY_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class LibraryMapError(PipebridgeError):
    """The mapping file is missing, unreadable, or structurally invalid."""


@dataclass(frozen=True)
class LibraryEntry:
    name: str
    path: Path
    root: Path


@dataclass(frozen=True)
class LibraryMap:
    entries: dict[str, "LibraryEntry"]


def _reject_duplicate_keys(pairs):
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise LibraryMapError(f"duplicate key in library map: {key!r}")
        seen.add(key)
    return dict(pairs)


def _check_name(name: str) -> None:
    if not isinstance(name, str) or LIBRARY_NAME_RE.fullmatch(name) is None:
        raise LibraryMapError(f"invalid library name: {name!r}")


def _check_path_segment(segment: str) -> None:
    if segment in ("", ".", ".."):
        raise LibraryMapError(f"invalid path segment in library map: {segment!r}")


def _validate_path(raw, base: Path) -> Path:
    if not isinstance(raw, str) or raw == "":
        raise LibraryMapError("library path must be a non-empty string")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise LibraryMapError("library path contains a control character")
    if "\\" in raw:
        raise LibraryMapError("library path must use forward slashes")
    # Validate raw segments before constructing Path.
    for segment in raw.split("/"):
        if segment in ("", ".", ".."):
            raise LibraryMapError(f"invalid path segment in library map: {segment!r}")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise LibraryMapError("library path must be relative")
    for part in candidate.parts:
        _check_path_segment(part)
    resolved_base = base.resolve()
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(resolved_base)
    except ValueError:
        raise LibraryMapError(f"library path escapes the map directory: {raw}")
    if not resolved.is_dir():
        raise LibraryMapError(f"library path is not a directory: {raw}")
    if not (resolved / "vars").is_dir():
        raise LibraryMapError(f"library root has no vars/ directory: {raw}")
    return resolved


def load_library_map(path: Path) -> LibraryMap:
    if not path.exists():
        raise LibraryMapError(f"library map not found: {path}")
    if not path.is_file():
        raise LibraryMapError(f"library map path is not a file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LibraryMapError(f"cannot read library map {path}: {exc}") from exc
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except LibraryMapError:
        raise
    except json.JSONDecodeError as exc:
        raise LibraryMapError(f"library map is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise LibraryMapError("library map must be a JSON object")
    if set(data.keys()) != {"schema_version", "libraries"}:
        raise LibraryMapError("library map top-level keys must be schema_version and libraries")
    version = data["schema_version"]
    if type(version) is not int or version != 1:
        raise LibraryMapError("library map schema_version must be the integer 1")
    libraries = data["libraries"]
    if not isinstance(libraries, dict):
        raise LibraryMapError("libraries must be a JSON object")

    base = path.parent.resolve()
    entries: dict[str, LibraryEntry] = {}
    for name, entry in libraries.items():
        _check_name(name)
        if not isinstance(entry, dict) or set(entry.keys()) != {"path"}:
            raise LibraryMapError(f"library entry {name!r} must contain only 'path'")
        resolved = _validate_path(entry["path"], base)
        entries[name] = LibraryEntry(name=name, path=Path(entry["path"]), root=resolved)

    # deterministic ordering
    entries = dict(sorted(entries.items()))
    return LibraryMap(entries=entries)
