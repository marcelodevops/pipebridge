# pipebridge

A Python CLI that migrates declarative Jenkins pipelines (`Jenkinsfile`) to GitHub Actions workflows — and tells you the truth about what migrated, what needs human work, and why.

pipebridge translates a deliberately limited, clearly documented subset of Jenkins declarative pipeline syntax and produces an actionable migration report alongside the generated workflow. It **never silently discards unsupported behavior**, never replaces an unsupported step with an `echo` that appears to succeed, and never invents a "migration confidence percentage".

## Design principles

- **Parse, don't regex.** A real tokenizer/parser with line and column tracking handles a documented grammar subset; no regex-substitution conversion.
- **No execution.** Jenkinsfiles, Groovy fragments, and extracted shell commands are never executed.
- **Evidence over optimism.** Every assumption, blocker, and warning is reported with a source location and a stable finding code.
- **Honest validation.** Reports distinguish YAML parsing, workflow linting (`actionlint`, when installed), and actual runtime validation. Generated workflows are never claimed to have been executed.
- **Reviewable drafts.** Even when blockers exist, pipebridge generates a disabled, reviewable draft workflow plus reports.

## Installation

Requires Python 3.10+ (CI tests 3.10 and 3.13).

### From a GitHub release wheel

The [v0.1.0 alpha release](https://github.com/marcelodevops/pipebridge/releases/tag/v0.1.0) is published (prerelease):

```sh
pip install https://github.com/marcelodevops/pipebridge/releases/download/v0.1.0/pipebridge-0.1.0-py3-none-any.whl
# or, for an isolated CLI:
pipx install https://github.com/marcelodevops/pipebridge/releases/download/v0.1.0/pipebridge-0.1.0-py3-none-any.whl
```

The attached `SHA256SUMS` file lets you verify the download. pipebridge is not published to PyPI.

### From source

```sh
git clone https://github.com/marcelodevops/pipebridge.git
cd pipebridge
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Verify:

```sh
pipebridge --version
# pipebridge 0.1.0 from the published v0.1.0 wheel
# pipebridge 0.2.0 from this release-preparation source branch
```

## CLI

### `pipebridge analyze <jenkinsfile>`

Analyzes a Jenkinsfile and prints supported constructs, assumptions, and blockers. Writes nothing.

```sh
pipebridge analyze Jenkinsfile                 # human-readable text
pipebridge analyze Jenkinsfile --format json   # machine-readable JSON (same data as migration-report.json)
```

### `pipebridge convert <jenkinsfile> --output <dir>`

Generates a migration into the given directory:

```sh
pipebridge convert Jenkinsfile --output ./migration
```

Produces:

| File | Purpose |
| --- | --- |
| `workflow.yml` | The generated GitHub Actions workflow (disabled with `if: false` when blockers exist) |
| `migration-report.md` | Human-readable migration report |
| `migration-report.json` | The same report as structured JSON with stable finding codes |

pipebridge **never overwrites existing outputs by default**. Add `--force` to replace previously generated files.

Generation is staged: all artifacts are written to unique temporary files and the previous contents backed up **before** anything is replaced. Temporary and backup paths are registered before the write or copy that creates them, so a failure that leaves partially written bytes on disk is still cleaned up. A handled failure (disk full, permission error) during staging or while committing rolls back — previous files are restored byte-for-byte, newly introduced outputs are removed, and temporary files are cleaned; this is reported as a **complete rollback**. If a restoration itself fails, the rollback is reported as **incomplete**: the backup holding the only surviving copy of the original bytes is **never deleted**, and the error names each affected target and the exact recovery-backup path for manual recovery. This is deliberately **not** a crash-atomic multi-file transaction: a process kill between the individual file replacements can still leave a partial set on disk. Output paths that would overwrite the input Jenkinsfile (including via symlink) are rejected before anything is written.

### `pipebridge --version`

Prints the tool version.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Analysis or conversion completed **without** migration blockers |
| `1` | Malformed input (including missing required structure: no `stages` section, no stage, or a stage without a non-empty `steps` section), I/O failure, or internal error |
| `2` | Analysis or conversion completed with migration blockers — **valid** Jenkins that uses constructs outside the supported subset |

Malformed input and valid-but-unsupported input are deliberately distinguished: a pipeline missing its required `stages`/`steps` structure cannot be interpreted at all (exit 1), while a scripted pipeline or a pipeline with an `input` gate is valid Jenkins that pipebridge does not support (exit 2, with a disabled draft).

## What gets migrated

| Jenkins construct | Status | Notes |
| --- | --- | --- |
| One declarative `pipeline { }` block | ✅ Supported | Groovy **around** the block is recognized and reported (see rows below) but never evaluated or translated; genuinely scripted pipelines are still rejected with `PB-SCRIPT` |
| `agent any` | ⚠️ With assumption | Target runner assumed `ubuntu-latest`; Jenkins `agent any` does **not** establish OS, installed tools, or network access (`PB-ASSUME-RUNNER`) |
| `agent none`, `label`, `node`, `docker`, `dockerfile`, `kubernetes` | ❌ Blocked | `PB-AGENT` |
| Sequential `stages` / `stage` / `steps` | ✅ Supported | Kept as sequential steps in **one** job so the filesystem (workspace) state is preserved between stages (`PB-SINGLE-JOB`) |
| `sh` with literal strings, including multiline | ✅ Supported | Emitted as `run:` block scalars; shell variables like `$MY_VAR` are preserved as shell variables |
| `echo` with literal strings | ✅ Supported | Translated to `printf '%s\n' …` to preserve Jenkins `echo` semantics (no shell expansion of the argument) |
| `checkout scm` | ⚠️ With assumption | Becomes `actions/checkout`; assumes the workflow runs in the migrated source repository (`PB-ASSUME-CHECKOUT`) |
| *no* `checkout scm` | ⚠️ With assumption | Jenkins checks out source by default before the first stage; an implicit `Checkout source (implicit)` step is inserted before the first translated step (`PB-ASSUME-CHECKOUT`) |
| `environment` at pipeline level | ✅ Supported | Mapped to job-level `env` |
| `environment` at stage level | ✅ Supported | Mapped to step-level `env` on that stage's steps only — scope is preserved |
| Single-quoted Groovy strings `'…'` | ✅ Supported | Literal; only `\'` and `\\` are escapes |
| Double-quoted Groovy strings `"…"` without interpolation | ✅ Supported | Standard Groovy escapes processed |
| Groovy interpolation `"… ${expr} …"`, `"… $var …"` | ❌ Blocked | `PB-INTERP` — dynamic behavior has no tested translation |
| Triple-quoted strings `'''…'''`, `"""…"""` | ✅ Supported | Same rules as their single/double counterparts; newlines preserved |
| `script { }` blocks and scripted pipelines | ❌ Blocked | `PB-SCRIPT` |
| Shared libraries, custom steps | ❌ Blocked | `PB-LIB`, `PB-SYNTAX` |
| `credentials()` / `withCredentials` | ❌ Blocked | `PB-CRED` — automatic secret migration is a later phase |
| `parallel` / `matrix` | ❌ Blocked | `PB-PARALLEL`, `PB-MATRIX` |
| `tools` | ❌ Blocked | `PB-TOOLS` |
| `when`, `parameters`, `triggers`, `input`, `post`, `options` | ❌ Blocked | `PB-WHEN`, `PB-PARAM`, `PB-TRIGGER`, `PB-INPUT`, `PB-POST`, `PB-SYNTAX` |
| Unknown or arbitrary Groovy syntax | ❌ Blocked | `PB-SYNTAX` |
| Groovy `import` before the block: `import [static] a.b.Class`, optionally ending `.*` | ⚠️ Recognized, info-level | `PB-GROOVY-IMPORT` — imports execute nothing and are never evaluated; references to imported symbols inside steps stay blocked. `as` aliasing or any other form is blocked (`PB-GROOVY-PRELUDE`) |
| Variable declarations before the block (`def x`, `String x = …`, any initializer) | ❌ Blocked | `PB-GROOVY-PRELUDE` — executable Groovy, never evaluated, never judged harmless (even an unused variable can have a side-effecting initializer); the declarative block is still extracted and listed |
| Annotations before the block other than `@Library` | ❌ Blocked | `PB-GROOVY-PRELUDE` — `@Library` keeps its existing `PB-LIB` classification |
| Helper function definitions or other statements after the block | ❌ Blocked | `PB-GROOVY-POSTLUDE` — executable Groovy, skipped without evaluation; the declarative block is still extracted and listed, and calls to the helpers from steps stay blocked |

Unsupported blocks are **not traversed**: a `script { }` or `withCredentials { … }` body is never mined for `sh`/`echo` commands as though its enclosing behavior didn't exist.

Groovy **surrounding** the pipeline block is likewise never evaluated or translated: only its statement boundaries are recognized (enough to report it precisely and still parse the pipeline block). Surrounding executable Groovy is a pipeline-level blocker, so the generated draft remains a disabled skeleton that lists the extracted stages; a draft never appears fully migrated while surrounding Groovy is unmodeled.

## Generated workflow behavior

- Trigger: `workflow_dispatch` only (`PB-TRIGGER-MANUAL`).
- Minimal explicit permissions: `contents: read` — widen deliberately if a step proves it needs more.
- Explicit `shell: bash` via `defaults.run`.
- **Implicit source checkout**: Jenkins performs a default SCM checkout before the first stage. The generated workflow models this with a `Checkout source (implicit)` step (pinned `actions/checkout`) before the first translated step. Explicit `checkout scm` steps are **never deduplicated** against it — Jenkins performs both, and a later checkout can change workspace state. The assumption that the workflow runs in the migrated source repository is disclosed in the report (`PB-ASSUME-CHECKOUT`).
- Referenced actions are pinned to **verified full commit SHAs**, with the release version documented in a trailing comment and in the report (e.g. `actions/checkout@<full-sha> # vX.Y.Z`).
- All sequential stages run in a single job so later stages see earlier stages' filesystem state, mirroring a Jenkins executor workspace.
- Stage names are retained in generated step names.
- Literal source text containing GitHub expression syntax (`${{ … }}`) is **neutralized** so Jenkins strings are not unintentionally evaluated by GitHub Actions; each occurrence is reported (`PB-GHEXPR`). Two mechanisms, both verified by tests that execute the generated commands under `bash`:
  - text placed in fields GitHub itself evaluates (step names, env values, unquoted `sh` scripts) uses the documented escaping idiom `${{ '${{' }}`;
  - text that lands inside shell quotes (`echo` messages, placeholder messages) is single-quoted in pieces joined by a shell concatenation that rebuilds the literal `${{` at runtime — the raw script contains **no** `${{` sequence at all, because the idiom corrupts inside shell quotes.
- Recognizable Jenkins-specific variable references in commands (`$BUILD_NUMBER`, `$WORKSPACE`, `$BRANCH_NAME`, …) are preserved as-is but reported as warnings (`PB-JENV`) since they have no value on GitHub Actions runners without a mapping decision.
- Shell/environment differences are documented in the report (`PB-ASSUME-SHELL`): each `sh` step runs in its own shell on both systems, but GitHub Actions `bash` adds `pipefail` and drops Jenkins' `-x` tracing, and the runner image replaces the Jenkins agent's toolset.

### When blockers exist

The workflow is still generated for review, but the job is **disabled with a literal `if: false` condition** plus a generated comment explaining why. A blocked stage becomes a placeholder step that **fails loudly with an explanation** — it is never replaced by a step that appears to succeed.

## Migration reports

Every report contains:

- Source file path and its SHA-256, and the tool version.
- **Translated items** — what was migrated, stage by step.
- **Assumptions** — e.g. `ubuntu-latest` runner, checkout of the migrated repository.
- **Blockers** — what could not be translated and why.
- **Validation results** — YAML parse, `actionlint` (when installed), and an explicit statement that runtime validation was **not** performed.
- **Findings**, each with:

| Field | Example |
| --- | --- |
| Code (stable) | `PB-INTERP` |
| Severity | `blocker`, `warning`, or `info` |
| Source line:column | `24:21` |
| Construct | Groovy interpolated string in `echo` |
| Explanation | Groovy would substitute `${BUILD_NUMBER}` at runtime; pipebridge has no tested translation for dynamic expressions |
| Suggested next action | Replace with a shell variable or a GitHub Actions expression, chosen deliberately by a human |

### Finding codes

| Code | Severity | Meaning |
| --- | --- | --- |
| `PB-SCRIPT` | blocker | Scripted pipeline syntax or `script { }` block |
| `PB-LIB` | blocker | Shared library usage |
| `PB-CRED` | blocker | Credentials / credential bindings |
| `PB-PARALLEL` | blocker | `parallel` execution |
| `PB-MATRIX` | blocker | `matrix` execution |
| `PB-AGENT` | blocker | Custom / Docker / Kubernetes / labeled agent, or `agent none` |
| `PB-TOOLS` | blocker | `tools` declaration |
| `PB-WHEN` | blocker | Stage conditions (`when`) |
| `PB-PARAM` | blocker | `parameters` |
| `PB-TRIGGER` | blocker | `triggers` |
| `PB-INPUT` | blocker | `input` approval gates |
| `PB-POST` | blocker | `post` actions |
| `PB-INTERP` | blocker | Groovy interpolation / dynamic expression in a string |
| `PB-ENVVAL` | blocker | Non-literal `environment` value |
| `PB-SYNTAX` | blocker | Unknown or unsupported syntax |
| `PB-JENV` | warning | Jenkins-specific variable reference in shell text |
| `PB-GHEXPR` | warning | GitHub expression syntax in source literal (escaped in output) |
| `PB-SHELLCHECK` | warning | shellcheck note about a faithfully-migrated script (reported against the generated workflow; never fails the conversion) |
| `PB-ASSUME-RUNNER` | info | `agent any` → `ubuntu-latest` assumption |
| `PB-ASSUME-CHECKOUT` | info | Source checkout: implicit default checkout modeled for translated pipelines, and/or explicit `checkout scm` → `actions/checkout` in the migrated repository |
| `PB-ASSUME-SHELL` | info | Shell and execution-environment differences |
| `PB-TRIGGER-MANUAL` | info | Workflow triggers `workflow_dispatch` only |
| `PB-GROOVY-IMPORT` | info | Ordinary Groovy import statement before the pipeline block (limited grammar; never evaluated) |
| `PB-GROOVY-PRELUDE` | blocker | Executable Groovy before the pipeline block (declarations, annotations, unsupported import forms) |
| `PB-GROOVY-POSTLUDE` | blocker | Executable Groovy after the pipeline block (helper functions, other statements) |
| `PB-SINGLE-JOB` | info | All stages kept in one job to preserve workspace state |

## Example migration

**Input — `Jenkinsfile`** (line numbers added for reference):

```groovy
 1  pipeline {
 2      agent any
 3      environment {
 4          TF_IN_AUTOMATION = 'true'
 5      }
 6      stages {
 7          stage('Init') {
 8              steps {
 9                  checkout scm
10                  sh 'terraform init -input=false'
11              }
12          }
13          stage('Plan') {
14              steps {
15                  sh 'terraform plan -out=tfplan'
16                  sh 'echo "Plan for build $BUILD_NUMBER ready"'
17              }
18          }
19          stage('Deploy') {
20              input {
21                  message 'Apply this plan?'
22              }
23              steps {
24                  echo "Deploying build ${BUILD_NUMBER}"
25                  sh 'terraform apply -auto-approve tfplan'
26              }
27          }
28      }
29  }
```

**Generated — `migration/workflow.yml`**:

```yaml
# Generated by pipebridge 0.2.0 — DO NOT EDIT BY HAND.
# Source: Jenkinsfile (sha256: 2c986ed778bd75556627f6f8623edf2c4a8371e9c545f81ba5f87009f0924ae5)
#
# This pipeline had 1 migration blocker(s) (PB-INPUT).
# The job below is DISABLED (`if: false`). Read the migration
# report and resolve every blocker before removing the condition.

name: Migrated Jenkins pipeline
on:
  workflow_dispatch:
permissions:
  contents: read
defaults:
  run:
    shell: bash

jobs:
  migrated-pipeline:
    # Disabled by pipebridge: 1 blocker(s) (PB-INPUT).
    # This condition is a literal false: the job never runs until a human removes it.
    if: false
    runs-on: ubuntu-latest
    env:
      TF_IN_AUTOMATION: "true"
    steps:
      - name: "Checkout source (implicit)"
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1 (pinned to full commit SHA)
      - name: Init
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1 (pinned to full commit SHA)
      - name: "Init (step 2)"
        run: |2-
          terraform init -input=false
      - name: Plan
        run: |2-
          terraform plan -out=tfplan
      - name: "Plan (step 2)"
        run: |2-
          echo "Plan for build $BUILD_NUMBER ready"
      # Stage "Deploy" (line 19) was NOT migrated: it contains
      # unsupported constructs (PB-INPUT). See the migration report.
      - name: "[NOT MIGRATED] Deploy"
        run: |2-
          echo '"Deploy" was not migrated: it contains migration blockers (PB-INPUT). Read migration-report.md and fix deliberately before enabling this workflow.' >&2
          exit 1
```

Note the **implicit checkout**: the pipeline's first stage checks out explicitly (`checkout scm`), and Jenkins' default checkout before the first stage is modeled as well — both appear, in that order. Explicit checkouts are never deduplicated, because a later checkout can change workspace state.

Note also that the `input` gate blocks the **whole Deploy stage**: its steps are
never traversed, so the Groovy interpolation at line 24 is inside a stage
whose contents were not analyzed at all — it produces no finding of its own.
The report is explicit about what was and was not read.

**Generated — `migration/migration-report.md`** (excerpt):

```markdown
# Migration report

- **Source:** `Jenkinsfile` (sha256 `2c986ed7…9024ae5`)
- **Tool:** pipebridge 0.2.0
- **Generated:** 2026-11-18T17:19:53Z
- **Result:** converted **with 1 blocker(s)** — the generated job is DISABLED (`if: false`)
- **Exit code:** 2

## Summary

| Severity | Count |
| --- | --- |
| blocker | 1 |
| warning | 1 |
| info | 6 |
| translated stages | 3 |
| translated steps | 4 |

## Translated items

| Stage | Step kind | Source line | Detail |
| --- | --- | --- | --- |
| Init | checkout | 9 | `checkout scm` |
| Init | sh | 10 | `terraform init -input=false` |
| Plan | sh | 15 | `terraform plan -out=tfplan` |
| Plan | sh | 16 | `echo "Plan for build $BUILD_NUMBER ready"` |
| Deploy | — | 19 | **not migrated** (contains blockers; placeholder step fails loudly) |

## Blockers

### PB-INPUT — input approval gate (line 20, col 13)

- Stage 'Deploy' waits for interactive approval; no workflow_dispatch equivalent exists.
- **Next action:** Use a GitHub environment with required reviewers and attach the deploy steps to a deployment job.

## Warnings

### PB-JENV — sh command (line 16, col 42)

- Jenkins-specific variable 'BUILD_NUMBER' is referenced in shell text.
- **Next action:** Map it to a GitHub Actions equivalent (e.g. github.run_number) or remove it, deliberately.

## Validation

| Check | Result |
| --- | --- |
| YAML parse | ✅ passes (`yaml.safe_load`) |
| actionlint | ✅ passes (exit 0, actionlint 1.7.12) |
| Runtime execution | ⚠️ Not performed: pipebridge does not execute generated workflows. |

> pipebridge reports what it verified and nothing more: YAML parsing and
> linting are static checks; runtime behavior was **not** validated.
```

## Known limitations

- The supported subset is deliberately small; anything outside it is reported, never approximated.
- Surrounding Groovy is recognized only within a deliberately limited grammar (ordinary imports, annotations, variable declarations, function definitions). It is **never evaluated or translated**, and this is not complete Groovy parsing: an unrecognized statement before the block still classifies the whole file as `PB-SCRIPT`, and multiple or ambiguous `pipeline` occurrences are rejected rather than resolved.
- Nested constructs inside blocked pipelines are not enumerated (D2, deferred: a `parallel` block inside a pipeline that already has a pipeline-level blocker produces no additional findings); the disabled draft and the report say what was and was not analyzed.
- No Jenkins runtime equivalence is claimed or tested: values computed by surrounding Groovy at Jenkins runtime are not carried into any generated workflow.
- One workflow, one job, `workflow_dispatch` only. No push/PR triggers in the MVP.
- Groovy is supported only as far as literal string forms; any dynamic expression is a blocker.
- Credentials, parameters, triggers, conditions, approvals, and post actions are never migrated — they require human decisions.
- `echo` becomes `printf '%s\n'` to preserve semantics; output is identical but the command differs.
- The runner assumption (`ubuntu-latest`) is just that — an assumption. Jenkins `agent any` guarantees nothing about OS, tools, or network.
- The implicit checkout models Jenkins' default behavior but cannot verify the migrated repository is the right source; a pipeline that never checked out source (artifact-only jobs) must have the implicit step removed by a human.
- Multi-file output replacement is staged with rollback, but is **not** crash-atomic: a process kill between the individual file renames can leave a partial set on disk. Handled failures (I/O errors) roll back byte-for-byte; if a rollback restoration itself fails, the rollback is incomplete — the original bytes remain in a recovery backup whose path is reported, and a human must restore it.
- `actionlint` runs only when installed locally; the report says so explicitly either way.
- Generated workflows are **never executed** by pipebridge; "passes validation" means YAML parsing and linting only.
- No confidence percentage: pipebridge reports facts, not vibes.

## Later phases (explicitly out of scope for this MVP)

AI-assisted migration advice, bulk repository scanning, Jenkins API integration, and automatic secret migration are future work. This increment is intentionally focused on a correct, honest core.

## Shipped example

[`examples/python-build/`](examples/python-build/) is a small declarative pipeline (checkout, then test, then build) that converts with no blockers. Its unmodified pipebridge output is in `examples/python-build/migration/`.

GitHub Actions discovers workflows only in [`.github/workflows/`](.github/workflows/). The live test is [`.github/workflows/python-build-example.yml`](.github/workflows/python-build-example.yml): the generated workflow with `defaults.run.working-directory` set to `examples/python-build`. That adjustment, and why checkout still runs at the repository root, is documented in the example README.

The live workflow has been dispatched for real: a successful run and an intentional-failure run (failure propagation) are recorded with exact commits in [`docs/validation.md`](docs/validation.md). CI repeats the example validation on every change — unittest, example wheel/sdist build, `greet()` smoke test from the wheel, conversion with the installed package, byte-for-byte workflow comparison, structural live-workflow comparison, and field-wise report validation. We have executed the migrated workflow on GitHub Actions; we have **not** compared it against a live Jenkins run, and no runtime equivalence is claimed.

## Changelog and releases

Notable changes are documented in [`CHANGELOG.md`](CHANGELOG.md). The **v0.1.0 alpha** release is published at <https://github.com/marcelodevops/pipebridge/releases/tag/v0.1.0>; its release notes (installation options, supported versions, conversion subset, known limitations) are in [`docs/release-notes-v0.1.0.md`](docs/release-notes-v0.1.0.md). **v0.2.0** (a bounded analysis improvement for surrounding Groovy) is prepared for release; its notes are in [`docs/release-notes-v0.2.0.md`](docs/release-notes-v0.2.0.md). It is **not yet published**: no tag or release asset exists for it yet.

## Development

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Tests cover source positions and nested blocks, comments/braces inside strings, all string forms, shell variable preservation, environment scope, shared workspace across sequential stages, unknown syntax, unsupported enclosing blocks, GitHub expression injection through source literals (including executing generated commands under `bash` to verify literal preservation), implicit source checkout, required-structure validation and exit codes, staged writes under injected failures (commit-time rollback including failed restorations that preserve recovery backups, and partial staging/backup writes), and overwrite protection. `actionlint` (optional) is exercised on generated workflows when present, with dedicated tests for absent, failing, and unexecutable states; the suite passes without it (those tests skip honestly).

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.10 (the declared minimum) and 3.13, lints the repository's workflows with a checksum-verified pinned actionlint, builds the package, and smoke-tests the installed CLI outside the source directory — using minimal permissions and full-SHA action pins.

## License

MIT — see [LICENSE](LICENSE).
