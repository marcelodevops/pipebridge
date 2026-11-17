# python-build

Small Python example with a declarative Jenkinsfile: checkout, then test, then build.

The Jenkinsfile stays inside pipebridge's supported subset (`agent any`, `checkout scm`, literal `sh` steps).

## Test

From this directory:

```sh
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## Build

From this directory:

```sh
python3 -m pip install build
python3 -m build
```

The wheel is written to `dist/`. That directory is gitignored by the repository root.

## Migration output

`migration/` is the unmodified output of:

```sh
pipebridge convert examples/python-build/Jenkinsfile --output examples/python-build/migration
```

That directory holds `workflow.yml`, `migration-report.md`, and `migration-report.json`. Do not edit those files by hand. Regenerate them with `--force` when the Jenkinsfile changes, then re-apply the live-workflow adjustment below.

## Live workflow

GitHub Actions discovers workflows only in the repository root `.github/workflows/` directory. `migration/workflow.yml` is not a live workflow.

The live test is [`.github/workflows/python-build-example.yml`](../../.github/workflows/python-build-example.yml). It is the generated workflow with one adjustment: `defaults.run.working-directory` is `examples/python-build`.

Checkout steps still run at the repository root. They use `actions/checkout`, and `working-directory` does not apply to `uses` steps. The translated `sh` steps then run in this directory, which is what the Jenkinsfile assumes is the workspace root.

The trigger is `workflow_dispatch`, as pipebridge generated it. Dispatch **Migrated Jenkins pipeline** from the Actions tab and select the branch that contains this file. pipebridge does not add `push` or `pull_request` triggers; add those only deliberately.
