# D2 design — diagnostic traversal inside blocked scopes

> **Status: planning only.** This document describes a bounded change. It does
> not implement it, change code, bump the version, or alter any published
> release asset. Scope is defect **D2** from
> [`docs/compatibility-study.md`](compatibility-study.md) §2.

## Problem

pipebridge stops walking a scope as soon as translation becomes ineligible:

- a pipeline-level blocker (`agent none`, `options`, …) makes
  `_parse_stage` skip the whole stage body, and
- a stage-level blocker makes `_parse_stage_body`/`_parse_steps` call
  `_skip_rest_of_block()` at the first unsupported construct.

That is correct for **translation** — nothing inside a blocked scope is safe to
emit — but it also stops **diagnosis**. The `findings` list is the user's
migration checklist, so it under-reports the work. The output is not
semantically wrong: the draft is already disabled with `if: false`. Adding
findings can legitimately change the diagnostic comment and blocker-code text
in that disabled workflow, which is why this design compares blocked workflows
structurally rather than byte-for-byte.

### Current vs proposed findings (Jetty-like synthetic)

Source:
`docs/compatibility-study/synthetic/java-maven-jetty-like.Jenkinsfile`.

Current output (exit 2, draft disabled, `translated = ["Parallel Stage"]`):

```
PB-GROOVY-POSTLUDE  L55, L63, L67   (3 postlude functions)
PB-AGENT            L7             agent none
PB-SYNTAX           L8             options directive
PB-POST             L42            post section
PB-ASSUME-SHELL / PB-SINGLE-JOB / PB-TRIGGER-MANUAL  L6  (info)
```

Proposed additional findings (all still blockers, all parent-scoped):

| Line | Code | Construct | Parent scope |
|------|------|-----------|--------------|
| 16 | `PB-PARALLEL` | `parallel` with two branches | stage `Parallel Stage` |
| 18 | `PB-AGENT` | `agent { node { label 'linux-dind' } }` | `Parallel Stage` → `Build / Test - JDK21` |
| 19 | `PB-WHEN` | `when { beforeAgent true; expression { … } }` | `… → Build / Test - JDK21` |
| 21 | `PB-SYNTAX` | step `timeout` | `… → Build / Test - JDK21` |
| 22 | `PB-SCRIPT` | `script` block | `… → Build / Test - JDK21` |
| 26 | `PB-SYNTAX` | step `mavenBuild` | `… → Build / Test - JDK21` |
| 31 | `PB-AGENT` | `agent { node { label 'linux-dind' } }` | `… → Build / Test - JDK25` |
| 32 | `PB-WHEN` | `when { … }` | `… → Build / Test - JDK25` |
| 34 | `PB-SYNTAX` | step `timeout` | `… → Build / Test - JDK25` |
| 35 | `PB-SYNTAX` | step `mavenBuild` | `… → Build / Test - JDK25` |

`checkout scm` (L25) is a supported step and produces no finding; it is **not**
translated because its enclosing scope is blocked. Branch stage names appear in
the `PB-PARALLEL` message, so a nested stage with no unsupported constructs is
still visible.

What must not change: `translated` still lists only the top-level `Parallel
Stage` with no steps, the draft stays disabled with `if: false`, and exit stays
2. The workflow's **parsed YAML** stays equal — same jobs, steps, triggers,
permissions, runner, and disabled condition. Only diagnostic text may differ:
the `#` comments and the blocker-code list embedded in the `[NOT MIGRATED]`
placeholder step grow with the findings. Byte equality is *not* required for
blocked inputs, because that text is derived from the blocker set.

## 1. Traversal boundaries and diagnostic grammar

Two traversals share one token stream but not one eligibility rule:

- **Translation traversal** — unchanged. Same recursion, same early exits,
  same blocker gating.
- **Diagnostic traversal** — read-only. It reports constructs and never
  produces a `Step`, never clears a blocker, never appends a nested `Stage` to
  `pipeline.stages`.

The diagnostic traversal is entered **only** at the two existing stop points:

1. `_parse_stage` when `pipeline.blocked` is already true (body would be
   brace-skipped today), and
2. a stage-level blocker (today the code calls `_skip_rest_of_block()`), plus
   the same condition inside nested scopes.

At each stop point the traversal covers **both the triggering construct's
eligible body and the remaining siblings** in the enclosing scope. A
stage-level `parallel` blocker must therefore still descend into its branch
`stage` blocks before diagnosing the sections that follow `parallel`; nested
`stages`, `matrix.stages`, and allowlisted step-wrapper bodies are entered the
same way. The construct that produced the blocker is not reported twice — the
`(code, line, col)` suppression below applies inside its body.

Opaque bodies are still never entered, even when they belong to the triggering
construct: `script`, shared-library content, agent internals, `when`
expressions, `post` closures, and unknown/non-allowlisted step closures stop
analysis as listed below.

It is never run on files that already translate cleanly, so clean output is
unaffected by construction.

### Structural descent (recognized declarative grammar)

| Position | Descend into | Report |
|----------|--------------|--------|
| `pipeline` body | `stages`, `post`, `options`, `tools`, `parameters`, `triggers`, `environment`, `agent`, `library` | existing codes, one per section |
| `stages` / nested `stages` | each `stage(…) { … }` | `PB-SYNTAX` for the nested section, then each stage's constructs |
| `stage` body | `agent`, `environment`, `options`, `tools`, `input`, `when`, `steps`, `post`, `stages`, `parallel`, `matrix` | existing codes |
| `parallel` | each branch `stage(…) { … }`, recursively | `PB-PARALLEL` once, with branch names in the message |
| `matrix` | `axis` names (listed, not expanded) and the `stages` block | `PB-MATRIX` once |
| `steps` / wrapper bodies | allowlisted wrappers: `timeout`, `retry`, `catchError`, `dir`, `withEnv`, `withCredentials` | wrapper's own code, then nested steps |
| `environment` | — | existing literal/interpolation rules (values discarded) |

Findings reuse the existing stable codes — `PB-PARALLEL`, `PB-MATRIX`,
`PB-AGENT`, `PB-WHEN`, `PB-INPUT`, `PB-TOOLS`, `PB-POST`, `PB-CRED`,
`PB-SCRIPT`, `PB-INTERP`, `PB-SYNTAX`. **No new codes** are introduced.

### Explicit stopping points (stated in finding text)

Analysis stops, and the finding says so, at:

- `script { … }` — reported (`PB-SCRIPT`), body never inspected.
- Shared-library bodies, `@Library`, and `library { … }` — reported, never
  parsed as declarative syntax.
- `agent { node/docker/dockerfile/kubernetes … }` — reported as one agent
  finding; the agent block's internals are not analyzed.
- `post { … }` condition closures — reported as one post finding; `junit`,
  `websiteBuild()`, etc. inside them are not enumerated.
- `when { expression { … } }` — reported once; the Groovy condition is opaque.
- Any **unknown step closure** not in the wrapper allowlist (`node`,
  `parallel` in steps position, custom functions) — reported once, body
  skipped, "nested content was not analyzed" in the message.
- Unknown syntax in **section** position — one `PB-SYNTAX`, then analysis of
  that scope stops. In **steps** position the statement is reported and
  skipped, and the next step is analyzed (a steps list is a safe sequence).
- Nesting deeper than a fixed depth cap (proposed 20) — one truncation
  `PB-SYNTAX` at the cap, then stop.

### Dedupe and source positions

- Every finding keeps the exact `line`/`col` of its construct token.
- Parent scope is rendered into `message` and `construct` as
  `stage 'X' → parallel branch 'Y'`; this preserves lineage without a new
  field.
- `_add` gains a `(code, line, col)` seen-set. A construct already reported by
  the translation traversal is suppressed when the diagnostic traversal enters
  its body (e.g. `PB-PARALLEL` appears exactly once).
- Before reporting, findings are stable-sorted by `(line, col, code)`. Existing
  emissions are already source-ordered, so current fixtures keep their order;
  a regression test asserts it.

## 2. Model and report changes

**No model change is required.**

- `model.py`: no new `Stage`/`Step`/`ParseResult` fields. Nested stages are
  held on a parser-local parent-scope stack and are never added to
  `pipeline.stages`. `Stage.steps` remains empty for blocked scopes because the
  diagnostic traversal has no step sink.
- `findings.py`: no new codes, severities, or registry entries.
- `reporting.py`: no schema change. Findings still have exactly
  `code`, `severity`, `construct`, `message`, `line`, `col`, `suggestion`;
  `blockers`, `assumptions`, `translated`, and `summary` keep their shapes and
  types. Only the number of entries grows, and `summary.blockers`/`warnings`
  reflect it.

**JSON consumers:** not broken structurally — no keys, types, or exit codes
change. Two behavioral consequences are documented and tested:

1. `findings[]` and `blockers[]` contain more entries for blocked inputs
   (this is the point of D2); consumers that assert exact finding counts or
   full-report snapshots must update expectations deliberately.
2. Findings gain no new keys, so strict schema validators are unaffected.

Ordering stays source-ordered, so report diffs remain reviewable.

**Non-goals:** no translation of newly visible constructs, no enabling of
drafts, no Groovy evaluation, no shared-library analysis, no change to the
`if: false` skeleton, no new CLI flags, no severity reclassification.

## 3. Acceptance criteria and regression tests

Contract:

1. **Jetty-like fixture:** exit **2**; `if: false` present; `translated` still
   `["Parallel Stage"]` with zero steps; findings include the ten additions in
   the table above, with correct `line`/`col` and parent scope.
   `workflow.yml` must be **structurally equal** to the pre-change output
   after parsing both documents: identical `jobs` graph, step count/names/
   order, `runs-on`, `on`/triggers, `permissions`, and `if: false`. The only
   permitted differences are diagnostic text — `#` comments and the
   blocker-code list inside the `[NOT MIGRATED]` placeholder step's `run`
   string. A comparison helper applies exactly that normalization (replace the
   parenthesized `PB-…` list in that placeholder) and asserts the rest of the
   parsed document is equal. Raw byte equality is not asserted for blocked
   inputs.
2. **Clean build-and-test example** (`tests/fixtures/build-and-test`): exit
   **0** and `workflow.yml` **byte-identical**. No diagnostic traversal runs
   on a clean translation, so this fixture is the byte-level guarantee that
   supported output is untouched; it also guards triggers, permissions, and
   steps in the enabled path.
3. **Already-blocked synthetic fixtures** `python-gpu-kymatio-like` (3
   blockers) and `node-minimal-do400-like` (1 blocker) both **exit 2 today and
   must keep exit 2**. Their disabled drafts stay disabled, `translated`
   entries keep their stage lists, and parsed YAML equality (with the same
   diagnostic-text normalization) holds. Newly diagnosed findings inside their
   blocked scopes are expected; a change to exit 0 or to an enabled draft is a
   failure.
4. **Triggering-construct body:** an isolated ordinary file (not
   pipeline-blocked) with a stage-level `parallel` must report the branch
   agents, conditions, steps, and nested stages, not just the `parallel`
   finding. `PB-PARALLEL` appears exactly once; sections after `parallel` are
   still diagnosed; stage list and parsed YAML stay unchanged; exit 2.
5. Nested `stages`, `matrix`, `options`, `tools`, `input`, `when`, `post`,
   stage agents and unsupported steps each produce one finding per construct
   with the correct scope; `(code, line, col)` is unique across the report.
6. `script` and shared-library bodies are never traversed: a fixture with
   DSL-looking text inside `script { }` produces no findings for that text,
   including when the `script` is inside a triggering `parallel` branch.
7. Malformed/unterminated braces and unknown section syntax: no crash, no
   duplicate `PB-SYNTAX`, analysis-stopped text present, existing exit code
   preserved.
8. D1 behavior unchanged: prelude/postlude findings, imports-only info
   findings, and genuinely scripted `PB-SCRIPT` classification.
9. Exit-code matrix unchanged: 0 / 1 / 2 exactly as documented in README, and
   specifically no blocked fixture moves from 2 to 0.
10. Finding object keys are exactly the current set (schema guard test);
    `translated[]` entries still have `stage`, `source_line`, `blocked`,
    `steps`.
11. Full suite green on Python 3.10 and 3.13; `actionlint` 1.7.12 clean on
    generated workflows; documented example validation passes.

Test files: extend `tests/test_surrounding_groovy.py` (synthetic matrix,
stage lists, preserved baseline exit codes), add `tests/test_diagnostics.py`
(grammar, trigger-body traversal, dedupe, stopping points, schema and no-step
guarantees), and add fixtures under `tests/fixtures/` for the isolated
parallel/matrix/nested cases. Use PyYAML `safe_load` for the structural
workflow comparison and keep the clean fixture's byte golden. Store the
pre-change Jetty report and normalized YAML as baselines before touching the
parser.

## 4. Risks and bounded implementation sequence

| Risk | Mitigation |
|------|------------|
| Diagnostic traversal accidentally enables translation | No step sink in diagnostic mode; assert `Stage.steps` empty; parsed-YAML equality on blocked fixtures and byte equality on the clean build-and-test example |
| Only siblings are diagnosed; the blocking construct's body is skipped | Explicit trigger-body rule; isolated stage-level `parallel` test asserts branch findings plus `PB-PARALLEL` exactly once |
| Duplicate findings (translation + diagnostics) | `(code, line, col)` seen-set; suppression of the triggering construct inside its body; uniqueness test |
| Mis-scoping through braces in strings/comments or unterminated blocks | Traverse lexer tokens, never raw text; reuse balanced skipping; fixture matrix incl. brace-bearing strings |
| Arbitrary Groovy read as declarative DSL | Closed grammar table; explicit stop list; never enter `script`, shared-library, `node`, unknown step closures |
| Over-claiming completeness | Message text names every stopping point; docs call diagnostics best-effort within the grammar |
| Deep/large inputs | One token pass; diagnostics only on already-blocked paths; depth cap 20 with explicit truncation finding |
| Consumer surprise from more findings | No schema/key change; ordering preserved; exit 2 preserved for blocked inputs; changelog and README note the added checklist entries; snapshot tests updated deliberately |
| Diagnostic-text comparison drift | One shared normalization helper strips only `#` comments and the placeholder blocker-code list; jobs, steps, triggers, permissions, runner, and `if: false` compare exactly |

Bounded sequence (each step is a reviewable commit/PR, none merges or
releases):

1. **Baseline** — capture the clean build-and-test byte golden and the
   pre-change Jetty/Kymatio/DO400 reports plus normalized parsed YAML; add the
   `(code, line, col)` dedupe and source-order guarantee as no-op behavior.
2. **Eligibility split** — introduce the read-only traversal mode and wire both
   skip sites to it, including the triggering construct's eligible body. No
   new findings yet: clean fixture byte-identical, blocked fixtures
   parsed-YAML equal, baseline exit codes preserved.
3. **Nested stages** — parent-scope stack, `parallel`/nested-`stages`/
   `matrix.stages` branch enumeration from inside the triggering construct,
   branch names in messages.
4. **Sections and steps** — `agent`, `when`, `options`, `tools`, `input`,
   `matrix`, environment values, wrapper allowlist, unsupported-step reporting.
5. **Hardening and contract** — stopping-point messages, depth cap, schema and
   exit-code guards, the YAML comparison helper, fixture matrix,
   README/compatibility-study updates.
6. **Verification** — full suite on 3.10/3.13, actionlint, example validation;
   confirm Kymatio/DO400 still exit 2 and build-and-test still exits 0; report
   exact command output. No version bump, tag, release, or asset change.

Expected size: roughly 250–400 lines of parser code plus tests, no new
dependencies, no new finding codes, and no report schema change.
