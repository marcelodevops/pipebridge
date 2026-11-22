# Migration report

- **Source:** `examples/shared-library/failure/Jenkinsfile` (sha256 `0a04f3dd51aca3fef26c9b7622f374481ec71dd1f416f8b6dd00ebdeac3ccf99`)
- **Tool:** pipebridge 0.4.0
- **Generated:** 2026-11-22T20:29:03Z
- **Result:** converted without blockers (review assumptions below)
- **Exit code:** 0

## Summary

| Severity | Count |
| --- | --- |
| blocker | 0 |
| warning | 0 |
| info | 6 |
| translated stages | 2 |
| translated steps | 5 |

## Translated items

| Stage | Step kind | Source line | Detail |
| --- | --- | --- | --- |
| Fail | sh | 2 | `printf %s before > marker.txt` |
| Fail | sh | 3 | `exit 1` |
| Fail | stash | 4 | `dist` |
| Restore | unstash | 12 | `dist` |
| Restore | sh | 13 | `echo restored` |

## Libraries

Local library directories were used for static analysis only; pipebridge did not fetch repositories or execute Groovy.

| Library | Local path | Revision (unverified) | Discovered vars | Reached vars |
| --- | --- | --- | --- | --- |
| `build-lib` | `build-lib` | — | `publish` | `publish` |

| Call | Status | Source | Call chain |
| --- | --- | --- | --- |
| `publish` | resolved | `examples/shared-library/failure/Jenkinsfile:7:17` | `examples/shared-library/failure/Jenkinsfile:publish@7:17` |

## Blockers

None.

## Warnings

None.

## Assumptions

### PB-ASSUME-LIBRARY — shared library annotation (line 1, col 1)

- Local directory 'build-lib' was used as library 'build-lib'. Jenkins library resolution was not run.
- **Next action:** Verify the local directory matches the intended Jenkins library.

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

## Validation

| Check | Result |
| --- | --- |
| YAML parse | ✅ passes (`yaml.safe_load`) |
| actionlint | ✅ passes (exit 0, 1.7.12) |
| Runtime execution | ⚠️ Not performed: pipebridge does not execute generated workflows. YAML parsing and actionlint are static checks only; validate at runtime by dispatching the workflow manually. |

> pipebridge reports what it verified and nothing more: YAML parsing and linting are static checks; runtime behavior was **not** validated.
