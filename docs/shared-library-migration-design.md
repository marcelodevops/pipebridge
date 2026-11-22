# Design — shared-library migration to a workflow and `scripts/`

> **Status: design only, not implemented.** This document specifies a later
> milestone. It does not change the translator, the version (`0.4.0`),
> findings behavior, generated workflows, or published releases. Current
> pipebridge still reports `@Library` and the pipeline `library` section as
> `PB-LIB`, and it still reports an unknown step as `PB-SYNTAX`. The fixtures
> under `examples/shared-library/` are source for that later milestone. They
> are not converted, not wired into CI, and not a claim that today's
> `pipebridge convert` accepts them.
>
> This is the planning spec that
> `docs/v0.4.0-credential-bindings-design.md` §13 F2 deferred. It does not
> edit that document. F1 (extracting Jenkinsfile `sh` bodies) stays deferred.
> This milestone extracts shell only from resolved library bodies.

## 1. Problem and current evidence

A shared-library call is a name whose behavior lives in another Groovy file.
pipebridge currently refuses the name instead of reading an explicitly
supplied local copy of that file. The result is a blanket blocker even when
the called file is a straight-line sequence of steps the translator already
knows.

| Area | Current behavior on `origin/main` (`261c39f`) |
| --- | --- |
| Prelude `@Library` | `PB-LIB`, construct `shared library annotation`, message `Shared libraries are not supported by the MVP.` Suggestion: inline the library steps. The finding is a blocker, so the generated job is `if: false`. The prelude path does not call `_mark_pipeline_blocked()`; supported steps in the Jenkinsfile can still be translated. `src/pipebridge/parser.py`, `_scan_prelude_statement`. |
| Pipeline section `library` | `PB-LIB`, construct `shared library`, same MVP message, and `_mark_pipeline_blocked()`. `parser.py`, pipeline-section dispatch. |
| Unknown step, including a `vars/` call | `PB-SYNTAX`, construct `step '<name>'`. Suggestion says to check whether it is a shared-library or plugin step. A closure body is not entered. `parser.py`, `_parse_steps` and `_diagnose_step`. |
| Diagnostic traversal | Shared-library bodies are opaque. This design does not widen D2. |
| Model | `Step.kind` is `sh`, `echo`, or `checkout`. There is no library call, script path, or stash step. `src/pipebridge/model.py`. |
| Workflow | One job, `workflow_dispatch`, `runs-on` from the existing agent rules. `sh` text is inlined into `run:`. Credential env is injected only on steps whose `credential_binding_ids` resolve. `src/pipebridge/workflow.py`. |
| Credentials | Explicit map, step-scoped `NAME: ${{ secrets.MAPPED }}`, `--secrets-ready` as an unverified acknowledgement. No secret values are read. `src/pipebridge/credentials.py`. |

No code path reads a `vars/*.groovy` file. No code path executes Groovy. Both stay true after this milestone: the new resolver parses a bounded grammar and never runs the source.

## 2. Goal

Given a Jenkinsfile plus an explicit library-name → local-directory map, translate one representative pipeline into:

- one existing-style GitHub Actions workflow, and
- deterministic `scripts/` files under the convert output directory,

when every reached library operation is in the grammar below.

The representative case is `examples/shared-library/success/`:

1. `@Library('build-lib') _` loads only the mapped local directory.
2. `publish('packaged')` calls `vars/publish.groovy` `call(String label)`.
3. That `call()` calls the same-file helper `packageSources(label)`. The argument is a bare in-scope parameter, not an expression. §7.2 and §8 require this form and resolve it to the literal `packaged` from `publish('packaged')`. No Groovy is evaluated.
4. The helper runs a shell step whose only Groovy interpolation is `label`.
5. `call()` then uses one supported `string` credential binding and runs a shell step that tests the variable without printing it.
6. `call()` stashes `dist/**`.
7. A later stage deletes `dist`, unstashes, and checks the restored bytes.

`examples/shared-library/failure/` is the intentional runtime failure: conversion succeeds, the generated job fails on `sh 'exit 1'`, and the later `echo restored` step does not run.

A library declaration or helper call is not a blanket blocker when its complete reached behavior is in this grammar and the map supplies the source. Anything else stays blocked, with the source location and the call chain.

## 3. Non-goals

- Implementing this design in the design PR.
- Version bump, tag, release, asset upload, secret creation, or `gh` invocation by pipebridge.
- Fetching a library from Jenkins, Git, or `@rev`. The local directory is the only source.
- `src/`, `resources/`, classpath, `@Grab`, retrievers, `modernSCM`, implicit global libraries, and the pipeline `library { ... }` section.
- The `library 'name'` step. It stays an unknown step (`PB-SYNTAX`) unless a later design says otherwise.
- Control flow: `if`, `else`, `for`, `while`, `switch`, `try`, `catch`, `return`, assignment, and operators.
- `script`, `dir`, `node`, `parallel`, `matrix`, `when`, `post`, `checkout`, `readFile`, `writeFile`, and plugin steps inside a library body.
- Cross-job, cross-agent, or matrix stash transfer. No `actions/upload-artifact`.
- Extracting Jenkinsfile `sh` or `echo` into `scripts/`. Those stay inline so a conversion that does not resolve a library keeps today's workflow bytes.
- Widening D2 so diagnostic traversal enters library files.
- Evaluating Groovy, interpolating a parameter value into a script file, reading a secret value, or calling `gh`.
- Claiming Jenkins runtime equivalence. Section 16 lists what a run demonstrates and what it does not.

## 4. Chosen approach

Three shapes were considered.

1. **Keep `PB-LIB` and only document a manual inlining procedure.** Small, but it does not produce a runnable workflow or `scripts/`. It misses the goal.
2. **Execute the library on a Groovy runtime and record the steps it calls.** That can follow real Jenkins dispatch, and it violates the requirement that conversion never execute source Groovy. Rejected.
3. **Parse a bounded straight-line grammar and lower it into the existing `Step` list.** The example fits. Unsupported syntax stays a finding. Credential mapping, the readiness gate, and step-scoped env are reused unchanged. This is the design.

Library calls are expanded in source order before workflow emission. They do not become composite actions, extra jobs, or a second model.

## 5. CLI and library map

`analyze` and `convert` gain one optional flag:

```text
--library-map PATH
```

Omitted means today's behavior, even if a `library-map.json` sits next to the Jenkinsfile. There is no implicit discovery.

The file contains names and relative paths only. pipebridge does not fetch, does not invoke `gh`, and does not read secret values. The checked-in fixture uses `build-lib/` as the library root because this repository's `.gitignore` ignores every `lib/` directory. That is a fixture constraint, not a grammar rule.

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

Rules, all exact:

- Top-level keys are exactly `schema_version` and `libraries`.
- `schema_version` is the integer `1`.
- `libraries` is a JSON object. Empty is valid.
- Duplicate keys anywhere in the file are rejected.
- Each entry's only key is `path`, and `path` is a string.
- The object key is the library name. It must `fullmatch` `^[A-Za-z][A-Za-z0-9_-]{0,63}$`. No trim, no case-fold.
- `path` is relative to the map file's parent. Reject an absolute path, a backslash, a NUL or other control character, an empty string, or any `.` or `..` segment.
- Resolve the path, including symlinks. The resolved path must be a directory and must stay inside the map file's parent (`Path.relative_to`). A symlink that escapes is rejected.
- The directory must contain a `vars/` subdirectory. The map points at the library root, not at `vars/`.
- Structural failure, a missing file, a directory path, or an unreadable file is exit `1` with `pipebridge: error: ...` on stderr. No workflow, report, or `scripts/` tree is written. This matches credential-map load failures.
- A valid map that nothing declares produces no blocker. Each unused name is `PB-LIB-MAP-UNUSED` (info).

`analyze --library-map` writes nothing, including no `scripts/`.

## 6. What is eligible to load

Only this prelude form is eligible:

```text
@Library('name') _
@Library("name") _
@Library('name@rev') _
@Library("name@rev") _
```

`name` is a Groovy string literal with no interpolation. It must `fullmatch` the library-name grammar. `rev` is everything after the first `@`: one or more characters, no whitespace, quote, or second `@`. `name@` with an empty revision is not eligible.

The `_` is a separate identifier statement. It is required. Another receiver, a list argument, a named argument, a retriever closure, or a missing `_` is not eligible.

Eligibility is not success. The annotation is resolved only when it is eligible and `name` is a map key. Otherwise the finding is the current `PB-LIB` finding, unchanged: same code, construct, message, suggestion, and line/col. Existing tests that assert that text keep passing. The annotation is not rewritten into a friendlier blocker.

A resolved annotation does not emit `PB-LIB` and does not by itself mark the pipeline blocked.

Several resolved annotations are allowed when each name is unique. A second eligible annotation of a name already declared is `PB-LIB-CALL` at the second annotation: `Library 'build-lib' is declared more than once.` The pipeline is marked blocked.

The pipeline `library` section is not this form. It keeps today's `PB-LIB` and `_mark_pipeline_blocked()`.

A map entry that no resolved annotation names is `PB-LIB-MAP-UNUSED`.

## 7. Library file grammar

Reached files are tokenized with the existing lexer and decoded with the existing Groovy string decoder. No second string language. No `groovy` binary, `eval`, `exec`, or import of the file as code.

Load reads only `vars/<name>.groovy` files in the library root, non-recursive. `src/`, `resources/`, and subdirectories of `vars/` are ignored, not executed.

Filename rules, before bodies are parsed:

- `<name>` must `fullmatch` `^[A-Za-z_][A-Za-z0-9_]{0,127}$` and must not be a built-in step name. The built-ins are `sh`, `echo`, `checkout`, `withCredentials`, `stash`, and `unstash`.
- A built-in filename in a loaded library is `PB-LIB-CALL` at line 1 of that file: `Library var 'sh' shadows a built-in step.` The pipeline is marked blocked. The built-in Jenkinsfile step keeps its current parser. The vars file is not called.
- The same `<name>` in two loaded libraries is `PB-LIB-CALL`: `Library var 'publish' is defined in more than one loaded library: <path1>, <path2>.` Paths are sorted. The pipeline is marked blocked.

A file is parsed only if a reached call names it, or if it is already open while resolving a helper. An unused vars file is not opened, not even to resolve a symlink. Filename checks use the directory entry name only.

Before the first read of a reached file, resolve its path, including every symlink. The resolved path must be a regular file and must stay inside the resolved library root (`Path.relative_to`). Do not open the path until that check passes. A symlink that escapes, a directory, or a path that is not a regular file is exit `1`: `pipebridge: error: library file escapes the library root: <path>.` No workflow, report, or `scripts/` tree is written. The error names the path and does not include the outside file's bytes. An unreadable or non-UTF-8 file that is inside the root is `PB-LIB-CALL`, not exit `1`: `Library file '<path>' cannot be read: <reason>.`

### 7.1 Definitions

A vars file body is zero or more definitions. No other top-level statement is supported.

```text
def call() { statements }
def call(params) { statements }
def <helper>() { statements }
def <helper>(params) { statements }
```

`<helper>` uses the same identifier grammar as a var name and is not `call`. Parameters are either bare identifiers or `String` followed by an identifier. No default, no varargs, no other type, no trailing comma. Duplicate parameter names are unsupported.

`call` is the only definition a Jenkinsfile step can invoke. A helper is visible only as a bare call inside the same file. A Jenkinsfile step `packageSources()` is not a call of the helper; it is a missing var unless `vars/packageSources.groovy` exists.

Zero or one `def call` per file. A second `def call` is `PB-LIB-CALL` at the second `call` token: `Library file '<path>' has more than one call().` A reached file with no `call()` is `PB-LIB-CALL`: `Library file '<path>' has no call().`

### 7.2 Statements

Statements are separated by newlines or semicolons at depth 0. A semicolon inside a string, comment, parentheses, brackets, or braces does not split a statement. Braces inside strings and comments do not change depth, because the lexer, not a raw brace count, drives the scan.

```text
statement := sh-step | echo-step | with-credentials | stash-step | unstash-step | invocation
```

`sh` and `echo` accept only the forms `_parse_sh` and `_parse_echo` accept today. Named arguments are not among them.

Supported:

- `sh 'cmd'` and `sh "cmd"`
- `sh('cmd')` and `sh("cmd")` — one positional string, then `)`
- `echo 'msg'` and `echo "msg"`

Not supported, and not added by this milestone: `sh(script: 'cmd')`, `sh(label: ...)`, `echo('msg')`, `echo(script: ...)`, `returnStdout`, and `encoding`. `_parse_sh` already rejects named arguments with `PB-SYNTAX` and the message `sh with named arguments (label:, script:) is not supported by the MVP; the enclosing stage was not translated.` `_parse_echo` accepts only a string token; a parenthesis is `PB-SYNTAX`, `echo requires a string argument in the supported subset.` The library parser emits those same codes and messages. It does not treat `script:` as a supported form. A parameter may appear in a supported string only as specified in §8.

`with-credentials` accepts only the header the credential milestone already accepts: one `string(credentialsId: '<literal>', variable: '<NAME>')` element, no nested binding, no interpolation in the id or variable. The body is `statements`, not an arbitrary Jenkins body. An unsupported header is the existing `PB-CRED` finding, the body is not mined, and the opaque-body rule is unchanged. A supported header whose body contains an unsupported statement is `PB-LIB-CALL` at that statement. The binding is still inventoried.

```text
stash name: '<literal>', includes: '<glob>'
stash name: '<literal>', includes: '<glob>', excludes: '<glob>'
unstash '<literal>'
unstash('<literal>')
```

`name`, then `includes`, then optional `excludes`, in that order. Any other key, order, or `allowEmpty` is unsupported. The name must `fullmatch` `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`. The globs use §11. A parameter is not a legal stash name, include, or exclude.

```text
argument   := string | bare-parameter
invocation := ident '(' ')'
invocation := ident '(' argument (',' argument)* ')'
```

No named arguments, no closure, no trailing comma. A `string` argument is a single- or double-quoted literal with no interpolation. A `bare-parameter` is an identifier token that exactly matches a parameter of the function being parsed. It is not a string, not an interpolation, and not an expression. The callee is either a helper in the same file or a var name. Argument count must equal the callee's parameter count.

`packageSources(label)` in `examples/shared-library/success/build-lib/vars/publish.groovy` is this form. `label` is the parameter of `call(String label)`. That call is in the grammar. It is not a non-literal argument and it is not evaluated.

Anything else, including `if` and `return`, is unsupported. The finding is at that token. The scanner then reports further unsupported statements in the same function without lowering them, and it does not enter an opaque `script` / unknown closure body. A remainder that is not even a statement boundary is one malformed finding, then that function stops: `Library file '<path>' is malformed: <reason>.` A malformed library file does not become `MalformedPipelineError` for a well-formed Jenkinsfile. Exit code stays `2`.

## 8. Parameters, substitution, and call order

Jenkinsfile call arguments must be literal strings. Calls inside library functions may also pass bare in-scope parameters, resolved statically to their original literal values. The formal parameter list and the argument list must have the same length. A non-literal argument is `PB-LIB-CALL`: `Library call 'publish' argument 1 is not a literal string.` An identifier is accepted only when it names an in-scope parameter whose value has already resolved to a literal. Expressions, unknown identifiers, method calls, and Groovy evaluation remain unsupported. A count mismatch is `Library call 'publish' passed 1 argument; call() requires 0.`

Inside a body, a parameter may appear only as:

- the entire `sh` or `echo` argument, or
- a bare `$param` or `${param}` interpolation in a double-quoted `sh` or `echo` string, where every interpolation in that string is a bare in-scope parameter.

A parameter in a credential id, credential variable, stash name, include, or exclude is unsupported. An interpolation that is not a bare parameter (`${label.foo}`, `${env.FOO}`, `${label + 'x'}`, a method call) is the existing `PB-INTERP` finding at the library location. No script is written for that step.

Substitution does not insert the argument value into the script file. Each distinct parameter in one `sh` step gets a positional parameter in order of first appearance, starting at `$1`. The interpolation token is replaced by `$N`. Surrounding characters in the decoded string stay, including quotes the author wrote. pipebridge does not add shell quotes around `$N` and does not rewrite the author's shell quoting.

The value is passed only as a workflow argument, single-quoted with the existing `_single_quote_shell`. A value that contains quotes, spaces, or metacharacters remains one shell word. It is still absent from the script file.

Source-derived values are neutralized against GitHub Actions expression injection before shell quoting: any `${{` sequence in the resolved literal is replaced so it cannot be reinterpreted by the runner as an expression. Shell quoting then applies to the neutralized string. Quotes, spaces, metacharacters, and a literal `${{ secrets.EXAMPLE }}` argument are covered by tests and must survive as one argv token. Generated credential expressions (`${{ secrets.X }}` produced by the credential milestone) are never passed through this path; they remain on the trusted credential emission path and are not neutralized or shell-quoted as data.

`echo` of a library parameter uses the same script-plus-argv rule, not `printf` with the value spliced into `run:`. `echo` of a library literal with no parameter is lowered as today's `echo` step. Jenkinsfile `echo` and `sh` are unchanged.

Call order is depth-first and source order. The Jenkinsfile call is expanded in place into the stage's step list. A helper's steps appear at the helper call, not after the rest of `call()`. There is no parallelism. The success example lowers, inside stage `Publish`, in this order:

1. `packageSources` shell step, script argument `packaged`.
2. credential-bound shell step, no script argument, `NPM_TOKEN` env on that step only.
3. `stash` name `dist`, includes `dist/**`.

Stage `Restore` then lowers the Jenkinsfile `sh 'rm -rf dist'` inline, the `unstash`, and the final inline `sh`. The existing implicit checkout step is still emitted. This design does not remove it.

The script for the helper step is exactly:

```text
mkdir -p dist && printf %s "$1" > dist/marker.txt
```

with one trailing newline and no shebang. The word `packaged` is not in the file. The credential step's script is exactly:

```text
test -n "$NPM_TOKEN" && printf %s ok > dist/seen.txt
```

with one trailing newline. `$NPM_TOKEN` is shell syntax. The secret value is not in the file.

Depth and cycles:

- A static cycle in var and helper calls is `PB-LIB-CALL` at the back-edge: `Library call cycle: publish -> packageSources -> publish.`
- `LIBRARY_CALL_DEPTH_CAP` is `20`. The Jenkinsfile call is depth 1. A call that would be depth 21 is `PB-LIB-CALL`: `Library call depth exceeded 20 at '<name>'.`
- Both findings include the call chain. Neither is repaired by executing the call.

## 9. Lowering

Resolved operations become existing steps plus two new kinds. No second workflow model.

`Step` gains fields with defaults so current constructors stay valid:

- `args: tuple[str, ...] = ()` — literal parameter values, never secret values.
- `script_path: str | None = None` — path relative to the process cwd at conversion, using the `--output` argument as given.
- `stash_includes: str | None = None`
- `stash_excludes: str | None = None`
- `source_path: str | None = None` — set when the step's span is not in the Jenkinsfile.

`kind` `stash` uses `text` as the stash name. `kind` `unstash` uses `text` as the name. `kind` `sh` with `script_path` set is a library shell step; `text` is the script body after `$N` replacement, not the parameter value.

Spans of lowered library steps are the library token's line and column. The Jenkinsfile call does not remain a step.

A blocked stage still clears its steps and keeps credential inventory, including bindings whose spans are in a library file. `stage_name` on those records is the Jenkinsfile stage that reached the binding.

When any lowered step has a `script_path`, `--output` must be a relative path with no `..` segment. Otherwise exit `1`: `pipebridge: error: --output must be a relative path under the working directory when library scripts are emitted.` Absolute `--output` remains valid for conversions that emit no library scripts, so current commands are unchanged.

Script paths:

```text
<output>/scripts/<library>/<var>/<function>-<n>.sh
<output>/scripts/pipebridge_stash.py
<output>/scripts/pipebridge_unstash.py
```

`<n>` is the 1-based source order of `sh` steps in that function. The success example, converted from the repository root with `--output examples/shared-library/success/migration`, references:

```text
bash examples/shared-library/success/migration/scripts/build-lib/publish/packageSources-1.sh 'packaged'
bash examples/shared-library/success/migration/scripts/build-lib/publish/call-1.sh
```

The workflow already sets `defaults.run.shell: bash`. Library steps still invoke `bash` explicitly so the script path is an argument, not a shell string built by concatenation. `pipebridge_stash.py` and `pipebridge_unstash.py` are pipebridge-owned templates, written only if a stash or unstash step was lowered. They are not extracted from Groovy.

`--force` covers `workflow.yml`, both reports, and `scripts/`. Without `--force`, an existing file in that set is a refusal, exit `1`, and no partial tree is written. Scripts are written only after the workflow write succeeds. A later failure deletes scripts this run created.

Staging is one handled-failure transaction across workflow, reports, and scripts: all artifacts are staged to unique temp files and previous contents backed up before commit; a handled failure restores previous files byte-for-byte, removes newly introduced outputs, and cleans temp files. `--force` follows the same rollback. Stale scripts from a previous run that this run did not create are not deleted unless `--force` covers them; ownership is tracked per run. Original files are preserved on handled failures. Process-kill between replacements remains a documented non-crash-atomic limit.

A disabled draft (`if: false`) still contains lowered steps when the only blocker is `PB-CRED-SETUP`, and it still contains the scripts those steps reference, so a reviewer can read them. A conversion with no lowered library `sh` and no stash writes no `scripts/` directory.

## 10. Credentials

Library `withCredentials` uses the current header rules, the current map schema, and the current naming rules. This design does not restate them loosely:

- Variable `fullmatch` `^[A-Za-z_][A-Za-z0-9_]{0,127}$`, and the uppercase form must not start with `GITHUB_` or `RUNNER_`.
- Secret `fullmatch` `^[A-Z][A-Z0-9_]{0,99}$`, and must not start with `GITHUB_` or `RUNNER_`.
- Map schema remains `{"schema_version":1,"credentials":{"<id>":{"secret":"<NAME>"}}}`.

Injection stays step-scoped, on the lowered steps that were inside the binding, through `credential_binding_ids`. Generated secret expressions are still not passed through `escape_github_expressions`.

The success example's map is `examples/shared-library/success/credential-map.json`: credential id `npm-token`, secret `NPM_TOKEN_GH`. The bound step is the only step with:

```yaml
NPM_TOKEN: ${{ secrets.NPM_TOKEN_GH }}
```

`packageSources`, `stash`, `unstash`, and the Jenkinsfile `sh` steps do not get that env entry.

Readiness is unchanged. A complete map without `--secrets-ready` is exit `2`, `PB-CRED-SETUP`, and a disabled draft whose lowered steps remain for review. `--secrets-ready` is an unverified acknowledgement (`PB-ASSUME-CREDENTIALS`). It does not read values and does not call `gh`.

Inventory records remain after a stage is cleared. A binding discovered in a library file keeps its library span and the Jenkinsfile stage name.

## 11. Stash and unstash

One job only. Storage is a directory on that runner:

```text
$RUNNER_TEMP/pipebridge-stash/<name>/
```

It is not an Actions artifact. A later job, a matrix leg, or another agent cannot unstash it. That transfer is a different milestone and must not be approximated with `actions/upload-artifact` in this one.

Static checks, after lowering, in job source order:

- Every `unstash` name has an earlier `stash` of that name. Otherwise `PB-LIB-CALL`: `unstash 'dist' has no earlier stash of that name in this job.`
- A second `stash` of the same name is `PB-LIB-CALL`: `stash name 'dist' is already used in this job.` Jenkins overwrite is not reproduced.
- A stash in a stage that was blocked and cleared does not count. A later unstash of that name is the missing-stash finding.
- These checks do not require the stash step to have run. The failure fixture stashes `dist` textually before the next stage's unstash, so conversion succeeds even though `exit 1` is earlier in the same function. Runtime never reaches that stash. That is intentional.

Glob grammar, `fullmatch` of the whole pattern:

```text
glob    := segment ('/' segment)*
segment := '**' | '*' | literal
literal := [A-Za-z0-9._-][A-Za-z0-9._-]*
```

No segment may be `.` or `..`. No leading `/`. No empty segment. No backslash. `*` matches one path segment. `**` matches zero or more segments. `dist/**` therefore matches a regular file whose first segment is `dist`, including a regular file whose whole path is `dist`. Directories are not copied as files.

No implicit exclude of `.git` or of SCM metadata. An omitted `excludes` excludes nothing. A file matching both patterns is excluded. Zero matches is a runtime failure. `allowEmpty` is not accepted.

`pipebridge_stash.py` contract:

- Arguments: name, includes, optional excludes.
- Workspace is `$GITHUB_WORKSPACE`. Destination is `$RUNNER_TEMP/pipebridge-stash/<name>`.
- Reject a name or glob that fails the grammar, a destination that already exists, or a missing `GITHUB_WORKSPACE` or `RUNNER_TEMP`. Exit `2` for those caller errors.
- Walk with `followlinks=False`. Skip nothing silently if a candidate's realpath escapes the workspace or if a matched path is a symlink: exit `2`, copy nothing, remove a destination this run created.
- Copy matching regular files with `shutil.copy2`, preserving the relative path.
- Zero copies: exit `1`, remove the destination, stderr `pipebridge-stash: no files matched`.

`pipebridge_unstash.py` contract:

- Argument: name.
- Source directory must exist under `$RUNNER_TEMP/pipebridge-stash/<name>` and must not escape that parent.
- Copy regular files back onto `$GITHUB_WORKSPACE`, overwriting the same relative paths. A symlink in the stash is exit `2`. A missing source is exit `1`, stderr `pipebridge-unstash: stash not found`.

Before copying, validate every source-relative destination against `$GITHUB_WORKSPACE`: resolve the target path and reject any destination that escapes the workspace, including through an existing parent symlink. No file outside `$GITHUB_WORKSPACE` is read or overwritten. Tests must prove this with a symlinked parent and a `..` destination, showing no outside file is touched.

Cleanup is a pipebridge-owned final step, emitted only when a stash or unstash was lowered:

```yaml
- name: Remove pipebridge stash
  if: always()
  continue-on-error: true
  run: python3 -c 'import os, shutil; root=os.path.join(os.environ["RUNNER_TEMP"], "pipebridge-stash"); shutil.rmtree(root, ignore_errors=True)'
```

`continue-on-error: true` keeps a cleanup failure from masking the original job failure. This is not a translation of Jenkins `post`. It does not run if the runner is killed. It does not delete the workspace.

The helpers require `python3` on the runner. `agent any` still maps to `ubuntu-latest`, which has `python3` and `bash`. A mapped self-hosted label is not checked for either binary. That requirement is an assumption (§16), not a Jenkins feature.

## 12. Findings

New codes, added to `REGISTRY` and never renumbered:

| Code | Severity | When |
| --- | --- | --- |
| `PB-LIB` | blocker | Unchanged. Unsupported or unresolved library form, including an eligible annotation whose name is not in the map, and the pipeline `library` section. |
| `PB-LIB-CALL` | blocker | Missing var, missing `call()`, ambiguous var, shadowing, recursion, depth cap, unsupported library operation, bad arguments, bad stash/unstash, unreadable reached file. |
| `PB-LIB-MAP-UNUSED` | info | Map entry not named by a resolved annotation. |
| `PB-ASSUME-LIBRARY` | info | One per resolved library. |

`PB-ASSUME-LIBRARY` message, no revision:

```text
Local directory '<path>' was used as library 'build-lib'. Jenkins library resolution was not run.
```

With a revision:

```text
Local directory '<path>' was used as library 'build-lib'. Annotated revision 'v1' was not fetched or checked.
```

Every `PB-LIB-CALL` message ends with a space and `Call chain: <chain>.` The chain is `file:line name()` joined by ` -> `, from the Jenkinsfile call through each helper to the failing call. Example:

```text
Library call 'missing' has no vars/missing.groovy in the loaded libraries. Call chain: Jenkinsfile:8 missing().
```

`file` in the chain is the path relative to the process cwd when that file is under it, otherwise the path as opened. Finding `line` and `col` are the failing token. Finding JSON keeps its current keys and types. `source_path` is included only when the token is not in the Jenkinsfile, so existing Jenkinsfile findings keep today's key set.

`PB-INTERP`, `PB-CRED`, `PB-CRED-MAP`, and `PB-CRED-SETUP` keep their current codes. When the token is in a library file, the message is the current message plus the same call-chain suffix, and `source_path` is set. Jenkinsfile findings of those codes do not gain the suffix.

A reached unsupported call blocks that stage and clears its steps. Other stages that fully lower may still translate. A load-time failure (shadowing, duplicate var name, duplicate declaration) marks the pipeline blocked so no stage is presented as translated from a library that was not accepted.

D2 is unchanged. An unresolved custom step inside an already blocked Jenkinsfile scope remains an opaque unknown step. Library files are not opened from diagnostic traversal.

Dedup is the existing finding dedup. Exit codes are unchanged: blockers exit `2`, infos do not, map and CLI structural errors exit `1`, a clean resolved conversion exits `0`.

## 13. Report

`build_report` gains a `libraries` object on every report:

```json
{
  "map_supplied": true,
  "loaded": [
    {
      "name": "build-lib",
      "path": "examples/shared-library/success/build-lib",
      "revision": null,
      "vars": ["publish"]
    }
  ],
  "calls": [
    {
      "name": "publish",
      "status": "resolved",
      "source_path": "examples/shared-library/success/Jenkinsfile",
      "line": 7,
      "chain": [
        "examples/shared-library/success/Jenkinsfile:7 publish()",
        "examples/shared-library/success/build-lib/vars/publish.groovy:2 packageSources()"
      ]
    }
  ]
}
```

`map_supplied` is false, and both arrays are empty, when no map is given and no library call was resolved. `revision` is the annotation text after `@`, or `null`. `vars` lists reached var names in source order. `status` is `resolved` or `blocked`. A blocked call still appears, with the chain that was known.

Translated steps that came from a library include `source_path` and `script_path` in the step object when those fields are set. Jenkinsfile steps do not gain those keys. `detail` for a library `sh` is the script body after `$N` replacement, never the parameter value and never a secret value. `args` is included only when non-empty.

This object is additive. The implementation PR updates schema checks and committed reports on purpose. Workflow YAML for a pipeline that does not resolve a library stays byte-for-byte identical, including `examples/python-build/migration/workflow.yml`. This design PR does not regenerate those files.

Markdown gains a short Libraries section when `loaded` or `calls` is non-empty: name, path, unverified revision if any, and each call's status and chain. It says the local directory was not fetched and was not executed.

## 14. Runtime validation

The implementation PR, not this one, validates the generated example. Convert from the repository root.

Success:

```sh
pipebridge convert examples/shared-library/success/Jenkinsfile \
  --library-map examples/shared-library/success/library-map.json \
  --credential-map examples/shared-library/success/credential-map.json \
  --secrets-ready \
  --force \
  --output examples/shared-library/success/migration
```

Expected conversion: exit `0`, no `PB-LIB`, no `PB-LIB-CALL`. Infos include the existing runner, checkout, shell, trigger, and single-job assumptions, plus `PB-ASSUME-LIBRARY` and `PB-ASSUME-CREDENTIALS`.

The same command without `--secrets-ready` is exit `2`, `PB-CRED-SETUP`, `if: false`, and the lowered steps are still in the draft.

GitHub discovers workflows only in the repository root `.github/workflows/` directory. The implementation copies the generated workflow there for the live run. It must not set `defaults.run.working-directory`. Script paths are relative to `$GITHUB_WORKSPACE` after checkout at the repository root. A working-directory override would break those paths. This is the same discovery constraint as `examples/python-build`, with the opposite working-directory choice, and it must be stated in that example's README when the live workflow is added. This design PR does not add a live workflow, so actionlint's current set is unchanged.

Before dispatch, a human creates the dummy secret interactively. pipebridge does not run this:

```sh
gh secret set NPM_TOKEN_GH
```

The dummy value must not occur in the workflow, the scripts, or the Jenkinsfile. The bound step checks `-n` and writes `ok`. It must not print the value.

Dispatch `workflow_dispatch` on the copied workflow. Assert:

- job conclusion `success`;
- the log does not contain the dummy value;
- the restore test step succeeded, which is the check that `dist/marker.txt` is exactly `packaged` and `dist/seen.txt` exists after `rm -rf dist` and `unstash`;
- the workflow YAML has `NPM_TOKEN` only on the step lowered from inside `withCredentials`.

Failure, no credential map:

```sh
pipebridge convert examples/shared-library/failure/Jenkinsfile \
  --library-map examples/shared-library/failure/library-map.json \
  --force \
  --output examples/shared-library/failure/migration
```

Expected conversion: exit `0`, workflow enabled. Dispatch it. Assert the `exit 1` step's conclusion is `failure`, the job conclusion is `failure`, and the later step that would run `echo restored` has conclusion `skipped`. Do not treat a grep of the workflow file as evidence that the step ran.

A unit test runs `pipebridge_stash.py` and `pipebridge_unstash.py` in a temp directory with `GITHUB_WORKSPACE` and `RUNNER_TEMP` set: write `dist/marker.txt`, stash `dist/**`, delete the workspace copy, unstash, compare bytes. That test does not need a runner. The dispatch above is the end-to-end demonstration.

## 15. Tests the implementation must add

Parser and resolver:

- eligible annotation plus a complete map lowers the success example in the order in §8;
- `@Library` with no map, or a name absent from the map, keeps the current `PB-LIB` text, exit `2`, disabled draft, no `scripts/`;
- pipeline `library` section and `library 'name'` stay blocked as they are today;
- missing var, missing `call()`, argument count mismatch, non-literal argument;
- two loaded libraries with `vars/publish.groovy`: ambiguous, both paths, pipeline blocked;
- `vars/sh.groovy` in a loaded library: shadow finding, pipeline blocked, Jenkinsfile `sh` still uses the built-in parser;
- direct recursion and mutual recursion, with the cycle text;
- a chain of 21 calls hits the depth cap;
- `script { forbiddenStep() }` inside a reached library body does not translate `forbiddenStep` and does not enter the body;
- a semicolon inside a library string does not split the statement; a later unsupported sibling after a semicolon is still reported;
- braces in library strings and comments do not desync the scan;
- a malformed reached library file is exit `2`, not a Jenkinsfile `MalformedPipelineError`.

Paths, quoting, credentials, restoration:

- map path `../outside`, an absolute path, and a symlink that escapes the map parent are exit `1` with no artifacts;
- map path pointing at `vars/` rather than the library root is exit `1`;
- parameter value `a'b c;rm` appears as one single-quoted argv token and does not appear in the script file;
- `NPM_TOKEN` env is only on the bound lowered step;
- inventory still contains the library binding after the stage is cleared for an unrelated blocker;
- stash helper restores bytes after deletion; a pattern of `..` is rejected; zero matches exits `1`;
- duplicate stash name and unstash-before-stash are `PB-LIB-CALL`.

Compatibility:

- `examples/python-build` workflow bytes unchanged;
- Kymatio-like and other current exit-`2` fixtures keep their codes and disabled drafts when no library map is passed;
- malformed Jenkinsfile still writes no artifacts;
- a test fails if conversion invokes `groovy`, `gh`, or a secret-value read. Follow the existing credential tests' approach rather than adding a network call.

## 16. Demonstrated behavior and assumptions

A successful dispatch demonstrates only this:

- the generated workflow runs on GitHub-hosted `ubuntu-latest`;
- `bash` ran the extracted script;
- the literal argument arrived as argv and the restored file bytes matched;
- the dummy secret was present enough for `test -n` on the bound step, and the value was not printed;
- a non-zero library `sh` failed the job and later steps were skipped;
- stash files survived a workspace delete on the same job, then were restored.

It does not demonstrate:

- Jenkins CPS, library classpath, `src/`, or global-library configuration;
- that the local directory matches an `@rev` or a Jenkins library repository;
- credential-value equality with Jenkins;
- stash across agents, nodes, or jobs;
- Ant includes beyond the glob in §11, implicit SCM excludes, `allowEmpty`, symlink stashing, or file-owner preservation;
- that `python3` exists on a self-hosted label;
- that the author's unquoted `$N` will not word-split. Safe passing is the argv boundary. The success script quotes `"$1"` because the Groovy source quotes the interpolation.

`PB-ASSUME-LIBRARY` records the local-directory assumption on every resolved library. `PB-ASSUME-RUNNER`, `PB-ASSUME-CHECKOUT`, `PB-ASSUME-SHELL`, `PB-TRIGGER-MANUAL`, and `PB-SINGLE-JOB` remain the existing infos. None of them is a runtime-equivalence claim.

## 17. Implementation boundaries

Later implementation, not this PR. One new module owns library parsing and lowering: `src/pipebridge/libraries.py`. It returns lowered steps, findings, and script bodies. It does not emit YAML.

| File | Responsibility |
| --- | --- |
| `src/pipebridge/libraries.py` | Map load, vars resolution, statement grammar, cycle and depth checks, script-body substitution. |
| `src/pipebridge/parser.py` | Resolved `@Library` omits `PB-LIB`. Unresolved forms stay on the current path. A custom step is handed to the library resolver only when a library was resolved; otherwise today's `PB-SYNTAX` path runs. |
| `src/pipebridge/model.py` | New `Step` fields with defaults. No new pipeline type. |
| `src/pipebridge/workflow.py` | Emit script-plus-argv, stash/unstash helper invocations, and the cleanup step. Leave inline `sh` emission as it is when `script_path` is unset. |
| `src/pipebridge/findings.py` | The three new codes. |
| `src/pipebridge/reporting.py` | Additive `libraries` object and the optional step keys. |
| `src/pipebridge/cli.py` | `--library-map` on `analyze` and `convert`. |
| `tests/` | Section 15. |
| `examples/shared-library/` | Already the fixtures. The implementation adds `migration/` only after conversion is real, and documents the live-workflow copy. |

Do not widen `parser.py`'s diagnostic walker into library files. Do not change credential naming or the `--secrets-ready` meaning.

## 18. Acceptance for the later implementation

1. The success fixture with both maps and `--secrets-ready` exits `0`, emits no `PB-LIB`, and writes the two scripts in §8 plus the stash helpers.
2. The same command without `--secrets-ready` exits `2`, disables the job, and still writes the reviewable steps and scripts.
3. The failure fixture converts at exit `0`. A dispatched run fails, and the `echo restored` step is skipped.
4. Unmapped `@Library` keeps the current `PB-LIB` finding and writes no `scripts/`.
5. No reached supported call remains a blanket `PB-SYNTAX` or `PB-LIB` when the map and the body are both accepted.
6. Recursion, missing definitions, ambiguous vars, and unsupported operations each produce `PB-LIB-CALL` with a source location and a call chain.
7. Parameter values are absent from script files. Secret values are absent from every generated file and are never read.
8. Non-library workflow bytes, including the python-build example, stay identical.
9. The full suite, actionlint, and the existing python-build example validation pass.
10. No version bump, tag, or release is part of the implementation PR unless a later release PR says so.

**Status:** Implemented (PR #26 `7a2f067abf98e28bfcb57438344dc317668fcbfc`, PR #27 `522b0088ee0595b39b542ba2cb4a9ce810d73079`, PR #28 `f54d56e87b8ca8c94cf03aff25a6436e7444bf3a`). Live `workflow_dispatch` validation results and limits are recorded in [`docs/shared-library-live-validation.md`](shared-library-live-validation.md).

## 19. What this design PR does not change

- `src/pipebridge/**`
- tests, changelog, version, or release notes
- `examples/python-build/**`
- `.github/workflows/**`
- committed migration reports
- any tag, release, or secret

CI on this PR is the existing four jobs. They do not convert `examples/shared-library/`.
