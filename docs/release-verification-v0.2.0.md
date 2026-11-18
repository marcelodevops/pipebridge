# Release verification — pipebridge v0.2.0 (alpha)

**Scope:** verification of the *published* release artifacts, performed from
outside the repository after publication. This document does not modify the
release, the tag, or any asset; it only records evidence. The release was
tagged from a commit whose four CI checks passed; no claim of Jenkins runtime
equivalence is made.

- **Release:** <https://github.com/marcelodevops/pipebridge/releases/tag/v0.2.0>
  (prerelease, not latest stable)
- **Tag:** `v0.2.0` (annotated) at commit
  `b29f37d12619a5165d6b65c9d937679eb21a67a9`
- **Parent release-preparation PR:** <https://github.com/marcelodevops/pipebridge/pull/12>
  (merged; this follow-up PR is documentation only)
- **Release-candidate CI:** <https://github.com/marcelodevops/pipebridge/actions/runs/44363782136>
  — all four jobs passed on the exact tagged commit (`tests (python 3.10)`,
  `tests (python 3.13)`, `workflow lint and package smoke test`,
  `validate python-build example`)
- **Verification date:** 2026-11-18
- **Method:** artifacts downloaded from the published release into a fresh
  temporary directory; two fresh virtual environments (one per artifact);
  all CLI checks run from outside the checkout with `PYTHONPATH` unset;
  fixtures copied from a clean checkout of the tagged commit.

## Result summary

| # | Check | Wheel install | Sdist install |
|---|-------|---------------|---------------|
| 1 | Downloaded asset SHA256 matches `SHA256SUMS` | ✅ OK | ✅ OK |
| 2 | `pipebridge --version` → `pipebridge 0.2.0` | ✅ | ✅ |
| 3 | `pipebridge.__file__` resolves inside the venv (not the checkout) | ✅ | ✅ |
| 4 | `convert` supported declarative fixture → exit 0 | ✅ | ✅ |
| 5 | `convert` ordinary-imports fixture → exit 0, no blockers, 3 info imports | ✅ | ✅ |
| 6 | `convert` surrounding executable Groovy → exit 2, stages extracted, disabled draft, `PB-GROOVY-PRELUDE` | ✅ | ✅ |
| 7 | `convert` malformed import → exit 2, blocker, disabled draft, no info import | ✅ | ✅ |
| 8 | `convert` scripted input → exit 2, `PB-SCRIPT`, disabled draft | ✅ | ✅ |
| 9 | `convert` ambiguous/multiple pipelines → exit 1, no artifacts | ✅ | ✅ |

**Overall: PASS — no discrepancies found.** The wheel and the sdist each
passed **13/13** individual assertions (the grouped rows above expand to the
13 checks listed below).

## Environment

| Item | Value |
|------|-------|
| Host | macOS 26.6.2, `arm64` |
| Python (both venvs, from `python3 -m venv`) | 3.13.15 |
| pip (both venvs) | 26.2.1 |
| Work root | a fresh `mkdtemp` directory outside the repository |
| Fixtures | copied from a clean checkout of the tagged commit (`tests/fixtures`), plus a two-`pipeline` scratch input |
| actionlint (local) | 1.7.12 (used by the release-candidate CI and local example validation) |

## Step 1 — Download and checksum verification

```sh
BASE=$(mktemp -d)   # outside the checkout
gh release download v0.2.0 \
  --dir "$BASE/dl" \
  --pattern 'pipebridge-0.2.0-py3-none-any.whl' \
  --pattern 'pipebridge-0.2.0.tar.gz' \
  --pattern 'SHA256SUMS'
cd "$BASE/dl"
shasum -a 256 -c SHA256SUMS
```

Result: both artifacts **OK**. The attached `SHA256SUMS` is identical to the
file generated from the pre-publication build, and the GitHub asset digests
match the local hashes:

```
f63ed3d8e95e642fa5506c719a4e67679d4848b23a6849dbe75391e5c1316302  pipebridge-0.2.0-py3-none-any.whl
7afe24624d6389a43f433ce4abfd02b548e62d3a1f17c9e25677908cbf1fc2c3  pipebridge-0.2.0.tar.gz
```

`SHA256SUMS` itself has SHA256
`c6c8a5d5a04241dd4c14240fa854d06e91611a317d5083cafed20a8ffb570013`.

## Step 2 — Fresh installations (one venv per artifact)

```sh
python3 -m venv "$BASE/venv-wheel"
env -u PYTHONPATH "$BASE/venv-wheel/bin/pip" install --quiet \
  "$BASE/dl/pipebridge-0.2.0-py3-none-any.whl"

python3 -m venv "$BASE/venv-sdist"
env -u PYTHONPATH "$BASE/venv-sdist/bin/pip" install --quiet \
  "$BASE/dl/pipebridge-0.2.0.tar.gz"
```

Both report `pipebridge 0.2.0` for `--version`. Import resolution:

```sh
env -u PYTHONPATH "$BASE/venv-wheel/bin/python" \
  -c "import pipebridge; print(pipebridge.__file__); print(pipebridge.__version__)"
```

- wheel venv → `…/venv-wheel/lib/python3.13/site-packages/pipebridge/__init__.py` `0.2.0`
- sdist venv → `…/venv-sdist/lib/python3.13/site-packages/pipebridge/__init__.py` `0.2.0`

Neither path contains a checkout directory.

## Step 3 — CLI smoke matrix (identical commands in both venvs)

Every command was invoked as `env -u PYTHONPATH <venv>/bin/pipebridge …`
from a working directory outside the checkout.

| Command | Exit code | Observed result |
|---------|-----------|-----------------|
| `pipebridge --version` | 0 | `pipebridge 0.2.0` |
| `pipebridge convert <build-and-test> --output out-supported` | 0 | `workflow.yml`, `migration-report.md`, `migration-report.json` created |
| `pipebridge convert <prelude-imports-only> --output out-imports` | 0 | no `if: false`; exactly 3 `PB-GROOVY-IMPORT` info findings |
| `pipebridge convert <prelude-decl-literal> --output out-surrounding` | 2 | `if: false`; report lists stages `Build` and `Test`; blocker `PB-GROOVY-PRELUDE` |
| `pipebridge convert <malformed-import> --output out-badimport` | 2 | `if: false`; `PB-GROOVY-PRELUDE` blocker; **no** `PB-GROOVY-IMPORT` finding |
| `pipebridge convert <scripted-node> --output out-scripted` | 2 | `if: false`; `PB-SCRIPT` blocker |
| `pipebridge convert <two-pipeline-input> --output out-ambiguous` | 1 | output directory absent/empty — **zero artifacts** |

The two-pipeline input was a scratch Jenkinsfile containing two top-level
`pipeline { }` blocks; pipebridge rejects the ambiguous input instead of
selecting one.

## Step 4 — Published release state

- GitHub release `v0.2.0`: `draft: false`, `prerelease: true`, title
  `v0.2.0 — alpha`, published `2026-11-18T18:08:18Z`.
- Annotated tag object: `2c5643935f4aaed80457f922b684959255f1a201`; it
  resolves to commit `b29f37d12619a5165d6b65c9d937679eb21a67a9`.
- Assets attached: `pipebridge-0.2.0-py3-none-any.whl`,
  `pipebridge-0.2.0.tar.gz`, `SHA256SUMS`.
- **v0.1.0 untouched:** its release remains a prerelease with the same
  assets and hashes recorded at v0.1.0 publication
  (`490f50e…` wheel, `3f5990a…` sdist). This increment did not modify,
  replace, or delete any v0.1.0 tag, release, or asset.
- pipebridge is **not** published to PyPI.

## Conclusion

The published v0.2.0 alpha assets are internally consistent and behave per
the release notes in fresh environments on Python 3.13.15 / macOS arm64:
version reporting, exit codes (0 / 2 / 1), generated artifacts, import
resolution, malformed-import blocking, surrounding-Groovy structure
extraction with disabled drafts, scripted-pipeline blocking, and ambiguous
pipeline rejection all verified. No failed verification occurred, and
nothing was merged, altered, or republished as part of this verification.
