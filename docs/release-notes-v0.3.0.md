# Release notes — pipebridge v0.3.0 (ALPHA)

> **Status: release preparation, not published.** These notes describe a
> prepared alpha increment. No `v0.3.0` tag, GitHub release, or release
> asset exists yet; the published `v0.2.1` assets, tag, and notes are
> unchanged. The exact release-preparation commit, CI runs, installation
> results, and independent checks are recorded in the release-preparation
> pull request.
>
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

When published, the expected attached assets are:

- `pipebridge-0.3.0-py3-none-any.whl`
- `pipebridge-0.3.0.tar.gz`

pipebridge is not published to PyPI. The published v0.2.1 installation
instructions remain valid until v0.3.0 is released. This preparation does
not upload those assets.

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
- Package build: wheel and sdist built from the release-preparation tree;
  `twine check` **PASSED** for both. These are local preparation builds,
  not uploaded release assets:
  - `d3c28474936490acc4055fe02cfd51b438b77110bb71d42d737a03278c14bfd7`
    `pipebridge-0.3.0-py3-none-any.whl`
  - `92f604d49d27b58787fbcfff8c1b01d6fee4111d884a0e460c533d90ccde7869`
    `pipebridge-0.3.0.tar.gz`
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

## Release checklist state

Prepared and verified locally:

- [x] Version bumped to `0.3.0` (`src/pipebridge/__init__.py`).
- [x] Changelog entry added; these release notes added.
- [x] Committed example output, live-workflow version comment, clean
      baseline, and pure-declarative goldens regenerated with 0.3.0.
- [x] Full suite, actionlint, and example validation green.
- [x] Wheel and sdist built; `twine check` passed.
- [x] Fresh wheel and sdist venvs outside the checkout, `PYTHONPATH`
      unset: 24/24 checks each.

Deliberately **not** done in this increment:

- [ ] Merge the release-preparation PR (human decision).
- [ ] Tag `v0.3.0`.
- [ ] Publish a GitHub release or upload artifacts.
- [ ] Modify or replace any v0.1.0, v0.2.0, or v0.2.1 tag, release, or asset.
- [ ] Publish to PyPI.
