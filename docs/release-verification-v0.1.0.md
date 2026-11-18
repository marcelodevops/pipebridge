# Independent release verification — pipebridge v0.1.0 (alpha)

**Scope:** verification of the *published* release artifacts, performed from
outside this repository, after the release was published. This document does
not modify the release, the tag, or any asset; it only records evidence.

- **Release:** <https://github.com/marcelodevops/pipebridge/releases/tag/v0.1.0>
  (prerelease, not latest stable)
- **Tag:** `v0.1.0` (annotated) at commit `e97b8a0a6e4f9a14d74d527d03b35c811ba7f88b`
- **Verification date:** 2026-11-18
- **Method:** fresh temporary directory, fresh clone of the repository, two
  fresh virtual environments (one per artifact type), all CLI checks run from
  outside the checkout with `PYTHONPATH` unset, fixtures taken from the exact
  release-tag commit.

## Result summary

| # | Check | Wheel install | Sdist install |
|---|-------|---------------|---------------|
| 1 | SHA256 hashes match `SHA256SUMS` | ✅ OK | ✅ OK (same files) |
| 2 | `pipebridge --version` → `pipebridge 0.1.0` | ✅ | ✅ |
| 3 | `analyze` (supported fixture) → exit 0 | ✅ | ✅ |
| 4 | `convert` (supported fixture) → exit 0, all 3 outputs | ✅ | ✅ |
| 5 | `convert` (unsupported fixture) → exit 2, job disabled (`if: false`) | ✅ | ✅ |
| 6 | `convert` (malformed input) → exit 1, no output artifacts | ✅ | ✅ |
| 7 | Re-convert without `--force` → exit 1 "refusing to overwrite", outputs byte-identical | ✅ | ✅ |
| 8 | Re-convert with `--force` → exit 0 | ✅ | ✅ |
| 9 | `pipebridge.__file__` resolves inside the venv (not the checkout) | ✅ | ✅ |
| 10 | actionlint distinction: absent → `available=false, ok=null` ("skipped"); present → `available=true, ok=true` | ✅ | ✅ (sdist run shown) |

**Overall: PASS — no discrepancies found.** All published artifacts behave
exactly as the release notes and the CLI contract describe.

## Environment

| Item | Value |
|------|-------|
| Host | macOS 26.6.2 (BuildVersion 25G83), `arm64` |
| Python (both venvs, from `python3 -m venv`) | 3.13.15 (`macOS-26.6.2-arm64-arm-64bit-Mach-O`) |
| pip (sdist venv) | 26.2.1 |
| Work root (fresh, outside the repo) | a new `mkdtemp` directory; the earlier publishing-run directories were **not** reused |
| Clone | fresh `git clone`, then `git checkout v0.1.0` → `e97b8a0a6e4f9a14d74d527d03b35c811ba7f88b` |
| Fixtures | extracted with `git archive v0.1.0 tests/fixtures` (provenance: the release tag itself) |
| actionlint (when present) | 1.7.12 at `/opt/homebrew/bin/actionlint` |

## Step 1 — Download and hash verification

```sh
BASE_URL=https://github.com/marcelodevops/pipebridge/releases/download/v0.1.0
curl -sSL -O "$BASE_URL/pipebridge-0.1.0-py3-none-any.whl" \
            -O "$BASE_URL/pipebridge-0.1.0.tar.gz" \
            -O "$BASE_URL/SHA256SUMS"
shasum -a 256 -c SHA256SUMS
```

`SHA256SUMS` (as downloaded from the release):

```
490f50e1285941cd221758c2aa19f27d6b687e82d1da58f10e6a71dce00d04cf  pipebridge-0.1.0-py3-none-any.whl
3f5990a817884cd67e49b74d36a7d4103120ad1a391b5ec3f903d5b824666048  pipebridge-0.1.0.tar.gz
```

Result: both files **OK** — the downloaded artifacts match the published
checksums. (Verification stops on any mismatch; no mismatch occurred.)

## Step 2/4 — Installations (two independent fresh venvs)

```sh
python3 -m venv "$BASE/venv-wheel" && "$BASE/venv-wheel/bin/pip" install "$BASE/dl/pipebridge-0.1.0-py3-none-any.whl"
python3 -m venv "$BASE/venv-sdist" && "$BASE/venv-sdist/bin/pip" install "$BASE/dl/pipebridge-0.1.0.tar.gz"
```

Both report `pipebridge 0.1.0` for `--version` (see below).

## Step 3 — CLI checks (wheel venv; identical commands for the sdist venv)

Run from a scratch working directory **outside the checkout**, every command
invoked as `env -u PYTHONPATH <venv>/bin/pipebridge …`; fixtures come from
`git archive v0.1.0 tests/fixtures`:

| Command | Exit code | Observed result |
|---------|-----------|-----------------|
| `pipebridge --version` | 0 | `pipebridge 0.1.0` |
| `pipebridge analyze tests/fixtures/build-and-test/Jenkinsfile` | 0 | analysis report printed |
| `pipebridge convert tests/fixtures/build-and-test/Jenkinsfile --output out-supported` | 0 | `workflow.yml`, `migration-report.md`, `migration-report.json` all created |
| `pipebridge convert tests/fixtures/container-credentials/Jenkinsfile --output out-unsupported` | 2 | generated job disabled: parsed YAML shows `jobs.migrated-pipeline.if` is `False` |
| `pipebridge convert malformed.input --output out-malformed` (input `pipeline {\n    agent any\n}`) | 1 | output directory contains **zero** artifacts |
| re-convert into `out-supported` (no `--force`) | 1 | `pipebridge: error: refusing to overwrite existing file(s): … Use --force to replace them.`; SHA256 of all three outputs identical before/after |
| re-convert into `out-supported --force` | 0 | outputs replaced |

The same matrix was repeated verbatim in the sdist venv with identical
results (see the summary table).

## Step 5 — Import resolution (installed environment, not the checkout)

```sh
env -u PYTHONPATH <venv>/bin/python -c "import pipebridge; print(pipebridge.__file__, pipebridge.__version__)"
```

- wheel venv → `…/venv-wheel/lib/python3.13/site-packages/pipebridge/__init__.py` `0.1.0`
- sdist venv → `…/venv-sdist/lib/python3.13/site-packages/pipebridge/__init__.py` `0.1.0`

Neither path contains the clone/checkout directory — imports resolve to the
installed environments.

## Step 6 — actionlint: missing-optional vs. successful lint

The same supported-fixture convert was run twice in the sdist venv:

1. **actionlint removed from `PATH`** (`env PATH=/usr/bin:/bin`):
   convert exit 0, and `migration-report.json` contains
   `"actionlint": {"available": false, "ok": null, "exit_code": null,
   "output": "actionlint is not installed; workflow linting was skipped."}` —
   linting is an optional check; absence is reported, never faked as success.
2. **actionlint 1.7.12 on `PATH`**:
   convert exit 0, `"actionlint": {"available": true, "ok": true}` (with
   shellcheck info notes for the generated script in the output field).

## Conclusion

The published v0.1.0 alpha artifacts (wheel, sdist, `SHA256SUMS`) are
internally consistent and behave per specification in fresh environments on
Python 3.13.15 / macOS arm64: version reporting, exit codes (0 / 2 / 1),
generated artifacts, overwrite protection, import resolution, and the
optional-actionlint distinction all verified. No defect to report; nothing
was merged, altered, or published as part of this verification.
