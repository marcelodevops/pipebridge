# Release notes — pipebridge v0.4.0 (ALPHA)

> **Status: release preparation, not published.** These notes describe a
> prepared alpha increment. No `v0.4.0` tag, GitHub release, or release
> asset exists yet; the published `v0.3.0` assets, tag, and notes are
> unchanged. The exact release-preparation commit, CI runs, installation
> results, and independent checks are recorded in the release-preparation
> pull request.
>
> The implementation increment is pull request
> [#23](https://github.com/marcelodevops/pipebridge/pull/23), merged at
> `c8d953270d5db67b66a7deeb2ee56350e9baa068`. All four required CI checks
> passed on that exact merge commit:
> <https://github.com/marcelodevops/pipebridge/actions/runs/44675729123>.

## What v0.4.0 is

A **bounded string credential-binding mapping**, not secret migration and
not a claim of Jenkins runtime equivalence.

v0.4.0 accepts one binding in a stage `steps` block:

```groovy
withCredentials([string(credentialsId: 'npm-token', variable: 'NPM_TOKEN')]) {
    sh 'npm publish'
}
```

and, when `--credential-map` maps `npm-token` to a GitHub secret name,
emits that name only on the bound steps:

```yaml
env:
  NPM_TOKEN: ${{ secrets.NPM_TOKEN_GH }}
```

The secret name comes only from the map. pipebridge does not guess a name
from the credential ID or the variable, does not read a secret value, does
not invoke `gh`, and does not create or modify GitHub configuration.

## Accepted grammar

Exactly one `withCredentials([string(...)]) { … }` whose header is:

- `string` only, one element;
- `credentialsId` and `variable` each exactly once, either order;
- both values single- or double-quoted literals;
- the decoded credential ID non-empty, without leading or trailing
  whitespace;
- the variable a Jenkins identifier.

The body must be only already-supported `sh`, `echo`, and `checkout scm`
steps. Semicolons inside that body still separate statements. Newlines
before `{` are allowed. A semicolon between header tokens, or between the
call and `{`, rejects the header.

Names are matched with a full-string match. A trailing decoded newline
does not pass.

## Explicit mapping

`--credential-map PATH` loads a JSON object of credential ID → secret name.
It is accepted by `analyze` and `convert`. Validation rejects a missing
file, invalid JSON, a non-object, empty or non-string names, and secret
names that are not GitHub secret-name shaped. Unused map entries are
reported (`PB-CRED-MAP-UNUSED`) and do not by themselves block conversion.

A source credential ID absent from the map, an invalid name, or two
credential IDs that collide on the same secret name (case-insensitive)
are `PB-CRED-MAP`. The affected stage stays blocked. No command is emitted
for that binding.

## Step-scoped injection

A resolved binding injects `NAME: ${{ secrets.MAPPED }}` only on the steps
inside the binding. Sibling steps, other stages, and the implicit checkout
do not receive that env entry. Generated secret expressions are not passed
through the expression-escaping path that would neutralize a literal
`${{ }}` the user wrote in a shell command; a user-written expression in a
command is still neutralized.

## Independent inventory

Every seen binding, including unsupported forms, is recorded in a
credential inventory that is not stored on translated steps. Clearing a
blocked stage removes steps and does not erase the inventory record. An
inventory entry alone never emits an env entry.

## Report contract

Reports gain one additive top-level `credentials` object:

- `map_supplied`
- `setup_acknowledged`
- `bindings` (source order, from the inventory)
- `required_secrets`
- `checklist`

Existing top-level keys, finding keys, and finding types are unchanged.
The object is present even when there are no bindings. When a binding is
present, the Markdown report adds a "Required GitHub Actions secrets"
section. Workflow bytes for pipelines without an accepted binding change
only in the tool-version header.

## Readiness gate

`--secrets-ready` records `credentials.setup_acknowledged: true` and the
info finding `PB-ASSUME-CREDENTIALS`. It is an **unverified
acknowledgement** that the named secrets exist in the target repository.
pipebridge does not list, read, or create those secrets.

- A complete map without the acknowledgement exits 2, disables the draft
  (`if: false`) with `PB-CRED-SETUP`, and still leaves the resolved steps
  in the draft for review.
- A complete map with the acknowledgement exits 0 when the pipeline is
  otherwise clean, and enables the job.
- The acknowledgement does not clear `PB-CRED`, `PB-CRED-MAP`, or any
  unrelated blocker.

## What stays blocked

Unsupported forms stay `PB-CRED` and opaque. That includes other binding
types (`usernamePassword`, `file`, `sshUserPrivateKey`, …), `credentials()`
in `environment`, dynamic IDs or variables, nested bindings, extra header
tokens, a semicolon in the header or between the call and the body, and a
body that is not the supported step subset. A semicolon-detached closure
is skipped and not translated. Later siblings are still diagnosed.

An accepted binding does not clear unrelated blockers. Malformed input
still exits 1 and writes nothing.

Existing pipeline-level literal agent-label support is unchanged.

## Requirements and installation

Requires Python 3.10+ (CI tests 3.10 and 3.13). Runtime dependency:
PyYAML >= 6.0. `actionlint` is optional and reported honestly when absent.

When published, the expected attached assets are:

- `pipebridge-0.4.0-py3-none-any.whl`
- `pipebridge-0.4.0.tar.gz`

pipebridge is not published to PyPI. The published v0.3.0 installation
instructions remain valid until v0.4.0 is released. This preparation does
not upload those assets, create secrets, or modify existing releases.

## Verification

- Implementation PR #23 merged at
  `c8d953270d5db67b66a7deeb2ee56350e9baa068`; all four required checks
  passed on that exact merge commit
  (<https://github.com/marcelodevops/pipebridge/actions/runs/44675729123>):
  tests on Python 3.10 and 3.13, workflow lint and package smoke test, and
  python-build example validation.
- Release-preparation full test suite: **372 passed**
  (`PYTHONPATH=src .venv/bin/python -m pytest tests/ -q`).
- `actionlint -no-color`: clean (actionlint 1.7.12).
- Example validation (`scripts/validate-python-build-example.py`): all
  steps passed, including byte-for-byte workflow comparison and the
  structural live-workflow comparison with only the documented
  `defaults.run.working-directory: examples/python-build` adjustment.
  Report tool version was `0.4.0`.
- Package build: wheel and sdist built from the release-preparation tree;
  `twine check` **PASSED** for both. These are local preparation builds,
  not uploaded release assets:
  - `f44f2f1de87e9f166de84776e68dc8be1f8b434b8b35e32f512e6a7993f7c4cb`
    `pipebridge-0.4.0-py3-none-any.whl`
  - `be4702d957b20261b1f7d9f2058545faf76b724a9c0428903ace1390a4fce165`
    `pipebridge-0.4.0.tar.gz`
- Fresh-environment installation, one new venv per artifact, outside the
  checkout, with `PYTHONPATH` unset: **41/41 checks passed for the wheel
  and 41/41 for the sdist**, covering:
  - `pipebridge --version` → `pipebridge 0.4.0`, import resolving inside
    the venv and not from the checkout;
  - missing, invalid, and colliding mappings → exit 2, disabled draft, no
    secret env; a missing map file → exit 1, nothing written;
  - a complete map without `--secrets-ready` → exit 2, disabled draft,
    `PB-CRED-SETUP`, resolved step still present for review;
  - a complete map with `--secrets-ready` → exit 0 when otherwise clean,
    enabled job, `PB-ASSUME-CREDENTIALS`;
  - step-only secret scope: sibling steps and the implicit checkout have
    no credential env;
  - inventory and required-secret list survive stage clearing after an
    unrelated `post` blocker; the cleared stage emits no secret env;
  - unsupported `usernamePassword` stays `PB-CRED` and is not translated
    even with a map and `--secrets-ready`;
  - a semicolon between the call and the body stays blocked with
    `--secrets-ready`: disabled draft, unsupported inventory, detached
    closure not translated;
  - existing `agent { label 'nodejs' }` support still exits 0 with
    `runs-on: [self-hosted, nodejs]`; `self-hosted` stays exit 2,
    `ubuntu-latest`, `PB-AGENT`, no label assumption;
  - malformed input (missing `stages`) → exit 1, no artifacts;
  - no secret-value reads and no `gh` execution. A sentinel environment
    value did not appear in any artifact, and a `gh` placed first on
    `PATH` was never invoked.

## The example artifacts and goldens

The committed `examples/python-build/migration/` output and the
`.github/workflows/python-build-example.yml` version comment were
regenerated with pipebridge 0.4.0. The generated `workflow.yml` differs
only in the tool-version header line; the JSON/Markdown reports differ in
the tool version, the generation timestamp, and the additive empty
`credentials` object already present on main. The live workflow keeps its
documented `defaults.run.working-directory` adjustment; only its
generated-by version comment changed.

The clean build-and-test workflow baseline and the two pure-declarative
goldens differ only in the tool-version header. Blocked drafts that are
compared structurally, not byte-for-byte, are otherwise unchanged.

## Known limitations

- A mapped binding names a secret. It does not create the secret, read its
  value, or claim the value matches the Jenkins credential.
- `--secrets-ready` is an acknowledgement, not a verification.
- Unsupported credential forms, dynamic arguments, nested bindings, and
  opaque bodies stay blocked.
- No Jenkins controller and no GitHub Actions runner were used for this
  increment. Static validation only. No runtime equivalence is claimed.
- `workflow_dispatch` only; one workflow, one job; no automatic secret
  migration.

## Release checklist state

Prepared and verified locally:

- [x] Version bumped to `0.4.0` (`src/pipebridge/__init__.py`).
- [x] Changelog entry added; these release notes added.
- [x] Committed example output, live-workflow version comment, clean
      baseline, and pure-declarative goldens regenerated with 0.4.0.
- [x] Full suite, actionlint, and example validation green.
- [x] Wheel and sdist built; `twine check` passed.
- [x] Fresh wheel and sdist venvs outside the checkout, `PYTHONPATH`
      unset: 41/41 checks each.

Deliberately **not** done in this increment:

- [ ] Merge the release-preparation PR (human decision).
- [ ] Tag `v0.4.0`.
- [ ] Publish a GitHub release or upload artifacts.
- [ ] Modify or replace any v0.1.0, v0.2.0, v0.2.1, or v0.3.0 tag,
      release, or asset.
- [ ] Publish to PyPI.
- [ ] Create GitHub secrets or invoke `gh` to change repository
      configuration.
