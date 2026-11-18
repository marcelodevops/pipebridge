# Migration report

- **Source:** `docs/compatibility-study/synthetic/python-gpu-kymatio-like.Jenkinsfile` (sha256 `fd5aac6cd0d4bd8c14ebc6804182d85e1f040b5056487459212a6304060bca58`)
- **Tool:** pipebridge 0.2.0
- **Generated:** 2026-11-18T22:26:02Z
- **Result:** converted **with 3 blocker(s)** — the generated job is DISABLED (`if: false`)
- **Exit code:** 2

## Summary

| Severity | Count |
| --- | --- |
| blocker | 3 |
| warning | 0 |
| info | 3 |
| translated stages | 1 |
| translated steps | 0 |

## Translated items

| Stage | Step kind | Source line | Detail |
| --- | --- | --- | --- |
| main | — | 16 | **not migrated** (contains blockers; placeholder step fails loudly) |

## Blockers

### PB-AGENT — agent declaration (line 9, col 3)

- 'agent none' requires per-stage agents, which are not supported by the MVP.
- **Next action:** Choose the runner deliberately (runs-on) and document tool/network needs.

### PB-SYNTAX — options directive (line 10, col 3)

- The options directive is not supported by the MVP; it changes build behavior and was not migrated.
- **Next action:** Migrate the option deliberately (e.g. timeout via timeout-minutes).

### PB-POST — post section (line 38, col 3)

- Post actions are not supported by the MVP; their steps were not extracted.
- **Next action:** Translate post conditions to job-level steps with explicit conditions.

## Warnings

None.

## Assumptions

### PB-ASSUME-SHELL — shell execution environment (line 8, col 1)

- Steps run under 'bash --noprofile --norc -eo pipefail' on GitHub Actions; Jenkins 'sh' uses '/bin/sh -xe'. Shell differences (pipefail, tracing, tool availability) may change behavior.
- **Next action:** Review each command under 'set -eo pipefail' bash semantics.

### PB-SINGLE-JOB — sequential stages (line 8, col 1)

- All sequential stages are kept in a single GitHub Actions job so filesystem state (the Jenkins executor workspace) is preserved between stages.
- **Next action:** Split into multiple jobs only with explicit needs/ and artifact passing.

### PB-TRIGGER-MANUAL — workflow trigger (line 8, col 1)

- The generated workflow triggers on workflow_dispatch only.
- **Next action:** Add push/pull_request/schedule triggers deliberately after review.

## Validation

| Check | Result |
| --- | --- |
| YAML parse | ✅ passes (`yaml.safe_load`) |
| actionlint | ✅ passes (exit 0, 1.7.12) |
| Runtime execution | ⚠️ Not performed: pipebridge does not execute generated workflows. YAML parsing and actionlint are static checks only; validate at runtime by dispatching the workflow manually. |

> pipebridge reports what it verified and nothing more: YAML parsing and linting are static checks; runtime behavior was **not** validated.
