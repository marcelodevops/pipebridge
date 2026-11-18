"""Recursive-descent parser for the limited declarative pipeline grammar.

Design rules:

- The grammar is deliberately limited. Anything outside it produces a
  blocker finding with a source position — never a guess.
- Unsupported blocks (``script { }``, ``withCredentials (…) { }``,
  scripted pipelines, …) are **not traversed**: their contents are skipped
  by balanced-brace skipping and no commands are extracted from them.
- Once a stage contains a blocker, none of its steps are translated: the
  enclosing behavior is not preserved, so extracting its commands would
  misrepresent the pipeline.
- A pipeline-level blocker (custom agent, parameters, …) stops step
  translation for the whole pipeline: the draft workflow becomes a
  reviewable skeleton.
- Groovy **around** a top-level declarative pipeline block is recognized
  within a documented, limited grammar (imports, variable declarations,
  annotations, function definitions) so the block's structure can still be
  extracted for analysis. The surrounding Groovy is never evaluated and
  never translated: imports are reported at info level, every other
  surrounding form is a blocker, and the draft stays disabled. Content
  outside the recognized grammar keeps the scripted classification.
"""

from __future__ import annotations

from .errors import MalformedPipelineError
from .findings import Finding, REGISTRY, PB_AGENT, PB_CRED, PB_ENVVAL, PB_GROOVY_IMPORT, PB_GROOVY_POSTLUDE, PB_GROOVY_PRELUDE, PB_INPUT, PB_INTERP, PB_LIB, PB_MATRIX, PB_PARAM, PB_PARALLEL, PB_POST, PB_SCRIPT, PB_SYNTAX, PB_TRIGGER, PB_TOOLS, PB_WHEN
from .groovystrings import Decoded, decode_string
from .lexer import (
    ANNOTATION,
    DOT,
    EOF,
    IDENT,
    LBRACE,
    LBRACKET,
    LPAREN,
    NEWLINE,
    OTHER,
    RBRACE,
    RBRACKET,
    RPAREN,
    SEMI,
    STRING_DQ,
    STRING_SQ,
    STRING_TD,
    STRING_TS,
    tokenize,
)
from .model import EnvVar, ParseResult, Pipeline, Span, Stage, Step

STRING_KINDS = (STRING_SQ, STRING_DQ, STRING_TS, STRING_TD)

# Keywords that begin a Groovy statement but can never name a type. A prelude
# statement starting with one of these is arbitrary Groovy (a script), not a
# recognized declaration.
_RESERVED_STATEMENT_KEYWORDS = frozenset(
    {
        "as", "assert", "break", "case", "catch", "class", "continue", "def",
        "default", "do", "else", "enum", "extends", "false", "finally", "for",
        "if", "implements", "import", "in", "interface", "new", "null",
        "package", "pipeline", "return", "super", "switch", "this", "throw",
        "throws", "true", "try", "void", "while",
    }
)

# Declaration modifiers accepted (limited grammar) before a variable
# declaration or function definition in the surrounding Groovy.
_DECLARATION_MODIFIERS = frozenset(
    {"public", "private", "protected", "static", "final"}
)

# Groovy keywords can never be an identifier segment of an import path. A
# segment that is one of these makes the statement unsupported (a blocker),
# never an info-level import. Kept deliberately broad: rejecting a valid
# import is the safe direction, because a blocker only disables the draft.
_IMPORT_KEYWORDS = frozenset(
    {
        "abstract", "as", "assert", "boolean", "break", "byte", "case",
        "catch", "char", "class", "const", "continue", "def", "default",
        "do", "double", "else", "enum", "extends", "false", "final",
        "finally", "float", "for", "goto", "if", "implements", "import",
        "in", "instanceof", "int", "interface", "long", "native", "new",
        "null", "package", "private", "protected", "public", "return",
        "short", "static", "strictfp", "super", "switch", "synchronized",
        "this", "throw", "throws", "trait", "transient", "true", "try",
        "var", "void", "volatile", "while",
    }
)


class _Parser:
    def __init__(self, source: str) -> None:
        self._tokens = tokenize(source)
        self._pos = 0
        self._findings: list[Finding] = []
        self.pipeline: Pipeline | None = None
        # Required-structure bookkeeping: which stages parsed a steps
        # section, and which of those sections were non-empty.
        self._saw_stages_section = False
        self._stages_with_steps_section: set[int] = set()
        self._stages_with_nonempty_steps: set[int] = set()

    # ---- token helpers -------------------------------------------------

    def _peek(self, offset: int = 0):
        idx = min(self._pos + offset, len(self._tokens) - 1)
        return self._tokens[idx]

    def _advance(self):
        tok = self._tokens[self._pos]
        if tok.kind != EOF:
            self._pos += 1
        return tok

    def _skip_newlines(self) -> None:
        while self._peek().kind in (NEWLINE, SEMI):
            self._advance()

    def _statement_preview(self, start_index: int) -> str:
        """Render one statement's tokens for a finding message.

        Reads ahead without consuming, stopping at the depth-0 newline or
        semicolon that closes the statement (or at end of file). Punctuation
        is attached to its neighbour so the preview resembles the source.
        """
        pieces: list[str] = []
        depth = 0
        idx = start_index
        while idx < len(self._tokens):
            tok = self._tokens[idx]
            if tok.kind == EOF:
                break
            if depth == 0 and tok.kind in (NEWLINE, SEMI):
                break
            if tok.kind in (LPAREN, LBRACE, LBRACKET):
                depth += 1
            elif tok.kind in (RPAREN, RBRACE, RBRACKET):
                depth = max(0, depth - 1)
            pieces.append(tok.value)
            idx += 1
        text = ""
        for piece in pieces:
            if not text:
                text = piece
            elif piece == ".":
                if text.rsplit(" ", 1)[-1] in ("import", "static"):
                    text += " ."
                else:
                    text += "."
            elif piece in {",", ":", ")", "]"}:
                text += piece
            elif piece in {"(", "["} or text.endswith((".", "(", "[")):
                text += piece
            else:
                text += " " + piece
        return text

    def _skip_balanced(self, open_kind: str, close_kind: str) -> None:
        """Consume from the current open token through its matching close."""
        if self._peek().kind != open_kind:
            return
        depth = 0
        while True:
            tok = self._advance()
            if tok.kind == EOF:
                return
            if tok.kind == open_kind:
                depth += 1
            elif tok.kind == close_kind:
                depth -= 1
                if depth == 0:
                    return

    def _skip_statement(self) -> None:
        """Consume tokens up to (not including) the next newline at depth 0."""
        depth = 0
        while True:
            tok = self._peek()
            if tok.kind == EOF:
                return
            if tok.kind in (LPAREN, LBRACE, "[") :
                depth += 1
                self._advance()
                continue
            if tok.kind in (RPAREN, RBRACE, "]"):
                if depth == 0:
                    return
                depth -= 1
                self._advance()
                continue
            if tok.kind == NEWLINE and depth == 0:
                return
            self._advance()

    def _skip_step_tail(self) -> None:
        """Skip arguments/blocks that may follow an unsupported step name."""
        if self._peek().kind == LPAREN:
            self._skip_balanced(LPAREN, RPAREN)
        if self._peek().kind in STRING_KINDS:
            self._advance()
        if self._peek().kind == LBRACE:
            self._skip_balanced(LBRACE, RBRACE)

    def _skip_rest_of_block(self) -> None:
        """Consume tokens through the matching close of the enclosing block."""
        depth = 0
        while True:
            tok = self._advance()
            if tok.kind == EOF:
                return
            if tok.kind == LBRACE:
                depth += 1
            elif tok.kind == RBRACE:
                if depth == 0:
                    return
                depth -= 1

    def _mark_stage_blocked(self, stage: Stage) -> None:
        """A blocked stage translates nothing: discard any collected steps."""
        stage.blocked = True
        stage.steps.clear()

    def _mark_pipeline_blocked(self) -> None:
        """A pipeline-level blocker reduces the draft to a named skeleton."""
        if self.pipeline is None:
            return
        self.pipeline.blocked = True
        for stage in self.pipeline.stages:
            self._mark_stage_blocked(stage)

    # ---- findings ------------------------------------------------------

    def _make(self, code: str, construct: str, message: str, line: int, col: int, suggestion: str) -> Finding:
        severity, _ = REGISTRY[code]
        return Finding(
            code=code,
            severity=severity,
            construct=construct,
            message=message,
            line=line,
            col=col,
            suggestion=suggestion,
        )

    def _add(self, code: str, construct: str, message: str, line: int, col: int, suggestion: str) -> None:
        self._findings.append(self._make(code, construct, message, line, col, suggestion))

    def _decode_step_string(self, tok, context: str) -> Decoded | None:
        """Decode a string token used in a step; None when interpolated."""
        decoded = decode_string(tok.value, tok.kind, tok.line, tok.col)
        if decoded.has_interpolation:
            interp = decoded.interpolations[0]
            self._add(
                PB_INTERP,
                f"Groovy interpolated string in {context}",
                f"Groovy would substitute '{interp.text}' at pipeline runtime; "
                "pipebridge only translates string forms whose meaning can be preserved.",
                interp.line,
                interp.col,
                "Compute the value in a workflow step (e.g. from the github context) "
                "and pass it as a shell variable, deliberately chosen by a human.",
            )
            return None
        return decoded

    # ---- entry point ---------------------------------------------------

    def parse(self) -> ParseResult:
        buffered = self._scan_prelude()
        if buffered is None:
            # Scripted pipeline (or arbitrary Groovy): classification
            # unchanged from previous releases. self._findings carries
            # exactly the one PB-SCRIPT blocker; no pipeline was parsed.
            return ParseResult(pipeline=self.pipeline, findings=self._findings)

        self._parse_pipeline()
        if self.pipeline is not None:
            self._validate_required_structure()
        postlude = self._scan_postlude()

        # Commit the surrounding-Groovy findings only now that the scan has
        # terminated at a parsed top-level pipeline block.
        self._findings.extend(buffered)
        self._findings.extend(postlude)
        if any(
            f.code in (PB_GROOVY_PRELUDE, PB_GROOVY_POSTLUDE)
            for f in self._findings
        ):
            # Executable surrounding Groovy is a pipeline-level blocker: the
            # draft becomes a named skeleton (stages extracted and listed,
            # no steps translated) and is disabled like any other blocker.
            self._mark_pipeline_blocked()
        return ParseResult(pipeline=self.pipeline, findings=self._findings)

    # ---- surrounding Groovy --------------------------------------------

    def _scripted_finding(self, tok) -> Finding:
        return self._make(
            PB_SCRIPT,
            "scripted pipeline",
            "The file is a scripted pipeline (or arbitrary Groovy), not a "
            "declarative pipeline. Scripted pipelines are not supported and "
            "their contents were not analyzed.",
            tok.line,
            tok.col,
            "Rewrite as a declarative pipeline, or migrate manually.",
        )

    def _skip_surrounding_statement(self) -> tuple[bool, tuple[int, int] | None]:
        """Skip the rest of one prelude/postlude statement.

        Consumes tokens up to (not including) the newline or semicolon that
        closes the statement at bracket depth 0. Parentheses, braces, and
        brackets inside the statement (parameter lists, function bodies,
        closure literals, subscripts) are consumed as part of it, so a
        multi-line function definition is skipped whole. Groovy strings are
        single lexer tokens, so braces or the word ``pipeline`` inside them
        are never structural.

        Returns ``(terminated, nested_pipeline_pos)``: ``terminated`` is
        False when the file ends before the statement is closed;
        ``nested_pipeline_pos`` is the (line, col) of a ``pipeline {`` token
        sequence inside the skipped span, if any.
        """
        depth = 0
        nested_pipeline: tuple[int, int] | None = None
        while True:
            tok = self._peek()
            if tok.kind == EOF:
                return False, nested_pipeline
            if (
                tok.kind == IDENT
                and tok.value == "pipeline"
                and self._peek(1).kind == LBRACE
                and nested_pipeline is None
            ):
                nested_pipeline = (tok.line, tok.col)
            if tok.kind in (LPAREN, LBRACE, LBRACKET):
                depth += 1
                self._advance()
                continue
            if tok.kind in (RPAREN, RBRACE, RBRACKET):
                if depth == 0:
                    # A stray closer inside the surrounding content: consume
                    # it so the scan always advances; the statement still
                    # ends at the next depth-0 newline or semicolon.
                    self._advance()
                    continue
                depth -= 1
                self._advance()
                continue
            if depth == 0 and tok.kind in (NEWLINE, SEMI):
                return True, nested_pipeline
            self._advance()

    def _scan_prelude(self) -> list[Finding] | None:
        """Scan the Groovy before a top-level pipeline block.

        Recognized statement classes (documented, limited grammar): import
        statements, annotations, variable declarations, and function
        definitions. Everything they contain is skipped, never evaluated.

        Returns the buffered surrounding-Groovy findings when the scan
        reaches a top-level ``pipeline`` block. Returns None when there is
        no top-level pipeline block (scripted pipeline, or an unrecognized
        statement): self._findings then carries exactly the one PB-SCRIPT
        blocker and the buffered findings are discarded, so a scripted
        file's report is unchanged from previous releases.
        """
        self._skip_newlines()
        if self._peek().kind == EOF:
            # An empty (or comments-only) file is malformed input: there is
            # no pipeline here at all, not even a scripted one to report.
            raise MalformedPipelineError(
                "the file is empty; there is no pipeline to migrate", 1, 1
            )
        first = self._peek()
        buffered: list[Finding] = []
        nested_pipeline: tuple[int, int] | None = None
        while True:
            self._skip_newlines()
            tok = self._peek()
            if tok.kind == EOF:
                self._findings = [self._scripted_finding(first)]
                return None
            if tok.kind == IDENT and tok.value == "pipeline":
                if nested_pipeline is not None:
                    raise MalformedPipelineError(
                        "more than one 'pipeline' block occurrence was found; "
                        "which one is the declarative pipeline is ambiguous",
                        nested_pipeline[0],
                        nested_pipeline[1],
                    )
                return buffered
            recognized, shape = self._scan_prelude_statement(buffered)
            if not recognized:
                # Arbitrary Groovy: the prelude is a script. Unchanged
                # scripted classification, buffered findings discarded.
                self._findings = [self._scripted_finding(first)]
                return None
            if shape is not None and nested_pipeline is None:
                nested_pipeline = shape

    def _scan_prelude_statement(self, buffered: list[Finding]) -> tuple[bool, tuple[int, int] | None]:
        """Recognize and record one prelude statement.

        Returns ``(recognized, nested_pipeline_pos)``. A False ``recognized``
        means the statement is arbitrary Groovy outside the documented
        grammar (the caller falls back to the scripted classification).
        Recognized statements are never evaluated: their text is skipped and
        reported through a finding.
        """
        tok = self._peek()
        if tok.kind == ANNOTATION:
            self._advance()
            if tok.value == "@Library":
                # Existing stable behavior for shared libraries (unchanged).
                buffered.append(
                    self._make(
                        PB_LIB,
                        "shared library annotation",
                        "Shared libraries are not supported by the MVP.",
                        tok.line,
                        tok.col,
                        "Inline the library steps or migrate them manually; list every "
                        "custom step used from the library.",
                    )
                )
            else:
                buffered.append(
                    self._make(
                        PB_GROOVY_PRELUDE,
                        "annotation before the pipeline block",
                        "This annotation is Groovy that pipebridge does not "
                        "evaluate; its effect on the Jenkins runtime is not "
                        "represented in the generated workflow.",
                        tok.line,
                        tok.col,
                        "Reproduce the needed effect deliberately in the "
                        "workflow, or migrate the annotation manually.",
                    )
                )
            _, shape = self._skip_surrounding_statement()
            return True, shape
        if tok.kind == IDENT and tok.value == "import":
            return self._scan_import_statement(buffered)
        if tok.kind == IDENT:
            return self._scan_declaration_or_function(buffered)
        return False, None

    def _scan_import_statement(self, buffered: list[Finding]) -> tuple[bool, tuple[int, int] | None]:
        """Recognize one ``import`` statement (documented, limited grammar):

        ``import [static] a.b.Class`` — one or more dotted identifier
        segments, optionally ending in the ``.*`` wildcard, terminated by a
        newline, semicolon, or end of file. Every other form is executable
        Groovy outside the grammar (``as`` aliasing, punctuation, misplaced
        wildcards, repeated/missing dots, keyword segments, …) and is
        reported as a PB-GROOVY-PRELUDE blocker, never as an info-level
        import: an unsupported import must never leave the draft enabled.
        """
        statement_start = self._pos
        start = self._advance()  # 'import'
        is_static = False
        if self._peek().kind == IDENT and self._peek().value == "static":
            self._advance()
            is_static = True
        segments: list[str] = []
        wildcard = False
        supported = True
        tok = self._peek()
        if tok.kind != IDENT or tok.value in _IMPORT_KEYWORDS:
            supported = False
        else:
            segments.append(self._advance().value)
            while supported and self._peek().kind == DOT:
                self._advance()
                nxt = self._peek()
                if nxt.kind == IDENT and nxt.value not in _IMPORT_KEYWORDS:
                    segments.append(self._advance().value)
                elif (
                    nxt.kind == OTHER
                    and nxt.value == "*"
                    and self._peek(1).kind in (NEWLINE, SEMI, EOF)
                ):
                    # The wildcard is allowed only as the final segment.
                    self._advance()
                    wildcard = True
                    break
                else:
                    supported = False
            if supported and self._peek().kind not in (NEWLINE, SEMI, EOF):
                supported = False
        if supported:
            path = ".".join(segments + (["*"] if wildcard else []))
            if is_static:
                path = "static " + path
            buffered.append(
                self._make(
                    PB_GROOVY_IMPORT,
                    "import statement",
                    f"Import '{path}' is ordinary import syntax: it only "
                    "brings symbols into the Groovy runtime. pipebridge does "
                    "not evaluate it, and nothing about it is carried into "
                    "the generated workflow.",
                    start.line,
                    start.col,
                    "No action is needed for the import itself; references "
                    "to imported symbols in steps are reported separately.",
                )
            )
            return True, None
        # Recognized as an import statement, but outside the supported
        # grammar: executable surrounding Groovy → blocker, not info.
        preview = self._statement_preview(statement_start)
        buffered.append(
            self._make(
                PB_GROOVY_PRELUDE,
                "unsupported import statement",
                f"Import statement '{preview}' uses syntax outside the "
                "supported form ('import [static] some.package.Class', "
                "optionally ending in '.*'; 'as' aliasing, punctuation, "
                "repeated dots, and misplaced wildcards are not supported). "
                "It was not evaluated.",
                start.line,
                start.col,
                "Use the supported import form, or migrate the import "
                "manually.",
            )
        )
        _, shape = self._skip_surrounding_statement()
        return True, shape

    def _scan_declaration_or_function(self, buffered: list[Finding]) -> tuple[bool, tuple[int, int] | None]:
        """Recognize one prelude variable declaration or function definition.

        Limited grammar: zero or more modifiers (public/private/protected/
        static/final), then ``def`` or a type name, then a name; a function
        definition continues with a parameter list and body. The rest of the
        statement (any initializer, parameter list, body) is skipped and
        never evaluated: even a literal initializer is reported as a blocker
        because pipebridge does not decide that any initializer is harmless.
        """
        start = self._peek()
        while (
            self._peek().kind == IDENT
            and self._peek().value in _DECLARATION_MODIFIERS
        ):
            self._advance()
        tok = self._peek()
        if tok.kind != IDENT:
            return False, None
        if tok.value in _RESERVED_STATEMENT_KEYWORDS and tok.value != "def":
            return False, None
        self._advance()  # 'def' or a type name
        name = self._peek()
        if name.kind != IDENT:
            return False, None
        self._advance()  # variable or function name
        is_function = self._peek().kind == LPAREN
        _, shape = self._skip_surrounding_statement()
        if is_function:
            construct = "function definition before the pipeline block"
            message = (
                "This function definition is executable Groovy; pipebridge "
                "does not evaluate or translate it, and calls to it from "
                "steps remain unsupported and are reported separately."
            )
        else:
            construct = "variable declaration before the pipeline block"
            message = (
                "This variable declaration is executable Groovy that runs "
                "at Jenkins runtime before the pipeline starts; pipebridge "
                "does not evaluate it, and any value it computes is not "
                "carried into the generated workflow. Even an unused "
                "variable can have a side-effecting initializer."
            )
        buffered.append(
            self._make(
                PB_GROOVY_PRELUDE,
                construct,
                message,
                start.line,
                start.col,
                "Recreate the needed value or behavior in a workflow step "
                "or repository script, deliberately chosen by a human; do "
                "not assume it exists in the migrated workflow.",
            )
        )
        return True, shape

    def _scan_postlude(self) -> list[Finding]:
        """Scan the Groovy after the pipeline block (helper functions, …).

        Every statement after the block is executable surrounding Groovy and
        produces a PB-GROOVY-POSTLUDE blocker; nothing is evaluated or
        translated. Unterminated trailing content is reported the same way
        (a blocker, not a parse error). A further ``pipeline`` occurrence —
        at top level or inside a skipped statement — is rejected: pipebridge
        never silently selects one of several pipeline blocks.
        """
        findings: list[Finding] = []
        while True:
            self._skip_newlines()
            tok = self._peek()
            if tok.kind == EOF:
                return findings
            if tok.kind == IDENT and tok.value == "pipeline":
                raise MalformedPipelineError(
                    "more than one 'pipeline' block occurrence was found; "
                    "which one is the declarative pipeline is ambiguous",
                    tok.line,
                    tok.col,
                )
            start = tok
            construct = self._postlude_construct()
            terminated, shape = self._skip_surrounding_statement()
            if shape is not None:
                raise MalformedPipelineError(
                    "more than one 'pipeline' block occurrence was found; "
                    "which one is the declarative pipeline is ambiguous",
                    shape[0],
                    shape[1],
                )
            if terminated:
                message = (
                    "This Groovy content after the pipeline block is "
                    "executable; pipebridge does not evaluate or translate "
                    "it, and calls to it from steps remain unsupported and "
                    "are reported separately."
                )
            else:
                message = (
                    "The Groovy content after the pipeline block is not "
                    "closed: the file ends in the middle of this statement. "
                    "It was skipped without evaluation."
                )
            findings.append(
                self._make(
                    PB_GROOVY_POSTLUDE,
                    construct,
                    message,
                    start.line,
                    start.col,
                    "Recreate the needed behavior deliberately in the "
                    "workflow (a step or a repository script); do not "
                    "assume this code runs after the migrated pipeline.",
                )
            )

    def _postlude_construct(self) -> str:
        """Label the upcoming postlude statement (no tokens consumed)."""
        tok = self._peek()
        if tok.kind == ANNOTATION:
            return "annotation after the pipeline block"
        if tok.kind == IDENT:
            is_type_or_def = tok.value == "def" or tok.value not in _RESERVED_STATEMENT_KEYWORDS
            name = self._peek(1)
            paren = self._peek(2)
            if is_type_or_def and name.kind == IDENT and paren.kind == LPAREN:
                return "function definition after the pipeline block"
        return "Groovy content after the pipeline block"

    # ---- grammar -------------------------------------------------------

    def _validate_required_structure(self) -> None:
        """Enforce required declarative structure (official Jenkins syntax:
        'stages' requires at least one stage; every stage requires a
        'steps' section with at least one step). Violations are malformed
        input. Skipped for pipeline-level-blocked files, whose stage bodies
        were never traversed, so structure cannot be judged."""
        pipeline = self.pipeline
        if pipeline.blocked:
            return
        if not self._saw_stages_section:
            raise MalformedPipelineError(
                "the pipeline block has no 'stages' section; declarative "
                "pipelines require one (with at least one stage)",
                pipeline.span.line,
                pipeline.span.col,
            )
        if not pipeline.stages:
            raise MalformedPipelineError(
                "the 'stages' section contains no stage; declarative "
                "pipelines require at least one stage",
                pipeline.span.line,
                pipeline.span.col,
            )
        for stage in pipeline.stages:
            if stage.blocked:
                # A blocked stage's remaining body was deliberately not
                # traversed (the enclosing behavior is not preserved), so
                # its structure cannot be judged: report the unsupported
                # construct instead (valid-but-unsupported, exit 2).
                continue
            if id(stage) not in self._stages_with_steps_section:
                raise MalformedPipelineError(
                    f"stage '{stage.name}' has no 'steps' section; every "
                    "stage requires one (with at least one step)",
                    stage.span.line,
                    stage.span.col,
                )
            if id(stage) not in self._stages_with_nonempty_steps:
                raise MalformedPipelineError(
                    f"the 'steps' section of stage '{stage.name}' is empty; "
                    "it must contain one or more steps",
                    stage.span.line,
                    stage.span.col,
                )

    def _parse_pipeline(self) -> None:
        start = self._advance()  # 'pipeline'
        self.pipeline = Pipeline(span=Span(start.line, start.col))
        self._skip_newlines()

        if self._peek().kind != LBRACE:
            tok = self._peek()
            self._add(
                PB_SYNTAX,
                "pipeline block",
                "Expected '{' after 'pipeline'.",
                tok.line,
                tok.col,
                "Fix the pipeline block syntax.",
            )
            self._skip_statement()
            return

        self._advance()  # '{'
        saw_stages = False
        while True:
            self._skip_newlines()
            tok = self._peek()
            if tok.kind == RBRACE:
                self._advance()
                return
            if tok.kind == EOF:
                self._add(
                    PB_SYNTAX,
                    "pipeline block",
                    "Unterminated pipeline block.",
                    tok.line,
                    tok.col,
                    "Add the missing '}'.",
                )
                return
            if tok.kind != IDENT:
                self._add(
                    PB_SYNTAX,
                    "pipeline section",
                    f"Unexpected '{tok.value or tok.kind}' in pipeline body.",
                    tok.line,
                    tok.col,
                    "Use declarative sections only (agent, environment, stages, ...).",
                )
                self._mark_pipeline_blocked()
                self._advance()
                self._skip_statement()
                continue

            name = tok.value
            if name == "agent":
                self._parse_agent(pipeline_level=True)
            elif name == "environment":
                self._advance()
                self._parse_env_block(self.pipeline.env, context="pipeline environment", scope=None)
            elif name == "stages":
                if saw_stages:
                    self._add(
                        PB_SYNTAX,
                        "stages section",
                        "Duplicate 'stages' section.",
                        tok.line,
                        tok.col,
                        "Keep a single stages section.",
                    )
                    self._mark_pipeline_blocked()
                    self._advance()
                    self._skip_statement()
                else:
                    saw_stages = True
                    self._saw_stages_section = True
                    self._advance()
                    self._parse_stages()
            elif name in ("parameters",):
                self._add(
                    PB_PARAM,
                    "parameters directive",
                    "The parameters directive is not supported by the MVP; the "
                    "parameters were not migrated.",
                    tok.line,
                    tok.col,
                    "Recreate parameters as workflow_dispatch inputs deliberately.",
                )
                self._mark_pipeline_blocked()
                self._advance()
                self._skip_step_tail()
            elif name in ("triggers",):
                self._add(
                    PB_TRIGGER,
                    "triggers directive",
                    "The triggers directive is not supported by the MVP.",
                    tok.line,
                    tok.col,
                    "Configure GitHub-native triggers (push, schedule, ...) deliberately.",
                )
                self._mark_pipeline_blocked()
                self._advance()
                self._skip_step_tail()
            elif name in ("post",):
                self._add(
                    PB_POST,
                    "post section",
                    "Post actions are not supported by the MVP; their steps were "
                    "not extracted.",
                    tok.line,
                    tok.col,
                    "Translate post conditions to job-level steps with explicit conditions.",
                )
                self._mark_pipeline_blocked()
                self._advance()
                self._skip_step_tail()
            elif name in ("tools",):
                self._add(
                    PB_TOOLS,
                    "tools section",
                    "The tools section is not supported by the MVP; Jenkins-managed "
                    "tool installs have no automatic equivalent.",
                    tok.line,
                    tok.col,
                    "Install the tools in the workflow (setup actions or package manager).",
                )
                self._mark_pipeline_blocked()
                self._advance()
                self._skip_step_tail()
            elif name in ("options", "library"):
                code = PB_LIB if name == "library" else PB_SYNTAX
                construct = "shared library" if name == "library" else "options directive"
                message = (
                    "Shared libraries are not supported by the MVP."
                    if name == "library"
                    else "The options directive is not supported by the MVP; it changes build behavior and was not migrated."
                )
                self._add(
                    code,
                    construct,
                    message,
                    tok.line,
                    tok.col,
                    "Migrate the option deliberately (e.g. timeout via timeout-minutes).",
                )
                self._mark_pipeline_blocked()
                self._advance()
                self._skip_step_tail()
            else:
                self._add(
                    PB_SYNTAX,
                    "pipeline section",
                    f"Unknown pipeline section '{name}'.",
                    tok.line,
                    tok.col,
                    "Remove it or extend pipebridge deliberately.",
                )
                self._mark_pipeline_blocked()
                self._advance()
                self._skip_step_tail()

    def _parse_agent(self, pipeline_level: bool) -> None:
        tok = self._advance()  # 'agent'
        self._skip_newlines()
        nxt = self._peek()

        def block(message: str, code: str = PB_AGENT) -> None:
            if pipeline_level:
                self._mark_pipeline_blocked()
            else:
                self._mark_stage_blocked(self._current_stage)
            self._add(
                code,
                "agent declaration",
                message,
                tok.line,
                tok.col,
                "Choose the runner deliberately (runs-on) and document tool/network needs.",
            )

        if nxt.kind == IDENT and nxt.value == "any":
            self._advance()
            if pipeline_level:
                self.pipeline.has_agent_any = True
                self.pipeline.agent_span = Span(tok.line, tok.col)
            return
        if nxt.kind == IDENT and nxt.value == "none":
            self._advance()
            block(
                "'agent none' requires per-stage agents, which are not supported "
                "by the MVP."
            )
            return
        if nxt.kind == LBRACE:
            block(
                "Custom agents (label, node, docker, dockerfile, kubernetes) are "
                "not supported by the MVP; the agent configuration was not analyzed."
            )
            self._skip_balanced(LBRACE, RBRACE)
            return
        self._add(
            PB_SYNTAX,
            "agent declaration",
            "Could not parse the agent declaration.",
            nxt.line,
            nxt.col,
            "Use 'agent any' or report this pipeline as requiring manual migration.",
        )
        if pipeline_level:
            self._mark_pipeline_blocked()
        else:
            self._mark_stage_blocked(self._current_stage)
        self._skip_statement()

    def _parse_env_block(self, target: list[EnvVar], context: str, scope: "Stage | None" = None) -> None:
        if self._peek().kind != LBRACE:
            tok = self._peek()
            self._add(
                PB_SYNTAX,
                context,
                "Expected '{' after 'environment'.",
                tok.line,
                tok.col,
                "Fix the environment block syntax.",
            )
            self._skip_statement()
            return
        self._advance()  # '{'
        while True:
            self._skip_newlines()
            tok = self._peek()
            if tok.kind == RBRACE:
                self._advance()
                return
            if tok.kind == EOF:
                self._add(
                    PB_SYNTAX,
                    context,
                    "Unterminated environment block.",
                    tok.line,
                    tok.col,
                    "Add the missing '}'.",
                )
                return
            if tok.kind != IDENT:
                self._add(
                    PB_SYNTAX,
                    context,
                    f"Unexpected '{tok.value or tok.kind}' in environment block.",
                    tok.line,
                    tok.col,
                    "Use NAME = 'value' entries only.",
                )
                self._advance()
                self._skip_statement()
                continue
            name_tok = self._advance()
            eq = self._peek()
            if eq.kind != "EQUALS":
                self._add(
                    PB_SYNTAX,
                    context,
                    f"Expected '=' after environment variable '{name_tok.value}'.",
                    eq.line,
                    eq.col,
                    "Use NAME = 'value' entries only.",
                )
                self._skip_statement()
                continue
            self._advance()  # '='
            self._parse_env_value(target, name_tok, context, scope)

    def _mark_env_scope_blocked(self, scope: "Stage | None") -> None:
        if scope is None:
            self._mark_pipeline_blocked()
        else:
            self._mark_stage_blocked(scope)

    def _parse_env_value(self, target: list[EnvVar], name_tok, context: str, scope: "Stage | None") -> None:
        tok = self._peek()
        if tok.kind in STRING_KINDS:
            self._advance()
            decoded = decode_string(tok.value, tok.kind, tok.line, tok.col)
            if decoded.has_interpolation:
                interp = decoded.interpolations[0]
                self._add(
                    PB_INTERP,
                    f"Groovy interpolated string in {context}",
                    f"Environment variable '{name_tok.value}' uses interpolation "
                    f"('{interp.text}'); its runtime value is dynamic.",
                    interp.line,
                    interp.col,
                    "Compute the value in a workflow step or use a GitHub Actions expression, deliberately.",
                )
                self._mark_env_scope_blocked(scope)
                return
            target.append(
                EnvVar(
                    name_tok.value,
                    decoded.value,
                    Span(tok.line, tok.col),
                    dollar_spans=tuple(decoded.dollar_spans),
                )
            )
            return
        if tok.kind == "NUMBER":
            # Jenkins stringifies numeric environment values: meaning preserved.
            self._advance()
            target.append(EnvVar(name_tok.value, tok.value, Span(tok.line, tok.col)))
            return
        if tok.kind == IDENT and tok.value in ("true", "false"):
            self._advance()
            target.append(EnvVar(name_tok.value, tok.value, Span(tok.line, tok.col)))
            return
        if tok.kind == IDENT and tok.value == "credentials" and self._peek(1).kind == LPAREN:
            self._add(
                PB_CRED,
                "credentials() in environment block",
                f"Environment variable '{name_tok.value}' binds a Jenkins credential; "
                "credentials are not migrated automatically.",
                tok.line,
                tok.col,
                "Create a GitHub Actions secret and reference it explicitly (secrets.<NAME>).",
            )
            self._advance()  # 'credentials'
            self._skip_balanced(LPAREN, RPAREN)
            self._mark_env_scope_blocked(scope)
            return
        self._add(
            PB_ENVVAL,
            f"non-literal environment value for '{name_tok.value}'",
            "Environment values must be literals (string, number, true/false) in "
            "the supported subset.",
            tok.line,
            tok.col,
            "Replace with a literal value or compute it in a workflow step, deliberately.",
        )
        self._mark_env_scope_blocked(scope)
        self._skip_statement()

    def _parse_stages(self) -> None:
        if self._peek().kind != LBRACE:
            tok = self._peek()
            self._add(
                PB_SYNTAX,
                "stages section",
                "Expected '{' after 'stages'.",
                tok.line,
                tok.col,
                "Fix the stages block syntax.",
            )
            self._skip_statement()
            return
        self._advance()  # '{'
        while True:
            self._skip_newlines()
            tok = self._peek()
            if tok.kind == RBRACE:
                self._advance()
                return
            if tok.kind == EOF:
                self._add(
                    PB_SYNTAX,
                    "stages section",
                    "Unterminated stages block.",
                    tok.line,
                    tok.col,
                    "Add the missing '}'.",
                )
                return
            if tok.kind == IDENT and tok.value == "stage":
                header = self._advance()
                self._parse_stage(header)
                continue
            self._add(
                PB_SYNTAX,
                "stages section",
                f"Unexpected '{tok.value or tok.kind}' in stages block; only "
                "stage directives are supported.",
                tok.line,
                tok.col,
                "Move the construct into a stage's steps or migrate manually.",
            )
            self.pipeline.blocked = True
            self._advance()
            self._skip_statement()

    def _parse_stage(self, header) -> None:
        # The caller has consumed the 'stage' token (passed as `header`);
        # here we parse ( name ) { body }.
        self._skip_newlines()
        if self._peek().kind != LPAREN:
            tok = self._peek()
            self._add(
                PB_SYNTAX,
                "stage directive",
                "Expected '(' after 'stage'.",
                tok.line,
                tok.col,
                "Use stage('Name') { ... }.",
            )
            self._skip_statement()
            return
        self._advance()  # '('
        name_tok = self._peek()
        stage_name: str | None = None
        if name_tok.kind in STRING_KINDS:
            self._advance()
            decoded = decode_string(name_tok.value, name_tok.kind, name_tok.line, name_tok.col)
            if decoded.has_interpolation:
                interp = decoded.interpolations[0]
                self._add(
                    PB_INTERP,
                    "Groovy interpolated stage name",
                    f"Stage name uses interpolation ('{interp.text}').",
                    interp.line,
                    interp.col,
                    "Use a literal stage name.",
                )
            else:
                stage_name = decoded.value
        else:
            self._add(
                PB_SYNTAX,
                "stage directive",
                "Stage name must be a string literal.",
                name_tok.line,
                name_tok.col,
                "Use stage('Name') { ... }.",
            )
        if self._peek().kind == RPAREN:
            self._advance()
        else:
            self._add(
                PB_SYNTAX,
                "stage directive",
                "Expected ')' after the stage name.",
                self._peek().line,
                self._peek().col,
                "Use stage('Name') { ... }.",
            )
        self._skip_newlines()

        stage = Stage(
            name=stage_name if stage_name is not None else "<unparsed stage>",
            span=Span(header.line, header.col),
            dollar_spans=tuple(decoded.dollar_spans) if decoded is not None and not decoded.has_interpolation else (),
        )
        self.pipeline.stages.append(stage)

        if self._peek().kind != LBRACE:
            tok = self._peek()
            self._add(
                PB_SYNTAX,
                "stage directive",
                "Expected '{' to open the stage body.",
                tok.line,
                tok.col,
                "Use stage('Name') { ... }.",
            )
            self._skip_statement()
            return

        if self.pipeline.blocked:
            # Pipeline-level blocker: keep the stage name for the skeleton
            # report, but do not traverse its body for steps.
            self._skip_balanced(LBRACE, RBRACE)
            return

        self._parse_stage_body(stage)

    def _parse_stage_body(self, stage: Stage) -> None:
        self._current_stage = stage
        self._advance()  # '{'
        while True:
            self._skip_newlines()
            tok = self._peek()
            if tok.kind == RBRACE:
                self._advance()
                return
            if tok.kind == EOF:
                self._add(
                    PB_SYNTAX,
                    "stage block",
                    "Unterminated stage block.",
                    tok.line,
                    tok.col,
                    "Add the missing '}'.",
                )
                return
            if tok.kind != IDENT:
                self._add(
                    PB_SYNTAX,
                    "stage section",
                    f"Unexpected '{tok.value or tok.kind}' in stage body.",
                    tok.line,
                    tok.col,
                    "Use stage sections only (agent, environment, steps, ...).",
                )
                self._mark_stage_blocked(stage)
                break
            name = tok.value
            if name == "agent":
                self._parse_agent(pipeline_level=False)
            elif name == "environment":
                self._advance()
                self._parse_env_block(stage.env, context=f"stage '{stage.name}' environment", scope=stage)
            elif name == "steps":
                self._advance()
                self._parse_steps(stage)
            elif name == "when":
                self._add(
                    PB_WHEN,
                    "when condition",
                    f"Stage '{stage.name}' has a when condition; conditional "
                    "execution is not supported by the MVP and the stage was not "
                    "translated.",
                    tok.line,
                    tok.col,
                    "Translate to job/step-level 'if' conditions deliberately.",
                )
                self._mark_stage_blocked(stage)
                self._advance()
                self._skip_step_tail()
            elif name == "input":
                self._add(
                    PB_INPUT,
                    "input approval gate",
                    f"Stage '{stage.name}' waits for interactive approval; no "
                    "workflow_dispatch equivalent exists.",
                    tok.line,
                    tok.col,
                    "Use a GitHub environment with required reviewers and attach the "
                    "deploy steps to a deployment job.",
                )
                self._mark_stage_blocked(stage)
                self._advance()
                self._skip_step_tail()
            elif name == "parallel":
                self._add(
                    PB_PARALLEL,
                    "parallel execution",
                    f"Stage '{stage.name}' contains parallel branches, which are "
                    "not supported by the MVP.",
                    tok.line,
                    tok.col,
                    "Split into separate jobs with explicit needs/dependencies.",
                )
                self._mark_stage_blocked(stage)
                self._advance()
                self._skip_step_tail()
            elif name == "matrix":
                self._add(
                    PB_MATRIX,
                    "matrix execution",
                    f"Stage '{stage.name}' uses matrix execution, which is not "
                    "supported by the MVP.",
                    tok.line,
                    tok.col,
                    "Translate to a workflow matrix strategy deliberately.",
                )
                self._mark_stage_blocked(stage)
                self._advance()
                self._skip_step_tail()
            elif name in ("post", "options", "tools", "stages"):
                label = {
                    "post": "post section",
                    "options": "options directive",
                    "tools": "tools section",
                    "stages": "nested stages",
                }[name]
                code = {
                    "post": PB_POST,
                    "options": PB_SYNTAX,
                    "tools": PB_TOOLS,
                    "stages": PB_SYNTAX,
                }[name]
                message = {
                    "post": f"Stage '{stage.name}' has a post section; post "
                    "conditions are not supported by the MVP and the stage was "
                    "not translated.",
                    "options": f"Stage '{stage.name}' has an options directive; it "
                    "changes stage behavior and is not supported by the MVP.",
                    "tools": f"Stage '{stage.name}' has a tools section; tool "
                    "installs are not supported by the MVP.",
                    "stages": f"Stage '{stage.name}' contains nested stages, which "
                    "are not supported by the MVP.",
                }[name]
                self._add(
                    code,
                    label,
                    message,
                    tok.line,
                    tok.col,
                    "Migrate the construct deliberately (see documentation).",
                )
                self._mark_stage_blocked(stage)
                self._advance()
                self._skip_step_tail()
            else:
                self._add(
                    PB_SYNTAX,
                    "stage section",
                    f"Unknown stage section '{name}'; the enclosing stage was not "
                    "translated.",
                    tok.line,
                    tok.col,
                    "Move it into steps or migrate manually.",
                )
                self._mark_stage_blocked(stage)
                self._advance()
                self._skip_step_tail()

            if stage.blocked:
                # Do not traverse the remainder of a blocked stage: the
                # enclosing behavior is not preserved.
                self._skip_rest_of_block()
                return

    def _parse_steps(self, stage: Stage) -> None:
        if self._peek().kind != LBRACE:
            tok = self._peek()
            self._add(
                PB_SYNTAX,
                "steps section",
                "Expected '{' after 'steps'.",
                tok.line,
                tok.col,
                "Use steps { ... }.",
            )
            self._skip_statement()
            return
        self._advance()  # '{'
        # A steps section exists; record it and whether it is non-empty
        # (an empty section is a required-structure violation).
        self._stages_with_steps_section.add(id(stage))
        self._skip_newlines()
        if self._peek().kind != RBRACE:
            self._stages_with_nonempty_steps.add(id(stage))
        while True:
            self._skip_newlines()
            tok = self._peek()
            if tok.kind == RBRACE:
                self._advance()
                return
            if tok.kind == EOF:
                self._add(
                    PB_SYNTAX,
                    "steps section",
                    "Unterminated steps block.",
                    tok.line,
                    tok.col,
                    "Add the missing '}'.",
                )
                return
            if stage.blocked:
                self._skip_rest_of_block()
                return
            if tok.kind != IDENT:
                self._add(
                    PB_SYNTAX,
                    "step",
                    f"Unexpected '{tok.value or tok.kind}' in steps block.",
                    tok.line,
                    tok.col,
                    "Use supported steps only (sh, echo, checkout scm).",
                )
                self._mark_stage_blocked(stage)
                self._skip_rest_of_block()
                return
            name = tok.value
            span = Span(tok.line, tok.col)
            if name == "sh":
                self._advance()
                self._parse_sh(stage, span)
            elif name == "echo":
                self._advance()
                self._parse_echo(stage, span)
            elif name == "checkout":
                self._advance()
                self._parse_checkout(stage, span)
            elif name == "script":
                self._add(
                    PB_SCRIPT,
                    "script block",
                    f"Stage '{stage.name}' contains a script block with arbitrary "
                    "Groovy; it was not analyzed or translated.",
                    tok.line,
                    tok.col,
                    "Rewrite the logic as plain shell steps or migrate manually.",
                )
                self._mark_stage_blocked(stage)
                self._advance()
                self._skip_step_tail()
            elif name == "withCredentials":
                self._add(
                    PB_CRED,
                    "withCredentials binding",
                    f"Stage '{stage.name}' binds credentials; credentials are not "
                    "migrated automatically.",
                    tok.line,
                    tok.col,
                    "Create GitHub Actions secrets and reference them explicitly "
                    "(secrets.<NAME>); rewrite the bound step manually.",
                )
                self._mark_stage_blocked(stage)
                self._advance()
                self._skip_step_tail()
            else:
                self._add(
                    PB_SYNTAX,
                    f"step '{name}'",
                    f"Step '{name}' is not supported by the MVP; the enclosing "
                    "stage was not translated.",
                    tok.line,
                    tok.col,
                    "Check whether the step is a shared-library or plugin step and "
                    "migrate it deliberately.",
                )
                self._mark_stage_blocked(stage)
                self._advance()
                self._skip_step_tail()

    def _parse_sh(self, stage: Stage, span: Span) -> None:
        tok = self._peek()
        if tok.kind == LPAREN:
            self._advance()
            self._skip_newlines()
            tok = self._peek()
            if tok.kind in STRING_KINDS:
                self._advance()
                self._add_sh_step(stage, tok, span)
                if self._peek().kind == RPAREN:
                    self._advance()
                else:
                    self._add(
                        PB_SYNTAX,
                        "sh step",
                        "Expected ')' after the sh script string.",
                        self._peek().line,
                        self._peek().col,
                        "Use sh('command').",
                    )
                return
            self._add(
                PB_SYNTAX,
                "sh step",
                "sh with named arguments (label:, script:) is not supported by "
                "the MVP; the enclosing stage was not translated.",
                tok.line,
                tok.col,
                "Use sh '<command>' and set the environment explicitly if needed.",
            )
            stage.blocked = True
            self._skip_balanced(LPAREN, RPAREN)
            return
        if tok.kind in STRING_KINDS:
            self._advance()
            self._add_sh_step(stage, tok, span)
            return
        self._add(
            PB_SYNTAX,
            "sh step",
            "sh requires a string argument in the supported subset.",
            tok.line,
            tok.col,
            "Use sh '<command>'.",
        )
        stage.blocked = True
        self._skip_step_tail()

    def _add_sh_step(self, stage: Stage, tok, span: Span) -> None:
        decoded = self._decode_step_string(tok, "sh")
        if decoded is None:
            self._mark_stage_blocked(stage)
            return
        stage.steps.append(
            Step(kind="sh", text=decoded.value, span=span, dollar_spans=tuple(decoded.dollar_spans))
        )

    def _parse_echo(self, stage: Stage, span: Span) -> None:
        tok = self._peek()
        if tok.kind in STRING_KINDS:
            self._advance()
            decoded = self._decode_step_string(tok, "echo")
            if decoded is None:
                self._mark_stage_blocked(stage)
                return
            stage.steps.append(
                Step(kind="echo", text=decoded.value, span=span, dollar_spans=tuple(decoded.dollar_spans))
            )
            return
        self._add(
            PB_SYNTAX,
            "echo step",
            "echo requires a string argument in the supported subset.",
            tok.line,
            tok.col,
            "Use echo '<message>'.",
        )
        stage.blocked = True
        self._skip_step_tail()

    def _parse_checkout(self, stage: Stage, span: Span) -> None:
        tok = self._peek()
        if tok.kind == IDENT and tok.value == "scm":
            self._advance()
            stage.steps.append(Step(kind="checkout", text="checkout scm", span=span))
            return
        self._add(
            PB_SYNTAX,
            "checkout step",
            "Only 'checkout scm' is supported by the MVP; the enclosing stage "
            "was not translated.",
            tok.line,
            tok.col,
            "Use 'checkout scm' or configure actions/checkout deliberately.",
        )
        stage.blocked = True
        self._skip_step_tail()


def parse(source: str) -> ParseResult:
    return _Parser(source).parse()
