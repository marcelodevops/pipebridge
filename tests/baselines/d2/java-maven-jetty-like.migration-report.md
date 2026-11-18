# Migration report

- **Source:** `docs/compatibility-study/synthetic/java-maven-jetty-like.Jenkinsfile` (sha256 `3902a0f1a7c350ab63dc8145e8124e3fdaff2a3fc7d31655bab2995276615bb4`)
- **Tool:** pipebridge 0.2.0
- **Generated:** 2026-11-18T22:26:02Z
- **Result:** converted **with 6 blocker(s)** — the generated job is DISABLED (`if: false`)
- **Exit code:** 2

## Summary

| Severity | Count |
| --- | --- |
| blocker | 6 |
| warning | 0 |
| info | 3 |
| translated stages | 1 |
| translated steps | 0 |

## Translated items

| Stage | Step kind | Source line | Detail |
| --- | --- | --- | --- |
| Parallel Stage | — | 15 | **not migrated** (contains blockers; placeholder step fails loudly) |

## Blockers

### PB-AGENT — agent declaration (line 7, col 3)

- 'agent none' requires per-stage agents, which are not supported by the MVP.
- **Next action:** Choose the runner deliberately (runs-on) and document tool/network needs.

### PB-SYNTAX — options directive (line 8, col 3)

- The options directive is not supported by the MVP; it changes build behavior and was not migrated.
- **Next action:** Migrate the option deliberately (e.g. timeout via timeout-minutes).

### PB-POST — post section (line 42, col 3)

- Post actions are not supported by the MVP; their steps were not extracted.
- **Next action:** Translate post conditions to job-level steps with explicit conditions.

### PB-GROOVY-POSTLUDE — function definition after the pipeline block (line 55, col 1)

- This Groovy content after the pipeline block is executable; pipebridge does not evaluate or translate it, and calls to it from steps remain unsupported and are reported separately.
- **Next action:** Recreate the needed behavior deliberately in the workflow (a step or a repository script); do not assume this code runs after the migrated pipeline.

### PB-GROOVY-POSTLUDE — function definition after the pipeline block (line 63, col 1)

- This Groovy content after the pipeline block is executable; pipebridge does not evaluate or translate it, and calls to it from steps remain unsupported and are reported separately.
- **Next action:** Recreate the needed behavior deliberately in the workflow (a step or a repository script); do not assume this code runs after the migrated pipeline.

### PB-GROOVY-POSTLUDE — function definition after the pipeline block (line 67, col 1)

- This Groovy content after the pipeline block is executable; pipebridge does not evaluate or translate it, and calls to it from steps remain unsupported and are reported separately.
- **Next action:** Recreate the needed behavior deliberately in the workflow (a step or a repository script); do not assume this code runs after the migrated pipeline.

## Warnings

None.

## Assumptions

### PB-ASSUME-SHELL — shell execution environment (line 6, col 1)

- Steps run under 'bash --noprofile --norc -eo pipefail' on GitHub Actions; Jenkins 'sh' uses '/bin/sh -xe'. Shell differences (pipefail, tracing, tool availability) may change behavior.
- **Next action:** Review each command under 'set -eo pipefail' bash semantics.

### PB-SINGLE-JOB — sequential stages (line 6, col 1)

- All sequential stages are kept in a single GitHub Actions job so filesystem state (the Jenkins executor workspace) is preserved between stages.
- **Next action:** Split into multiple jobs only with explicit needs/ and artifact passing.

### PB-TRIGGER-MANUAL — workflow trigger (line 6, col 1)

- The generated workflow triggers on workflow_dispatch only.
- **Next action:** Add push/pull_request/schedule triggers deliberately after review.

## Validation

| Check | Result |
| --- | --- |
| YAML parse | ✅ passes (`yaml.safe_load`) |
| actionlint | ✅ passes (exit 0, 1.7.12) |
| Runtime execution | ⚠️ Not performed: pipebridge does not execute generated workflows. YAML parsing and actionlint are static checks only; validate at runtime by dispatching the workflow manually. |

> pipebridge reports what it verified and nothing more: YAML parsing and linting are static checks; runtime behavior was **not** validated.
