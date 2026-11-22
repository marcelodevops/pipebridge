# Release notes — pipebridge v0.5.0 (ALPHA)

> **Status: release preparation, not published.** These notes describe a
> prepared alpha increment. No `v0.5.0` tag, GitHub release, or release
> asset exists yet; the published `v0.3.0` assets, tag, and notes are
> unchanged. The exact release-preparation commit, CI runs, installation
> results, and independent checks are recorded in the release-preparation
> pull request.
>
> The implementation and live-validation increments are pull requests
> [#26](https://github.com/marcelodevops/pipebridge/pull/26) (merged at
> `7a2f067abf98e28bfcb57438344dc317668fcbfc`),
> [#27](https://github.com/marcelodevops/pipebridge/pull/27) (merged at
> `522b0088ee0595b39b542ba2cb4a9ce810d73079`),
> [#28](https://github.com/marcelodevops/pipebridge/pull/28) (merged at
> `f54d56e87b8ca8c94cf03aff25a6436e7444bf3a`), and
> [#29](https://github.com/marcelodevops/pipebridge/pull/29) (merged at
> `983e2eb2013c45340a786f6064d70c0e71cb92c9`). All four required CI checks
> passed on `983e2eb2013c45340a786f6064d70c0e71cb92c9`:
> <https://github.com/marcelodevops/pipebridge/actions/runs/45069839515>.

## What v0.5.0 is

A **bounded local shared-library migration (`vars/*.groovy`) with script
emission, bounded `withCredentials` string bindings, and single-job
`stash` / `unstash`**, per
[`docs/shared-library-migration-design.md`](shared-library-migration-design.md).
It does not fetch repositories, does not execute Groovy, does not read
secret values, and does not claim Jenkins CPS or runtime equivalence.

## Bounded shared-library resolution

`analyze` and `convert` accept `--library-map PATH`:

```json
{
  "schema_version": 1,
  "libraries": {
    "build-lib": {
      "path": "build-lib"
    }
  }
}
```

- `schema_version` must be the integer `1`.
- Library names must full-match `^[A-Za-z][A-Za-z0-9_-]{0,63}$`.
- Each `path` must be a relative path (no `.`, `..`, backslashes, or
  control characters) inside the map file's directory that resolves to a
  directory containing `vars/`.
- Only eligible prelude annotations (`@Library('name') _` and
  `@Library('name@rev') _`) whose `name` is in `--library-map` are
  resolved. Undeclared map entries emit `PB-LIB-MAP-UNUSED` (info) and
  are never loaded. Unmapped or ineligible `@Library` declarations and
  the declarative `library` section retain `PB-LIB`.
- Each resolved library emits `PB-ASSUME-LIBRARY` (info) recording that
  the local directory was used without running Jenkins resolution or
  fetching/checking `@rev`.
- Reached `vars/<name>.groovy` files are checked for regular-file
  containment inside the library root before reading and parsed
  statically for `def call` and local helper definitions (`String` or
  untyped identifier parameters). Duplicate declarations, built-in step
  shadowing, ambiguous var names across loaded libraries, missing
  definitions, arity mismatches, recursion, and call depth exceeding `20`
  emit `PB-LIB-CALL` with `source_path` and `call_chain` provenance.

## Generated scripts and parameter passing

- Lowered library `sh` steps and parameterized `echo` steps emit
  deterministic scripts under
  `<output>/scripts/<library>/<var>/<function>-<n>.sh`, committed
  transactionally alongside `workflow.yml` and reports via `_write_all`.
- When scripts or `stash`/`unstash` helpers are emitted, `--output` must
  be a relative path under the working directory with no `..` segments,
  and the `<output>/scripts/` tree must be committed alongside
  `workflow.yml` without overriding `defaults.run.working-directory`.
- Literal argument values are never spliced into generated `.sh` files:
  script templates use braced positional parameters (`${1}`, `${2}`, …,
  `${10}`) decoded via structured template parts so literal `$1` / `${1}`
  and escaped `\$` remain literal, while workflow steps invoke
  `bash --noprofile --norc -eo pipefail <script> <argv...>` with
  expression-neutralized, single-quoted arguments.
- `sh(param)` executes parameter-supplied shell text via `argv` using
  `bash --noprofile --norc -eo pipefail -c "${1}"`.
- Unbraced dotted property interpolations (`$x.length`, `$a.b.c`) as well
  as braced non-parameter expressions are rejected with `PB-INTERP`.

## String credential bindings in library calls

- `withCredentials([string(credentialsId: '<lit>', variable: '<NAME>')])`
  inside a library body reuses the existing `CredentialInventory`,
  `--credential-map`, and `--secrets-ready` gate.
- `NAME: "${{ secrets.MAPPED }}"` is emitted only on lowered steps inside
  that binding's scope; sibling steps, `stash`/`unstash`, and implicit
  checkout do not inherit the binding.
- Without `--secrets-ready`, conversion exits `2` (`PB-CRED-SETUP`) with
  a disabled draft (`if: false`) while keeping lowered steps and scripts
  reviewable. `--secrets-ready` remains an unverified acknowledgement
  (`PB-ASSUME-CREDENTIALS`).
- Credential inventory records, `source_path`, and `call_chain` survive
  stage clearing when a stage is blocked.

## Single-job `stash` and `unstash`

- `stash name: '<lit>', includes: '<glob>'[, excludes: '<glob>']` and
  `unstash '<lit>'` are supported in Jenkinsfile stages and library
  bodies using literal names (`^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`) and
  bounded globs (`**`, `*`, `[A-Za-z0-9._-]+`).
- Static job-order validation rejects duplicate stash names and
  `unstash` without a preceding surviving `stash` in the same job
  (`PB-LIB-CALL`). A `stash` in a blocked/cleared stage does not satisfy
  a later `unstash`.
- Emits `scripts/pipebridge_stash.py` and `scripts/pipebridge_unstash.py`
  storing files under `$RUNNER_TEMP/pipebridge-stash/<name>` plus a final
  `Remove pipebridge stash` step (`if: always()`,
  `continue-on-error: true`).
- `pipebridge_stash.py` walks `$GITHUB_WORKSPACE` with
  `followlinks=False`, rejects symlinks (including symlinked directories
  whose descendants could match `includes` after accounting for
  `excludes`) and containment escapes (exit `2`), and fails on zero
  matches (exit `1`).
- `pipebridge_unstash.py` prevalidates all selected source entries as
  regular files and validates all destination parents (directories) and
  existing leaves (regular files) before copying anything.

## Live GitHub Actions validation

Live `workflow_dispatch` validation on `main`
(`f54d56e87b8ca8c94cf03aff25a6436e7444bf3a`) is recorded in
[`docs/shared-library-live-validation.md`](shared-library-live-validation.md):

- Post-merge CI:
  [run `45067676101`](https://github.com/marcelodevops/pipebridge/actions/runs/45067676101)
  — `success`
- Success workflow (`shared-library-success-example.yml`):
  [run `45067732351`](https://github.com/marcelodevops/pipebridge/actions/runs/45067732351)
  — `success` (restored `dist/marker.txt == b"packaged"` and
  `dist/seen.txt == b"ok"`, `$RUNNER_TEMP/pipebridge-stash` removed and
  verified absent)
- Expected-failure workflow (`shared-library-failure-example.yml`):
  [run `45067735656`](https://github.com/marcelodevops/pipebridge/actions/runs/45067735656)
  — `failure` at `Fail (step 2)`, with `Fail (step 3)` (stash) and
  `Restore` skipped and `always()` cleanup verified green.

## Regenerated example artifacts and goldens

- `examples/python-build/migration/workflow.yml`,
  `examples/shared-library/success/migration/workflow.yml`,
  `examples/shared-library/failure/migration/workflow.yml`,
  `.github/workflows/python-build-example.yml`,
  `.github/workflows/shared-library-success-example.yml`,
  `.github/workflows/shared-library-failure-example.yml`,
  `tests/baselines/d2/build-and-test.workflow.yml`, and
  `tests/goldens/pure-declarative/*.workflow.yml` differ **only** in the
  `0.5.0` tool-version header comment.
- `examples/shared-library/*/migration/scripts/*` are byte-for-byte
  unchanged.
- `examples/python-build/migration/migration-report.json` differs in
  `tool.version` (`0.5.0`), `generated_at`, and the additive empty
  `libraries` object (`map_supplied: false`, `conversion_deferred: false`,
  `loaded: []`, `calls: []`) introduced on `main`.
- `examples/shared-library/*/migration/migration-report.{json,md}` differ
  only in `tool.version` (`0.5.0`), `generated_at`, and the worktree
  directory prefix on resolved `source_path` / `call_chain` entries.

## Verification and local package hashes

- Full test suite: **488 passed** (`pytest -q`).
- `actionlint -no-color`: clean across `.github/workflows/*.yml` and
  generated example workflows.
- `scripts/validate-python-build-example.py`: all steps passed with
  `pipebridge 0.5.0`.
- Local preparation wheel and sdist builds (`twine check` **PASSED** for
  both; not uploaded as release assets):
  - `2259aa0187001678b729db731e50d9d855456cc759a3fa2d24c18f3b370a8dee`
    `pipebridge-0.5.0-py3-none-any.whl`
  - `77a2e946ea662116af7aa7e69463737673fee8982bfed8fbd845db1b5e34157a`
    `pipebridge-0.5.0.tar.gz`
- Installed wheel and sdist in separate fresh virtualenvs outside the
  checkout with `PYTHONPATH` unset: both passed all checks for
  `--version`, supported conversion, credential setup gating, overwrite
  protection and `--force`, controlled success and failure script
  execution, unsupported calls, recursion, malformed input, and
  containment failures.

## Known limitations

- Local mapped libraries only (`vars/*.groovy`); no repository fetching,
  no Groovy execution, and no `src/` or `resources/` support.
- Single-job `stash` / `unstash` only
  (`$RUNNER_TEMP/pipebridge-stash/<name>`); no cross-job or matrix
  transfer. Requires `bash` and `python3` on the runner.
- `sh(param)` assumes `bash --noprofile --norc -eo pipefail` semantics.
- Runtime `pipebridge_unstash.py` copy `OSError`s fail non-zero without
  rolling back partial destination changes; multi-file output replacement
  on disk is staged with `OSError` rollback, not crash-atomic across
  process kills.
- In the live expected-failure validation run (`45067735656`), failure
  occurred at `Fail (step 2)` before `stash`, so that run verified
  `always()` cleanup execution after early failure rather than removal of
  a populated stash after failure. A synthetic secret was used for the
  success run, and no comparison against live Jenkins execution was
  performed.
