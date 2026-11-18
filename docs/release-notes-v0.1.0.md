# Release notes — pipebridge v0.1.0 (ALPHA)

> **Status: alpha, release not yet published.** This document prepares
> the forthcoming v0.1.0 release. Release assets (wheel and source
> distribution) do not exist on the
> [releases page](https://github.com/marcelodevops/pipebridge/releases)
> yet; the download instructions below are the instructions for that
> forthcoming release and must not be read as evidence that it is
> already published. This release is **not** published to PyPI.

## What v0.1.0 is

The first milestone of pipebridge: a **proven, repeatable, installable**
CLI that migrates a deliberately limited subset of declarative Jenkins
pipelines to GitHub Actions workflows, with honest, actionable migration
reports. Alpha quality: the conversion subset is small by design, every
unsupported construct is reported as a blocker, and generated workflows
for blocked pipelines are disabled drafts.

Validated for this milestone (see `docs/validation.md` for run links
and exact commits):

- 157-charge test suite (unit + end-to-end) passing on Python 3.10 and
  3.13 in CI, with actionlint 1.7.12 present and honestly skipped when
  absent.
- The python-build example's migrated workflow executed live on
  `ubuntu-latest` (success), and an intentional-failure branch
  demonstrating failure propagation (Test step fails on an assertion,
  Build steps skipped, workflow concludes failure).
- Repeatable example validation in CI, including byte-for-byte workflow
  regeneration and structural live-workflow comparison.
- Wheel and sdist build cleanly; metadata passes `twine check`; the
  wheel installs and passes the CLI smoke matrix in a fresh environment
  outside the repository.

## Installation (for the forthcoming v0.1.0 release)

Requires Python 3.10 or newer (CI tests 3.10 and 3.13).

### From the GitHub release wheel (once published)

```sh
pip install https://github.com/marcelodevops/pipebridge/releases/download/v0.1.0/pipebridge-0.1.0-py3-none-any.whl
# or with pipx, for an isolated CLI:
pipx install https://github.com/marcelodevops/pipebridge/releases/download/v0.1.0/pipebridge-0.1.0-py3-none-any.whl
```

### From the source distribution (once published)

```sh
pip install https://github.com/marcelodevops/pipebridge/releases/download/v0.1.0/pipebridge-0.1.0.tar.gz
```

### From the repository (works today)

```sh
git clone https://github.com/marcelodevops/pipebridge.git
cd pipebridge
python3 -m venv .venv && source .venv/bin/activate
pip install .
```

Verify:

```sh
pipebridge --version
# pipebridge 0.1.0
```

## Supported Python versions

- Declared minimum: Python **3.10** (`requires-python = ">=3.10"`).
- CI runs the test suite on **3.10 and 3.13**; the example-validation
  job runs on 3.13.
- Runtime dependency: PyYAML >= 6.0. Optional: `actionlint` (used for
  static workflow linting when installed; never required).

## Conversion subset (what migrates)

Supported declarative constructs: `pipeline` with `agent any` (or no
agent), `environment` (pipeline/stage), `stages` with stages that have
non-empty `steps` sections, and literal `sh` / `echo` steps, plus
`checkout scm`. Translated steps run in a single job in source order
(shared workspace); `echo` becomes `printf '%s\n'` (semantically
identical output); the Jenkins default SCM checkout is modeled as an
implicit `actions/checkout` step and explicit checkouts are never
deduplicated.

Anything else — `script { }` blocks, credentials, parallel/matrix,
`input` approval gates, `post` conditions, `when` conditions, custom
(container/k8s) agents, parameters, triggers, `tools`, scripted
pipelines — is **unsupported**: reported as a blocker with a source
position, and the generated job is a **disabled** reviewable draft
(`if: false`) with loud placeholder steps (exit code 2). Missing
required structure (no `stages`, no steps) is malformed input (exit 1).

## Known limitations

- **Subset by design.** Unsupported constructs are never approximated;
  they require human decisions and are reported instead.
- **`workflow_dispatch` only.** No push/PR triggers are generated; add
  them deliberately after review.
- **Static validation, plus the live runs in `docs/validation.md`.**
  Pipebridge never executes generated workflows itself, and no claim of
  Jenkins-to-GitHub runtime equivalence is made: the migrated workflow
  was executed on GitHub Actions, but it was **not** compared with a
  live Jenkins run.
- **Output replacement is not crash-atomic.** Replacement is staged:
  artifacts are written to unique temp files and previous artifacts
  backed up before anything is replaced; handled I/O failures roll back
  byte-for-byte. A process kill between the individual file renames can
  still leave a partial set on disk.
- **Manual recovery after incomplete rollback.** If a rollback
  restoration itself fails, the rollback is reported as **incomplete**:
  the affected file's original bytes remain in a recovery backup
  (`.workflow.yml.<id>.bak` next to the output), the error names the
  exact backup path, and a human must restore it. Pipebridge never
  deletes that backup and never claims a complete rollback when a
  restoration failed.
- **Reports are environment-specific.** They carry a generation
  timestamp and tool version; only the workflow is deterministic
  byte-for-byte, and report validation is field-wise.
- No confidence percentage; no telemetry; no execution of Jenkinsfile
  commands by the tool itself.

## Release checklist (for the release manager)

Nothing below has been done for v0.1.0 yet.

- [ ] All CI checks green on `main` (tests on 3.10/3.13, lint + build +
      smoke test, example validation) —
      <https://github.com/marcelodevops/pipebridge/actions>
- [ ] Full suite green locally with `actionlint` present:
      `python -m pytest tests/ -q`
- [ ] `docs/validation.md` evidence current (live run + expected-failure
      run links resolve, commits match)
- [ ] Version stays `0.1.0` (`src/pipebridge/__init__.py`); do **not**
      regenerate committed example output solely for version strings —
      regenerate only when the conversion output itself changes, then
      re-apply the live-workflow working-directory adjustment
- [ ] Build: `python -m pip install build && python -m build --outdir dist .`
- [ ] Metadata: `twine check dist/*` passes
- [ ] Fresh-environment smoke test **outside the repository** (see the
      validated commands in `docs/validation.md`):
      - `pipebridge --version` → `pipebridge 0.1.0`
      - `pipebridge analyze <supported fixture>` → exit 0
      - `pipebridge convert <supported fixture> --output out` → exit 0,
        `workflow.yml` + `migration-report.md` + `migration-report.json`
      - `pipebridge convert <unsupported fixture> --output out` → exit 2,
        draft disabled (`if: false`)
      - `pipebridge convert <malformed fixture> --output out` → exit 1,
        no generated artifacts
- [ ] Tag `v0.1.0` on `main`; create the GitHub release titled
      `v0.1.0 — alpha`, marked as a **pre-release**, with this document
      as the body
- [ ] Upload `dist/pipebridge-0.1.0-py3-none-any.whl` and
      `dist/pipebridge-0.1.0.tar.gz` as release assets
- [ ] Verify the release-download URL resolves after publishing, and
      only then update the README's "not yet published" note
- [ ] Out of scope for v0.1.0: publishing to PyPI
