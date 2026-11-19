# Changelog

All notable changes to pipebridge are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.1] — Alpha (2026-11-18)

**Diagnostic completeness inside blocked scopes (defect D2), not broader
conversion support.** When translation stops at a blocker, pipebridge now
keeps reading the declarative constructs it can still see and reports them
as additional findings. Findings in a blocked scope remain a migration
checklist: they are never translated behavior. The supported translation
subset, exit codes, disabled drafts, finding JSON keys, and report schema
are unchanged, and Groovy is still never evaluated.

The deeper traversal covers the blocking construct's eligible body and the
remaining siblings in the same scope, with parent-scope labels, stable
source ordering, deduplication, and an explicit depth limit (20). It enters
only the documented declarative grammar and a bounded step-wrapper
allowlist. Opaque bodies — `script`, shared-library calls, agent internals,
`when` expressions, `post`, `withCredentials`, and unknown closures — are
reported once as boundaries and are never entered, so no translated `Step`
or nested model `Stage` is created from a blocked scope.

Supported step arguments are validated inside blocked scopes too:
interpolation, dynamic expressions, and unsupported `checkout` forms are
reported rather than assumed safe. Diagnostic argument recovery stops at a
top-level semicolon, so a later sibling on the same line is still analyzed
and reported. Opaque bodies stay opaque.

### Added

- Diagnostic traversal inside blocked stage and pipeline scopes, including
  `parallel` branches, `matrix` stages, nested `stages`, agents, `when`,
  `options`, `tools`, `input`, `post`, environment values, and unsupported
  steps.
- Branch and axis names in `PB-PARALLEL` and `PB-MATRIX` messages where the
  declarative names are statically readable.
- A depth-limit finding when diagnostic traversal stops at nesting depth 20;
  deeper content is explicitly reported as not analyzed.

### Fixed

- `sh`, `echo`, and `checkout` arguments in blocked scopes were treated as
  safe from the step name alone. They now reuse the supported-subset checks,
  so interpolation, dynamic Groovy expressions, and non-`checkout scm` forms
  are reported without translating anything.
- Blocked-scope argument recovery consumed the rest of the line, hiding a
  later sibling after a top-level `;`. Recovery now stops at that semicolon
  while leaving shared statement recovery unchanged; semicolons inside
  strings, parentheses, brackets, and closures are not split points.
- Diagnostic `sh` argument consumption no longer leaves the parser
  misaligned and emitting cascading false findings for later tokens.

### Known limitations

- Diagnostics are best-effort within the documented declarative grammar.
  Opaque bodies are boundaries, not analyzed code, and diagnostic traversal
  stops at depth 20 (reported explicitly).
- No construct newly visible in a blocked scope is translated; the draft
  stays disabled and the exit code stays 2.
- No Groovy is evaluated, no initializer is classified as safe, and no
  Jenkins-to-GitHub runtime equivalence is claimed.

## [0.2.0] — Alpha (2026-11-18)

**Bounded analysis improvement, not broader conversion support.** The
declarative `pipeline { }` block is now recognized and analyzed when it
is surrounded by ordinary Groovy. Nothing about the supported translation
subset changed: Groovy is never evaluated or translated, every surrounding
executable form still produces a blocker (exit 2, disabled draft), and no
Jenkins-to-GitHub runtime equivalence is claimed or tested. This addresses
defect **D1** (surrounding Groovy discarded or truncated the analysis) from
the v0.1.0 compatibility study. Defect **D2** (nested constructs are not
enumerated once a pipeline-level blocker exists) remains deferred.

Published as an alpha prerelease:
<https://github.com/marcelodevops/pipebridge/releases/tag/v0.2.0>.

### Added

- Surrounding-Groovy recognition before and after one top-level
  declarative `pipeline` block:
  - Ordinary imports (`import [static] a.b.Class`, optionally ending in
    `.*`) are info-level `PB-GROOVY-IMPORT` findings and do not block.
  - Variable declarations and other annotations before the block are
    executable Groovy and block as `PB-GROOVY-PRELUDE`; initializers are
    never judged harmless and their values are never carried over.
  - Helper function definitions and other statements after the block block
    as `PB-GROOVY-POSTLUDE`.
  - The declarative structure is still extracted and every top-level stage
    is listed in the disabled draft and report. Pure-declarative output is
    unchanged apart from the tool-version header line.
- `docs/release-notes-v0.2.0.md`: scope, verification, installation, and
  known limitations for this release-preparation increment.
- A CLI fixture and test matrix for malformed imports.

### Fixed

- Import validation now enforces the documented limited grammar: dotted
  identifier segments, an optional wildcard only as the final segment, and
  correct ordinary/static structure. Malformed forms (punctuation such as
  `import foo.+`, `import foo.@`, misplaced wildcards such as
  `import foo.*.Bar`, aliases, repeated/missing segments, keyword segments)
  are `PB-GROOVY-PRELUDE` blockers and can never leave the draft enabled.
- Imports no longer classify as info just because their path tokens were
  arbitrary punctuation.

### Known limitations

- **D2 remains deferred:** when a pipeline-level blocker exists, nested
  constructs inside the pipeline (for example a `parallel` block and its
  branches) are not enumerated as additional findings. The disabled draft
  and report still state what was and was not analyzed.
- Surrounding Groovy is recognized only for the limited statement forms
  above. Unrecognized statements before the block still classify the file
  as `PB-SCRIPT`; multiple or ambiguous `pipeline` occurrences are rejected
  as malformed (exit 1, no artifacts).
- No Groovy is evaluated, no initializer is classified as safe, and no
  Jenkins runtime behavior is reproduced. See the README limitations and
  the v0.2.0 release notes.

## [0.1.0] — Alpha (2026-11-18)

First milestone: a proven, repeatable, installable MVP of the
Jenkins-to-GitHub-Actions migration CLI. **Alpha** — the conversion
subset is deliberately small and everything outside it is reported,
never approximated. Published as a GitHub pre-release:
<https://github.com/marcelodevops/pipebridge/releases/tag/v0.1.0>

### Added

- Declarative-Jenkinsfile tokenizer/parser with line/column tracking for
  a documented grammar subset.
- Migration analysis with stable finding codes (`PB-*`), severities, and
  source positions; unsupported constructs block and disable the
  generated job (`if: false`) instead of being silently dropped.
- Deterministic GitHub Actions workflow generation: single job,
  `workflow_dispatch` only, `contents: read`, explicit `shell: bash`,
  actions pinned to verified full commit SHAs.
- `analyze` and `convert` subcommands with the exit-code contract:
  `0` no blockers, `1` malformed input / I-O / internal error, `2`
  valid-but-unsupported.
- JSON and Markdown migration reports with an honest validation section
  (YAML parse, actionlint when installed, runtime never executed).
- python-build example: declarative Jenkinsfile, greeter package, tests,
  committed migration output, and a live GitHub Actions workflow
  (`.github/workflows/python-build-example.yml`).
- Repeatable example validation (`scripts/validate-python-build-example.py`)
  run in CI: example unittest, example wheel/sdist build, `greet()`
  smoke test from the wheel, conversion with the installed pipebridge,
  byte-for-byte workflow comparison, structural live-workflow comparison,
  and field-wise report validation.
- `docs/validation.md`: recorded live-run and expected-failure evidence
  with exact commits and local reproduction commands.

### Fixed

- GitHub expression safety: literal `${{ … }}` from Jenkins source is
  neutralized in shell-quoted text (no `${{` in the raw script at all)
  and in GitHub-evaluated fields (documented escaping idiom); source-
  derived comments cannot inject workflow structure via newlines.
- Implicit source checkout: Jenkins' default checkout is modeled as a
  `Checkout source (implicit)` step before the first translated step;
  explicit `checkout scm` steps are never deduplicated against it.
- Required-structure validation: missing/empty `stages`, stages without
  a non-empty `steps` section, and empty files are malformed input
  (exit 1); scripted pipelines stay exit 2 with a valid disabled draft.
- Output replacement: staged writes back up previous artifacts
  byte-for-byte before committing; handled failures roll back; failed
  restorations preserve a recovery backup whose exact path is reported
  (incomplete rollback is never claimed as complete); partially written
  staging/backup files are always cleaned; targets that would overwrite
  the input Jenkinsfile (including via symlink) are rejected.
- Test portability: the suite passes without `actionlint`, with the
  absent/failing/unexecutable states handled and reported honestly.

### Known limitations

- See "Known limitations" in the README and in the v0.1.0 release
  notes. Highlights: `script {}`, credentials, parallel/matrix,
  `input` approvals, post conditions, custom agents, and other
  constructs are unsupported (blocked, exit 2); `workflow_dispatch`-only
  trigger; output replacement is not crash-atomic; after an incomplete
  rollback, the original bytes remain in a reported recovery backup for
  manual restoration.

[0.1.0]: https://github.com/marcelodevops/pipebridge/releases/tag/v0.1.0
[0.2.0]: https://github.com/marcelodevops/pipebridge/releases/tag/v0.2.0
[0.2.1]: https://github.com/marcelodevops/pipebridge/releases/tag/v0.2.1
