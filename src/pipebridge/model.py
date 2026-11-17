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


@dataclass(frozen=True)
class Step:
    """A translated step. kind is one of 'sh', 'echo', 'checkout'."""

    kind: str
    text: str
    span: Span


@dataclass
class Stage:
    name: str
    span: Span
    env: list[EnvVar] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    blocked: bool = False


@dataclass
class Pipeline:
    span: Span
    has_agent_any: bool = False
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
