"""Intermediate pipeline model produced by the parser."""

from __future__ import annotations

from dataclasses import dataclass, field

from .findings import Finding


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


@dataclass(frozen=True)
class Step:
    """A translated step. kind is one of 'sh', 'echo', 'checkout'."""

    kind: str
    text: str
    span: Span
    # (offset_in_text, line, col) of literal '$' characters in text.
    dollar_spans: tuple[tuple[int, int, int], ...] = ()


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
class ParseResult:
    pipeline: Pipeline | None
    findings: list[Finding]

    @property
    def has_blockers(self) -> bool:
        return any(f.is_blocker for f in self.findings)
