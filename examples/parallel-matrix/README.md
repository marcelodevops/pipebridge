# Declarative Parallel and Matrix Migration Fixtures

> **Status: proposed / planning.** These fixtures accompany
> [`docs/parallel-matrix-migration-design.md`](../../docs/parallel-matrix-migration-design.md)
> and demonstrate the proposed supported grammar, cross-job artifact transfer,
> matrix strategy, and negative validation rules for declarative Jenkins pipelines.

## Fixture Catalog

### Success Fixtures

1. [`success/build-parallel-package.Jenkinsfile`](success/build-parallel-package.Jenkinsfile):
   - **Structure**: Linear `Build` stage -> `parallel` stage with `Unit Tests` and `Lint` branches -> linear `Package` fan-in stage.
   - **Artifacts**: Explicit `stash name: 'dist-bin'` in `Build`, followed by `unstash 'dist-bin'` in `Unit Tests` and `Package`.
   - **Target Behavior**: Translates to 4 distinct GitHub Actions jobs (`build`, `verify-unit-tests`, `verify-lint`, `package`) wired with deterministic `needs:` edges, using `actions/upload-artifact@v4` and `actions/download-artifact@v4` for cross-job file transfer.

2. [`success/matrix-two-axis.Jenkinsfile`](success/matrix-two-axis.Jenkinsfile):
   - **Structure**: Top-level `Cross-Matrix` stage containing a declarative `matrix` block with two axes (`OS`: `ubuntu-latest`, `macos-latest`; `NODE_VERSION`: `18`, `20`) and one exclusion (`macos-latest` + `18`).
   - **Target Behavior**: Translates to a single GitHub Actions job with `strategy.matrix:` and explicit `strategy.fail-fast: false`, preserving YAML scalar quoting on string numbers (`'18'`, `'20'`).

### Negative Diagnostic Fixtures

1. [`negative/missing-artifact.Jenkinsfile`](negative/missing-artifact.Jenkinsfile):
   - `unstash 'nonexistent-bin'` called without any preceding dominating `stash` step.
   - **Expected Diagnostic**: `PB-STASH-MISSING` blocker.

2. [`negative/ambiguous-stash.Jenkinsfile`](negative/ambiguous-stash.Jenkinsfile):
   - Multiple concurrent parallel branches (`Branch A`, `Branch B`) defining `stash name: 'shared-data'`.
   - **Expected Diagnostic**: `PB-STASH-AMBIGUOUS` blocker.

3. [`negative/unmodeled-workspace-transfer.Jenkinsfile`](negative/unmodeled-workspace-transfer.Jenkinsfile):
   - A fan-in stage attempts to read build outputs created in a previous job without an explicit `stash`/`unstash` declaration.
   - **Expected Diagnostic**: `PB-WORKSPACE-TRANSFER` blocker.

4. [`negative/matrix-dynamic-groovy.Jenkinsfile`](negative/matrix-dynamic-groovy.Jenkinsfile):
   - A matrix axis definition uses dynamic Groovy expression evaluation.
   - **Expected Diagnostic**: `PB-INTERP` blocker.
