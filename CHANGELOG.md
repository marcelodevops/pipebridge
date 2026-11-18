# Changelog

All notable changes to pipebridge are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project adheres to [Semantic Versioning](https://semver.org/).

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
