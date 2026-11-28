# Design — Declarative Parallel and Matrix Migration to GitHub Actions

> **Status: proposed / planning.** This document specifies the architectural design
> for migrating Jenkins Declarative Pipeline `parallel` and `matrix` stages to
> GitHub Actions workflows. It is based on `origin/main`
> (`3b4aaf0c444c12f6fefa75fa7b38d8397f173b28`) and establishes the execution
> graph, cross-job artifact transfer, and matrix configuration for implementation
> across three bounded increments. Accompanying synthetic fixtures are located
> under [`examples/parallel-matrix/`](../examples/parallel-matrix/).

---

## 1. Problem and Current Behavior

Declarative Jenkinsfiles frequently use `parallel` stages to fan out independent test,
lint, or packaging suites across separate worker threads or agent nodes, and use
`matrix` stages to evaluate multidimensional build configurations across platforms,
compilers, and runtimes.

Today, on `origin/main` (`3b4aaf0`), pipebridge treats any `parallel` or `matrix`
declaration as an immediate blocker:

| Construct | Current Behavior on `origin/main` (`3b4aaf0`) |
| :--- | :--- |
| `stage('...') { parallel { ... } }` | `_parse_stage()` in `src/pipebridge/parser.py` emits `PB-PARALLEL` (`parallel execution`), marks the enclosing stage blocked (`_mark_stage_blocked()`), diagnoses the inner block for syntax and opaque boundaries, and generates a placeholder failing step in the single sequential job `migrated-pipeline`. |
| `stage('...') { matrix { ... } }` | `_parse_stage()` in `src/pipebridge/parser.py` emits `PB-MATRIX` (`matrix execution`), marks the enclosing stage blocked (`_mark_stage_blocked()`), diagnoses axes and inner stages, and generates a placeholder failing step in the single sequential job `migrated-pipeline`. |
| Cross-stage file transfer | `stash` and `unstash` are validated only within a single job (`validate_job_stashes()` in `src/pipebridge/stash.py`). Cross-job transfer is unsupported because pipebridge emits exactly one GitHub Actions job (`migrated-pipeline`). |
| Pipeline execution model | The intermediate representation (`Pipeline` in `src/pipebridge/model.py`) assumes a strictly linear list of `Stage` objects compiled into a single GitHub Actions job with an implicit initial `actions/checkout`. |

### Key Gap

In GitHub Actions, parallel execution cannot be achieved inside a single job. Steps
within a job execute strictly sequentially on a single virtual machine runner. To execute
stages in parallel or evaluate matrix configurations, pipebridge must compile the
linear stage pipeline into an **execution graph (DAG) of distinct GitHub Actions jobs**
connected by `needs:` dependencies, while preserving linear sequential execution within
individual stages, handling workspace isolation cleanly, and transferring explicitly
stashed files across runner boundaries.

---

## 2. Goals and Non-Goals

### 2.1 Goals

1. **Execution Graph & Declarative Parallel (Increment 1)**:
   - Compile top-level sequential stages, `parallel` branch stages, and post-parallel
     fan-in stages into deterministic GitHub Actions jobs connected by `needs:` edges.
   - Preserve linear execution ordering: stages before `parallel` finish before branches
     start; parallel branches execute concurrently; stages after `parallel` run only after
     all branch jobs complete successfully.
   - Derive deterministic, collision-free GitHub Actions job IDs from stage and branch names.
2. **Cross-Job Stash / Unstash through Artifacts (Increment 2)**:
   - Lower cross-job `stash` calls to `actions/upload-artifact@v4` and `unstash` calls
     to `actions/download-artifact@v4`.
   - Validate stash producer-consumer relationships statically over the DAG: ensure
     unique artifact names, detect missing or ambiguous producers, and enforce
     reachability.
   - Maintain fast local python-based stash/unstash when operations remain within a
     single job boundary.
3. **Literal Matrix Axes and Exclusions (Increment 3)**:
   - Lower Jenkins Declarative `matrix` stages into GitHub Actions jobs parameterized
     with `strategy.matrix`.
   - Support literal axis definitions (`axis { name '...'; values '...' }`) and literal
     exclusions (`excludes { exclude { axis { ... } } }`).
   - Reconcile failure defaults: explicitly emit `strategy.fail-fast: false` to match
     Jenkins' default behavior (unless Jenkins explicitly set `failFast true`).
   - Expose matrix coordinates to cell steps as environment variables, preserving exact
     YAML string representations (e.g. `'3.10'`, `'true'`, `'on'`).
4. **Preserve Compatibility & Guarantees**:
   - Maintain 100% byte-identical workflow output for existing sequential pipelines that
     do not use `parallel` or `matrix`.
   - Retain all security and safety invariants: step-scoped secret injection via
     `withCredentials`, neutralized GitHub expressions (`PB-GHEXPR`), shared-library
     and postlude-helper lowering under `scripts/`, and overwrite refusal.

### 2.2 Non-Goals

- Translating dynamic Groovy code, closures, loops, or scripted pipeline `parallel` maps
  (`parallel branch1: { ... }, branch2: { ... }`).
- Translating matrix axes defined by dynamic expressions, environment variables, or Groovy
  function calls.
- Inferring implicit filesystem dependencies across jobs or automatically creating
  tarballs of the entire runner workspace.
- Using GitHub Actions `concurrency:` groups as a mechanism for intra-workflow parallel
  execution.
- Simulating heterogeneous cross-job `failFast: true` via privileged API calls or
  third-party workflow-cancelling actions.

---

## 3. Accepted Grammar and Lowering Semantics

### 3.1 Declarative `parallel` Grammar

A `parallel` block is valid only inside a top-level `stage`:

```groovy
stage('Verify') {
    parallel {
        stage('Unit Tests') {
            environment { SUITE = 'unit' }
            steps {
                sh 'pytest tests/unit'
            }
        }
        stage('Lint') {
            environment { SUITE = 'lint' }
            steps {
                sh 'flake8 src/'
            }
        }
    }
}
```

**Grammar Rules**:
1. An enclosing `stage` containing a `parallel` block MUST NOT contain a `steps` block,
   `matrix` block, or `stages` block at the same level (official Jenkins Declarative syntax).
2. Inside `parallel { ... }`, each entry must be a `stage('<name>') { ... }`.
3. Each branch stage may declare its own `agent`, `environment`, and `steps` block.
4. Nested `parallel` inside a parallel branch is rejected (`PB-PARALLEL` with nested
   scope message).
5. Branch names within a `parallel` block must be non-empty and mutually distinct.

### 3.2 Declarative `matrix` Grammar

A `matrix` block is valid only inside a top-level `stage`:

```groovy
stage('Cross-Platform Test') {
    matrix {
        axes {
            axis {
                name 'PLATFORM'
                values 'ubuntu-latest', 'macos-latest'
            }
            axis {
                name 'PYTHON_VERSION'
                values '3.10', '3.11', '3.12'
            }
        }
        excludes {
            exclude {
                axis {
                    name 'PLATFORM'
                    values 'macos-latest'
                }
                axis {
                    name 'PYTHON_VERSION'
                    values '3.10'
                }
            }
        }
        stages {
            stage('Test') {
                steps {
                    sh 'python -m pytest'
                }
            }
        }
    }
}
```

**Grammar Rules**:
1. An enclosing `stage` containing a `matrix` block MUST NOT contain a `steps` block or
   `parallel` block at the same level.
2. `axes { ... }` requires at least one `axis { name '...'; values '...' }`.
3. Axis names must match `^[A-Za-z_][A-Za-z0-9_]{0,63}$` and cannot collide with reserved
   workflow keys (`matrix`, `env`, `job`, `steps`, `runner`).
4. Values must be literal strings, booleans, or numbers. Dynamic Groovy or variable
   interpolation is rejected (`PB-INTERP`).
5. `excludes { ... }` is optional; each `exclude { ... }` must reference valid axis names
   and declare one or more axis coordinate filters.
6. `stages { ... }` requires one or more sequential stages that execute within each matrix
   cell.

### 3.3 Cross-Job `stash` and `unstash` Grammar

The existing bounded argument grammar for `stash` and `unstash` is retained:
- `stash name: '<lit>', includes: '<glob>'[, excludes: '<glob>']`
- `unstash '<lit>'`

When `stash` and `unstash` occur in different jobs, pipebridge compiles them to artifact
upload and download steps instead of local Python runner scripts.

---

## 4. Required Design Decisions

### 4.1 Execution Graph, DAG Scheduling, and Fan-In

**Decision: Contiguous sequential stages before a parallel block are coalesced into an upstream job; each parallel branch becomes an independent job; post-parallel stages coalesce into downstream fan-in jobs.**

```
[ stage: Build ] (Job: build)
       │
       ├────────────────────────┐
       ▼                        ▼
[ stage: Unit Tests ]     [ stage: Lint ]
(Job: test-unit)          (Job: test-lint)
needs: [build]            needs: [build]
       │                        │
       └────────────────────────┘
       ▼
[ stage: Package ] (Job: package)
needs: [test-unit, test-lint]
```

1. **Job ID Determinism & Slugification**:
   - Job IDs in GitHub Actions workflows must match `^[a-zA-Z_][a-zA-Z0-9_-]*$`.
   - Pipebridge normalizes stage and branch names using a deterministic slug function:
     1. Convert to lowercase.
     2. Replace spaces and non-alphanumeric characters (except `_` and `-`) with `-`.
     3. Strip leading/trailing hyphens and collapse consecutive hyphens into a single `-`.
     4. Prefix with `job-` if the first character is not `[a-zA-Z_]`.
     5. If duplicate IDs arise in the same workflow, append `-1`, `-2` in source order.
   - Example: `stage('Build & Prepare')` -> `build-prepare`.
   - Example branch: `stage('Verify') { parallel { stage('Unit (x86)') ... } }` ->
     `verify-unit-x86`.

2. **Dependency Edges (`needs:`)**:
   - The first job in a workflow has no `needs:` key.
   - Parallel branch jobs set `needs: [<upstream_job_id>]`.
   - The first sequential stage following a parallel block (the fan-in stage) sets
     `needs: [<branch1_id>, <branch2_id>, ...]`.
   - By default in GitHub Actions, a job with `needs: [A, B]` runs only when all
     prerequisites evaluate to `success()`. This precisely mirrors Jenkins' default
     fan-in condition (a downstream stage runs only if all upstream parallel branches
     succeeded).

3. **Sequential Pipeline Invariant**:
   - A pipeline consisting solely of sequential stages with no `parallel` or `matrix`
     constructs continues to compile into a single `migrated-pipeline` job, guaranteeing
     **byte-identical output** with earlier Pipebridge releases.

---

### 4.2 Job Partitioning vs. `strategy.matrix` vs. Concurrency Groups

**Decision: Heterogeneous parallel branches become separate DAG jobs. Homogeneous combinatorial axes become a single job with `strategy.matrix`. Concurrency groups are strictly prohibited as a mechanism for intra-workflow parallelism.**

1. **Heterogeneous Branches (`parallel`) -> Separate Jobs**:
   - In Declarative Jenkins, parallel branches frequently execute entirely different
     scripts, require different tools, have distinct environment variables, or use
     differing agent labels.
   - These are lowered into distinct top-level jobs under `jobs:`.

2. **Homogeneous Variants (`matrix`) -> Single Matrix Job**:
   - When a matrix stage evaluates the same sequence of steps across multiple parameter
     combinations, it lowers into a single top-level job with a `strategy.matrix:` block.
   - GitHub Actions executes each matrix cell as an independent runner instance, while
     maintaining a single job definition in the workflow YAML.

3. **Concurrency Groups Prohibition**:
   - GitHub Actions `concurrency:` groups (e.g. `concurrency: group-${{ github.ref }}`)
     operate at the workflow or job level to cancel or serialize *different workflow runs*
     on the same branch/ref.
   - Concurrency groups cannot fan out work within a single workflow run, and attempting
     to use them to model parallel branches would serialize execution or cause runs to
     cancel each other. Concurrency groups are never emitted for `parallel` or `matrix`.

---

### 4.3 Failure Behavior: Jenkins vs. GitHub Defaults and `fail-fast`

**Decision: In matrix jobs, pipebridge MUST explicitly emit `strategy.fail-fast: false` by default. For heterogeneous parallel jobs, GitHub Actions DAG semantics are retained and cross-job fail-fast is not claimed.**

1. **Matrix Default Inversion**:
   - **Jenkins Declarative Default**: If a matrix cell fails, Jenkins continues running
     sibling cells until all finish (`failFast false`).
   - **GitHub Actions Default**: GitHub's default for `strategy.matrix` is
     `fail-fast: true` (if any matrix cell fails, all in-progress cell runners are
     immediately cancelled).
   - **Resolution**: To prevent accidental cancellation of sibling tests, pipebridge
     **always explicitly generates `fail-fast: false`** in `strategy:` unless the
     Jenkinsfile explicitly specified `failFast true`:
     ```yaml
     strategy:
       fail-fast: false
       matrix:
         ...
     ```

2. **Heterogeneous Parallel Jobs (`parallel`)**:
   - In GitHub Actions, independent jobs in a DAG run concurrently without shared
     lifecycle controls. If job `test-unit` fails, job `test-lint` continues running to
     completion. Downstream job `package` (`needs: [test-unit, test-lint]`) is skipped.
   - This matches Jenkins' default `failFast false` behavior.
   - **Handling Jenkins `failFast: true` on `parallel`**: GitHub Actions does not provide
     a native declaration to abort running sibling jobs in a DAG without external API
     tokens calling `actions/runs/{id}/cancel`. Pipebridge will **not** inject privileged
     API scripts or unverified third-party actions; if a Jenkinsfile specifies
     `failFast: true` on a heterogeneous `parallel` block, pipebridge will emit warning
     `PB-PARALLEL-FAILFAST` explaining that GitHub Actions will let sibling jobs complete.

---

### 4.4 Workspace Isolation: Fresh Runner per Job

**Decision: Every GitHub Actions job executes in a fresh, isolated workspace. Pipebridge never infers arbitrary file dependencies or uploads whole-workspace tarballs.**

1. **Clean Checkout per Job**:
   - Every generated job in the workflow begins with:
     ```yaml
     - name: Checkout source (implicit)
       uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
     ```
   - Uncommitted files, build outputs, and downloaded packages created in Job A do
     **not** exist in Job B.

2. **No Whole-Workspace Inference**:
   - Automatically tarring and uploading the entire workspace directory across jobs is
     prohibited:
     - It wastes runner bandwidth and storage on build caches (`.git`, `node_modules`,
       `.venv`, `.gradle`).
     - It creates severe security risks by propagating ephemeral state, temporary tokens,
       and unscrubbed files.
     - It masks broken builds where dependencies between stages were implicit.
   - Files needed across jobs MUST be declared via `stash` and `unstash`.

---

### 4.5 Artifact-Backed Cross-Job Stash and Unstash

**Decision: Cross-job file transfer lowers to pinned `actions/upload-artifact@v4` and `actions/download-artifact@v4` with deterministic names, 1-day retention, and static producer-consumer validation.**

1. **Step Lowering**:
   - In the producer job:
     ```yaml
     - name: Stash "build-artifacts" (actions/upload-artifact)
       uses: actions/upload-artifact@b4b15b8c7c6ac21ea08fcf65892d2ee8f75cf882 # v4.4.3
       with:
         name: pb-stash-build-artifacts
         path: |
           dist/**
           !dist/*.tmp
         retention-days: 1
         if-no-files-found: error
     ```
   - In consumer jobs:
     ```yaml
     - name: Unstash "build-artifacts" (actions/download-artifact)
       uses: actions/download-artifact@fa0a91b85d4f404e444e00e005971372dc801d16 # v4.1.8
       with:
         name: pb-stash-build-artifacts
         path: .
     ```

2. **Artifact Naming Conventions**:
   - Standard cross-job stash: `pb-stash-<stash_name>`.
   - Matrix cell stash: When a matrix cell stashes artifacts, the artifact name must
     interpolate the cell's coordinates to avoid upload collisions:
     `pb-stash-<stash_name>-${{ matrix.PLATFORM }}-${{ matrix.PYTHON_VERSION }}`.

3. **Static Validation Rules**:
   - **Unique Producer Rule**: A stash name may be produced by at most one upstream job
     dominating the consumer. Two parallel branches cannot both produce `stash 'output'`
     under the same name (`PB-STASH-AMBIGUOUS`).
   - **Precedence Rule**: An `unstash` step must be preceded in the DAG by a job that
     produces that stash name (`PB-STASH-MISSING`).
   - **Path Containment**: The `path:` parameter in `upload-artifact` is validated
     using existing `valid_stash_glob()` to ensure globs do not escape workspace
     containment (`..`, absolute paths).

4. **Permissions, Metadata, and Retention**:
   - `actions/upload-artifact@v4` preserves POSIX file permission bits (`+x`), making
     compiled binaries runnable upon download without extra `chmod` calls.
   - `retention-days: 1` is configured to prevent pipeline storage buildup while
     guaranteeing availability for downstream jobs during the workflow execution.

---

### 4.6 Handling Inherited Workspaces and Unresolved Dependencies

**Decision: Workspaces are modeled explicitly. If a downstream stage relies on uncommitted files without a matching `stash`/`unstash`, pipebridge reports `PB-WORKSPACE-TRANSFER`.**

In Jenkins on a single node, Stage 2 can access files written by Stage 1 directly on disk.
In GitHub Actions, Job 2 cannot.

1. **Modeled Pipelines**: Pipelines using explicit `stash` and `unstash` are fully
   supported and converted cleanly into artifact transfer.
2. **Unmodeled State**: If a stage following a parallel fan-in executes packaging steps
   (e.g. `tar -czf app.tar.gz dist/`) without an upstream `stash 'dist'` and corresponding
   `unstash 'dist'`, pipebridge cannot prove that `dist/` will exist on the fresh runner.
   - Pipebridge reports `PB-WORKSPACE-TRANSFER` (severity: blocker) alerting the user
     that the stage boundary requires an explicit stash/unstash declaration or pipeline
     refactoring.

---

### 4.7 Environment Scope, Secret Injection, and Script Availability

**Decision: Environment scopes map hierarchically to workflow, job, and step levels. Secrets are injected strictly into step-level environments. Generated helper scripts are available to all jobs via repository checkout.**

1. **Hierarchical Environment Scoping**:
   - Pipeline-level `environment { FOO = 'bar' }` -> top-level `env:` in the workflow.
   - Stage-level `environment { STAGE_VAR = 'val' }` -> job-level `env:` in the corresponding job.
   - Parallel branch-level `environment { BRANCH_VAR = 'bval' }` -> branch job-level `env:`.
   - Matrix cell coordinates -> automatically injected by GitHub Actions into `matrix.<AXIS>`
     and mirrored into job `env:` as `<AXIS>: ${{ matrix.<AXIS> }}`.

2. **Step-Only Secret Injection**:
   - Secrets mapped via `withCredentials([string(credentialsId: 'SECRET_ID', variable: 'TOKEN')])`
     are **never lifted to job-level `env:`**.
   - They are mapped strictly into the `env:` block of the individual steps inside that
     `withCredentials` block:
     ```yaml
     - name: Step calling API
       run: bash --noprofile --norc -eo pipefail scripts/_jenkinsfile/callApi-1.sh
       env:
         TOKEN: ${{ secrets.MAPPED_SECRET_ID }}
     ```

3. **Generated Script Availability Across Jobs**:
   - Generated scripts for shared libraries (`scripts/<lib>/*.sh`) and postlude helpers
     (`scripts/_jenkinsfile/*.sh`) reside in the repository root.
   - Because every generated job performs `actions/checkout`, the entire `scripts/`
     directory is present on every job runner. No extra artifact upload is required for
     Pipebridge's lowered shell scripts.

---

### 4.8 Runner Mapping for Parallel Branches and Matrix Cells

**Decision: Runner configurations map from Jenkins `agent` blocks. Matrix axis values are never assumed to be runner names without explicit mapping.**

1. **Default Runner**: If pipeline or stage specifies `agent any`, the job sets
   `runs-on: ubuntu-latest`.
2. **Stage Agent Labels**: If a stage specifies `agent { label 'linux-gpu' }`, pipebridge
   uses the existing `agent-label` mapping system to set `runs-on: [self-hosted, gpu]`.
3. **Matrix Runner Mapping**:
   - If an axis is named `PLATFORM` or `OS`, values like `'ubuntu-latest'`, `'macos-latest'`,
     `'windows-latest'` can be used in `runs-on: ${{ matrix.PLATFORM }}` ONLY if every
     value matches known valid GitHub runner labels.
   - Arbitrary axis names (e.g. `TARGET_OS: 'linux'`) are NOT assumed to be runner labels;
     the job sets static `runs-on: ubuntu-latest` unless an explicit mapping is configured.

---

### 4.9 Literal Matrix Axes, Exclusions, Typing, and Limits

**Decision: Matrix axes require literal values. Strings, numbers, and booleans are preserved with exact YAML quoting. Expansion is capped at 256 cells.**

1. **YAML Scalar Quoting**:
   - Axis values such as `'3.10'`, `'true'`, `'off'`, `'yes'`, `'none'` must be emitted
     as quoted YAML strings to prevent YAML parsers from converting them into floats
     (`3.1`) or booleans (`true`):
     ```yaml
     strategy:
       matrix:
         PYTHON_VERSION: ["3.10", "3.11", "3.12"]
         DEBUG: ["true", "false"]
     ```

2. **Exclusions Mapping**:
   - Jenkins `excludes { exclude { axis { name 'X'; values '1' } axis { name 'Y'; values '2' } } }`
     compiles directly to:
     ```yaml
     strategy:
       matrix:
         X: ["1", "2"]
         Y: ["1", "2"]
         exclude:
           - X: "1"
             Y: "2"
     ```

3. **Expansion Limits**:
   - GitHub Actions imposes a hard limit of **256 matrix jobs** per workflow run.
   - Pipebridge computes the total number of cells ($N = \prod |values| - |excludes|$)
     statically during analysis. If $N > 256$, pipebridge emits blocker `PB-MATRIX-LIMIT`.

---

### 4.10 Backward Compatibility, Model Architecture, and Reporting

**Decision: Workflows without `parallel` or `matrix` retain byte-identical output. The model introduces `JobGraph` and `JobNode` to represent DAG structures.**

1. **Intermediate Model Evolution**:
   - `src/pipebridge/model.py` introduces:
     ```python
     @dataclass
     class JobNode:
         id: str
         name: str
         needs: list[str]
         runs_on: list[str]
         env: list[EnvVar]
         stages: list[Stage]
         matrix: MatrixConfig | None = None
         blocked: bool = False

     @dataclass
     class JobGraph:
         jobs: list[JobNode]
         edges: list[tuple[str, str]]
     ```
   - For sequential pipelines, `JobGraph` contains exactly one `JobNode` (`migrated-pipeline`).
   - `generate_workflow()` uses the existing single-job code path when `len(job_graph.jobs) == 1`,
     guaranteeing **100% byte-identical workflow output** for existing test baselines.

2. **Migration Report Schema**:
   - The JSON and Markdown reports are extended with a `jobs` breakdown:
     - Lists each job ID, its dependencies (`needs`), whether it runs as a matrix, and its
       blocker status.
   - If any job in the graph has blockers, the entire workflow or the affected job branch
     is disabled with `if: false`. Runnable partial workflows are never emitted.

---

## 5. Runnable Acceptance Examples

### 5.1 Build -> Parallel Unit/Lint -> Package (with Artifact Transfer)

Jenkins Declarative Pipeline:

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'mkdir -p dist && echo "build v1" > dist/app.bin'
                stash name: 'dist-bin', includes: 'dist/**'
            }
        }
        stage('Verify') {
            parallel {
                stage('Unit Tests') {
                    steps {
                        unstash 'dist-bin'
                        sh 'test -f dist/app.bin && echo "Unit tests passed"'
                    }
                }
                stage('Lint') {
                    steps {
                        sh 'echo "Lint passed"'
                    }
                }
            }
        }
        stage('Package') {
            steps {
                unstash 'dist-bin'
                sh 'tar -czf dist/app.tar.gz dist/app.bin'
            }
        }
    }
}
```

Generated GitHub Actions Workflow:

```yaml
# Generated by pipebridge 0.6.0 — DO NOT EDIT BY HAND.
name: Migrated Jenkins pipeline
on:
  workflow_dispatch:
permissions:
  contents: read
defaults:
  run:
    shell: bash

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout source (implicit)
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: sh
        run: bash --noprofile --norc -eo pipefail -c 'mkdir -p dist && echo "build v1" > dist/app.bin'
      - name: Stash "dist-bin" (actions/upload-artifact)
        uses: actions/upload-artifact@b4b15b8c7c6ac21ea08fcf65892d2ee8f75cf882 # v4.4.3
        with:
          name: pb-stash-dist-bin
          path: dist/**
          retention-days: 1
          if-no-files-found: error

  verify-unit-tests:
    needs: [build]
    runs-on: ubuntu-latest
    steps:
      - name: Checkout source (implicit)
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Unstash "dist-bin" (actions/download-artifact)
        uses: actions/download-artifact@fa0a91b85d4f404e444e00e005971372dc801d16 # v4.1.8
        with:
          name: pb-stash-dist-bin
          path: .
      - name: sh
        run: bash --noprofile --norc -eo pipefail -c 'test -f dist/app.bin && echo "Unit tests passed"'

  verify-lint:
    needs: [build]
    runs-on: ubuntu-latest
    steps:
      - name: Checkout source (implicit)
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: sh
        run: bash --noprofile --norc -eo pipefail -c 'echo "Lint passed"'

  package:
    needs: [verify-unit-tests, verify-lint]
    runs-on: ubuntu-latest
    steps:
      - name: Checkout source (implicit)
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Unstash "dist-bin" (actions/download-artifact)
        uses: actions/download-artifact@fa0a91b85d4f404e444e00e005971372dc801d16 # v4.1.8
        with:
          name: pb-stash-dist-bin
          path: .
      - name: sh
        run: bash --noprofile --norc -eo pipefail -c 'tar -czf dist/app.tar.gz dist/app.bin'
```

---

### 5.2 Two-Axis Matrix with Exclusion and Cell Coordinates

Jenkins Declarative Pipeline:

```groovy
pipeline {
    agent any
    stages {
        stage('Cross-Matrix') {
            matrix {
                axes {
                    axis {
                        name 'OS'
                        values 'ubuntu-latest', 'macos-latest'
                    }
                    axis {
                        name 'NODE_VERSION'
                        values '18', '20'
                    }
                }
                excludes {
                    exclude {
                        axis {
                            name 'OS'
                            values 'macos-latest'
                        }
                        axis {
                            name 'NODE_VERSION'
                            values '18'
                        }
                    }
                }
                stages {
                    stage('Run Test') {
                        steps {
                            sh 'echo "Testing on ${OS} with Node ${NODE_VERSION}"'
                        }
                    }
                }
            }
        }
    }
}
```

Generated GitHub Actions Workflow:

```yaml
# Generated by pipebridge 0.6.0 — DO NOT EDIT BY HAND.
name: Migrated Jenkins pipeline
on:
  workflow_dispatch:
permissions:
  contents: read
defaults:
  run:
    shell: bash

jobs:
  cross-matrix:
    runs-on: ${{ matrix.OS }}
    strategy:
      fail-fast: false
      matrix:
        OS: ["ubuntu-latest", "macos-latest"]
        NODE_VERSION: ["18", "20"]
        exclude:
          - OS: "macos-latest"
            NODE_VERSION: "18"
    steps:
      - name: Checkout source (implicit)
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: sh
        run: bash --noprofile --norc -eo pipefail -c "echo \"Testing on ${OS} with Node ${NODE_VERSION}\""
        env:
          OS: ${{ matrix.OS }}
          NODE_VERSION: ${{ matrix.NODE_VERSION }}
```

---

### 5.3 Sibling Failure Behavior and Fan-In Gating

- **Scenario**: In `verify-unit-tests` and `verify-lint`, suppose `verify-unit-tests` fails.
- **Sibling Behavior**: In GitHub Actions, `verify-lint` continues running independently.
- **Fan-in Gating**: `package` requires `needs: [verify-unit-tests, verify-lint]`. Because the
  default job condition in GitHub Actions is `success()`, `package` is skipped automatically.
  This exact behavior matches Jenkins Declarative defaults.

---

### 5.4 Missing and Ambiguous Stash Producer Diagnostics

1. **Missing Stash Producer**:
   ```groovy
   stage('Lint') {
       steps {
           unstash 'nonexistent-stash'
       }
   }
   ```
   - Analysis Result: Blocker `PB-STASH-MISSING` at line 3, col 9:
     `unstash 'nonexistent-stash' has no preceding stash step in any upstream job.`
2. **Ambiguous Stash Producer Across Parallel Branches**:
   ```groovy
   stage('Test') {
       parallel {
           stage('Branch A') { steps { stash name: 'shared', includes: '*.log' } }
           stage('Branch B') { steps { stash name: 'shared', includes: '*.log' } }
       }
   }
   ```
   - Analysis Result: Blocker `PB-STASH-AMBIGUOUS` at line 5, col 41:
     `stash name 'shared' is defined in multiple parallel branches ('Branch A', 'Branch B'); artifact names must be unique across concurrent jobs.`

---

### 5.5 Helpers and Mapped Credentials Inside Parallel Branches

```groovy
pipeline {
    agent any
    stages {
        stage('Deploy') {
            parallel {
                stage('Staging') {
                    steps {
                        withCredentials([string(credentialsId: 'STAGING_KEY', variable: 'KEY')]) {
                            publishChannel('staging', KEY)
                        }
                    }
                }
                stage('Prod') {
                    steps {
                        withCredentials([string(credentialsId: 'PROD_KEY', variable: 'KEY')]) {
                            publishChannel('prod', KEY)
                        }
                    }
                }
            }
        }
    }
}
def publishChannel(String envName, String token) {
    sh 'echo "Deploying to " + envName'
}
```

- Each parallel branch job (`deploy-staging`, `deploy-prod`) receives the lowered
  `publishChannel` step and generated script `scripts/_jenkinsfile/publishChannel-1.sh`.
- Secrets `STAGING_KEY` and `PROD_KEY` are bound strictly to their respective step
  `env:` blocks inside their separate runner jobs, preventing secret leakage across
  branches.

---

## 6. Implementation Plan: Three Bounded Increments

```
Increment 1: Execution Graph & Parallel
├── Intermediate Model: JobGraph, JobNode, Edges
├── Parser: AST recognition of stage-level `parallel`
├── Linear prefix & suffix coalescing into DAG jobs
├── Deterministic job slugification & needs: wiring
└── Unit & integration test suite

Increment 2: Cross-Job Stash / Unstash via Artifacts
├── DAG reachability analysis for stash/unstash
├── Lowering cross-job stash to actions/upload-artifact@v4
├── Lowering cross-job unstash to actions/download-artifact@v4
├── Diagnosing PB-STASH-MISSING, PB-STASH-AMBIGUOUS, PB-WORKSPACE-TRANSFER
└── End-to-end multi-job artifact transfer tests

Increment 3: Literal Matrix Strategy & Exclusions
├── Parser: AST recognition of stage-level `matrix`
├── Strategy emission: strategy.matrix, fail-fast: false, exclude
├── Safe YAML scalar quoting (preventing 3.10 / bool typing bugs)
├── Matrix coordinate injection into cell step environments
└── End-to-end matrix workflow validation & limits check (256 cap)
```

### Increment 1: Execution Graph and Declarative `parallel`
- Introduce `JobGraph` and `JobNode` in `src/pipebridge/model.py`.
- Update `src/pipebridge/parser.py` to parse `parallel { stage('...') { ... } }` into
  branch stages instead of stopping with blanket `PB-PARALLEL`.
- Update `src/pipebridge/workflow.py` to iterate over `job_graph.jobs` and emit top-level
  `jobs:` entries with `needs:` dependencies.
- Verify byte-for-byte identity of single-job sequential pipelines.

### Increment 2: Cross-Job Stash/Unstash via Artifacts
- Refactor `src/pipebridge/stash.py` to evaluate stash lifetimes across the `JobGraph`.
- Intra-job stash operations retain the local Python script runner.
- Inter-job stash operations emit `actions/upload-artifact@v4` with `retention-days: 1`
  and `actions/download-artifact@v4`.
- Enforce validation rules: `PB-STASH-MISSING`, `PB-STASH-AMBIGUOUS`, `PB-WORKSPACE-TRANSFER`.

### Increment 3: Literal Matrix Axes and Exclusions
- Update `src/pipebridge/parser.py` to parse `matrix { axes { ... } excludes { ... } stages { ... } }`.
- Emit `strategy.matrix:` with explicit `fail-fast: false` and `exclude:` filters.
- Expose matrix coordinates as environment variables for step scripts.
- Enforce literal typing and the 256-cell expansion cap (`PB-MATRIX-LIMIT`).

---

## 7. Acceptance Criteria and Verification Plan

1. **Execution Graph Correctness**:
   - Linear stages before `parallel` precede all branch jobs in the `needs:` graph.
   - All branch jobs list the upstream job in `needs:`.
   - Fan-in stages list all parallel branch jobs in `needs:`.
2. **Failure Gating**:
   - Controlled execution proves that a failure in one branch job causes downstream fan-in
     jobs to be skipped (`needs` default `success()`), while sibling branches execute to
     their own completion.
3. **Artifact Integrity**:
   - Stashed files uploaded by Job A are completely and accurately restored in Job B,
     including POSIX executable permissions.
4. **Matrix Determinism**:
   - A two-axis matrix with an exclusion evaluates exactly $(|A| \times |B| - |Exclusions|)$
     cells with exact literal coordinates.
   - Values like `'3.10'` are quoted as strings in workflow YAML.
5. **Negative Diagnostic Precision**:
   - Missing stash producers emit `PB-STASH-MISSING`.
   - Concurrent duplicate stash producers emit `PB-STASH-AMBIGUOUS`.
   - Matrix expansion $> 256$ cells emits `PB-MATRIX-LIMIT`.
   - Dynamic Groovy expressions in axes emit `PB-INTERP`.
6. **Backward Compatibility**:
   - All existing 504 unit and integration tests continue to pass without modification.
   - Regenerated committed examples (`python-build`, `jenkinsfile-helpers`) remain
     byte-for-byte identical.
