"""Intermediate pipeline model produced by the parser."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from .findings import Finding

if TYPE_CHECKING:
    from .librarybody import Operation


@dataclass(frozen=True)
class Span:
    line: int
    col: int


@dataclass(frozen=True)
class EnvVar:
    name: str
    value: str
    span: Span
    # (offset_in_value, line, col) of literal '$' characters in value.
    dollar_spans: tuple[tuple[int, int, int], ...] = ()


# Inventory statuses. ``pending`` is parser-internal and never emitted.
STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"
STATUS_MISSING_MAPPING = "missing_mapping"
STATUS_INVALID_SECRET_NAME = "invalid_secret_name"
STATUS_COLLISION = "collision"
STATUS_UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Step:
    """A translated step. kind is one of 'sh', 'echo', 'checkout'."""

    kind: str
    text: str
    span: Span
    # (offset_in_text, line, col) of literal '$' characters in text.
    dollar_spans: tuple[tuple[int, int, int], ...] = ()
    # References into CredentialInventory. Not copies of binding data.
    credential_binding_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CredentialBinding:
    """One ``withCredentials`` token discovered in a stage steps block.

    Analysis state, not translated workflow content. Clearing a stage's
    steps must not drop this record.
    """

    binding_id: str
    binding_type: str
    credential_id: str | None
    variable: str | None
    secret_name: str | None
    status: str
    reason: str | None
    stage_name: str
    span: Span


@dataclass
class CredentialInventory:
    """Append-only credential records for one analysis, in source order."""

    entries: list[CredentialBinding] = field(default_factory=list)

    def by_id(self, binding_id: str) -> CredentialBinding | None:
        for entry in self.entries:
            if entry.binding_id == binding_id:
                return entry
        return None

    def append(self, entry: CredentialBinding) -> None:
        self.entries.append(entry)

    def replace(self, binding_id: str, **changes) -> CredentialBinding:
        for index, entry in enumerate(self.entries):
            if entry.binding_id == binding_id:
                updated = replace(entry, **changes)
                self.entries[index] = updated
                return updated
        raise KeyError(binding_id)


@dataclass
class Stage:
    name: str
    span: Span
    env: list[EnvVar] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    blocked: bool = False
    # (offset_in_name, line, col) of literal '$' characters in the name.
    dollar_spans: tuple[tuple[int, int, int], ...] = ()


@dataclass
class Pipeline:
    span: Span
    has_agent_any: bool = False
    agent_span: Span | None = None
    # Accepted pipeline-level literal label (unsupported forms stay blocked).
    agent_label: str | None = None
    agent_label_span: Span | None = None
    env: list[EnvVar] = field(default_factory=list)
    stages: list[Stage] = field(default_factory=list)
    blocked: bool = False


@dataclass
class LoadedLibrary:
    """One explicitly declared and mapped shared library."""

    name: str
    path: str
    revision: str | None
    span: Span
    discovered_vars: list[str] = field(default_factory=list)
    vars: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LibraryCallRecord:
    """One shared-library call encountered in a stage steps block.

    Analysis state, not translated workflow content. Clearing a stage's
    steps must not drop this record.
    """

    name: str
    library: str | None
    status: str  # 'resolved', 'pending', or 'blocked'
    source_path: str | None
    line: int
    col: int
    stage_name: str
    chain: tuple[str, ...] = ()
    operations: tuple["Operation", ...] = ()


@dataclass
class LibraryInventory:
    """Append-only shared-library records and resolved operations."""

    map_supplied: bool = False
    libraries: list[LoadedLibrary] = field(default_factory=list)
    calls: list[LibraryCallRecord] = field(default_factory=list)
    operations: list["Operation"] = field(default_factory=list)

    def by_name(self, name: str) -> LoadedLibrary | None:
        for entry in self.libraries:
            if entry.name == name:
                return entry
        return None


@dataclass
class ParseResult:
    pipeline: Pipeline | None
    findings: list[Finding]
    credential_inventory: CredentialInventory = field(default_factory=CredentialInventory)
    library_inventory: LibraryInventory = field(default_factory=LibraryInventory)

    @property
    def has_blockers(self) -> bool:
        return any(f.is_blocker for f in self.findings)
