# Jenkinsfile postlude helper fixtures

> **Status: implemented.** These fixtures accompany
> [`docs/jenkinsfile-helper-translation-design.md`](../../docs/jenkinsfile-helper-translation-design.md)
> and exercise bounded translation of top-level `def <helper>(...) { ... }`
> functions defined after the `pipeline { ... }` block.

## Commands

Analyze or convert the success fixture from the repository root:

```sh
pipebridge analyze examples/jenkinsfile-helpers/success/Jenkinsfile --format json

pipebridge convert examples/jenkinsfile-helpers/success/Jenkinsfile \
  --output examples/jenkinsfile-helpers/success/migration
```

That conversion exits `0`, generates `workflow.yml` plus reports, and writes
`scripts/_jenkinsfile/writeReleaseMarker-1.sh` and
`scripts/_jenkinsfile/publishChannel-1.sh` (each reused across both
`publishChannel(...)` calls). Commit `<output>/scripts/` alongside
`workflow.yml` when deploying to a repository.

Analyze any negative fixture (each exits `2` with explicit blockers):

```sh
pipebridge analyze examples/jenkinsfile-helpers/negative/unsupported-body.Jenkinsfile
pipebridge analyze examples/jenkinsfile-helpers/negative/captured-variable.Jenkinsfile
pipebridge analyze examples/jenkinsfile-helpers/negative/recursion.Jenkinsfile
pipebridge analyze examples/jenkinsfile-helpers/negative/collision-builtin.Jenkinsfile
pipebridge analyze examples/jenkinsfile-helpers/negative/collision-library-var.Jenkinsfile \
  --library-map examples/shared-library/success/library-map.json
pipebridge analyze examples/jenkinsfile-helpers/negative/collision-duplicate-helper.Jenkinsfile
pipebridge analyze examples/jenkinsfile-helpers/negative/mixed-executable-postlude.Jenkinsfile
```

## Layout

- [`success/Jenkinsfile`](success/Jenkinsfile) — declarative pipeline calling a
  top-level postlude helper `publishChannel(channel, tag)` twice with distinct
  literal arguments (`'alpha', 'build-1'` and `'beta', 'build-2'`).
  `publishChannel` forwards its bare in-scope parameters to a second same-file
  postlude helper `writeReleaseMarker(channel, tag)` and runs a parameterized
  `echo`. Demonstrates literal argument passing, same-file helper forwarding,
  and generated script reuse under `scripts/_jenkinsfile/`.
- [`negative/unsupported-body.Jenkinsfile`](negative/unsupported-body.Jenkinsfile) —
  called postlude helper whose body contains an unsupported `script { ... }`
  block (`PB-LIB-CALL` with call chain).
- [`negative/captured-variable.Jenkinsfile`](negative/captured-variable.Jenkinsfile) —
  prelude variable `GLOBAL_ENV` captured inside a postlude helper string
  interpolation (`PB-GROOVY-PRELUDE` and `PB-INTERP` with call chain).
- [`negative/recursion.Jenkinsfile`](negative/recursion.Jenkinsfile) — mutual
  recursion between two postlude helpers `firstStep` and `secondStep`
  (`PB-LIB-CALL` call cycle with call chain).
- [`negative/collision-builtin.Jenkinsfile`](negative/collision-builtin.Jenkinsfile) —
  postlude helper `def sh(String cmd)` shadowing built-in step `sh`
  (`PB-LIB-CALL`, pipeline blocked).
- [`negative/collision-library-var.Jenkinsfile`](negative/collision-library-var.Jenkinsfile) —
  postlude helper `def publish(String label)` colliding with a declared, mapped
  `@Library('build-lib') _` `vars/publish.groovy` entry (`PB-LIB-CALL`,
  pipeline blocked).
- [`negative/collision-duplicate-helper.Jenkinsfile`](negative/collision-duplicate-helper.Jenkinsfile) —
  duplicate postlude helper name `def deploy(...)` in the same Jenkinsfile
  (`PB-LIB-CALL`, pipeline blocked).
- [`negative/mixed-executable-postlude.Jenkinsfile`](negative/mixed-executable-postlude.Jenkinsfile) —
  a valid called postlude helper mixed with an unused postlude helper and a
  top-level executable statement `println 'postlude side effect'`
  (`PB-GROOVY-POSTLUDE`, pipeline blocked, no scripts emitted).
