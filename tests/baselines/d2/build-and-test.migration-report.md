# Migration report

- **Source:** `tests/fixtures/build-and-test/Jenkinsfile` (sha256 `19e57b3aa19b16caa6817cce58b5947200fc2ffb3f8ba354809bae7975db0fec`)
- **Tool:** pipebridge 0.2.0
- **Generated:** 2026-11-18T22:26:02Z
- **Result:** converted without blockers (review assumptions below)
- **Exit code:** 0

## Summary

| Severity | Count |
| --- | --- |
| blocker | 0 |
| warning | 2 |
| info | 6 |
| translated stages | 4 |
| translated steps | 6 |

## Translated items

| Stage | Step kind | Source line | Detail |
| --- | --- | --- | --- |
| Checkout | checkout | 11 | `checkout scm` |
| Build | sh | 19 | `mkdir -p "$BUILD_DIR"` |
| Build | sh | 20 | `make build VERSION=$VERSION` |
| Build | echo | 21 | `Build finished` |
| Test | sh | 26 | ` ⏎ # braces { and comments # inside the string are shell data ⏎ expor...` |
| Report | sh | 36 | `echo "Build $BUILD_NUMBER completed"` |

## Blockers

None.

## Warnings

### PB-JENV — sh command (line 36, col 33)

- Jenkins-specific variable 'BUILD_NUMBER' is referenced in shell text.
- **Next action:** Map it to a GitHub Actions equivalent (e.g. github.run_number) or remove it, deliberately.

### PB-SHELLCHECK — generated workflow script (generated workflow)

- 35:9: shellcheck reported issue in this script: SC2086:info:1:20: Double quote to prevent globbing and word splitting
- **Next action:** The script text was preserved verbatim from the source; fix the quoting in the Jenkinsfile (or the generated workflow) deliberately.

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

### PB-ASSUME-CHECKOUT — default SCM checkout (implicit) (line 9, col 9)

- Jenkins checks out source from SCM before the first stage (default checkout). An implicit 'Checkout source (implicit)' step was inserted before the first translated step, in addition to any explicit 'checkout scm' steps (Jenkins performs both; checkouts are not deduplicated). This assumes the workflow runs in the migrated source repository.
- **Next action:** If the Jenkins job did not check out source (e.g. it only used artifacts), remove the implicit checkout step.

### PB-ASSUME-CHECKOUT — checkout scm (line 11, col 17)

- 'checkout scm' is translated to the pinned actions/checkout step; the workflow is assumed to run in the migrated source repository.
- **Next action:** Confirm the workflow's repository matches the Jenkins SCM.

## Validation

| Check | Result |
| --- | --- |
| YAML parse | ✅ passes (`yaml.safe_load`) |
| actionlint | ✅ passes (exit 0, 1.7.12) |
| Runtime execution | ⚠️ Not performed: pipebridge does not execute generated workflows. YAML parsing and actionlint are static checks only; validate at runtime by dispatching the workflow manually. |

> pipebridge reports what it verified and nothing more: YAML parsing and linting are static checks; runtime behavior was **not** validated.
