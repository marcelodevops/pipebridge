# Python Build Example Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small stdlib Python project at `examples/python-build/` whose declarative Jenkinsfile converts with `pipebridge convert` exit code 0.

**Architecture:** A flat module `greeter.py` is imported by one unittest via `PYTHONPATH=.` before any wheel exists. `pyproject.toml` makes that same module buildable with `python3 -m build`. The Jenkinsfile only uses pipebridge's supported declarative subset and runs checkout, then that test command, then that build command.

**Tech Stack:** Python 3.10+, unittest (stdlib), setuptools, `python3 -m build`, declarative Jenkins pipeline, pipebridge 0.1.0.

**Spec:** `docs/superpowers/specs/2026-11-17-python-build-example-design.md`

## Global Constraints

- All new files live under `examples/python-build/`.
- `greeter.greet(name)` returns `Hello, {name}`. No extra validation or error handling.
- One unittest: `greet("Ada")` equals `Hello, Ada`.
- `pyproject.toml` uses setuptools, `py-modules = ["greeter"]`, `requires-python = ">=3.10"`, version `0.1.0`, and no runtime dependencies.
- Jenkinsfile stages, in order: Checkout (`checkout scm`), Test (`sh 'PYTHONPATH=. python3 -m unittest discover -s tests -v'`), Build (`sh 'python3 -m pip install build'` then `sh 'python3 -m build'`).
- One `pipeline` block, `agent any`. Every `sh` argument is a single-quoted literal. No Groovy interpolation, no Jenkins environment variables, no `post` / `when` / credentials.
- Info-level assumptions (`PB-ASSUME-RUNNER`, `PB-ASSUME-CHECKOUT`, and the usual trigger/shell notes) are expected. They are not blockers.
- Do not add a local `.gitignore`. Do not change pipebridge itself. Do not commit generated workflow or migration-report files, `dist/`, or `*.egg-info/`.
- Do not add a Co-authored-by trailer to commit messages.

---

### Task 1: Greeter module

**Files:**
- Create: `examples/python-build/tests/test_greeter.py`
- Create: `examples/python-build/greeter.py`
- Test: `examples/python-build/tests/test_greeter.py`

**Interfaces:**
- Consumes: nothing
- Produces: `greet(name: str) -> str` in module `greeter`, returning `Hello, {name}`

- [ ] **Step 1: Write the failing test**

Create `examples/python-build/tests/test_greeter.py`:

```python
import unittest

from greeter import greet


class GreeterTests(unittest.TestCase):
    def test_greet_includes_name(self):
        self.assertEqual(greet("Ada"), "Hello, Ada")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run from the repository root:

```bash
cd examples/python-build && PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'greeter'`.

- [ ] **Step 3: Write the minimal implementation**

Create `examples/python-build/greeter.py`:

```python
def greet(name: str) -> str:
    return f"Hello, {name}"
```

- [ ] **Step 4: Run the test to verify it passes**

Run from the repository root:

```bash
cd examples/python-build && PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Expected: `test_greet_includes_name ... ok` and `OK`.

- [ ] **Step 5: Commit**

```bash
git add examples/python-build/greeter.py examples/python-build/tests/test_greeter.py
git commit -m "feat: add greeter example module"
```

### Task 2: Package metadata

**Files:**
- Create: `examples/python-build/pyproject.toml`

**Interfaces:**
- Consumes: module `greeter` from Task 1 (`greet(name: str) -> str`)
- Produces: a setuptools project named `greeter` version `0.1.0` that `python3 -m build` can wheel

- [ ] **Step 1: Write the package metadata**

Create `examples/python-build/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "greeter"
version = "0.1.0"
description = "Small example Python project for a declarative Jenkins pipeline."
requires-python = ">=3.10"

[tool.setuptools]
py-modules = ["greeter"]
```

- [ ] **Step 2: Build a wheel to verify the metadata**

Run from the repository root. This is the same build the Jenkinsfile will run. It needs network access to install `build` if it is not already installed.

```bash
cd examples/python-build && python3 -m pip install build && python3 -m build
```

Expected: the command exits 0 and creates `examples/python-build/dist/greeter-0.1.0-py3-none-any.whl`.

- [ ] **Step 3: Confirm the unittest still passes without installing the wheel**

```bash
cd examples/python-build && PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Expected: `OK`. Do not `pip install` the wheel; tests must keep importing the workspace module.

- [ ] **Step 4: Commit**

Do not add `dist/` or `*.egg-info/`.

```bash
git add examples/python-build/pyproject.toml
git commit -m "build: add greeter example package metadata"
```

### Task 3: Declarative Jenkinsfile

**Files:**
- Create: `examples/python-build/Jenkinsfile`

**Interfaces:**
- Consumes: the Task 1 test command and the Task 2 build commands
- Produces: a declarative pipeline whose stages are Checkout, Test, Build, in that order

- [ ] **Step 1: Write the Jenkinsfile**

Create `examples/python-build/Jenkinsfile`:

```groovy
// python-build: declarative checkout, test, then build. Supported subset only.
pipeline {
    agent any
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Test') {
            steps {
                sh 'PYTHONPATH=. python3 -m unittest discover -s tests -v'
            }
        }
        stage('Build') {
            steps {
                sh 'python3 -m pip install build'
                sh 'python3 -m build'
            }
        }
    }
}
```

- [ ] **Step 2: Convert it and verify there are no blockers**

Run from the repository root. Use a fresh output directory. pipebridge refuses to overwrite an existing output directory.

```bash
OUT="$(mktemp -d)"
.venv/bin/pipebridge convert examples/python-build/Jenkinsfile --output "$OUT"
echo "exit=$?"
.venv/bin/python -c "
import json, sys
report = json.load(open(sys.argv[1]))
assert report['exit_code'] == 0, report['exit_code']
assert report['blockers'] == [], report['blockers']
print('blockers', len(report['blockers']))
" "$OUT/migration-report.json"
```

Expected: the convert command prints `exit code 0`, `echo` prints `exit=0`, and the Python check prints `blockers 0`. The output directory must contain `workflow.yml`, `migration-report.md`, and `migration-report.json`.

Info findings such as `PB-ASSUME-RUNNER` and `PB-ASSUME-CHECKOUT` may be present. Do not treat them as failure.

- [ ] **Step 3: Commit**

Do not add the temporary conversion directory.

```bash
git add examples/python-build/Jenkinsfile
git commit -m "ci: add python-build declarative Jenkinsfile"
```

### Task 4: README

**Files:**
- Create: `examples/python-build/README.md`

**Interfaces:**
- Consumes: the test command from Task 1 and the build commands from Task 2
- Produces: local instructions that match those commands exactly

- [ ] **Step 1: Write the README**

Create `examples/python-build/README.md` with exactly this content:

````markdown
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
````

- [ ] **Step 2: Check the README contains the exact commands**

Run from the repository root:

```bash
grep -F "PYTHONPATH=. python3 -m unittest discover -s tests -v" examples/python-build/README.md
grep -F "python3 -m pip install build" examples/python-build/README.md
grep -F "python3 -m build" examples/python-build/README.md
```

Expected: each command prints one matching line and exits 0.

- [ ] **Step 3: Commit**

```bash
git add examples/python-build/README.md
git commit -m "docs: document python-build example commands"
```
