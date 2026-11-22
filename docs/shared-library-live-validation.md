# Shared-library live GitHub Actions validation

Records the live `workflow_dispatch` validation of the shared-library migration milestone on `main`.

## Reference commit and post-merge CI

- **Branch / ref:** `main`
- **Commit SHA:** `f54d56e87b8ca8c94cf03aff25a6436e7444bf3a` (after PR #26 `7a2f067abf98e28bfcb57438344dc317668fcbfc`, PR #27 `522b0088ee0595b39b542ba2cb4a9ce810d73079`, and PR #28 `f54d56e87b8ca8c94cf03aff25a6436e7444bf3a`)
- **Post-merge CI:** [run `45067676101`](https://github.com/marcelodevops/pipebridge/actions/runs/45067676101) — `success`

## Success workflow (`shared-library-success-example.yml`)

- **Workflow:** `Shared-library success example (live validation)`
- **Run:** [run `45067732351`](https://github.com/marcelodevops/pipebridge/actions/runs/45067732351) — `success`
- **Job:** `migrated-pipeline` (`ubuntu-latest`)

| Step | Outcome | Notes |
| --- | --- | --- |
| `Checkout source (implicit)` | `success` | Pinned `actions/checkout` before generated scripts |
| `Publish` | `success` | Runs `packageSources-1.sh 'packaged'` |
| `Publish (step 2)` | `success` | Runs `call-1.sh` with step-scoped `NPM_TOKEN` from `secrets.NPM_TOKEN_GH` |
| `Publish (step 3)` | `success` | Runs `pipebridge_stash.py 'dist' 'dist/**'` |
| `Restore` | `success` | Runs `rm -rf dist` |
| `Restore (step 2)` | `success` | Runs `pipebridge_unstash.py 'dist'` |
| `Restore (step 3)` | `success` | Checks `dist/marker.txt`, `packaged`, and `dist/seen.txt` |
| `Verify restored file bytes` | `success` | Asserts `dist/marker.txt` is `b"packaged"` and `dist/seen.txt` is `b"ok"` |
| `Remove pipebridge stash` | `success` | `if: always()`, `continue-on-error: true` |
| `Verify pipebridge stash cleanup` | `success` | `if: always()`, confirms `$RUNNER_TEMP/pipebridge-stash` does not exist |

## Expected-failure workflow (`shared-library-failure-example.yml`)

- **Workflow:** `Shared-library failure example (live validation)`
- **Run:** [run `45067735656`](https://github.com/marcelodevops/pipebridge/actions/runs/45067735656) — `failure` (expected)
- **Job:** `migrated-pipeline` (`ubuntu-latest`)

| Step | Outcome | Notes |
| --- | --- | --- |
| `Checkout source (implicit)` | `success` | Pinned `actions/checkout` |
| `Fail` | `success` | Runs `call-1.sh` |
| `Fail (step 2)` | `failure` | Runs `call-2.sh` (`exit 1`) |
| `Fail (step 3)` | `skipped` | `pipebridge_stash.py` skipped after earlier failure |
| `Restore` | `skipped` | `pipebridge_unstash.py` skipped |
| `Restore (step 2)` | `skipped` | `echo restored` skipped |
| `Remove pipebridge stash` | `success` | `if: always()`, `continue-on-error: true` |
| `Verify pipebridge stash cleanup` | `success` | `if: always()`, confirms `$RUNNER_TEMP/pipebridge-stash` does not exist |

## Limits of this validation

- In the expected-failure run, the failure occurred at `Fail (step 2)`; `Fail (step 3)` (stash), `Restore`, and `Restore (step 2)` were skipped.
- Cleanup (`Remove pipebridge stash` and `Verify pipebridge stash cleanup`) executed after failure, but that run did not test removal of an existing stash after failure because the stash step was skipped.
- A synthetic repository secret (`NPM_TOKEN_GH`) was used for the success run; its value is never included in this record or in generated files.
- No comparison against live Jenkins execution was performed.
