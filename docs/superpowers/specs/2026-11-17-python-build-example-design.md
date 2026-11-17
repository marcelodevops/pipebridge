# Python build example

## Purpose

Add a small Python project at `examples/python-build/` whose declarative Jenkinsfile is a clean pipebridge input. `pipebridge convert` of that file must exit 0 (no migration blockers).

## Scope

In scope:

- A flat, stdlib-only module and one unittest.
- Packaging metadata so `python3 -m build` can produce a wheel.
- A declarative Jenkinsfile with stages in this order: Checkout, Test, Build.
- A short README with the local test and build commands.

Out of scope:

- pytest, a `src/` layout, runtime dependencies, or a fake `compileall` build.
- Jenkins constructs outside pipebridge's supported subset (`post`, `when`, credentials, interpolation, parameters, triggers, parallel, custom agents).
- A local `.gitignore`. The repository already ignores `dist/`, `build/`, and `__pycache__/`.
- Changing pipebridge itself, or generating the GitHub Actions workflow as a committed artifact.

## Layout

```
examples/python-build/
  Jenkinsfile
  README.md
  pyproject.toml
  greeter.py
  tests/test_greeter.py
```

## Behavior

`greeter.greet(name)` returns `Hello, {name}`. No extra validation or error handling.

`tests/test_greeter.py` is one `unittest` case: `greet("Ada")` equals `Hello, Ada`.

`pyproject.toml` uses setuptools, `py-modules = ["greeter"]`, `requires-python = ">=3.10"`, version `0.1.0`, and no runtime dependencies.

## Jenkinsfile

Supported subset only:

- One `pipeline` block, `agent any`.
- `stage('Checkout')` runs `checkout scm`.
- `stage('Test')` runs `sh 'PYTHONPATH=. python3 -m unittest discover -s tests -v'`. Tests run before the wheel exists, so the module is imported from the workspace, not from an install.
- `stage('Build')` runs `sh 'python3 -m pip install build'` and then `sh 'python3 -m build'`.
- Every `sh` argument is a single-quoted literal. No Groovy interpolation, no Jenkins environment variables, no `post` / `when` / credentials.

Info-level assumptions (`PB-ASSUME-RUNNER`, `PB-ASSUME-CHECKOUT`, and the usual trigger/shell notes) are expected. They are not blockers.

## Success criteria

- From `examples/python-build/`, `PYTHONPATH=. python3 -m unittest discover -s tests -v` passes.
- `pipebridge convert examples/python-build/Jenkinsfile --output <temp dir>` exits 0.
