# Migration report

- **Source:** `docs/compatibility-study/synthetic/node-minimal-do400-like.Jenkinsfile` (sha256 `75ab050b507b4861be0bb6209ffae057d4fd836b91e03fbf9eabc59171af1802`)
- **Tool:** pipebridge 0.2.0
- **Generated:** 2026-11-18T22:26:02Z
- **Result:** converted **with 1 blocker(s)** — the generated job is DISABLED (`if: false`)
- **Exit code:** 2

## Summary

| Severity | Count |
| --- | --- |
| blocker | 1 |
| warning | 0 |
| info | 3 |
| translated stages | 3 |
| translated steps | 0 |

## Translated items

| Stage | Step kind | Source line | Detail |
| --- | --- | --- | --- |
| Install dependencies | — | 11 | (no steps) |
| Check Style | — | 17 | (no steps) |
| Test | — | 23 | (no steps) |

## Blockers

### PB-AGENT — agent declaration (line 7, col 5)

- Custom agents (label, node, docker, dockerfile, kubernetes) are not supported by the MVP; the agent configuration was not analyzed.
- **Next action:** Choose the runner deliberately (runs-on) and document tool/network needs.

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
