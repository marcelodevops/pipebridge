# Release notes — pipebridge v0.3.0 (ALPHA)

> **Status: published alpha prerelease, 2026-11-20.** Published at
> <https://github.com/marcelodevops/pipebridge/releases/tag/v0.3.0>
> (annotated tag `v0.3.0` at commit `a13a0a00f9eff7e6505f6ade9fd0db40bbd7ca9c`),
> marked **alpha (pre-release)** and deliberately **not** latest stable.
> The wheel, source distribution, and `SHA256SUMS` are attached to the
> release. pipebridge is **not** published to PyPI. Existing `v0.1.0`,
> `v0.2.0`, and `v0.2.1` tags, releases, and assets are unchanged.
>
> Release-preparation pull request
> [#20](https://github.com/marcelodevops/pipebridge/pull/20) merged at
> `a13a0a00f9eff7e6505f6ade9fd0db40bbd7ca9c`. All four required CI checks
> passed on that exact merge commit:
> <https://github.com/marcelodevops/pipebridge/actions/runs/44659066648>
> (335 passed on Python 3.10 and 3.13).
> The implementation increment is pull request
> [#19](https://github.com/marcelodevops/pipebridge/pull/19), merged at
> `09a0e7f45b21cced69a7bac6709681dfba7ddbd7`. All four required CI checks
> passed on that exact merge commit:
> <https://github.com/marcelodevops/pipebridge/actions/runs/44614669117>.

## What v0.3.0 is

A **bounded runner-selector mapping**, not an environment translation and
not a claim of Jenkins runtime equivalence.

v0.3.0 accepts one pipeline-level literal agent label:

```groovy
agent { label 'nodejs' }
agent { label "nodejs" }
```

and emits:

```yaml
runs-on: [self-hosted, nodejs]
```

The mapping is reported as `PB-ASSUME-RUNNER-LABEL`. The finding says, in
substance, that a self-hosted GitHub Actions runner with that label is
assumed to exist and to provide the same OS, installed tools, network
access, permissions, and workspace behavior as the Jenkins agent. It also
says that Jenkins label expressions, variables, and stage-level agents are
not mapped.

That assumption is the whole claim. pipebridge does not check that the
runner exists, is online, or matches the Jenkins agent. It does not execute
the generated workflow. A label that looks like a GitHub-hosted runner
(`ubuntu-latest`) is still emitted as self-hosted; edit `runs-on`
deliberately if a hosted runner is intended.

`PB-ASSUME-RUNNER` remains the `agent any` → `ubuntu-latest` assumption and
is not emitted for a label.

## Accepted grammar

- One pipeline-level `agent { label '<literal>' }` or
  `agent { label "<literal>" }`.
- The decoded value must match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$` over the
  whole string (`fullmatch`). A trailing decoded newline does not pass.
- `self-hosted` is rejected case-insensitively (`SELF-HOSTED`,
  `Self-Hosted`, and mixed case included).
- Every other accepted spelling is preserved. Labels that look like YAML
  scalars (`true`, `null`, `123`, `1.2`) are emitted as quoted strings, so
  a YAML round-trip keeps them as strings.

## What stays blocked

Rejected labels and unsupported agent forms leave `PB-AGENT`, a disabled
draft (`if: false`), and `runs-on: ubuntu-latest`. No label assumption is
emitted. That includes:

- empty, too-long, or out-of-grammar labels, including escaped newline,
  tab, carriage return, and a valid prefix followed by `\n`;
- expressions, variables, concatenation, triple quotes, the `label()` call
  form, and extra directives;
- `agent none`, `node`, `docker`, `dockerfile`, and `kubernetes`;
- stage-level labels (all stages still share one job);
- duplicate pipeline-level `agent` sections (`PB-SYNTAX`).

An accepted label does not clear unrelated blockers. Memphis, HMRC, and
Tutanota get the labeled `runs-on` and stay exit 2. HMRC and Tutanota keep
their stage-level `PB-AGENT`. A missing `stages` section remains malformed
input (exit 1, nothing written).

actionlint's hosted-runner catalog does not include custom labels. When a
labeled `runs-on` list is emitted, that one unknown-label message is
suppressed and disclosed in the report. Other lint failures still reject
the conversion. The disclosure is not evidence that the runner exists.

## Intentional sample change

`node-minimal-do400-like` is the one checked-in sample this mapping makes
clean: exit 2 → 0, enabled job, `runs-on: [self-hosted, nodejs]`, implicit
checkout, and its three literal `sh` steps. Couchbase's expression label,
Jetty, and Kymatio stay `ubuntu-latest` and `PB-AGENT`. `agent any` output,
including `examples/python-build`, changes only in the tool-version header.

## Requirements and installation

Requires Python 3.10+ (CI tests 3.10 and 3.13). Runtime dependency:
PyYAML >= 6.0. `actionlint` is optional and reported honestly when absent.

Attached assets:

- `pipebridge-0.3.0-py3-none-any.whl`
- `pipebridge-0.3.0.tar.gz`
- `SHA256SUMS`

pipebridge is not published to PyPI. Install from the v0.3.0 release
assets, not from PyPI.

## Verification

- Implementation PR #19 merged at
  `09a0e7f45b21cced69a7bac6709681dfba7ddbd7`; all four required checks
  passed on that exact merge commit
  (<https://github.com/marcelodevops/pipebridge/actions/runs/44614669117>):
  tests on Python 3.10 and 3.13, workflow lint and package smoke test, and
  python-build example validation.
- Release-preparation full test suite: **335 passed**
  (`.venv/bin/python -m pytest tests/ -q`).
- `actionlint -no-color`: clean (actionlint 1.7.12).
- Example validation (`scripts/validate-python-build-example.py`): all
  steps passed, including byte-for-byte workflow comparison and the
  structural live-workflow comparison with only the documented
  `defaults.run.working-directory: examples/python-build` adjustment.
  Report tool version was `0.3.0`.
- Package build from a clean archive of the tagged commit
  `a13a0a00f9eff7e6505f6ade9fd0db40bbd7ca9c`; `twine check` **PASSED**
  for both. Uploaded asset SHA-256:
  - `71ed6befb9a0dd7a16f58f00214347abd0c852e6526de243ee4b32dd1b7f9db8`
    `pipebridge-0.3.0-py3-none-any.whl`
  - `2ea6cb3d22a37d46be1477dce15c9eb972931d88900e63f9786a492250d13db9`
    `pipebridge-0.3.0.tar.gz`
  File contents match the release-preparation wheel; the archive hashes
  differ only because zip entry timestamps come from this commit.
- Fresh-environment installation, one new venv per artifact, outside the
  checkout, with `PYTHONPATH` unset: **24/24 checks passed for the wheel
  and 24/24 for the sdist**, covering:
  - `pipebridge --version` → `pipebridge 0.3.0`, import resolving inside
    the venv and not from the checkout;
  - valid single-quoted `nodejs` and double-quoted `NodeJS` → exit 0,
    enabled workflow, labeled `runs-on`, `PB-ASSUME-RUNNER-LABEL`, no
    `PB-AGENT` and no `PB-ASSUME-RUNNER`;
  - reserved-label casings `self-hosted`, `SELF-HOSTED`, `Self-Hosted`,
    and `sElF-hOsTeD` → exit 2, disabled draft, `ubuntu-latest`,
    `PB-AGENT`, no label assumption;
  - YAML scalar-looking labels `true`, `null`, `123`, and `1.2` → exit 0,
    `runs-on` parts remain strings;
  - double-quoted escaped newline, tab, carriage return, and `nodejs\n`
    → exit 2, disabled draft, `ubuntu-latest`, `PB-AGENT`, no label
    assumption;
  - unsupported `agent none`, `docker`, `node`, `kubernetes`, and a
    stage-level label → exit 2, disabled draft, no label mapping;
  - a label plus an unrelated `script` blocker → exit 2, labeled
    `runs-on`, disabled draft, `PB-SCRIPT`, label assumption retained,
    no `PB-AGENT`;
  - malformed input (label, missing `stages`) → exit 1, no artifacts.

## The example artifacts and goldens

The committed `examples/python-build/migration/` output and the
`.github/workflows/python-build-example.yml` version comment were
regenerated with pipebridge 0.3.0. The generated `workflow.yml` differs
only in the tool-version header line; the JSON/Markdown reports differ only
in the tool version and generation timestamp. The live workflow keeps its
documented `defaults.run.working-directory` adjustment; only its
generated-by version comment changed.

The clean build-and-test workflow baseline and the two pure-declarative
goldens differ only in the tool-version header. DO400's enabled labeled
workflow and Kymatio's disabled draft are otherwise unchanged.

## Known limitations

- A mapped label selects a runner. It does not claim the runner exists or
  matches the Jenkins agent's OS, tools, network, permissions, or workspace.
- Unsupported agent forms, expressions, and stage-level agents stay blocked.
- actionlint cannot know a custom self-hosted label; that one message is
  disclosed as ignored, and other lint failures still fail conversion.
- No Jenkins controller and no GitHub Actions runner were used for this
  increment. Static validation only. No runtime equivalence is claimed.
- `workflow_dispatch` only; one workflow, one job; no automatic secret
  migration.

## Published assets (SHA-256)

```
71ed6befb9a0dd7a16f58f00214347abd0c852e6526de243ee4b32dd1b7f9db8  pipebridge-0.3.0-py3-none-any.whl
2ea6cb3d22a37d46be1477dce15c9eb972931d88900e63f9786a492250d13db9  pipebridge-0.3.0.tar.gz
```

## Release checklist state

Published:

- [x] Version bumped to `0.3.0` (`src/pipebridge/__init__.py`).
- [x] Changelog entry added; these release notes added.
- [x] Committed example output, live-workflow version comment, clean
      baseline, and pure-declarative goldens regenerated with 0.3.0.
- [x] Full suite, actionlint, and example validation green on the
      release-preparation PR and on the merge commit.
- [x] Release-preparation PR #20 merged at
      `a13a0a00f9eff7e6505f6ade9fd0db40bbd7ca9c`; all four CI checks green
      on that exact commit
      (<https://github.com/marcelodevops/pipebridge/actions/runs/44659066648>):
      335 passed on Python 3.10 and 3.13.
- [x] Wheel and sdist built from a clean checkout of that commit;
      `twine check` passed.
- [x] Fresh wheel and sdist venvs outside the checkout, `PYTHONPATH`
      unset: the documented acceptance matrix passed for both artifacts.
- [x] Annotated tag `v0.3.0` created at `a13a0a00f9eff7e6505f6ade9fd0db40bbd7ca9c`.
- [x] GitHub prerelease published with wheel, sdist, and `SHA256SUMS`,
      not marked latest.
- [x] v0.1.0, v0.2.0, and v0.2.1 tags, releases, and assets left untouched.
- [x] No PyPI publication.

Post-publication download, checksum verification, and fresh-venv
re-testing of the published assets are recorded in
[`docs/release-verification-v0.3.0.md`](release-verification-v0.3.0.md).
That record does not move the tag or replace any asset.
