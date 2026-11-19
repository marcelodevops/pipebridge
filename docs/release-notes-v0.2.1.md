# Release notes — pipebridge v0.2.1 (ALPHA)

> **Status: release preparation, not published.** These notes describe a
> prepared alpha increment. No `v0.2.1` tag, GitHub release, or release
> asset exists yet; the published `v0.2.0` assets, tag, and notes are
> unchanged. The exact release-preparation commit, CI runs, installation
> results, and independent checks are recorded in the release-preparation
> pull request.
>
> The implementation increment for diagnostic traversal is pull request
> [#15](https://github.com/marcelodevops/pipebridge/pull/15), merged at
> `ba5b583e26bac7bf01fe7987a8046bb0c7dc13e9`. All four required CI checks
> passed on that exact merge commit:
> <https://github.com/marcelodevops/pipebridge/actions/runs/44431519477>.

## What v0.2.1 is

A **diagnostic-completeness fix**, not broader conversion support.

v0.2.1 addresses defect **D2** from the compatibility study: when
translation stopped at a blocker, pipebridge also stopped reading the rest
of that scope, so the migration checklist under-reported the work. The
disabled draft and exit code were already safe; the report was incomplete.

**Nothing about the supported translation subset changed.** No construct
newly visible in a blocked scope is translated. The job stays disabled
(`if: false`) with exit 2, findings inside a blocked scope remain
diagnostics rather than translated behavior, Groovy is never evaluated,
and no Jenkins-to-GitHub runtime equivalence is claimed or tested.

## What changed in the analysis

Diagnostic traversal now continues through the blocking construct's
eligible body and the remaining siblings in the same scope. Findings keep
source positions, parent-scope labels (for example
`stage 'Parallel Stage' → parallel branch 'Build / Test - JDK21'`), stable
source ordering, and deduplication. No new finding codes, model fields, or
report keys were introduced.

The traversal enters only the documented declarative grammar and a bounded
step-wrapper allowlist (`timeout`, `retry`, `catchError`, `dir`,
`withEnv`, `wrap`, `withCredentials`). It does not create a translated
`Step` or a nested model `Stage` from a blocked scope.

### Step arguments are validated in blocked scopes

`sh`, `echo`, and `checkout` were previously treated as safe from the step
name alone during diagnosis. They now reuse the supported-subset argument
checks: interpolation, dynamic Groovy expressions, and non-`checkout scm`
forms are reported, while nothing is translated.

A blocked scope such as this now reports the interpolation, the map-form
checkout, and the later unsupported step:

```groovy
stage('Hidden') {
    steps {
        sh "echo " + env.BUILD_NUMBER
        checkout([$class: 'GitSCM'])
        mavenBuild 'later'
    }
}
```

### Diagnostic recovery stops at top-level semicolons

Argument recovery used to consume the rest of the line, hiding a sibling
after `;`. It now stops at a top-level semicolon, so
`echo env.JOB_NAME; mavenBuild 'visible'` reports both the unsupported
`echo` argument and the later `mavenBuild`. Semicolons inside strings,
parentheses, brackets, and closures are not split points, and opaque
bodies stay opaque.

### Explicit boundaries and depth limit

Opaque bodies are reported once as boundaries and are never entered:
`script`, shared-library calls, agent internals, `when` expressions,
`post`, `withCredentials`, and unknown closures. Traversal stops at nesting
depth 20 and emits an explicit truncation finding; deeper content is
reported as not analyzed. These boundaries are unchanged from the D2
design.

### Jetty-like before and after

For `java-maven-jetty-like.Jenkinsfile`, exit code, disabled state, and the
translated stage list do not change. The report gains the nested findings
inside the blocked `parallel` stage:

| Before (pipeline-level stop) | After (still exit 2, still disabled, still one top-level stage) |
| --- | --- |
| `PB-AGENT` L7, `PB-SYNTAX` L8 (options), `PB-POST` L42, three `PB-GROOVY-POSTLUDE` findings | Those findings remain, plus `PB-PARALLEL` L16, per-branch `PB-AGENT` L18/L31, `PB-WHEN` L19/L32, `PB-SYNTAX` timeout L21/L34, `PB-SCRIPT` L22, and `PB-SYNTAX` `mavenBuild` L26/L35 |

`checkout scm` inside the blocked timeout is supported syntax, so it
produces no finding and is not translated.

## Conversion subset (unchanged)

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

When published, the expected attached assets are:

- `pipebridge-0.2.1-py3-none-any.whl`
- `pipebridge-0.2.1.tar.gz`

pipebridge is not published to PyPI. The published v0.2.0 installation
instructions remain valid until v0.2.1 is released.

## Verification

- Implementation PR #15 merged at
  `ba5b583e26bac7bf01fe7987a8046bb0c7dc13e9`; all four required checks
  passed on that exact merge commit
  (<https://github.com/marcelodevops/pipebridge/actions/runs/44431519477>):
  tests on Python 3.10 and 3.13, workflow lint and package smoke test, and
  python-build example validation.
- Release-preparation full test suite: **255 passed**
  (`.venv/bin/python -m pytest tests/ -q`).
- `actionlint -no-color`: clean (actionlint 1.7.12).
- Example validation (`scripts/validate-python-build-example.py`): all
  steps passed, including byte-for-byte workflow comparison and the
  structural live-workflow comparison with only the documented
  `defaults.run.working-directory: examples/python-build` adjustment.
- Package build: wheel and sdist built from the release-preparation tree;
  `twine check` **PASSED** for both.
- Fresh-environment installation, one new venv per artifact, outside the
  checkout, with `PYTHONPATH` unset: **20/20 checks passed for the wheel
  and 20/20 for the sdist**, covering:
  - `pipebridge --version` → `pipebridge 0.2.1`, import resolving inside
    the venv;
  - supported declarative input → exit 0, enabled workflow, no blockers;
  - blocked-scope argument validation repro → exit 2, disabled draft,
    interpolation, unsupported checkout, and the later unsupported step
    reported, opaque `script` body not analyzed;
  - top-level semicolon repro → exit 2, disabled draft, later sibling and
    dynamic `echo` reported, opaque `script` sibling hidden;
  - Jetty-like nested diagnostics → exit 2, disabled draft, one blocked
    top-level stage, and the documented nested blocker positions;
  - malformed input (two `pipeline` blocks) → exit 1, no artifacts.

## The example artifacts and goldens

The committed `examples/python-build/migration/` output and the
`.github/workflows/python-build-example.yml` version comment were
regenerated with pipebridge 0.2.1. The generated `workflow.yml` differs
only in the tool-version header line; the JSON/Markdown reports differ only
in the tool version and generation timestamp. The live workflow keeps its
documented `defaults.run.working-directory` adjustment; only its
generated-by version comment changed. The Jenkinsfile, stage list, steps,
assumptions, and findings are unchanged.

The clean build-and-test workflow golden changed only in its version
header. The two pure-declarative goldens were regenerated too; the
Kymatio-like golden additionally carries the D2 diagnostic changes already
present in the report (its blocked placeholder lists `PB-INTERP`), while
the DO400-like golden differs only in the version header.

## Known limitations

- Diagnostics are best-effort within the documented declarative grammar.
  Opaque bodies are boundaries, not analyzed code, and diagnostic traversal
  stops at depth 20 (reported explicitly).
- No construct newly visible in a blocked scope is translated; the draft
  stays disabled and the exit code stays 2.
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

- [x] Version bumped to `0.2.1` (`src/pipebridge/__init__.py`).
- [x] Changelog entry added; these release notes added.
- [x] Committed example output, live-workflow version comment, and
      pure-declarative goldens regenerated with 0.2.1.
- [x] Clean build-and-test golden updated for the version header.
- [x] Full suite, actionlint, and example validation green.
- [x] Wheel and sdist built; `twine check` passed.
- [x] Fresh wheel and sdist venvs outside the checkout, `PYTHONPATH`
      unset: 20/20 checks each.

Deliberately **not** done in this increment:

- [ ] Merge the release-preparation PR (human decision).
- [ ] Tag `v0.2.1`.
- [ ] Publish a GitHub release or upload artifacts.
- [ ] Modify or replace any v0.2.0 tag, release, or asset.
- [ ] Publish to PyPI.
