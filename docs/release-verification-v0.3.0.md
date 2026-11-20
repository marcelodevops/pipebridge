# Release verification — pipebridge v0.3.0 (alpha)

**Scope:** verification of the *published* release artifacts, performed from
outside the repository after publication. This document does not modify the
release, the tag, or any asset; it only records evidence. The release was
tagged from a commit whose four CI checks passed; no claim of Jenkins runtime
equivalence is made.

- **Release:** <https://github.com/marcelodevops/pipebridge/releases/tag/v0.3.0>
  (prerelease, not latest stable; `GET /releases/latest` returns 404)
- **Tag:** `v0.3.0` (annotated, SSH-signed) at commit
  `a13a0a00f9eff7e6505f6ade9fd0db40bbd7ca9c`; annotated tag object
  `f72046f9c93dbcda0be7821498a3ee8944bcf12f`
- **Parent release-preparation PR:** <https://github.com/marcelodevops/pipebridge/pull/20>
  (merged; this follow-up PR is documentation only)
- **Post-merge CI:** <https://github.com/marcelodevops/pipebridge/actions/runs/44659066648>
  — all four jobs passed on the exact tagged commit (`tests (python 3.10)`,
  `tests (python 3.13)`, `workflow lint and package smoke test`,
  `validate python-build example`). Both test jobs reported **335 passed**.
- **Verification date:** 2026-11-20
- **Method:** artifacts downloaded from the published release into a fresh
  temporary directory; two fresh virtual environments (one per artifact);
  all CLI checks run from outside the checkout with `PYTHONPATH` unset.

## Result summary

| # | Check | Wheel | Sdist |
|---|-------|-------|-------|
| 1 | Downloaded asset SHA-256 matches `SHA256SUMS` | OK | OK |
| 2 | `pipebridge --version` → `pipebridge 0.3.0` | OK | OK |
| 3 | `pipebridge.__file__` resolves inside the venv | OK | OK |
| 4 | single-quoted `nodejs` → exit 0 | OK | OK |
| 5 | `nodejs`: enabled workflow, no `if: false` | OK | OK |
| 6 | `nodejs`: `runs-on: [self-hosted, nodejs]` | OK | OK |
| 7 | `nodejs`: `PB-ASSUME-RUNNER-LABEL` present | OK | OK |
| 8 | `nodejs`: no `PB-AGENT` | OK | OK |
| 9 | `nodejs`: no `PB-ASSUME-RUNNER` | OK | OK |
| 10 | double-quoted `NodeJS` → exit 0, labeled `runs-on` | OK | OK |
| 11 | `NodeJS` `runs-on` parts remain strings | OK | OK |
| 12 | reserved `self-hosted` → exit 2, disabled, `ubuntu-latest`, `PB-AGENT`, no label assumption | OK | OK |
| 13 | reserved `SELF-HOSTED` same | OK | OK |
| 14 | reserved `Self-Hosted` same | OK | OK |
| 15 | reserved `sElF-hOsTeD` same | OK | OK |
| 16 | scalar-looking `true` stays a string on `runs-on` | OK | OK |
| 17 | scalar-looking `null` stays a string | OK | OK |
| 18 | scalar-looking `123` stays a string | OK | OK |
| 19 | scalar-looking `1.2` stays a string | OK | OK |
| 20 | escaped newline rejected (`PB-AGENT`, no label assumption) | OK | OK |
| 21 | escaped tab rejected | OK | OK |
| 22 | escaped carriage return rejected | OK | OK |
| 23 | `nodejs` plus escaped newline rejected | OK | OK |
| 24 | `agent none` not mapped | OK | OK |
| 25 | `docker` agent not mapped | OK | OK |
| 26 | `node` agent not mapped | OK | OK |
| 27 | `kubernetes` agent not mapped | OK | OK |
| 28 | stage-level label not mapped | OK | OK |
| 29 | label plus unrelated `script` stays exit 2, labeled, disabled, `PB-SCRIPT`, assumption kept, no `PB-AGENT` | OK | OK |
| 30 | malformed input (label, missing `stages`) → exit 1 and no artifacts | OK | OK |

**Overall: PASS — no discrepancies found.** The wheel and the sdist each
passed **30/30** individual assertions, including the checksum check.

## Environment

| Item | Value |
|------|-------|
| Host | macOS 26.6.2, `arm64` |
| Python (both venvs, from `python3 -m venv`) | 3.13.15 |
| pip (both venvs) | 26.2.1 |
| Work root | a fresh temporary directory outside the repository |
| `PYTHONPATH` | unset |

## Step 1 — Download and checksum verification

```sh
gh release download v0.3.0 \
  --dir "$BASE/dl" \
  --pattern 'pipebridge-0.3.0-py3-none-any.whl' \
  --pattern 'pipebridge-0.3.0.tar.gz' \
  --pattern 'SHA256SUMS'
cd "$BASE/dl"
shasum -a 256 -c SHA256SUMS
```

Result: both artifacts **OK**. Downloaded bytes match the files uploaded
from the clean archive of `a13a0a00f9eff7e6505f6ade9fd0db40bbd7ca9c`.
GitHub asset digests:

```
sha256:71ed6befb9a0dd7a16f58f00214347abd0c852e6526de243ee4b32dd1b7f9db8  pipebridge-0.3.0-py3-none-any.whl
sha256:2ea6cb3d22a37d46be1477dce15c9eb972931d88900e63f9786a492250d13db9  pipebridge-0.3.0.tar.gz
sha256:27f09efe017a17f9b355f29278c5a8fdc17375fc0a0b0de01806c3d151e4d97b  SHA256SUMS
```

Archive hashes differ from the earlier local preparation build only because
zip entry timestamps come from this commit. Extracted package file contents
match that preparation wheel.

## Prior releases

`v0.1.0`, `v0.2.0`, and `v0.2.1` tags and asset digests were unchanged
after this publication. No PyPI upload was made.
