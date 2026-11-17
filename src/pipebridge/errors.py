"""Errors raised by pipebridge.

All are subclasses of :class:`PipebridgeError` so the CLI can distinguish
expected, user-facing failures (malformed input, I/O problems) from
unexpected internal errors. Both map to exit code 1.
"""


class PipebridgeError(Exception):
    """Base class for user-facing pipebridge errors."""


class LexError(PipebridgeError):
    """The source contains a lexical error (e.g. an unterminated string)."""

    def __init__(self, message: str, line: int, col: int) -> None:
        self.line = line
        self.col = col
        super().__init__(f"line {line}, column {col}: {message}")


class ValidationError(PipebridgeError):
    """A generated artifact failed validation and nothing was written."""


class MalformedPipelineError(PipebridgeError):
    """The input violates required declarative pipeline structure.

    Per the official Jenkins syntax reference, a declarative pipeline must
    have a ``stages`` section containing at least one stage, and every
    stage must have a ``steps`` section containing at least one step.
    Missing required structure is malformed input (exit code 1), distinct
    from valid-but-unsupported constructs (exit code 2).
    """

    def __init__(self, message: str, line: int, col: int) -> None:
        self.line = line
        self.col = col
        super().__init__(f"line {line}, column {col}: {message}")
