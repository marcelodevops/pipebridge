# Release verification — pipebridge v0.2.1 (alpha)

**Scope:** verification of the *published* release artifacts, performed from
outside the repository after publication. This document does not modify the
release, the tag, or any asset; it only records evidence. The release was
tagged from a commit whose four CI checks passed; no claim of Jenkins runtime
equivalence is made.

- **Release:** <https://github.com/marcelodevops/pipebridge/releases/tag/v0.2.1>
  (prerelease, not latest stable)
- **Tag:** `v0.2.1` (annotated) at commit
  `242af4ac5ce284a2b5e819349ac3092927f0012a`; annotated tag object
  `00675d1d317660e5696400d6a64ca4e5fa370ce0`
- **Parent release-preparation PR:** <https://github.com/marcelodevops/pipebridge/pull/16>
  (merged; this follow-up PR is documentation only)
- **Release-candidate CI:** <https://github.com/marcelodevops/pipebridge/actions/runs/44439897813>
  — all four jobs passed on the exact tagged commit (`tests (python 3.10)`,
  `tests (python 3.13)`, `workflow lint and package smoke test`,
  `validate python-build example`)
- **Verification date:** 2026-11-19
- **Method:** artifacts downloaded from the published release into a fresh
  temporary directory; two fresh virtual environments (one per artifact);
  all CLI checks run from outside the checkout with `PYTHONPATH` unset;
  the Jetty-like fixture matches a clean checkout of the tagged commit.

## Result summary

| # | Check | Wheel install | Sdist install |
|---|-------|---------------|---------------|
| 1 | Downloaded asset SHA256 matches `SHA256SUMS` | ✅ OK | ✅ OK |
| 2 | `pipebridge --version` → `pipebridge 0.2.1` | ✅ | ✅ |
| 3 | `pipebridge.__file__` resolves inside the venv (not the checkout) | ✅ | ✅ |
| 4 | `convert` supported declarative input → exit 0 | ✅ | ✅ |
| 5 | Supported input: enabled workflow, no blockers | ✅ | ✅ |
| 6 | Blocked argument-validation repro → exit 2 | ✅ | ✅ |
| 7 | Argument repro: disabled draft (`if: false`) | ✅ | ✅ |
| 8 | Argument repro: interpolation reported (`PB-INTERP`) | ✅ | ✅ |
| 9 | Argument repro: unsupported checkout reported | ✅ | ✅ |
| 10 | Argument repro: later unsupported sibling reported | ✅ | ✅ |
| 11 | Argument repro: opaque `script` body not analyzed | ✅ | ✅ |
| 12 | Semicolon-recovery repro → exit 2 | ✅ | ✅ |
| 13 | Semicolon repro: disabled draft (`if: false`) | ✅ | ✅ |
| 14 | Semicolon repro: visible later sibling reported | ✅ | ✅ |
| 15 | Semicolon repro: dynamic `echo` reported | ✅ | ✅ |
| 16 | Semicolon repro: opaque `script` sibling left hidden | ✅ | ✅ |
| 17 | Jetty-like nested diagnostics → exit 2 | ✅ | ✅ |
| 18 | Jetty-like: disabled draft (`if: false`) | ✅ | ✅ |
| 19 | Jetty-like: translated stage remains `Parallel Stage`, blocked, no steps | ✅ | ✅ |
| 20 | Malformed two-`pipeline` input → exit 1 | ✅ | ✅ |
| 21 | Malformed input leaves no artifacts | ✅ | ✅ |

**Overall: PASS — no discrepancies found.** The wheel and the sdist each
passed **21/21** individual assertions.

## Environment

| Item | Value |
|------|-------|
| Host | macOS 26.6.2, `arm64` |
| Python (both venvs, from `python3 -m venv`) | 3.13.15 |
| pip (both venvs) | 26.2.1 |
| Work root | a fresh `mkdtemp` directory outside the repository |
| Fixtures | Jetty-like fixture from a clean checkout of the tagged commit, plus scratch supported/argument/semicolon/malformed inputs |
| actionlint (local) | 1.7.12 (used by the release-candidate CI and local example validation) |

## Step 1 — Download and checksum verification

```sh
BASE=$(mktemp -d)   # outside the checkout
gh release download v0.2.1 \
  --dir "$BASE/dl" \
  --pattern 'pipebridge-0.2.1-py3-none-any.whl' \
  --pattern 'pipebridge-0.2.1.tar.gz' \
  --pattern 'SHA256SUMS'
cd "$BASE/dl"
shasum -a 256 -c SHA256SUMS
```

Result: both artifacts **OK**. The attached `SHA256SUMS` is identical to the
file generated from the pre-publication build, and the GitHub asset digests
match the local hashes:

```
54df0eca28bd30e61c16e9d1a8e18d76336cee8f64c66b61eb5976b2a8943196  pipebridge-0.2.1-py3-none-any.whl
f5beb62307e80eee4317195c24e1d2e5b29c2b633fc145f4a2c62cb7bf2c647a  pipebridge-0.2.1.tar.gz
```

`SHA256SUMS` itself has SHA256
`4e392b198d95d228a2373716ea967bb13fd02c1f48a4b9580872609015a76003`.

## Step 2 — Fresh installations (one venv per artifact)

```sh
python3 -m venv "$BASE/venv-wheel"
env -u PYTHONPATH "$BASE/venv-wheel/bin/pip" install --quiet \
  "$BASE/dl/pipebridge-0.2.1-py3-none-any.whl"

python3 -m venv "$BASE/venv-sdist"
env -u PYTHONPATH "$BASE/venv-sdist/bin/pip" install --quiet \
  "$BASE/dl/pipebridge-0.2.1.tar.gz"
```

Both report `pipebridge 0.2.1` for `--version`. Import resolution:

```sh
env -u PYTHONPATH "$BASE/venv-wheel/bin/python" \
  -c "import pipebridge; print(pipebridge.__file__); print(pipebridge.__version__)"
```

- wheel venv → `…/venv-wheel/lib/python3.13/site-packages/pipebridge/__init__.py` `0.2.1`
- sdist venv → `…/venv-sdist/lib/python3.13/site-packages/pipebridge/__init__.py` `0.2.1`

Neither path contains a checkout directory.

## Step 3 — CLI smoke matrix (identical commands in both venvs)

Every command was invoked as `env -u PYTHONPATH <venv>/bin/pipebridge …`
from a working directory outside the checkout.

| Command | Exit code | Observed result |
|---------|-----------|-----------------|
| `pipebridge --version` | 0 | `pipebridge 0.2.1` |
| `pipebridge convert <supported> --output out-supported` | 0 | `workflow.yml` created; no `if: false`; zero blockers |
| `pipebridge convert <argument-repro> --output out-args` | 2 | `if: false`; interpolation, unsupported map-form checkout, and later `mavenBuild` reported; opaque `script` body not analyzed |
| `pipebridge convert <semicolon-repro> --output out-semicolon` | 2 | `if: false`; later `mavenBuild` and dynamic `echo` reported; `hiddenStep` inside the opaque `script` not reported |
| `pipebridge convert <jetty-like> --output out-jetty` | 2 | `if: false`; translated stage list is `[("Parallel Stage", blocked, no steps)]`; documented nested blocker positions present |
| `pipebridge convert <two-pipeline-input> --output out-ambiguous` | 1 | output directory absent/empty — **zero artifacts** |

The two-pipeline input was a scratch Jenkinsfile containing two top-level
`pipeline { }` blocks; pipebridge rejects the ambiguous input instead of
selecting one. This release does **not** translate the newly diagnosed
nested constructs; findings in blocked scopes remain a migration checklist.

## Step 4 — Published release state

- GitHub release `v0.2.1`: `draft: false`, `prerelease: true`, title
  `v0.2.1 — alpha`, published `2026-11-19T02:32:24Z`.
- Explicitly **not** latest stable; v0.2.0 remains published as a
  prerelease and v0.1.0 remains published.
- Annotated tag object: `00675d1d317660e5696400d6a64ca4e5fa370ce0`; it
  resolves to commit `242af4ac5ce284a2b5e819349ac3092927f0012a`.
- Assets attached: `pipebridge-0.2.1-py3-none-any.whl`,
  `pipebridge-0.2.1.tar.gz`, `SHA256SUMS`.
- **v0.1.0 and v0.2.0 untouched:** no tag, release, or asset was modified,
  replaced, or deleted. Both remain prereleases and neither is marked
  latest stable.
- pipebridge is **not** published to PyPI.

## Conclusion

The published v0.2.1 alpha assets are internally consistent and behave per
the release notes in fresh environments on Python 3.13.15 / macOS arm64:
version reporting, exit codes (0 / 2 / 1), disabled drafts, blocked-scope
argument validation, semicolon recovery, Jetty-like nested diagnostics,
opaque boundaries, and ambiguous-pipeline rejection all verified. No failed
verification occurred, and nothing was merged, altered, or republished as
part of this verification.
