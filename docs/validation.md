# Validation evidence

This document records what has actually been verified about the
python-build example migration, with the exact runs and commits that
prove it, and how to reproduce it locally.

**Scope statement.** pipebridge's validation is *static*: YAML parsing,
workflow linting, and structural comparison of generated artifacts — plus
the live runs below, which are executions of the **migrated GitHub
Actions workflow**. We have executed the migrated workflow; we have
**not** compared it against a live Jenkins run. Nothing here claims
Jenkins-to-GitHub runtime equivalence.

## Live execution of the migrated workflow

The live workflow is `.github/workflows/python-build-example.yml` — the
unmodified pipebridge output for `examples/python-build/Jenkinsfile`,
with one documented adjustment (see below). It runs when dispatched via
`workflow_dispatch`.

### Successful run

- Run: <https://github.com/marcelodevops/pipebridge/actions/runs/44227121937>
- Commit: `537819b9071b0c836a0572b2125bf3d8ed02210c` (main at the time)
- Conclusion: **success**

What the logs actually demonstrate:

- Both checkout steps (`Checkout source (implicit)`, `Checkout`) ran and
  succeeded.
- The translated `Test` step ran the example's unittest:
  `test_greet_includes_name (test_greeter.GreeterTests.test_greet_includes_name) ... ok`,
  `Ran 1 test in 0.000s`, `OK`.
- The translated `Build` steps ran: `python3 -m pip install build`, then
  `python3 -m build`, both successfully.
- The job `migrated-pipeline` concluded **success**.

### Expected-failure run (failure propagation)

An evidence branch `test/expected-example-failure` changes **only** the
example unittest's expected greeting (deliberately wrong assertion); the
Jenkinsfile, the generated migration output, and the live workflow are
untouched.

- Branch: `test/expected-example-failure`
- Commit: `2079a4f7ac27ce72fd327eb2b3877886ec3371c8`
- Run: <https://github.com/marcelodevops/pipebridge/actions/runs/44239387591>
- Event: `workflow_dispatch`, conclusion: **failure**

What the logs actually demonstrate:

- Both checkout steps succeeded.
- The `Test` step **executed** the example unittest — the failure is the
  intentional assertion, not an infrastructure, import, or dependency
  error:
  `AssertionError: 'Hello, Ada' != 'Hello, World'`, `Ran 1 test in 0.001s`,
  `FAILED (failures=1)`, `Process completed with exit code 1`.
- The `Test` step concluded **failure**.
- Both `Build` steps were **skipped**.
- The job `migrated-pipeline` and the overall workflow concluded
  **failure**.

This branch is kept as evidence. It is intentionally failing: it must
not be merged, and no mergeable PR is opened from it.

## The working-directory adjustment

GitHub Actions discovers workflows only in the repository root
`.github/workflows/` directory, while the Jenkinsfile assumes its
checkout is the workspace root. The live workflow therefore carries a
single documented adjustment: `defaults.run.working-directory:
examples/python-build`, so the translated `sh` steps run in the example
directory. Checkout steps still run at the repository root (`uses`
steps ignore `working-directory`). No other behavior differs from the
generated workflow; the repeatable CI validation enforces exactly this
difference.

## Repeatable validation

CI runs `scripts/validate-python-build-example.py` as a dedicated
**validate python-build example** job (see `.github/workflows/ci.yml`).
It runs the example's own trusted commands as explicit subprocesses and
fails the check on any failure:

1. the example unittest (the Jenkinsfile's Test command),
2. build the example's wheel and sdist into a separate work directory,
3. install the example wheel into a fresh environment and smoke-test
   `greet()` from the installed package,
4. convert the Jenkinsfile with the installed pipebridge package
   (requires exit 0 — no blockers),
5. compare the regenerated `workflow.yml` **byte-for-byte** with the
   committed `examples/python-build/migration/workflow.yml`,
6. compare the live workflow with the generated workflow
   **structurally**, except the documented
   `defaults.run.working-directory` adjustment,
7. validate the report's fields and source hash **field-wise** — reports
   carry a generation timestamp and environment details, so they are
   deliberately not compared byte-for-byte.

### Local reproduction

```sh
git clone https://github.com/marcelodevops/pipebridge.git
cd pipebridge
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pip install build

# Full static example validation (all seven steps above):
python scripts/validate-python-build-example.py \
  --pipebridge "$(command -v pipebridge)"

# Dispatch the live workflow against a branch (requires gh authentication
# and write access):
gh workflow run python-build-example.yml --ref <branch>
gh run watch   # then inspect the run's step conclusions and logs
```

The reproduction commands for the two live runs above:

```sh
# successful run: main at 537819b
gh workflow run python-build-example.yml --ref main

# expected-failure run: evidence branch at 2079a4f
gh workflow run python-build-example.yml --ref test/expected-example-failure
```

## Static validation vs live execution

| Level | What it proves | Where |
| --- | --- | --- |
| YAML parse | the generated file is well-formed YAML | pipebridge reports, CI test suite |
| actionlint | the workflow passes static linting (incl. shellcheck notes on preserved scripts) | CI, local when installed |
| Structural comparison | the regenerated workflow is identical to the committed output, and the live workflow differs only in the documented working-directory adjustment | `scripts/validate-python-build-example.py` |
| Live execution | the **migrated GitHub Actions workflow** runs its translated steps to a successful conclusion on `ubuntu-latest` | the two dispatched runs above |

Live execution of the migrated workflow does **not** prove equivalence
with the original Jenkins pipeline on Jenkins infrastructure: no Jenkins
controller/agent was involved, and Jenkins-specific behavior (SCM
checkout semantics, `agent any` tooling, workspace reuse across builds)
was migrated as documented assumptions (see the `PB-ASSUME-*` findings
in the migration reports).
