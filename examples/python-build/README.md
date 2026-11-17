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
