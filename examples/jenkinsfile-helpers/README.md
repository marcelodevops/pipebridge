# Jenkinsfile postlude helper fixtures (design phase)

> **Status: design fixtures only, not yet converted.** These fixtures accompany
> [`docs/jenkinsfile-helper-translation-design.md`](../../docs/jenkinsfile-helper-translation-design.md)
> and specify the target inputs for the upcoming postlude-helper translation
> milestone. Current `pipebridge` (`0.5.0`) still reports postlude function
> definitions as `PB-GROOVY-POSTLUDE`.

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
