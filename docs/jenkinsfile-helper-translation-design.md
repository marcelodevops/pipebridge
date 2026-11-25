# Design — Jenkinsfile postlude helper translation via shared-library lowering

> **Status: design only, not implemented.** This document specifies the next
> bounded milestone on top of `origin/main`
> (`963e028d9a6b670545e0aea9b9564d215c809189`). It does not change translator
> behavior, the version (`0.5.0`), finding codes, generated workflows, or
> published releases. Current pipebridge still classifies every top-level
> postlude statement — including `def helper(...) { ... }` — as
> `PB-GROOVY-POSTLUDE` and reports calls to postlude helpers as `PB-SYNTAX`
> (or `PB-LIB-CALL` when a shared library is loaded). The fixtures under
> [`examples/jenkinsfile-helpers/`](../examples/jenkinsfile-helpers/) are
> source inputs for the planned implementation PR; they are not yet converted
> or wired into live workflows.

## 1. Problem and current behavior

Declarative Jenkinsfiles frequently factor repeated stage commands into small
top-level `def helper(...) { ... }` functions placed after the closing `}` of
`pipeline { ... }`. Today, even when every statement inside a postlude helper
is in the already-supported shared-library subset (`sh`, `echo`, bounded
`withCredentials`, single-job `stash` / `unstash`, and helper forwarding),
pipebridge rejects both the definition and the call:

| Area | Current behavior on `origin/main` (`963e028`) |
| --- | --- |
| Postlude `def helper(...) { ... }` | `_scan_postlude()` (`src/pipebridge/parser.py`) skips the definition and emits `PB-GROOVY-POSTLUDE` (`function definition after the pipeline block`). `parse()` then calls `_mark_pipeline_blocked()`, reducing the workflow to a disabled `[NOT MIGRATED] pipeline` skeleton. |
| Stage step `helper('arg')` without resolved `@Library` | `_parse_steps()` (`src/pipebridge/parser.py`) emits `PB-SYNTAX` (`Step 'helper' is not supported by the MVP; the enclosing stage was not translated.`) and clears the stage. |
| Stage step `helper('arg')` with resolved `@Library` | `_parse_library_call()` delegates to `Resolver.resolve()` (`src/pipebridge/librarybody.py`), which looks only in `vars/<name>.groovy` across loaded libraries and emits `PB-LIB-CALL` (`Library '<lib>' has no vars/helper.groovy.`). |
| Shared-library resolver & lowering (`libraryresolver.py`, `librarybody.py`) | Already parses `def <name>(<params>) { <statements> }` tokens, validates literal and forwarded bare-parameter arguments, lowers `sh` and parameterized `echo` to `<output>/scripts/...` templates invoked with `bash --noprofile --norc -eo pipefail`, enforces depth cap (`20`) and cycle detection, scopes `withCredentials([string(...)])`, and validates single-job `stash` / `unstash`. |

## 2. Goal and non-goals

### 2.1 Goal

Allow a declarative pipeline that calls one or more supported top-level
postlude `def <helper>(...) { ... }` definitions to convert into runnable
GitHub Actions workflow steps and deterministic `scripts/_jenkinsfile/*.sh`
files — reusing the existing `Definition`, `LibraryVar`, `Resolver`,
`CredentialInventory`, `LibraryInventory`, and transactional `_write_all`
machinery without creating a second resolver or executing Groovy.

### 2.2 Non-goals

- Implementing translator changes, bumping the version, tagging, or publishing
  in this planning PR.
- Prelude function definitions (`def helper(...)` *before* `pipeline { ... }`);
  they remain `PB-GROOVY-PRELUDE` in this first increment.
- Evaluating Groovy, supporting control flow (`if`, `for`, `while`, `try`,
  `catch`, `switch`, `return`), variable assignments, closures, or arithmetic /
  string-concatenation expressions.
- Capturing prelude or postlude variables, `env.*`, `params.*`, or any
  non-parameter identifier inside a helper body.
- Method overloading (multiple `def <name>` definitions with different
  arities), default parameter values (`def f(String x = 'a')`), varargs, or
  non-`String` type annotations (`int`, `boolean`, `Map`, `List`, `Object`,
  `void`).
- Defining helpers inside `pipeline { ... }`, `stages { ... }`, `stage { ... }`,
  or `script { ... }`.
- Widening D2 diagnostic traversal into helper bodies called from already
  blocked scopes (`parallel`, `when`, `post`, `script`, or blocked stages).

## 3. Accepted grammar and resolution rules

### 3.1 Postlude statement classification

After the top-level `pipeline { ... }` block closes, every top-level postlude
statement is classified before stage step resolution:

1. **Another `pipeline {` occurrence** (top-level or nested inside a postlude
   statement): raises `MalformedPipelineError` (`more than one 'pipeline' block
   occurrence was found; which one is the declarative pipeline is ambiguous`),
   unchanged from today.
2. **Eligible postlude helper candidate**: a top-level statement starting with
   the exact keyword token `def` followed by an identifier `<name>` and `(`.
   - Modifiers (`private`, `public`, `protected`, `static`, `final`), explicit
     return types (`void`, `String`, …), or annotations (`@NonCPS`, …) before
     `def` or in place of `def` are **not** eligible and remain
     `PB-GROOVY-POSTLUDE`.
   - `def <name> = ...` or `def <name>` without `(` is a variable declaration,
     not a function, and remains `PB-GROOVY-POSTLUDE`.
3. **Every other postlude statement** (top-level method calls such as
   `println 'x'`, assignments, annotations, class definitions, or unclosed
   statements): emits `PB-GROOVY-POSTLUDE` at the statement's first token and
   marks the pipeline blocked (`_mark_pipeline_blocked()`).

### 3.2 Postlude helper definition grammar

An eligible `def <name>(...)` postlude statement must satisfy the existing
`libraryresolver.py` definition grammar:

```text
helper-def := 'def' IDENT '(' [ param ( ',' param )* ] ')' NEWLINE* '{' statement* '}'
param      := [ 'String' ] IDENT
```

Exact rules:

- `<name>` and each parameter `IDENT` must `fullmatch`
  `VAR_NAME_RE` (`^[A-Za-z_][A-Za-z0-9_]{0,127}$`).
- Parameters accept only bare `<ident>` or `String <ident>`. Default values,
  trailing commas, varargs, and other type names are rejected.
- Parameter names within a helper must be distinct.
- The body `{ ... }` must be balanced to its matching `}` at token level (lexer
  string/comment tokens already isolate braces inside literals and comments).
  An unclosed body at `EOF` keeps today's `PB-GROOVY-POSTLUDE` (`not closed`
  message) so existing unbalanced-postlude tests remain unchanged.
- A semicolon or non-newline token immediately after the closing `}` on the
  same statement is fine only as a statement separator (`NEWLINE`, `SEMI`,
  `EOF`).
- Any `def <name>(` with a malformed parameter list, duplicate parameter name,
  or missing `{` after `)` emits `PB-LIB-CALL` at `<name>` (or `def`) and marks
  the pipeline blocked (`_library_load_failed = True`).

### 3.3 Name collisions and reserved names

Collision checks run deterministically across all postlude helpers and any
declared, mapped `@Library` vars before step lowering. Any collision marks the
pipeline blocked (`_library_load_failed = True`) so no stage is partially
translated under an ambiguous definition:

1. **Built-in step shadowing**: `<name>` in
   `{"sh", "echo", "checkout", "withCredentials", "stash", "unstash", "script"}`
   emits `PB-LIB-CALL` at `<name>`:
   `Postlude helper '<name>' shadows a built-in step.`
   Built-in steps inside `pipeline { ... }` still use their built-in parsers.
2. **Reserved shared-library entry point `call`**: `<name> == "call"` emits
   `PB-LIB-CALL` at `<name>`:
   `Postlude helper 'call' is reserved for shared-library vars/*.groovy entry points.`
3. **Duplicate postlude helper name**: a second `def <name>(...)` in the same
   Jenkinsfile (regardless of parameter count; overloading is unsupported)
   emits `PB-LIB-CALL` at the second definition's `<name>`:
   `Postlude helper '<name>' is defined more than once.`
4. **Collision with a declared, mapped shared-library var**: if `<name>` also
   exists as `vars/<name>.groovy` in any resolved `@Library`, emit
   `PB-LIB-CALL` at the postlude helper's `<name>`:
   `Postlude helper '<name>' collides with library var '<var_path>'.`

### 3.4 Unused postlude helper definitions and reachability tracking

Postlude helpers are top-level Groovy statements. **pipebridge never silently
discards an unreached postlude helper definition, and never emits a spurious
unused-helper blocker for a helper that was actually visited during step
resolution.**

Exact reachability rules:

- **Independent visited-helper tracking**: `Resolver` and `Resolution` track
  `visited_local_helpers: set[str]` independently of `Resolution.operations`
  and `Stage.steps`.
  - A postlude helper name `<name>` is added to `visited_local_helpers` as soon
    as `_parse_library_call` dispatches a top-level call to `<name>`, and
    whenever `Resolver._do_invocation` or `Resolver._expand` resolves or enters
    a same-file postlude helper `<callee>` during active step resolution.
  - Because `visited_local_helpers` is stored as analysis state on the parser /
    `Resolution` (and merged into `self._reached_postlude_helpers` before any
    branch on `res.blocked`), a visited helper **remains reached** even when:
    1. Its own call site fails argument or arity validation (`PB-LIB-CALL`).
    2. Its own body (or a transitive callee's body) fails resolution
       (`PB-LIB-CALL`, `PB-INTERP`, `PB-CRED`, cycle detection, or depth cap),
       causing `res.operations` to be cleared (`res.operations = []`).
    3. It resolves cleanly, and a subsequent step or directive in the same
       stage later blocks and clears the stage (`_mark_stage_blocked(stage)` ->
       `stage.steps.clear()`).
- **Transitive visits count**: If a stage step calls `helperA()`, and
  `helperA()` calls `helperB()` before or at a failure point, both `helperA`
  and `helperB` are recorded in `visited_local_helpers` and neither receives
  an unused-helper finding. (If `helperA()` fails *before* reaching the statement
  that calls `helperB()`, and nothing else calls `helperB()`, `helperB` was
  never visited and remains unreached.)
- **Diagnostic and opaque traversal never count**: Calls encountered only
  inside diagnostic traversal (`_diagnose_steps_remainder`,
  `_diagnose_wrapper_body`, `_diagnose_stage`, etc., after the enclosing stage
  or wrapper is already blocked) or inside untranslated/opaque constructs
  (`post { ... }`, `when { ... }`, `parallel { ... }`, `script { ... }`) never
  enter `Resolver` and do **not** mark any helper as visited.
- **Post-pipeline unused check**: After `_parse_pipeline()` completes, every
  postlude helper definition not in `self._reached_postlude_helpers` emits
  `PB-GROOVY-POSTLUDE` at its `def` token (same code, line, col, construct
  `function definition after the pipeline block`, and message as today), which
  marks the pipeline blocked.
- Consequently:
  - A pipeline where every postlude helper is valid and reached by translated
    steps emits **no** `PB-GROOVY-POSTLUDE`.
  - A failing reached helper (such as
    `examples/jenkinsfile-helpers/negative/unsupported-body.Jenkinsfile` or
    `recursion.Jenkinsfile`) or a valid reached helper in a stage later blocked
    by an unrelated step (such as `mavenBuild(...)` followed by `Result.dump()`
    in `tests/fixtures/calls-to-helper/Jenkinsfile`) emits its specific call or
    stage blocker and **no** spurious `PB-GROOVY-POSTLUDE`.
  - A pipeline with dead/unreferenced postlude helpers, or helpers only
    referenced from `post` / `when` / `parallel` / `script` blocks (such as the
    existing `postlude-functions`, `java-maven-jetty-like`,
    `container-k8s-memphis-like`, and `node-release-tutanota-like` fixtures),
    retains its exact `PB-GROOVY-POSTLUDE` findings and disabled skeleton draft.

### 3.5 Supported helper body grammar and statement semantics

Reached postlude helpers are represented as a `LibraryVar` whose `path` is the
Jenkinsfile path (`Path(source_path or "Jenkinsfile")`) and expanded by the
existing `Resolver` in `src/pipebridge/librarybody.py`. Inside a postlude
helper body, `_expand_statements` accepts the exact same statement grammar as
`vars/*.groovy`:

- `sh '<lit>'`, `sh "<template>"`, `sh('<lit>')`, `sh("<template>")`, and
  `sh(param)` / `sh param` (where `param` is a bare in-scope parameter).
- `echo '<lit>'`, `echo "<template>"`, `echo('<lit>')`, `echo("<template>")`,
  and `echo(param)` / `echo param`.
- `withCredentials([string(credentialsId: '<lit>', variable: '<NAME>')]) { <statements> }`
  (single literal string binding, non-nested, non-empty supported body, feeding
  the existing `CredentialInventory` and `--secrets-ready` gate).
- `stash name: '<lit>', includes: '<glob>'[, excludes: '<glob>']` and
  `unstash '<lit>'` / `unstash('<lit>')` (subject to the same job-wide
  uniqueness and `unstash`-after-surviving-`stash` validation).
- `<callee>([<arg>, ...])` where each `<arg>` is either a non-interpolated
  string literal or a bare in-scope formal parameter of the enclosing helper:
  - `<callee>` may be another postlude helper in the same Jenkinsfile, or (when
    `@Library` is declared and mapped) a discovered `vars/<callee>.groovy`
    entry point.
  - Note: external `vars/*.groovy` files cannot call back into Jenkinsfile
    postlude helpers; postlude helpers are scoped to the Jenkinsfile.
- Any other statement (`if`, `for`, `return`, `script { ... }`, `checkout scm`,
  plugin steps like `mail`, variable declarations, assignments, named arguments
  to `sh`/`echo`) emits `PB-LIB-CALL` at that statement token with the full
  call chain and blocks the calling stage.

### 3.6 Captured/global variables, interpolation, recursion, and depth cap

- **No variable capture**: Only the enclosing helper's own formal parameters
  are in scope (`params` dict in `_expand`).
  - Referencing a prelude/postlude variable or environment expression inside a
    double-quoted `sh` or `echo` string (`sh "deploy ${GLOBAL_ENV}"`,
    `echo "$BUILD_TAG"`, `echo "$param.length"`) fails `decode_template_parts`
    and emits `PB-INTERP` at the interpolation token with the call chain.
  - Passing a non-parameter identifier to `sh(GLOBAL_CMD)`, `echo(GLOBAL_MSG)`,
    or `otherHelper(GLOBAL_ARG)` fails parameter lookup and emits `PB-LIB-CALL`
    at the identifier token with the call chain.
  - In addition, any prelude or postlude variable declaration itself continues
    to emit `PB-GROOVY-PRELUDE` or `PB-GROOVY-POSTLUDE`.
- **Cycle detection and depth cap**:
  - Direct recursion (`a -> a`) and mutual recursion (`a -> b -> a`) are
    detected on the expansion stack `(var.path, defn.name)` and emit
    `PB-LIB-CALL`: `Library call cycle: <frame1> -> <frame2> -> ...`
  - Maximum call depth remains `LIBRARY_CALL_DEPTH_CAP = 20` across combined
    postlude-helper and shared-library call chains. Depth 21 emits
    `PB-LIB-CALL`: `Library call depth exceeded 20 at '<name>'.`

### 3.7 Step dispatch in `_parse_steps`

When `_parse_steps` encounters a non-built-in step identifier `<name>`:

1. If `<name>` matches a parsed postlude helper definition (or a postlude
   helper that recorded a header/collision finding): mark `<name>` as reached
   and resolve via `_parse_library_call` against the Jenkinsfile's local
   `LibraryVar`.
2. Else if `self._resolved_libraries` is non-empty: resolve via
   `_parse_library_call` against loaded shared libraries (emitting
   `PB-LIB-CALL` if `<name>` is not found in loaded libraries, unchanged).
3. Else: emit the existing `PB-SYNTAX` finding (`Step '<name>' is not supported
   by the MVP; the enclosing stage was not translated.`), unchanged.

This dispatch rule guarantees that pipelines without `@Library` and without a
matching postlude helper name (for example `Result.dump()` in
`calls-to-helper` or any unknown plugin step) retain their exact `PB-SYNTAX`
classification.

### 3.8 Script emission, reuse, and argument passing

- Lowered `sh` steps and parameterized `echo` steps from a postlude helper
  `<function>` set:
  - `op.library = None`
  - `op.var_name = None`
  - `op.func_name = <function>`
  - `op.step_index = <1-based script-step counter within function>`
  - `step.script_path = f"scripts/_jenkinsfile/{op.func_name}-{op.step_index}.sh"`
- Why `_jenkinsfile`: `LIBRARY_NAME_RE` (`^[A-Za-z][A-Za-z0-9_-]{0,63}$`)
  requires library names to start with an ASCII letter, so `_jenkinsfile` is
  syntactically disjoint from every valid `--library-map` library directory.
- Unparameterized literal `echo 'msg'` inside a postlude helper lowers to an
  inline `Step(kind="echo", text="msg")` (`printf '%s\n' 'msg'`) with
  `script_path=None`, matching shared-library lowering.
- **Script reuse**: `_collect_library_scripts` in `src/pipebridge/cli.py`
  deduplicates `(target, content)` pairs by target path. Because parameter
  values are lowered to `${1}`, `${2}`, … in the template and never spliced
  into the script body, repeated calls to `publishStep('alpha', 'build-1')` and
  `publishStep('beta', 'build-2')` emit a single script file per helper step
  and invoke it twice with distinct single-quoted, expression-neutralized
  `argv` tokens:
  ```yaml
  run: |2-
    bash --noprofile --norc -eo pipefail 'migration/scripts/_jenkinsfile/writeMarker-1.sh' 'alpha' 'build-1'
  ```
- **Output containment and transactional writes**: When any postlude-helper
  script (or `stash`/`unstash` helper) is emitted, `--output` must be a
  relative path under the working directory with no `..` segments. All
  generated scripts participate in `--force` overwrite checks, staged writes,
  and handled-`OSError` rollback via `_write_all`.

### 3.9 Provenance, stage clearing, stage-blocker attribution, and report contract

- Every `Operation`, `LibraryCredential`, `LibraryCallRecord`, and `Finding`
  produced during postlude helper resolution carries:
  - `source_path`: the Jenkinsfile path string (`str(source_path)` when
    supplied, or `"Jenkinsfile"`).
  - `call_chain`: tuple of `<path>:<func>@<line>:<col>` frames from the
    stage step call site through each nested helper call.
- `report["libraries"]["calls"]` records each top-level postlude helper call
  in source order (`name`, `status`, `source_path`, `line`, `col`, `chain`),
  while `report["libraries"]["loaded"]` remains `[]` when no `@Library` was
  loaded.
- If a stage is later blocked and cleared (`_mark_stage_blocked(stage)`), its
  collected `stage.steps` are cleared (so no scripts are emitted for that
  stage), while `CredentialInventory`, `LibraryInventory.calls`, and
  `self._reached_postlude_helpers` retain the recorded bindings, call records,
  and visited helper names.
- **Stage-blocker attribution and compatibility guarantees**:
  - In `src/pipebridge/workflow.py`, `_stage_blocker_codes(blockers, stage, next_stage)`
    currently checks only `stage.span.line <= f.line < upper`. When a blocker
    originates inside a postlude helper (where `f.line` is after `pipeline { ... }`)
    or inside a `vars/*.groovy` shared-library file (where `f.line` is a line
    number in that external file), `f.line` is the callee token line rather
    than the stage call-site line.
  - Updated rule:
    - When `f.call_chain` is **non-empty**, extract the root call-site line
      `<call_line>` from `f.call_chain[0]` (`<path>:<name>@<call_line>:<call_col>`)
      and attribute `f.code` to `stage` iff
      `stage.span.line <= call_line < upper`. (Do not match raw `f.line` when
      `f.call_chain` is present, so a `vars/*.groovy` line number or postlude
      line number never collides with an unrelated stage's line span.)
    - When `f.call_chain` is **empty** (all direct Jenkinsfile findings), test
      `stage.span.line <= f.line < upper` exactly as today.
  - **Compatibility reconciliation**:
    - For all unaffected inputs (pipelines without blocked shared-library calls
      or postlude helpers, including every enabled workflow, pure-declarative
      golden, D2 baseline, and non-library blocked draft), `f.call_chain` is
      empty and generated `workflow.yml` output remains **byte-for-byte
      identical**.
    - For existing blocked shared-library workflows where a blocker inside
      `vars/*.groovy` carries `f.call_chain`, corrected blocker attribution in
      the blocked stage's `# unsupported constructs (<codes>)` comment and
      `[NOT MIGRATED] <Stage>` placeholder `echo` text is **explicitly
      permitted** and verified with targeted before/after tests.
    - This attribution refinement affects **only** the blocker-code summary text
      inside already-blocked stage placeholders. The execution graph,
      job-level disabled state (`if: false`), surviving steps of unblocked
      stages, translation eligibility, and CLI exit codes remain completely
      unchanged.

## 4. Fixtures included in this design PR

All fixtures live under
[`examples/jenkinsfile-helpers/`](../examples/jenkinsfile-helpers/):

1. **Success fixture** —
   [`examples/jenkinsfile-helpers/success/Jenkinsfile`](../examples/jenkinsfile-helpers/success/Jenkinsfile):
   - Two-stage declarative pipeline (`Package` and `Verify`) with no
     `@Library`.
   - `Package` calls `publishChannel('alpha', 'build-1')` and
     `publishChannel('beta', 'build-2')`.
   - `def publishChannel(String channel, String tag)` forwards both bare
     in-scope parameters to `writeReleaseMarker(channel, tag)` and runs a
     parameterized `echo "published ${channel}:${tag}"`.
   - `def writeReleaseMarker(String channel, String tag)` runs a parameterized
     `sh` command writing `${1}:${2}` to `dist/${1}.txt`.
   - Demonstrates literal arguments, same-file helper-to-helper parameter
     forwarding, and generated script reuse
     (`scripts/_jenkinsfile/writeReleaseMarker-1.sh` and
     `scripts/_jenkinsfile/publishChannel-1.sh` emitted once and invoked twice
     with different `argv`).
2. **Negative fixtures** —
   [`examples/jenkinsfile-helpers/negative/`](../examples/jenkinsfile-helpers/negative/):
   - [`unsupported-body.Jenkinsfile`](../examples/jenkinsfile-helpers/negative/unsupported-body.Jenkinsfile):
     postlude helper containing an unsupported statement (`script { ... }`),
     diagnosed as `PB-LIB-CALL` with `call_chain`, blocking the calling stage.
   - [`captured-variable.Jenkinsfile`](../examples/jenkinsfile-helpers/negative/captured-variable.Jenkinsfile):
     prelude variable `String GLOBAL_ENV = 'prod'` referenced inside a postlude
     helper via `"${GLOBAL_ENV}"`, diagnosed with `PB-GROOVY-PRELUDE` (at line
     1) and `PB-INTERP` (at the helper's interpolation token with `call_chain`).
   - [`recursion.Jenkinsfile`](../examples/jenkinsfile-helpers/negative/recursion.Jenkinsfile):
     mutual recursion `firstStep('x') -> secondStep(label) -> firstStep(label)`,
     diagnosed with `PB-LIB-CALL` (`Library call cycle: ...`).
   - [`collision-builtin.Jenkinsfile`](../examples/jenkinsfile-helpers/negative/collision-builtin.Jenkinsfile):
     postlude helper `def sh(String cmd)` shadowing built-in step `sh`,
     diagnosed with `PB-LIB-CALL` (`Postlude helper 'sh' shadows a built-in step.`)
     and pipeline blocked.
   - [`collision-library-var.Jenkinsfile`](../examples/jenkinsfile-helpers/negative/collision-library-var.Jenkinsfile):
     `@Library('build-lib') _` mapped alongside a postlude `def publish(String label)`
     that collides with `vars/publish.groovy`, diagnosed with `PB-LIB-CALL`
     (`Postlude helper 'publish' collides with library var ...`) and pipeline
     blocked.
   - [`collision-duplicate-helper.Jenkinsfile`](../examples/jenkinsfile-helpers/negative/collision-duplicate-helper.Jenkinsfile):
     two postlude `def deploy(...)` definitions in the same Jenkinsfile,
     diagnosed with `PB-LIB-CALL` (`Postlude helper 'deploy' is defined more than once.`)
     and pipeline blocked.
   - [`mixed-executable-postlude.Jenkinsfile`](../examples/jenkinsfile-helpers/negative/mixed-executable-postlude.Jenkinsfile):
     a valid called helper `def runSuite(String suite)` mixed with an unreached
     helper `def unusedHelper()` and a top-level executable statement
     `println 'postlude side effect'`, diagnosed with `PB-GROOVY-POSTLUDE`
     blockers and reduced to a disabled skeleton draft with no `scripts/`
     emitted.

## 5. Acceptance criteria for the implementation PR

1. **Enabled conversion and script reuse**:
   - Converting `examples/jenkinsfile-helpers/success/Jenkinsfile` with a
     relative `--output` exits `0`, emits no `PB-GROOVY-POSTLUDE` or other
     blocker, enables the workflow (`if: false` absent), and writes exactly
     two scripts (`scripts/_jenkinsfile/writeReleaseMarker-1.sh` and
     `scripts/_jenkinsfile/publishChannel-1.sh`), each reused across both
     `publishChannel(...)` calls.
   - Literal argument values (`alpha`, `beta`, `build-1`, `build-2`) do not
     appear inside the generated `.sh` files; they appear only as single-quoted
     `argv` arguments in `workflow.yml`.
2. **Runtime execution and failure propagation**:
   - Executing the generated `run:` commands from `workflow.yml` under
     `bash --noprofile --norc -eo pipefail` creates `dist/alpha.txt`
     (`alpha:build-1`), `dist/beta.txt` (`beta:build-2`), and prints
     `published alpha:build-1` and `published beta:build-2`.
   - When a postlude helper script executes a failing command or pipeline
     (`false; printf SHOULD_NOT_RUN` or `exit 1 | cat` followed by a command),
     execution terminates non-zero immediately and subsequent commands/steps do
     not run.
3. **Quoting and expression neutralization**:
   - Calling a postlude helper with a literal containing single quotes, double
     quotes, spaces, shell metacharacters (`$HOME`, `$(id)`, `` `uname` ``),
     newlines, and `${{ secrets.EXAMPLE }}` emits `PB-GHEXPR` (warning), puts
     no raw `${{` in the generated `run:` command or script file, and passes
     the exact literal bytes as `$1` at runtime.
4. **Credentials and stash inside postlude helpers**:
   - `withCredentials([string(credentialsId: '...', variable: '...')])` inside
     a postlude helper scopes `NAME: ${{ secrets.MAPPED }}` exclusively to the
     lowered bound steps, requires `--credential-map` and `--secrets-ready` to
     enable the workflow, and preserves credential inventory (with `call_chain`
     and `source_path`) if the stage is later cleared.
   - Single-job `stash` / `unstash` inside a postlude helper participates in
     job-order validation (duplicate stash name and unstash-before-stash fail
     with `PB-LIB-CALL`) and emits `pipebridge_stash.py`,
     `pipebridge_unstash.py`, and the final `always()` cleanup step.
5. **Negative fixtures, reachability under failure/clearing, and provenance**:
   - Each negative fixture under `examples/jenkinsfile-helpers/negative/`
     exits `2`, emits a disabled workflow (`if: false`), writes no executable
     `scripts/` files, and reports the expected blocker code (`PB-LIB-CALL`,
     `PB-INTERP`, `PB-GROOVY-PRELUDE`, or `PB-GROOVY-POSTLUDE`) with accurate
     line, column, `source_path`, and `call_chain`.
   - **Failing reached helper produces no spurious unused-helper finding**:
     When a stage step invokes a postlude helper whose body (or transitive
     postlude helper callee) fails resolution (`unsupported-body.Jenkinsfile`,
     `captured-variable.Jenkinsfile`, `recursion.Jenkinsfile`, or `helperA ->
     failingHelperB`), all visited helpers remain marked reached and **no**
     `PB-GROOVY-POSTLUDE` finding is emitted for them.
   - **Successful helper call followed by an unrelated stage blocker produces
     no spurious unused-helper finding**: When a stage step invokes a postlude
     helper (including transitive same-file helper forwarding) that resolves
     cleanly, and a later step in the same stage blocks and clears the stage
     (e.g., `script { ... }` or `Result.dump()` in
     `tests/fixtures/calls-to-helper/Jenkinsfile`), the stage's steps are
     cleared and no scripts are emitted for that stage, while all visited
     helpers remain marked reached and **no** `PB-GROOVY-POSTLUDE` finding is
     emitted.
   - **Calls only in diagnostic/opaque traversal remain unreached**: A postlude
     helper referenced only after a stage is already blocked (during
     `_diagnose_steps_remainder` / `_diagnose_wrapper_body`), or only inside
     `post`, `when`, `parallel`, or `script`, is not visited by `Resolver` and
     still emits `PB-GROOVY-POSTLUDE`.
   - **Stage-blocker attribution**: `_stage_blocker_codes` attributes a
     postlude-helper or `vars/*.groovy` blocker via `f.call_chain[0]`'s
     call-site line to the calling stage's `[NOT MIGRATED] <Stage>` placeholder
     (and never to an unrelated stage whose line span happens to match the
     callee's line number in `vars/*.groovy` or the Jenkinsfile postlude).
6. **Compatibility and unchanged existing behavior**:
   - **Byte-identical output for unaffected inputs**: Existing inputs without
     postlude helpers or blocked library calls whose `f.line` fell outside the
     calling stage — including `examples/python-build`,
     `examples/shared-library/success`, `examples/shared-library/failure`,
     `tests/baselines/d2/*.workflow.yml`, and
     `tests/goldens/pure-declarative/*.workflow.yml` — produce byte-for-byte
     identical `workflow.yml` output.
   - **Permitted attribution fix in blocked shared-library workflows**: Where
     an existing blocked shared-library workflow had a finding inside
     `vars/*.groovy` with `call_chain` whose `f.line` did not fall within the
     calling stage's Jenkinsfile line range, updating the calling stage's
     `# unsupported constructs (<codes>)` comment and `[NOT MIGRATED] <Stage>`
     placeholder to show that blocker code (instead of `"see report"` or
     misattributing it to another stage) is explicitly permitted and covered by
     targeted before/after tests. Execution graph, `if: false` disabled state,
     surviving steps of other stages, translation eligibility, and exit codes
     must remain unchanged.
   - **Unreached postlude fixtures unchanged**: Existing fixtures with
     unreached postlude helpers or executable postlude statements
     (`postlude-functions`, `java-maven-jetty-like`,
     `container-k8s-memphis-like`, `node-release-tutanota-like`) retain their
     `PB-GROOVY-POSTLUDE` findings and disabled skeleton drafts.

## 6. Implementation sequence (reusing existing components)

1. **`src/pipebridge/libraryresolver.py` — extract single-definition parser**:
   - Factor out `parse_single_definition(tokens: list[Token], start: int, path: Path, *, allow_call: bool = True)`
     from `_parse_definitions` so both `vars/*.groovy` file loading and
     Jenkinsfile postlude scanning use the exact same `def <name>(<params>) { <body> }`
     parser and `Definition` dataclass.
   - Export `POSTLUDE_SHADOWED_STEPS = BUILTIN_STEPS | {"script"}`.
2. **`src/pipebridge/librarybody.py` — support optional Jenkinsfile `local_var` and visited-helper tracking in `Resolver`**:
   - Add `local_var: LibraryVar | None = None` to `Resolver.__init__` and
     `visited_local_helpers: set[str] = field(default_factory=set)` to
     `Resolution`.
   - Add `Resolver.resolve_local(helper_name: str, args: list[str], caller=None) -> Resolution`,
     which records `helper_name` in `res.visited_local_helpers` upon entry,
     looks up `helper_name` in `self.local_var.definitions`, checks arity, and
     calls the existing
     `self._expand(self.local_var, defn, args, [], (root_frame,), res, lib_name=None)`.
     When `res.blocked` is true, `res.operations` is cleared as today while
     `res.visited_local_helpers` is preserved.
   - In `_do_invocation`, when `lib_name is None` (expanding inside
     `self.local_var`), resolve `<callee>` against `self.local_var.definitions`
     first (recording `<callee>` in `res.visited_local_helpers` immediately
     when matched, before arity/cycle/body checks) and then
     `self._candidates(name_tok.value)` (collisions between the two are already
     blocked before expansion). When `lib_name is not None` (expanding inside a
     shared library `vars/*.groovy` file), keep current behavior (resolve only
     against `var.definitions` and `self._candidates`).
3. **`src/pipebridge/parser.py` — pre-scan postlude definitions and track reachability**:
   - After `_scan_prelude()` locates the top-level `pipeline` token, locate the
     matching closing `}` of `pipeline { ... }` by balanced-brace lookahead.
     (If `pipeline` is not followed by `{`, or the block is unterminated, or a
     second `pipeline {` appears in the postlude, skip helper pre-registration
     so `_parse_pipeline()`, `_validate_required_structure()`, and
     `_scan_postlude()` execute their existing error paths unchanged.)
   - Scan postlude statements in the token slice after `pipeline { ... }`:
     - Classify each statement as either an eligible `def <name>(...) { ... }`
       definition, a malformed/colliding `def <name>(...)` header (`PB-LIB-CALL`,
       `self._library_load_failed = True`), or an executable/unclosed postlude
       statement (`PB-GROOVY-POSTLUDE`).
     - Check postlude helper names against `POSTLUDE_SHADOWED_STEPS`, `"call"`,
       duplicate postlude definitions, and discovered `@Library` vars.
     - Pass the resulting `local_var = LibraryVar(name="_jenkinsfile", path=Path(self.source_path or "Jenkinsfile"), definitions=...)`
       into `LibraryBodyResolver`.
   - In `_parse_steps()`, dispatch `<name>` to `_parse_library_call()` when
     `<name>` is a postlude helper name (recording `<name>` in
     `self._reached_postlude_helpers` immediately, and merging
     `res.visited_local_helpers` into `self._reached_postlude_helpers` even
     when the call or stage is blocked) or when `self._resolved_libraries` is
     non-empty. Diagnostic traversal (`_diagnose_steps_remainder`,
     `_diagnose_wrapper_body`, etc.) never updates
     `self._reached_postlude_helpers`.
   - In `_parse_library_call()`, when `op.library is None`, set
     `rel_script = f"scripts/_jenkinsfile/{op.func_name}-{op.step_index}.sh"`.
   - After `_parse_pipeline()`, emit `PB-GROOVY-POSTLUDE` for every postlude
     helper definition not in `self._reached_postlude_helpers` as well as any
     non-helper postlude statements.
4. **`src/pipebridge/workflow.py` — stage blocker attribution via root `call_chain` frame**:
   - In `_stage_blocker_codes`, when `f.call_chain` is non-empty, parse the
     root call-site line from `f.call_chain[0]` and check
     `stage.span.line <= call_line < upper` (using `stage.span.line <= f.line < upper`
     only when `f.call_chain` is empty) so findings located in a postlude
     helper or `vars/*.groovy` file are attributed to the calling stage's
     `[NOT MIGRATED]` placeholder without misattributing callee line numbers.
5. **`tests/` — unit, integration, and CLI execution tests**:
   - Add tests covering the success fixture, all negative fixtures, script
     reuse, runtime failure propagation, expression neutralization, credential
     scoping + stage clearing, single-job stash/unstash from postlude helpers,
     failing reached helpers and cleared stages (asserting no spurious
     `PB-GROOVY-POSTLUDE` for direct or transitive visited helpers), targeted
     before/after stage-blocker attribution tests for blocked shared-library
     and postlude-helper stages, and byte-for-byte preservation of unaffected
     outputs.
