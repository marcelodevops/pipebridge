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

Requires Python 3.10+.

```sh
git clone https://github.com/OWNER/pipebridge.git
cd pipebridge
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

For an isolated CLI install, `pipx install /path/to/pipebridge` also works.

> pipebridge is not yet published to PyPI; install from a clone for now.

Verify:

```sh
pipebridge --version
# pipebridge 0.1.0
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

pipebridge **never overwrites existing outputs by default**. Add `--force` to replace previously generated files. Generation is all-or-nothing: files are written only after the workflow renders and validates, so a failure never leaves a partial set of artifacts.

### `pipebridge --version`

Prints the tool version.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Analysis or conversion completed **without** migration blockers |
| `1` | Malformed input, I/O failure, or internal error |
| `2` | Analysis or conversion completed, **with** migration blockers |

## What gets migrated

| Jenkins construct | Status | Notes |
| --- | --- | --- |
| One declarative `pipeline { }` block | ✅ Supported | Scripted pipelines are rejected with a blocker (nothing inside them is extracted) |
| `agent any` | ⚠️ With assumption | Target runner assumed `ubuntu-latest`; Jenkins `agent any` does **not** establish OS, installed tools, or network access (`PB-ASSUME-RUNNER`) |
| `agent none`, `label`, `node`, `docker`, `dockerfile`, `kubernetes` | ❌ Blocked | `PB-AGENT` |
| Sequential `stages` / `stage` / `steps` | ✅ Supported | Kept as sequential steps in **one** job so the filesystem (workspace) state is preserved between stages (`PB-SINGLE-JOB`) |
| `sh` with literal strings, including multiline | ✅ Supported | Emitted as `run:` block scalars; shell variables like `$MY_VAR` are preserved as shell variables |
| `echo` with literal strings | ✅ Supported | Translated to `printf '%s\n' …` to preserve Jenkins `echo` semantics (no shell expansion of the argument) |
| `checkout scm` | ⚠️ With assumption | Becomes `actions/checkout`; assumes the workflow runs in the migrated source repository (`PB-ASSUME-CHECKOUT`) |
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

Unsupported blocks are **not traversed**: a `script { }` or `withCredentials { … }` body is never mined for `sh`/`echo` commands as though its enclosing behavior didn't exist.

## Generated workflow behavior

- Trigger: `workflow_dispatch` only (`PB-TRIGGER-MANUAL`).
- Minimal explicit permissions: `contents: read` — widen deliberately if a step proves it needs more.
- Explicit `shell: bash` via `defaults.run`.
- Referenced actions are pinned to **verified full commit SHAs**, with the release version documented in a trailing comment and in the report (e.g. `actions/checkout@<full-sha> # vX.Y.Z`).
- All sequential stages run in a single job so later stages see earlier stages' filesystem state, mirroring a Jenkins executor workspace.
- Stage names are retained in generated step names.
- Literal source text containing GitHub expression syntax (`${{ … }}`) is **neutralized** (`${{ '${{' }}`) so Jenkins strings are not unintentionally evaluated by GitHub Actions; each occurrence is reported (`PB-GHEXPR`).
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
| `PB-ASSUME-RUNNER` | info | `agent any` → `ubuntu-latest` assumption |
| `PB-ASSUME-CHECKOUT` | info | `checkout scm` → `actions/checkout` in the migrated repository |
| `PB-ASSUME-SHELL` | info | Shell and execution-environment differences |
| `PB-TRIGGER-MANUAL` | info | Workflow triggers `workflow_dispatch` only |
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

**Generated — `migration/workflow.yml`** (excerpt):

```yaml
# Generated by pipebridge 0.1.0 from Jenkinsfile (sha256: 7f3a92c4d8e15b06af3c2d47e91b8a05c6d3f2e1b04a9c8d7e6f5a4b3c2d1e0f)
# Source pipeline had 2 migration blocker(s) — this job is DISABLED.
# See migration-report.md before enabling: remove `if: false` only after
# resolving every blocker (PB-INTERP, PB-INPUT).
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
    # Disabled by pipebridge: 2 blocker(s) in source (PB-INTERP, PB-INPUT).
    if: false
    runs-on: ubuntu-latest
    env:
      TF_IN_AUTOMATION: 'true'
    steps:
      - name: Init
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      - name: Init (sh 2)
        run: |-
          terraform init -input=false
      - name: Plan
        run: |-
          terraform plan -out=tfplan
          echo "Plan for build $BUILD_NUMBER ready"
      # Stage "Deploy" was NOT migrated: it contains unsupported constructs
      # (input approval gate at line 20, Groovy interpolation at line 24).
      - name: "[NOT MIGRATED] Deploy"
        run: |-
          echo 'Stage "Deploy" was not migrated; see migration-report.md (PB-INPUT, PB-INTERP).' >&2
          exit 1
```

**Generated — `migration/migration-report.md`** (excerpt):

```markdown
# Migration report

- **Source:** `Jenkinsfile` (sha256 `7f3a92c4…2d1e0f`)
- **Tool:** pipebridge 0.1.0
- **Generated:** 2026-11-17T17:04:11Z
- **Result:** converted **with 2 blocker(s)** — generated job is DISABLED (`if: false`)
- **Exit code:** 2

## Summary

| Severity | Count |
| --- | --- |
| blocker | 2 |
| warning | 1 |
| info    | 4 |

## Translated items

| Stage | Step | Workflow location | Kind |
| --- | --- | --- | --- |
| Init | checkout scm | job step 1 | actions/checkout |
| Init | sh line 10 | job step 2 | run (shell) |
| Plan | sh line 15 | job step 3 | run (shell) |
| Plan | sh line 16 | job step 3 | run (shell) |
| Deploy | — | not migrated | blocked (placeholder step fails loudly) |

## Blockers

### PB-INTERP — Groovy interpolation (line 24, col 21)

- **Construct:** double-quoted Groovy string in `echo` containing `${BUILD_NUMBER}`
- **Explanation:** Groovy substitutes the expression at pipeline runtime;
  pipebridge only translates string forms whose meaning can be preserved.
- **Next action:** compute the value in a workflow step (e.g. from the
  `github` context) and pass it as a shell variable, deliberately.

### PB-INPUT — input approval gate (line 20, col 13)

- **Construct:** `input` directive in stage `Deploy`
- **Explanation:** interactive approvals have no workflow_dispatch
  equivalent; GitHub Environments with required reviewers are the closest
  mechanism but change semantics and must be configured by a human.
- **Next action:** configure a GitHub environment with a required reviewer
  and attach the deploy step to a deployment job.

## Warnings

### PB-JENV — Jenkins-specific variable reference (line 16, col 43)

- **Construct:** shell text `$BUILD_NUMBER`
- **Explanation:** preserved as a shell variable, but no such environment
  variable exists on GitHub Actions runners.
- **Next action:** map to the GitHub Actions equivalent (e.g. `${{ github.run_number }}`)
  or remove.

## Assumptions

- **PB-ASSUME-RUNNER** (line 2): `agent any` does not establish OS, installed
  tools, or network access; the generated workflow assumes `ubuntu-latest`.
- **PB-ASSUME-CHECKOUT** (line 9): `checkout scm` is translated to
  `actions/checkout`, assuming this workflow runs in the migrated repository.
- **PB-ASSUME-SHELL:** steps run under `bash -eo pipefail` (Jenkins uses
  `/bin/sh -xe`); pipelines behave differently on pipe failures and no `-x`
  tracing is emitted.
- **PB-SINGLE-JOB:** all stages share one job to preserve filesystem state.
- **PB-TRIGGER-MANUAL:** the workflow triggers on `workflow_dispatch` only.

## Validation

| Check | Result |
| --- | --- |
| YAML parse | ✅ passes (`yaml.safe_load`) |
| actionlint | ✅ passes (actionlint 1.7.x, exit 0) |
| Runtime execution | ⚠️ NOT performed — pipebridge does not execute workflows; validate by dispatching manually |
```

## Known limitations

- The supported subset is deliberately small; anything outside it is reported, never approximated.
- One workflow, one job, `workflow_dispatch` only. No push/PR triggers in the MVP.
- Groovy is supported only as far as literal string forms; any dynamic expression is a blocker.
- Credentials, parameters, triggers, conditions, approvals, and post actions are never migrated — they require human decisions.
- `echo` becomes `printf '%s\n'` to preserve semantics; output is identical but the command differs.
- The runner assumption (`ubuntu-latest`) is just that — an assumption. Jenkins `agent any` guarantees nothing about OS, tools, or network.
- `actionlint` runs only when installed locally; the report says so explicitly either way.
- Generated workflows are **never executed** by pipebridge; "passes validation" means YAML parsing and linting only.
- No confidence percentage: pipebridge reports facts, not vibes.

## Later phases (explicitly out of scope for this MVP)

AI-assisted migration advice, bulk repository scanning, Jenkins API integration, and automatic secret migration are future work. This increment is intentionally focused on a correct, honest core.

## Development

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Tests cover source positions and nested blocks, comments/braces inside strings, all string forms, shell variable preservation, environment scope, shared workspace across sequential stages, unknown syntax, unsupported enclosing blocks, GitHub expression injection through source literals, disabled output under blockers, CLI exit codes, and overwrite protection. `actionlint` (optional, validated when available) is exercised on generated workflows when present.

## License

MIT — see [LICENSE](LICENSE).
