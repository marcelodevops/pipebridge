# Release notes — pipebridge v0.2.0 (ALPHA)

> **Status: published alpha prerelease, 2026-11-18.** Published at
> <https://github.com/marcelodevops/pipebridge/releases/tag/v0.2.0>
> (annotated tag `v0.2.0` at commit
> `b29f37d12619a5165d6b65c9d937679eb21a67a9`), marked **alpha
> (pre-release)** and deliberately **not** latest stable. The wheel,
> source distribution, and `SHA256SUMS` are attached to the release.
> pipebridge is **not** published to PyPI. Independent verification of the
> published assets is recorded in
> [`docs/release-verification-v0.2.0.md`](release-verification-v0.2.0.md).

## What v0.2.0 is

A **bounded analysis improvement**, not broader conversion support.

v0.2.0 recognizes a declarative `pipeline { }` block when it is wrapped in
ordinary Groovy, so the structure inside the block can be extracted and
reported. This addresses defect **D1** from the v0.1.0 compatibility study
(see `docs/compatibility-study.md` §7): imports or declarations before the
block used to classify the whole file as `PB-SCRIPT` with an empty stage
list, and trailing helper functions used to truncate the analysis.

**Nothing about the supported translation subset changed.** No surrounding
Groovy is evaluated or translated. Every surrounding executable form is a
blocker, so the generated job stays disabled (`if: false`, exit 2). There
is no broader conversion claim and no Jenkins-to-GitHub runtime
equivalence claim; generated workflows are not executed by pipebridge.

## What changed in the analysis

| Surrounding form | Finding | Effect |
| --- | --- | --- |
| Ordinary import: `import [static] a.b.Class`, optionally ending `.*` | `PB-GROOVY-IMPORT` (info) | Pipeline block analyzed; imports are never evaluated; references to imported symbols in steps keep their existing blockers |
| Any other import form (punctuation, misplaced wildcard, alias, repeated/missing segments, keyword/numeric segment) | `PB-GROOVY-PRELUDE` (blocker) | Structure still extracted; draft disabled |
| Variable declaration before the block (`def`/`String`/…, any initializer) | `PB-GROOVY-PRELUDE` (blocker) | Initializers are never judged harmless and their values are never carried over |
| Annotation other than `@Library` before the block | `PB-GROOVY-PRELUDE` (blocker) | `@Library` keeps its existing `PB-LIB` classification |
| Helper function definitions or other statements after the block | `PB-GROOVY-POSTLUDE` (blocker) | Skipped without evaluation; structure still extracted |
| Genuinely scripted file | `PB-SCRIPT` (blocker) | Unchanged classification; no structure claimed |
| Multiple or ambiguous `pipeline` occurrences | malformed input | Exit 1, no artifacts; one pipeline is never selected silently |

For the five affected synthetic fixtures, every top-level stage is now
listed in the disabled draft. The two pure-declarative golden outputs are
unchanged apart from the tool-version header line.

## Deferred: D2 remains a known limitation

**D2 is not fixed in v0.2.0.** When a pipeline-level blocker exists,
nested constructs inside the pipeline are still not enumerated as
additional findings. For example, a `parallel` block and its branches,
per-branch agents, or timeouts produce no additional findings when the
pipeline is already blocked. This is a completeness limitation of the
migration checklist, not a change in the disabled-draft safety behavior:
the draft is disabled and the report states that its contents were not
deeper-analyzed. Deeper enumeration remains explicitly out of scope.

## Conversion subset (unchanged from v0.1.0)

Still supported: one declarative `pipeline`, `agent any` (with the
documented `ubuntu-latest` assumption), sequential stages with non-empty
`steps`, literal `sh`/`echo`, `checkout scm`, and literal pipeline/stage
`environment`. Still unsupported and blocked: `script { }`, credentials,
parallel/matrix, `input`, `post`, `when`, custom/container agents,
parameters, triggers, tools, and anything else outside the documented
subset. Missing required structure remains malformed input (exit 1).

## Requirements and installation

Requires Python 3.10+ (CI tests 3.10 and 3.13). Runtime dependency:
PyYAML >= 6.0. `actionlint` is optional and reported honestly when absent.

The attached release assets are:

- `pipebridge-0.2.0-py3-none-any.whl`
- `pipebridge-0.2.0.tar.gz`

They are published on GitHub and can be installed with:

```sh
pip install https://github.com/marcelodevops/pipebridge/releases/download/v0.2.0/pipebridge-0.2.0-py3-none-any.whl
# or
pip install https://github.com/marcelodevops/pipebridge/releases/download/v0.2.0/pipebridge-0.2.0.tar.gz
```

From the repository at the `v0.2.0` tag:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install .
pipebridge --version   # pipebridge 0.2.0
```

## Verification

- Release-candidate CI: all four checks passed on the exact tagged
  commit `b29f37d12619a5165d6b65c9d937679eb21a67a9` —
  <https://github.com/marcelodevops/pipebridge/actions/runs/44363782136>
  (tests on Python 3.10 and 3.13, workflow lint/build/smoke test, example
  validation).
- Clean checkout of that commit: wheel and sdist built fresh;
  `twine check` passed for both.
- Full test suite: **229 passed** (`python -m pytest tests/ -q`).
- `actionlint -no-color`: clean (actionlint 1.7.12).
- Example validation (`scripts/validate-python-build-example.py`): all
  steps passed, including byte-for-byte workflow comparison and the
  structural live-workflow comparison with only the documented
  `defaults.run.working-directory: examples/python-build` adjustment.
- Package build: wheel and sdist built; `twine check` **PASSED** for both.
- Fresh-environment installation, one new venv per artifact, outside the
  checkout, with `PYTHONPATH` unset: **13/13 checks passed for the wheel
  and 13/13 for the sdist**, covering:
  - `pipebridge --version` → `pipebridge 0.2.0`, import resolving inside
    the venv;
  - supported declarative fixture → exit 0;
  - ordinary-imports fixture → exit 0, no blockers, three info imports;
  - surrounding executable Groovy → exit 2, disabled draft,
    structure/stages extracted, `PB-GROOVY-PRELUDE`;
  - malformed import → exit 2, disabled draft, blocker and no info import;
  - scripted input → exit 2, `PB-SCRIPT`;
  - ambiguous/multiple pipelines → exit 1, no artifacts.
- Published assets were downloaded again from the release, verified
  against the attached `SHA256SUMS`, and re-tested in two new fresh venvs:
  wheel 13/13 and sdist 13/13. See
  [`docs/release-verification-v0.2.0.md`](release-verification-v0.2.0.md).

### Asset checksums

```
f63ed3d8e95e642fa5506c719a4e67679d4848b23a6849dbe75391e5c1316302  pipebridge-0.2.0-py3-none-any.whl
7afe24624d6389a43f433ce4abfd02b548e62d3a1f17c9e25677908cbf1fc2c3  pipebridge-0.2.0.tar.gz
```

## The example artifacts

The committed `examples/python-build/migration/` output was regenerated
with pipebridge 0.2.0. Compared with the previous committed output, the
generated `workflow.yml` differs **only** in the tool-version header line;
the JSON/Markdown reports differ only in the tool version and generation
timestamp. The live workflow
`.github/workflows/python-build-example.yml` keeps its documented
`defaults.run.working-directory: examples/python-build` adjustment; only
its generated-by version comment changed. The Jenkinsfile, stage list,
steps, assumptions, and findings are unchanged.

## Known limitations

- **D2 deferred:** nested constructs are not enumerated once a
  pipeline-level blocker exists (see above).
- Surrounding Groovy is recognized only for a deliberately limited
  grammar. Unrecognized statements before the block still classify the
  file as `PB-SCRIPT`; multiple or ambiguous pipeline blocks are rejected
  as malformed (exit 1, no artifacts).
- No Groovy is evaluated; no initializer is classified as safe; values
  computed at Jenkins runtime are not carried into generated workflows.
- `workflow_dispatch` only; one workflow, one job; no automatic secret
  migration.
- Static validation only (YAML parse and actionlint when installed), plus
  the previously recorded live runs of the migrated example workflow. No
  Jenkins runtime was involved and no runtime equivalence is claimed.

## Release checklist

- [x] Version bumped to `0.2.0` (`src/pipebridge/__init__.py`).
- [x] Changelog entry added; these release notes added.
- [x] Committed example output and pure-declarative goldens regenerated
      with 0.2.0 (version-only differences, plus report timestamps).
- [x] Release-preparation PR #12 merged; post-merge CI green on the exact
      commit.
- [x] Wheel and sdist built from a clean checkout of that commit;
      `twine check` passed.
- [x] Fresh wheel and sdist venvs outside the checkout, `PYTHONPATH`
      unset: 13/13 checks each before publication.
- [x] Annotated tag `v0.2.0` created at
      `b29f37d12619a5165d6b65c9d937679eb21a67a9`.
- [x] GitHub prerelease published with wheel, sdist, and `SHA256SUMS`.
- [x] Published assets downloaded, checksum-verified, and re-tested:
      wheel 13/13 and sdist 13/13 after publication.
- [x] v0.1.0 tag, release, and assets left untouched; no PyPI publish.
