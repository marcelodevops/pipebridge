# Migration report

- **Source:** `examples/python-build/Jenkinsfile` (sha256 `7c680aa3e5b21c16f444f95d4817d5877b163556ebb71c468e52c5403666a354`)
- **Tool:** pipebridge 0.2.0
- **Generated:** 2026-11-18T17:19:27Z
- **Result:** converted without blockers (review assumptions below)
- **Exit code:** 0

## Summary

| Severity | Count |
| --- | --- |
| blocker | 0 |
| warning | 0 |
| info | 6 |
| translated stages | 3 |
| translated steps | 4 |

## Translated items

| Stage | Step kind | Source line | Detail |
| --- | --- | --- | --- |
| Checkout | checkout | 7 | `checkout scm` |
| Test | sh | 12 | `PYTHONPATH=. python3 -m unittest discover -s tests -v` |
| Build | sh | 17 | `python3 -m pip install build` |
| Build | sh | 18 | `python3 -m build` |

## Blockers

None.

## Warnings

None.

## Assumptions

### PB-ASSUME-SHELL — shell execution environment (line 2, col 1)

- Steps run under 'bash --noprofile --norc -eo pipefail' on GitHub Actions; Jenkins 'sh' uses '/bin/sh -xe'. Shell differences (pipefail, tracing, tool availability) may change behavior.
- **Next action:** Review each command under 'set -eo pipefail' bash semantics.

### PB-SINGLE-JOB — sequential stages (line 2, col 1)

- All sequential stages are kept in a single GitHub Actions job so filesystem state (the Jenkins executor workspace) is preserved between stages.
- **Next action:** Split into multiple jobs only with explicit needs/ and artifact passing.

### PB-TRIGGER-MANUAL — workflow trigger (line 2, col 1)

- The generated workflow triggers on workflow_dispatch only.
- **Next action:** Add push/pull_request/schedule triggers deliberately after review.

### PB-ASSUME-RUNNER — agent any (line 3, col 5)

- 'agent any' does not establish the required OS, installed tools, or network access; the generated workflow assumes the 'ubuntu-latest' runner.
- **Next action:** Verify the runner image provides every tool the commands need.

### PB-ASSUME-CHECKOUT — default SCM checkout (implicit) (line 5, col 9)

- Jenkins checks out source from SCM before the first stage (default checkout). An implicit 'Checkout source (implicit)' step was inserted before the first translated step, in addition to any explicit 'checkout scm' steps (Jenkins performs both; checkouts are not deduplicated). This assumes the workflow runs in the migrated source repository.
- **Next action:** If the Jenkins job did not check out source (e.g. it only used artifacts), remove the implicit checkout step.

### PB-ASSUME-CHECKOUT — checkout scm (line 7, col 17)

- 'checkout scm' is translated to the pinned actions/checkout step; the workflow is assumed to run in the migrated source repository.
- **Next action:** Confirm the workflow's repository matches the Jenkins SCM.

## Validation

| Check | Result |
| --- | --- |
| YAML parse | ✅ passes (`yaml.safe_load`) |
| actionlint | ✅ passes (exit 0, 1.7.12) |
| Runtime execution | ⚠️ Not performed: pipebridge does not execute generated workflows. YAML parsing and actionlint are static checks only; validate at runtime by dispatching the workflow manually. |

> pipebridge reports what it verified and nothing more: YAML parsing and linting are static checks; runtime behavior was **not** validated.
