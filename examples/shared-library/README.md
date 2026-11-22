# shared-library

Fixtures for [the shared-library migration design](../../docs/shared-library-migration-design.md).

`success/` is the representative case: a `vars/publish.groovy` helper runs shell, forwards a literal argument, uses one bounded `string` credential binding (`npm-token` -> `NPM_TOKEN_GH`), and stashes files (`dist/**`) that a later stage restores (`unstash 'dist'`). The library root is `build-lib/` because the repository `.gitignore` ignores `lib/`.

`failure/` converts with exit `0` and an enabled workflow, then fails at runtime on `exit 1` before `echo restored`.

## Map schemas

`library-map.json`:

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

`credential-map.json`:

```json
{
  "schema_version": 1,
  "credentials": {
    "npm-token": {
      "secret": "NPM_TOKEN_GH"
    }
  }
}
```

## Analyze and convert commands

Run from the repository root (note `--output` must be a relative path with no `..` segments when `scripts/` are emitted):

```sh
# Analyze success fixture (JSON report to stdout, writes nothing)
pipebridge analyze examples/shared-library/success/Jenkinsfile --format json \
  --library-map examples/shared-library/success/library-map.json \
  --credential-map examples/shared-library/success/credential-map.json

# Convert without --secrets-ready: exits 2, emits disabled draft (PB-CRED-SETUP) with reviewable scripts
pipebridge convert examples/shared-library/success/Jenkinsfile \
  --library-map examples/shared-library/success/library-map.json \
  --credential-map examples/shared-library/success/credential-map.json \
  --output examples/shared-library/success/migration

# Convert with --secrets-ready (unverified acknowledgement that NPM_TOKEN_GH exists): exits 0
pipebridge convert examples/shared-library/success/Jenkinsfile \
  --library-map examples/shared-library/success/library-map.json \
  --credential-map examples/shared-library/success/credential-map.json \
  --secrets-ready \
  --force \
  --output examples/shared-library/success/migration

# Convert intentional-failure fixture (no credentials): exits 0
pipebridge convert examples/shared-library/failure/Jenkinsfile \
  --library-map examples/shared-library/failure/library-map.json \
  --output examples/shared-library/failure/migration
```

## Generated scripts and limitations

- Generated scripts are written to `<output>/scripts/<library>/<var>/<function>-<n>.sh`, `<output>/scripts/pipebridge_stash.py`, and `<output>/scripts/pipebridge_unstash.py`. Commit the `<output>/scripts/` tree alongside `workflow.yml` and do not override `defaults.run.working-directory`.
- Local mapped libraries only: pipebridge never fetches repositories, invokes `gh`, reads secret values, or executes Groovy.
- Single-job `stash`/`unstash` only (`$RUNNER_TEMP/pipebridge-stash/<name>`), requiring `bash` and `python3` on the runner. Runtime restore `OSError`s fail non-zero and may leave partial destination changes; output replacement on disk is staged with `OSError` rollback but is not crash-atomic across process kills.
