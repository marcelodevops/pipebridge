# Changelog

All notable changes to pipebridge are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project adheres to [Semantic Versioning](https://semver.org/).

## [0.5.0] — Alpha (2026-11-22)

**Bounded local shared-library migration (`vars/*.groovy`), script emission,
library `withCredentials` string bindings, and single-job `stash` / `unstash`.**
When `--library-map` supplies a strict `schema_version: 1` mapping of library
names to relative local directories containing `vars/`, eligible prelude
declarations (`@Library('name') _` and `@Library('name@rev') _`) are resolved
statically without fetching repositories or executing Groovy. Unmapped or
ineligible `@Library` forms and the declarative `library` section retain
`PB-LIB`.

Reached `vars/<name>.groovy` files are parsed statically for `def call` and
same-file helpers. Supported statements are literal/parameterized `sh` and
`echo`, helper and cross-var calls with literal string or forwarded in-scope
parameter arguments, bounded single-entry `string` `withCredentials` bindings,
and single-job `stash` / `unstash`. Parameter values are never spliced into
generated `.sh` files: script bodies use braced positional parameters
(`${1}`, `${2}`, …, `${10}`) and workflow steps pass neutralized, single-quoted
`argv` tokens to `bash --noprofile --norc -eo pipefail`. `sh(param)` passes
parameter-supplied shell text via `argv` to
`bash --noprofile --norc -eo pipefail -c "${1}"`.

Single-job `stash` and `unstash` emit `scripts/pipebridge_stash.py` and
`scripts/pipebridge_unstash.py` storing files under
`$RUNNER_TEMP/pipebridge-stash/<name>` with a final `always()`
`continue-on-error: true` cleanup step. Both helpers reject symlinks and
containment escapes; `pipebridge_unstash.py` prevalidates all source entries
(regular files only) and destination parents/leaves before copying.

Live `workflow_dispatch` validation on GitHub Actions is recorded in
[`docs/shared-library-live-validation.md`](docs/shared-library-live-validation.md).
Not yet published: no `v0.5.0` tag, GitHub release, or release asset exists.
Published v0.1.0, v0.2.0, v0.2.1, and v0.3.0 assets are unchanged.

### Added

- `--library-map` on `analyze` and `convert` (`schema_version: 1` JSON mapping
  library names to relative local directories with `vars/`).
- Static resolution of eligible `@Library('name') _` and
  `@Library('name@rev') _` declarations and `vars/<name>.groovy` `def call` /
  helper definitions, with recursion and call-depth (`20`) checks.
- Deterministic `<output>/scripts/<library>/<var>/<function>-<n>.sh` emission
  committed transactionally with `workflow.yml` and reports via `_write_all`.
- Bounded `withCredentials([string(credentialsId: '…', variable: 'NAME')])`
  support inside library bodies, reusing `CredentialInventory`,
  `--credential-map`, and `--secrets-ready`.
- Bounded single-job `stash` and `unstash` in Jenkinsfiles and library bodies,
  emitting `scripts/pipebridge_stash.py`, `scripts/pipebridge_unstash.py`, and
  the `Remove pipebridge stash` `always()` cleanup step.
- Finding codes `PB-LIB-CALL`, `PB-LIB-MAP-UNUSED`, and `PB-ASSUME-LIBRARY`,
  plus additive `libraries` report inventory and `source_path` / `call_chain`
  provenance.

### Changed

- Generated library script invocations run under
  `bash --noprofile --norc -eo pipefail` so `errexit` and `pipefail` hold
  inside child scripts.
- Finding deduplication includes `source_path` and `call_chain` so identical
  coordinates across library files or distinct call sites are preserved.

### Fixed

- Unbraced dotted property interpolations (`$x.length`, `$a.b.c`) are rejected
  with `PB-INTERP` instead of being split into `${1}.length`.
- `pipebridge_stash.py` detects symlinked directories whose descendants could
  match `includes` (accounting for `excludes`) without following symlinks.
- `pipebridge_unstash.py` prevalidates all source entries as regular files and
  checks destination parents/leaves before writing any destination file.

### Known limitations

- Local mapped libraries only (`vars/*.groovy`); no repository fetching, no
  Groovy execution, and no `src/` or `resources/` support.
- Single-job `stash` / `unstash` only (`$RUNNER_TEMP/pipebridge-stash/<name>`);
  requires `bash` and `python3` on the runner. Runtime restore `OSError`s fail
  non-zero and may leave partial destination changes.
- Output replacement on disk is staged with `OSError` rollback, not
  crash-atomic across process kills.
- In the live expected-failure validation run, failure occurred at
  `Fail (step 2)` before `stash`, so that run verified `always()` cleanup
  execution after early failure rather than removal of a populated stash after
  failure. No comparison against live Jenkins execution was performed.

## [0.4.0] — Alpha (2026-11-20)

**Bounded literal `string` credential bindings.** One
`withCredentials([string(credentialsId: '…', variable: 'NAME')]) { … }`
in a stage `steps` block can be mapped to a step-scoped
`NAME: ${{ secrets.MAPPED }}` environment entry. The secret name comes
only from `--credential-map`. pipebridge does not guess IDs, read secret
values, invoke `gh`, or change GitHub configuration.

The binding body must be existing supported `sh`, `echo`, and
`checkout scm` steps. Other binding types, dynamic arguments, nested
bindings, and opaque bodies stay `PB-CRED`. A resolved map still disables
the job with `PB-CRED-SETUP` until `--secrets-ready` acknowledges that
the named secrets exist. That flag is an unverified acknowledgement, not
a check that the secret exists or that its value matches Jenkins.

Reports gain an additive `credentials` object (bindings, required secrets,
and a setup checklist) and, when a binding is present, a "Required GitHub
Actions secrets" section. The credential inventory is independent of
translated steps, so it survives stage clearing. Workflow bytes for
pipelines without an accepted binding are unchanged apart from this
version header. This is not Jenkins credential runtime equivalence.

Not yet published: no `v0.4.0` tag, GitHub release, or release asset exists.
Published v0.1.0, v0.2.0, v0.2.1, and v0.3.0 assets are unchanged.

### Added

- One literal `string` binding in `steps`, mapped to a step-scoped
  `env` entry whose value is `${{ secrets.MAPPED }}`.
- `--credential-map` (names only) and `--secrets-ready` (unverified
  acknowledgement, reported as `PB-ASSUME-CREDENTIALS`).
- Additive `credentials` report object, including an inventory that
  survives stage clearing.
- `PB-CRED-MAP`, `PB-CRED-SETUP`, `PB-CRED-MAP-UNUSED`, and
  `PB-ASSUME-CREDENTIALS`.

### Changed

- A complete map without `--secrets-ready` still exits 2 and disables the
  draft, but the resolved steps remain available for review.
- With a complete map and `--secrets-ready`, an otherwise clean pipeline
  exits 0. The acknowledgement does not verify the secret.

### Fixed

- A semicolon between credential-header tokens, or between the call and
  the body, is rejected. A detached closure is not translated. Semicolons
  inside a valid body still separate supported steps.

### Known limitations

- Unsupported credential forms stay blocked. pipebridge does not read
  secret values, create secrets, or call GitHub.
- `--secrets-ready` is an acknowledgement, not a verification.
- No Jenkins controller and no GitHub Actions runner were used. No
  runtime equivalence is claimed.

## [0.3.0] — Alpha (2026-11-20)

**Bounded pipeline-level literal agent-label mapping.** A single
pipeline-level `agent { label '<literal>' }` or `agent { label "<literal>" }`
is mapped to `runs-on: [self-hosted, <label>]` and reported as
`PB-ASSUME-RUNNER-LABEL`. This carries a runner **selector** only. It does
not claim a matching self-hosted runner exists, is online, or has the same
OS, tools, network, permissions, or workspace behavior as the Jenkins agent.
`PB-ASSUME-RUNNER` remains the `agent any` → `ubuntu-latest` assumption and
is not emitted for a label.

The decoded label must match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$` over the
whole value. `self-hosted` is rejected in any casing. Every other accepted
spelling is preserved, including labels that look like YAML scalars
(`true`, `null`, `123`, `1.2`), which stay quoted strings. A decoded
trailing newline does not satisfy the grammar. Expressions, variables,
concatenation, triple quotes, the call form, extra directives, `agent none`,
`node` / `docker` / `dockerfile` / `kubernetes`, and stage-level labels stay
blocked. An accepted label does not clear unrelated blockers and does not
make a malformed pipeline valid.

actionlint's hosted-runner catalog does not include custom labels. When a
labeled `runs-on` list is emitted, that one unknown-label message is
suppressed and disclosed in the report. Other lint failures still reject
the conversion. That disclosure is not evidence the runner exists.

The DO400-like synthetic is the one checked-in sample this mapping makes
clean: exit 2 → 0, enabled job, labeled runner, implicit checkout, and its
three literal `sh` steps. Memphis, HMRC, and Tutanota get the labeled
`runs-on` but stay exit 2 because unrelated blockers remain. Couchbase's
expression label, Jetty, and Kymatio stay `ubuntu-latest` and `PB-AGENT`.
`agent any` output, including `examples/python-build`, is otherwise
unchanged apart from this version header.

Published as an alpha prerelease:
<https://github.com/marcelodevops/pipebridge/releases/tag/v0.3.0>.
Published v0.1.0, v0.2.0, and v0.2.1 assets are unchanged.

### Added

- Pipeline-level literal `agent { label '…' }` / `agent { label "…" }` mapped
  to `runs-on: [self-hosted, label]`.
- Info finding `PB-ASSUME-RUNNER-LABEL`, attached to the `agent` keyword,
  stating the runner-selector assumption and that expressions, variables,
  and stage-level agents are not mapped.

### Changed

- `node-minimal-do400-like` converts cleanly (exit 0) instead of remaining a
  disabled `PB-AGENT` draft. Its blocked D2 baseline is removed; the
  pure-declarative golden is the enabled labeled workflow.
- Memphis, HMRC, and Tutanota drafts show the intended labeled runner while
  remaining disabled. HMRC and Tutanota keep their stage-level `PB-AGENT`.

### Fixed

- Label validation uses a full match, so a decoded trailing newline cannot
  pass the bounded grammar. Escaped newline, tab, and carriage return stay
  blocked.

### Known limitations

- This is a selector mapping, not runtime equivalence. No Jenkins controller
  and no self-hosted runner are involved.
- Unsupported agent forms stay blockers. A rejected label leaves `PB-AGENT`,
  `if: false`, and `runs-on: ubuntu-latest`.
- A label that looks like a GitHub-hosted runner (`ubuntu-latest`) is still
  emitted as self-hosted. Edit `runs-on` deliberately if a hosted runner is
  intended.

## [0.2.1] — Alpha (2026-11-19)

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

Published as an alpha prerelease:
<https://github.com/marcelodevops/pipebridge/releases/tag/v0.2.1>.

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
[0.3.0]: https://github.com/marcelodevops/pipebridge/releases/tag/v0.3.0
[0.4.0]: https://github.com/marcelodevops/pipebridge/releases/tag/v0.4.0
