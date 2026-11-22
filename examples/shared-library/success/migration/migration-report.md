# Migration report

- **Source:** `examples/shared-library/success/Jenkinsfile` (sha256 `623adc9f56a9df89076ea261ace58d088ed3fcdeb2c04795bdd097a6328dc85a`)
- **Tool:** pipebridge 0.5.0
- **Generated:** 2026-11-22T21:06:46Z
- **Result:** converted without blockers (review assumptions below)
- **Exit code:** 0

## Summary

| Severity | Count |
| --- | --- |
| blocker | 0 |
| warning | 0 |
| info | 7 |
| translated stages | 2 |
| translated steps | 6 |

## Translated items

| Stage | Step kind | Source line | Detail |
| --- | --- | --- | --- |
| Publish | sh | 10 | `mkdir -p dist && printf %s "${1}" > dist/marker.txt` |
| Publish | sh | 4 | `test -n "$NPM_TOKEN" && printf %s ok > dist/seen.txt` |
| Publish | stash | 6 | `dist` |
| Restore | sh | 12 | `rm -rf dist` |
| Restore | unstash | 13 | `dist` |
| Restore | sh | 14 | `test -f dist/marker.txt && grep -qx packaged dist/marker.txt && test ...` |

## Required GitHub Actions secrets

pipebridge never reads, prints, embeds, or invents secret values. It only knows the secret names supplied in the mapping file.

| Credential ID | Bound variable | GitHub secret | Status | Reason |
| --- | --- | --- | --- | --- |
| `npm-token` | `NPM_TOKEN` | `NPM_TOKEN_GH` | resolved | — |

### Create each secret

GitHub UI:

1. Open the target repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Select **New repository secret**.
4. Enter the name **exactly** as shown above.
5. Enter the value yourself. pipebridge never sees, prints, or stores it.
6. Select **Add secret**.

`gh` CLI, from a clone of the target repository with `gh auth login` already completed:

```sh
gh secret set NPM_TOKEN_GH
# gh prompts for the value; do not pass the value on the command line.
```

Outside the clone, add `--repo <owner>/<repo>` yourself. pipebridge does not guess or invent the repository.

After every secret above exists, re-run the same conversion with the same `--credential-map` plus `--secrets-ready`. That flag is an acknowledgement, not a verification: pipebridge still does not read or test the secret.

## Libraries

Local library directories were used for static analysis only; pipebridge did not fetch repositories or execute Groovy.

| Library | Local path | Revision (unverified) | Discovered vars | Reached vars |
| --- | --- | --- | --- | --- |
| `build-lib` | `build-lib` | — | `publish` | `publish` |

| Call | Status | Source | Call chain |
| --- | --- | --- | --- |
| `publish` | resolved | `examples/shared-library/success/Jenkinsfile:7:17` | `examples/shared-library/success/Jenkinsfile:publish@7:17` |

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

### PB-ASSUME-CREDENTIALS — credential setup acknowledgement (/Users/mac/ops/repos/pipebridge/.worktrees/release-v0.5.0-alpha/examples/shared-library/success/build-lib/vars/publish.groovy, line 3, col 5)

- The user acknowledged that every secret named in the credential checklist exists in the target repository. pipebridge did not verify that and never reads secret values.
- **Call chain:** `examples/shared-library/success/Jenkinsfile:publish@7:17`
- **Next action:** Confirm each secret name matches the checklist exactly before enabling the workflow.

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
