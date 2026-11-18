# Release notes — pipebridge v0.2.0 (ALPHA)

> **Status: release preparation, not published.** These notes describe a
> prepared alpha increment. No `v0.2.0` tag, GitHub release, or release
> asset exists yet; the published **v0.1.0** assets and tag are unchanged.
> The exact release-preparation commit, CI runs, and installation results
> are recorded in the release-preparation pull request.

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

The release artifacts prepared for this increment are:

- `pipebridge-0.2.0-py3-none-any.whl`
- `pipebridge-0.2.0.tar.gz`

They are built locally and verified, not published. After publication
they would be installed with:

```sh
pip install https://github.com/marcelodevops/pipebridge/releases/download/v0.2.0/pipebridge-0.2.0-py3-none-any.whl
# or
pip install https://github.com/marcelodevops/pipebridge/releases/download/v0.2.0/pipebridge-0.2.0.tar.gz
```

From a checkout of the release-preparation branch:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install .
pipebridge --version   # pipebridge 0.2.0
```

## Verification performed for this preparation

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

## Release checklist state

Prepared and verified locally:

- [x] Version bumped to `0.2.0` (`src/pipebridge/__init__.py`).
- [x] Changelog entry added; these release notes added.
- [x] Committed example output and pure-declarative goldens regenerated
      with 0.2.0 (version-only differences, plus report timestamps).
- [x] Wheel and sdist built; `twine check` passed.
- [x] Fresh wheel and sdist venvs outside the checkout, `PYTHONPATH`
      unset: 13/13 checks each.
- [x] Full suite, actionlint, and example validation green.

Deliberately **not** done in this increment:

- [ ] Merge the release-preparation PR (human decision).
- [ ] Tag `v0.2.0`.
- [ ] Publish a GitHub release or upload artifacts.
- [ ] Modify or replace any v0.1.0 tag, release, or asset.
