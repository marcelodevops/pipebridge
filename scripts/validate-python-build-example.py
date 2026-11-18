#!/usr/bin/env python3
"""Repeatable validation of the python-build example.

Verifies, step by step (every step is a subprocess; any non-zero exit or
failed assertion makes this script exit non-zero and fails the check):

1. Run the example's unittest (the Jenkinsfile's Test command).
2. Build the example's wheel and source distribution from the example
   directory (into a separate work directory — never into pipebridge's
   own dist/).
3. Install the example's wheel into a fresh virtual environment and
   smoke-test ``greet()``.
4. Convert the example's Jenkinsfile with the installed pipebridge
   package; require exit 0 (no blockers).
5. Compare the regenerated workflow.yml BYTE-FOR-BYTE with the committed
   ``examples/python-build/migration/workflow.yml``.
6. Compare the live workflow (``.github/workflows/python-build-example.yml``)
   with the regenerated workflow structurally, except for the documented
   ``defaults.run.working-directory`` adjustment.
7. Validate the regenerated report's fields and the source hash against
   the actual Jenkinsfile — reports contain timestamps and environment
   details, so they are NOT compared byte-for-byte.

The commands run here are the example's own, trusted, explicitly
selected commands (the same ones the Jenkinsfile and the live workflow
run). This script is deliberately NOT a generic "execute whatever a
Jenkinsfile says" mechanism.
"""

from __future__ import annotations

import argparse
import atexit
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = REPO_ROOT / "examples" / "python-build"
COMMITTED_WORKFLOW = EXAMPLE / "migration" / "workflow.yml"
LIVE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "python-build-example.yml"


def run(step: str, cmd: list, *, cwd: Path | None = None, env: dict | None = None) -> None:
    """Run a subprocess; any failure stops everything with a non-zero exit."""
    cmd = [str(part) for part in cmd]
    print(f"==> {step}\n    $ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=cwd, env=env)
    if proc.returncode != 0:
        raise SystemExit(f"FAILED ({step}): exit code {proc.returncode}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pipebridge",
        default="pipebridge",
        help="pipebridge CLI used for conversion (default: 'pipebridge' on PATH)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="work directory for builds and venvs (default: a fresh temp dir)",
    )
    parser.add_argument("--keep", action="store_true", help="keep the work directory")
    args = parser.parse_args()

    pipebridge = shutil.which(args.pipebridge)
    require(pipebridge is not None, f"pipebridge CLI not found: {args.pipebridge!r}")
    print(f"pipebridge CLI: {pipebridge}")

    work = Path(tempfile.mkdtemp(prefix="pb-example-validation-"))
    print(f"work directory: {work}")
    if not args.keep:
        atexit.register(shutil.rmtree, work, ignore_errors=True)

    example_dist = work / "example-dist"
    jenkinsfile = EXAMPLE / "Jenkinsfile"

    # 1. Run the example's unittest: the Jenkinsfile's Test command.
    unittest_env = dict(os.environ, PYTHONPATH=".")
    run(
        "example unittest (Test command)",
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=EXAMPLE,
        env=unittest_env,
    )

    # 2. Build the example's wheel and source distribution. Artifacts go to
    #    the work directory, separate from pipebridge's own dist/.
    run(
        "build example wheel + sdist",
        [sys.executable, "-m", "build", "--outdir", example_dist, EXAMPLE],
    )
    wheels = list(example_dist.glob("greeter-*.whl"))
    sdists = list(example_dist.glob("greeter-*.tar.gz"))
    require(len(wheels) == 1, f"expected exactly one example wheel, got {wheels}")
    require(len(sdists) == 1, f"expected exactly one example sdist, got {sdists}")

    # 3. Install the example's wheel into a fresh environment and smoke-test
    #    greet() from the installed package (not from the source tree).
    example_venv = work / "venv-example"
    run("create fresh environment for the example wheel", [sys.executable, "-m", "venv", example_venv])
    run(
        "install the example wheel",
        [example_venv / "bin" / "python", "-m", "pip", "install", "--quiet", wheels[0]],
    )
    greet_probe = (
        "from greeter import greet\n"
        "got = greet('Smoke')\n"
        "assert got == 'Hello, Smoke', got\n"
        "print('greet() smoke test OK:', got)\n"
    )
    run(
        "smoke-test greet() from the installed wheel",
        [example_venv / "bin" / "python", "-c", greet_probe],
    )

    # 4. Convert the Jenkinsfile with the installed pipebridge package.
    #    Exit 0 means the conversion found no blockers.
    migration_out = work / "migration"
    run(
        "convert the example Jenkinsfile",
        [pipebridge, "convert", jenkinsfile, "--output", migration_out],
    )
    report = json.loads((migration_out / "migration-report.json").read_text())

    # 5. The regenerated workflow must be BYTE-FOR-BYTE identical to the
    #    committed generated example (generation is deterministic).
    regenerated = (migration_out / "workflow.yml").read_bytes()
    committed = COMMITTED_WORKFLOW.read_bytes()
    require(
        regenerated == committed,
        "regenerated workflow.yml differs from the committed "
        f"{COMMITTED_WORKFLOW.relative_to(REPO_ROOT)} — regenerate it with "
        "`pipebridge convert ... --force` and re-apply the live-workflow adjustment",
    )
    print("regenerated workflow.yml matches the committed one byte-for-byte")

    # 6. The live workflow must match the generated workflow structurally,
    #    except for the documented defaults.run.working-directory adjustment.
    live = yaml.safe_load(LIVE_WORKFLOW.read_text())
    generated = yaml.safe_load(regenerated)
    live_run_defaults = live.get("defaults", {}).get("run", {})
    require(
        live_run_defaults.pop("working-directory", None) == "examples/python-build",
        f"the live workflow must carry the documented working-directory "
        f"adjustment (defaults.run.working-directory: examples/python-build); "
        f"found: {live_run_defaults.get('working-directory')!r}",
    )
    require(
        live == generated,
        "the live workflow differs structurally from the generated workflow "
        "(beyond defaults.run.working-directory)",
    )
    print("live workflow matches the generated workflow structurally "
          "(except defaults.run.working-directory)")

    # 7. Validate report fields and the source hash. Reports carry a
    #    timestamp and environment details, so they are compared
    #    field-wise, never byte-for-byte.
    require(report["exit_code"] == 0, f"report exit_code is {report['exit_code']}, expected 0")
    require(report["summary"]["blockers"] == 0, "report records blockers, expected none")
    source_hash = hashlib.sha256(jenkinsfile.read_bytes()).hexdigest()
    require(
        report["source"]["sha256"] == source_hash,
        f"report source sha256 {report['source']['sha256']} does not match the "
        f"actual Jenkinsfile hash {source_hash}",
    )
    require(
        report["source"]["sha256"] == "7c680aa3e5b21c16f444f95d4817d5877b163556ebb71c468e52c5403666a354",
        "the example Jenkinsfile hash changed — regenerate the migration output "
        "deliberately (pipebridge convert ... --force) and update this expectation",
    )
    require("tool" in report and "version" in report["tool"], "report is missing tool version")
    require(isinstance(report["findings"], list), "report findings must be a list")
    print(
        f"report validated: exit_code=0, blockers=0, source sha256={source_hash[:12]}..., "
        f"tool={report['tool']['version']}"
    )

    print("\nALL EXAMPLE VALIDATION STEPS PASSED")


if __name__ == "__main__":
    main()
