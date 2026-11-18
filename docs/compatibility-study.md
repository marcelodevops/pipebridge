# Pipeline compatibility study — evidence for v0.2.0 planning

**Date:** 2026-11-18
**Tool under study:** pipebridge **0.1.0** (installed release, wheel from
<https://github.com/marcelodevops/pipebridge/releases/download/v0.1.0/pipebridge-0.1.0-py3-none-any.whl>;
pipebridge is not on PyPI) in a fresh virtualenv, Python 3.13.15, macOS 26.6.2 arm64.
**Method:** static analysis only. Source Jenkinsfiles were **never executed**,
and no shell command from them was run; only `pipebridge analyze` /
`pipebridge convert` were invoked on them. Originals were kept **outside this
repository**; this PR carries links, metadata, and clearly labeled **synthetic
equivalents** (`synthetic/`) so the construct mix can be reproduced without
redistributing third-party files. No generated workflow was placed under
`.github/workflows/`.

## 1. Sample and provenance

All files are declarative `pipeline { … }` Jenkinsfiles from official project
repositories, fetched via `raw.githubusercontent.com` at an immutable commit
SHA (default-branch HEAD at retrieval). Retrieval date for all: **2026-11-18**.

| # | Project | Category | Source (immutable) | License | File sha256 | Redistribution |
|---|---------|----------|--------------------|---------|-------------|----------------|
| 1 | Eclipse Jetty | Java/Maven, parallel matrix build | <https://github.com/jetty/jetty.project/blob/1ba887ccc5fa3a5fa8a512b7deacc0fff02f0a87/Jenkinsfile> (branch `jetty-12.1.x`) | EPL-2.0/Apache-2.0 (GitHub: NOASSERTION) | `8a460d88b8225f366e14907561adc797b8c7684858630bab11ce0ecfb2f76252` | links + synthetic only |
| 2 | Couchbase CLI | Python application (Gerrit verify) | <https://github.com/couchbase/couchbase-cli/blob/d98e187d7e4e9758a46d859393aeee84801ba75e/Jenkinsfile> (branch `master`) | Apache-2.0 | `42311707672a028d9131576adfc426008a933667f35840582ecb811b34ef1141` | links + synthetic |
| 3 | Kymatio | Python application (GPU container) | <https://github.com/kymatio/kymatio/blob/50d7461db6111eb4b20d32e670a5556d4da6134f/Jenkinsfile> (branch `main`) | BSD-3-Clause | `68f22a456f332512ac1b76660418f00ae762956027f80602308c0751aae05d87` | links + synthetic |
| 4 | Tutanota (client release) | Node application (staged release) | <https://github.com/tutao/tutanota/blob/324b7b87649343ad4859b307f7e640249d6fa745/ci/Release.Jenkinsfile> (branch `master`) | GPL-3.0 | `1420840fd2ca9795b5b9c032062a51e304a4cece25277cfe3678c0434ea745f2` | links + synthetic only |
| 5 | Memphis | Container build/publish + Kubernetes deploy | <https://github.com/superstreamlabs/memphis/blob/0f97a13117ec04fa914c3c539e81a9a4145cec7a/Jenkinsfile> (branch `master`) | BSL 1.1 (GitHub: NOASSERTION) | `ae4fbc8fc77c90263cc83439f4f447245f8dd8c9a32564e5449bee1d79c77249` | links + synthetic only (not open source) |
| 6 | HMRC API Platform (lambda deploy) | Infrastructure deployment (gov cloud) | <https://github.com/hmrc/api-platform-get-apis-lambda/blob/f2276abf85d7c174b1a20cf80d4155b8a82722e5/Jenkinsfile> (branch `main`) | Apache-2.0 | `34def091ff7a049d22d52b4b7091411b94ff1ad8cd490c11844c066925b8c55a` | links + synthetic |
| 7 | Red Hat DO400 training app | Node application (minimal) | <https://github.com/RedHatTraining/DO400-apps/blob/cc78ffcccc68014a1c7d765e07d634fb462d392c/greeting-console/Jenkinsfile> (branch `main`) | Apache-2.0 | `00930c8359c0225db15e2f7a96d636f6767560f890c6cadd76188cad0d876407` | links + synthetic |

**Collection notes.** Found via GitHub code search (`filename:Jenkinsfile`
plus category markers) and direct verification. Inspected and **excluded**:
`jenkinsci/jenkins` (flagship, but **scripted** pipeline, not declarative),
`jenkinsci/docker` (scripted), `jenkins-infra` repos (scripted/shared-library),
`nimble-platform/k8s` (scripted), `kingdee/kd-charts` (scripted),
`hmrc/lambda-maxmind-downloader` (scripted). **Terraform:** **none found in this search.** The searches used surfaced no
official project repository with a declarative Terraform Jenkinsfile — the
remaining hits were personal/educational repos. This is a statement about
this search only, not about the ecosystem. The infrastructure category is
therefore represented by the HMRC government deployment pipeline (#6); this
is a recorded limit of the sample, not a claim that the category is
Terraform-tested.

**Secrets/sensitive-data inspection (manual read of every file):**

- **kymatio #3: contains a hardcoded codecov upload token** in shell text
  (a real credential in a public file). Not copied anywhere; the synthetic
  deliberately uses no token value. Flagged here so nobody treats that file
  as safe-to-copy material.
- couchbase #2: references public infrastructure hostnames
  (`review.couchbase.org`, Gerrit `buildbot@` user) — not secrets.
- memphis #5: uses `withCredentials` with a credential **ID** only (Jenkins-side
  reference, not a secret value); repository is **BSL 1.1** — not open source,
  so links + synthetic only.
- No hardcoded passwords/tokens/keys in any other file.

## 2. Analysis results (pipebridge 0.1.0)

`analyze` and `convert` were run per file; convert outputs were YAML-parsed
(all 7 valid), and findings were cross-checked by manual reading of every
source file. Exit codes: 0 = no blockers, 2 = blockers, 1 = parse error.

| # | Pipeline | analyze / convert | Findings (blockers, with source lines) | Manual accuracy | Generated output |
|---|----------|-------------------|----------------------------------------|-----------------|------------------|
| 1 | Jetty | 2 / 2 | `PB-AGENT` L4 (`agent none`), `PB-SYNTAX` L6 (options), `PB-POST` L106, `PB-SYNTAX` L123 (5 helper `def` functions after the pipeline block) | **Accurate** — every finding matches the cited line; but see **defect D2**: the nested `parallel` block (L15), 5 per-stage agents, and timeouts generated **no** findings | valid YAML; disabled draft; only top-level stage "Parallel Stage" listed |
| 2 | couchbase-cli | 2 / 2 | `PB-SCRIPT` L10 | **Inaccurate classification** — the file **is** a declarative pipeline; the tool rejects it wholesale because of 3 `import` statements at L10–12 before `pipeline {` (see **defect D1**) | valid YAML; disabled draft with **empty stage list** (no structure extracted) |
| 3 | Kymatio | 2 / 2 | `PB-AGENT` L2, `PB-SYNTAX` L3 (options), `PB-POST` L35 | **Accurate** — line-perfect; per-stage `dockerfile` agent (L10–15) subsumed under the pipeline-level `PB-AGENT` | valid YAML; disabled draft; stage "main" (L9) listed |
| 4 | Tutanota release | 2 / 2 | `PB-SCRIPT` L3 | **Inaccurate classification** — declarative pipeline (L5–489) preceded by `def releaseNotes` (L3), followed by 2 helper functions (L495, L500) → whole file rejected (**D1**) | valid YAML; disabled draft; empty stage list |
| 5 | Memphis | 2 / 2 | `PB-SCRIPT` L1 | **Inaccurate classification** — declarative pipeline (L2–332) preceded by a `String` declaration (L1), followed by 2 helper functions (L333, L341) (**D1**) | valid YAML; disabled draft; empty stage list |
| 6 | HMRC lambda deploy | 2 / 2 | `PB-SCRIPT` L4 | **Inaccurate classification** — declarative pipeline preceded by two `String` declarations (L4–7) (**D1**) | valid YAML; disabled draft; empty stage list |
| 7 | DO400 greeting-console | 2 / 2 | `PB-AGENT` L2 (`label "nodejs"`) | **Accurate** | valid YAML; disabled draft; all 3 stages listed |

All `PB-*` codes resolve to the stable registry (23 codes, severities
blocker/warning/info); info findings (`PB-ASSUME-SHELL`, `PB-SINGLE-JOB`,
`PB-TRIGGER-MANUAL`, `PB-ASSUME-RUNNER`) were emitted as documented.

**No parser crash occurred on any file (no exit 1); all generated
`workflow.yml` files parsed as valid YAML; drafts are loud about what was
not translated (`[NOT MIGRATED]` step, `if: false`). The finding list is
**not** complete in every case, however: nested constructs inside pipelines
with pipeline-level blockers are not enumerated (D2), so "everything was
reported" is **not** claimed.** Two systemic problems were found:

### D1 (correctness/accuracy defect): Groovy prelude/postlude discards or truncates the analysis

5 of 7 sample files wrap a declarative pipeline in surrounding Groovy:

- **Prelude** (Groovy statements before `pipeline {`): `import` (couchbase #2),
  `def`/`String` variable declarations (tutanota #4, memphis #5, hmrc #6) — **4 files**.
- **Postlude** (helper `def name() { … }` definitions after the closing brace):
  jetty #1 (5 functions), tutanota #4, memphis #5 — **3 files**.
- Prelude and/or postlude: **5 of 7 files**.

The two cases behave differently:

- The **4 prelude files** are rejected wholesale as `PB-SCRIPT`: **zero
  structure is extracted** — empty stage list, no per-construct findings —
  even though the `pipeline {}` block is present and parseable.
- **Jetty (postlude only)** is parsed and **partially extracted** first —
  correct findings for `agent none` (L4), the options directive (L6), and
  `post` (L106), plus the top-level stage in the draft — and only then
  rejected at the trailing functions with `PB-SYNTAX`
  ("unexpected content after the pipeline block", L123).

Minimal probes with the release binary isolate the rule: a leading `def x = 1`
before `pipeline {` yields `PB-SCRIPT` for the entire file; a trailing
`def helper() { … }` yields `PB-SYNTAX` after the pipeline block. On
**genuinely scripted** files (`jenkinsci/jenkins`, `jenkinsci/docker`)
`PB-SCRIPT` is the correct classification — the code is right for scripts and
wrong for the declarative-with-Groovy pattern. The consequence: the four
prelude files get zero extracted structure, and jetty's analysis is truncated
by its postlude — for files whose `pipeline {}` blocks could have been parsed.

### D2 (completeness defect): nested constructs are not enumerated when pipeline-level blockers exist

Jetty #1 contains a `parallel` block (L15) with 5 nested stages, per-stage
node agents, and timeouts — none of which appear as findings (no `PB-PARALLEL`;
only the top-level stage is listed in the draft). Enumeration stops at the
first pipeline-level blocker, so the finding list — the user's migration
checklist — under-reports the work. No output is wrong per se (the draft is
disabled and loud about it), but the report claims to enumerate what is
outside the subset and does not.

## 3. Frequency of unsupported constructs (manual count, 7 files)

| Construct | Files | Codes that cover it today |
|-----------|-------|---------------------------|
| Custom/labeled agent (`label`, `node`) | 7/7 | `PB-AGENT` |
| Docker/dockerfile agents (stage-level) | 3/7 (jetty-node, kymatio, hmrc) | `PB-AGENT` |
| `post` section | 4/7 (jetty, kymatio, couchbase, memphis) | `PB-POST` |
| Non-literal `environment` values (shell output, `readFile`, Groovy exprs) | 4/7 | `PB-ENVVAL`/`PB-INTERP` |
| Groovy prelude/postlude around the pipeline block | 5/7 | (mis)fired as `PB-SCRIPT` / `PB-SYNTAX` — see D1 |
| `options` directive | 2/7 | `PB-SYNTAX` (no dedicated code) |
| `when` conditions | 2/7 (jetty, hmrc) | `PB-WHEN` |
| `parallel` execution | 1/7 (jetty) | `PB-PARALLEL` (not emitted — see D2) |
| `script` blocks inside steps | 2/7 (jetty, hmrc) | `PB-SCRIPT` (blocker for the construct) |
| `parameters` | 1/7 (tutanota) | `PB-PARAM` |
| `stash`/`unstash` | 1/7 (hmrc) | covered under `PB-SYNTAX`/unsupported steps |
| `withCredentials` | 1/7 (memphis) | `PB-CRED` |
| `input` approval gate | 1/7 (tutanota) | `PB-INPUT` |
| `timeout` | 2/7 | under `PB-SYNTAX`/options |
| Jenkins-specific vars in shell text | 3/7 | `PB-JENV` (warning) |

## 4. Correctness defects vs missing features

- **Defects (correctness of the report itself):** D1 (prelude files lose all
  structure; the postlude-only file's analysis is truncated) and D2
  (nested-construct under-reporting).
- **Missing features (expected for the MVP subset):**
  docker/dockerfile agents, `post`, `parallel`, `options`, `when`,
  `parameters`, `stash/unstash`, `withCredentials`, `input`, `timeout`,
  `script` blocks, non-literal environment values. Constructs the MVP parses
  are reported — but **not all unsupported constructs are reported in every
  case**: D2 shows that nested findings are incomplete when pipeline-level
  blockers exist.
- **Parser robustness:** no crashes; all files lexed/parsed or cleanly
  rejected; all outputs valid YAML.
- **Runtime equivalence:** not tested and not claimed — the study is static
  (sources never executed).

## 5. Operational implications of the proposed translations (for when the blockers are addressed)

- `agent { dockerfile }` → GitHub `container:` requires the image to **exist
  first**: a faithful translation is a two-phase job (build/push image, then
  run steps inside it) — meaningfully different operational shape (registry
  dependency, cache behavior, GPU flags like kymatio's `--gpus 1` have no
  hosted-runner equivalent).
- `post { … }` → `if: always()/success()/failure()` steps change nothing about
  the job graph but alter result semantics (Jenkins `post` runs in-agent with
  workspace access; Actions `if:` steps run in the same job — comparable, but
  `unstable` results do not exist on Actions).
- `parallel` → `matrix` or separate jobs loses shared workspace state; jetty's
  per-branch `properties(buildDiscarder…)` script block has no Actions
  equivalent at all (retention is repo settings).
- `stash/unstash` (hmrc) → `actions/upload-artifact`/`download-artifact`
  introduces artifact-store latency and size limits absent in-Jenkins.
- `withCredentials` (memphis) → GitHub `secrets` mapping is manual and
  repo-config dependent; forgetting it fails at push time, not conversion time.
- `input` (tutanota) → GitHub Environments with required reviewers changes
  who can approve and where (deployment API), not a step-level translation.

## 6. Limits of this study

- **Small, deliberately selected sample** (7 files, one per planned category
  plus a bonus Node file). No percentages are claimed; counts above are
  frequencies within this sample only, not market estimates.
- Categories were sourced from Jenkins-heavy ecosystems (Jenkins plugins org,
  Eclipse, enterprise/government users); projects that publish no declarative
  Jenkinsfile (HashiCorp, Kubernetes, most CNCF) are absent by construction.
- The Terraform category is **unrepresented** (none found in this search; see
  collection notes).
- Shared libraries (`@Library`, jetty's `infra.*`, HMRC's framework calls) are
  not resolved; findings only cover what is visible in the file.
- Static analysis only: no Jenkins controller was used, nothing was executed,
  and runtime equivalence of any translation is neither tested nor claimed.
- Single analyst, single tool version (0.1.0), single platform.

## 7. Recommendation for v0.2.0 — ONE bounded feature

**Fix D1 first (correctness before features): recognize surrounding Groovy
and extract the declarative pipeline structure for analysis.** The
`pipeline {}` block is parsed and analyzed exactly as a pure declarative file
is today (top-level stage list, per-construct findings, draft). Unmodeled
**executable** Groovy around it is a **BLOCKER**, so generated drafts remain
disabled exactly as today. Info-level findings are reserved for explicitly
supported forms whose omission is demonstrably harmless. **Groovy is never
evaluated.**

- **Value:** today 4 of 7 sample files lose all structure (wholesale
  `PB-SCRIPT`, empty stage list) and the fifth (jetty) is parsed correctly
  and then truncated by its postlude (`PB-SYNTAX` at the trailing functions).
  The fix turns both cases into a complete, accurate report of the
  declarative block — the user's migration checklist — without translating
  anything new and without weakening the disabled-draft safety rule.
- **Classification rules (explicit):**
  1. **Prelude `import` statements** — the one *explicitly supported* form:
     imports execute nothing, so their omission is demonstrably harmless →
     **info-level** finding listing them; the pipeline block is analyzed.
  2. **Prelude variable declarations** (`def`/`String`/…, **any** initializer)
     — **executable Groovy, unmodeled → BLOCKER.** Initializers run at
     Jenkins runtime; an unused variable can still have a side-effecting
     initializer (memphis computes a random id; hmrc derives names from
     `env.JOB_NAME`). They are never evaluated, never classified as "safe",
     and their values are not carried into the workflow.
  3. **Postlude function definitions** (`def name(…) { … }` after the closing
     brace) and **any other statement forms** — **executable Groovy,
     unmodeled → BLOCKER.** Bodies are skipped by balanced-brace scanning —
     not analyzed, not executed.
  4. Content not covered by the recognized forms keeps today's behavior
     (`PB-SCRIPT` for genuinely scripted files, `PB-SYNTAX` for stray
     content after the recognized forms).
- **Draft behavior (invariant, not relaxed):** a draft is disabled
  (`if: false`, exit 2) whenever any blocker exists. Since every surrounding
  executable-Groovy form in this increment is a blocker, all five affected
  files keep disabled drafts; only the report improves.
- **Implementation scope (bounded):**
  - Lexer/parser entry: recognize prelude imports and declarations, and
    postlude function definitions; skip declaration/function bodies via
    balanced-brace scanning using the existing `groovystrings` lexer (Groovy
    strings containing braces must not read as block structure).
  - New stable finding codes, e.g. `PB-GROOVY-IMPORT` (info),
    `PB-GROOVY-PRELUDE` (blocker), `PB-GROOVY-POSTLUDE` (blocker).
  - Function **calls** from within steps keep their existing blockers
    (`PB-LIB`/`PB-INTERP`); nothing silently becomes translatable.
- **Semantic risks:** (1) classifying an initializer as side-effect-free is
  the core trap — therefore no initializer is ever classified; only imports
  get info level. (2) Brace-skipping mis-scoping — mitigated by the
  lexer-based scanner plus tests with brace-containing strings and comments.
  (3) A user assuming declared values were preserved — mitigated by explicit
  finding text ("values are computed at Jenkins runtime and were not carried
  over") and by the draft staying disabled.
- **Required tests (fixture matrix):** imports-only prelude (info finding;
  structure extracted); `def` declaration with a side-effecting initializer
  (blocker; structure extracted); `String` declaration with a **literal**
  initializer (still a blocker — no "safe initializer" special case);
  trailing function (blocker; structure extracted); prelude+postlude
  combined; genuinely scripted file still `PB-SCRIPT`; comment/shebang-only
  file unchanged (no new findings); a call to a postlude function from a step
  still blocks; **every fixture with surrounding executable Groovy
  (declarations/functions) produces a disabled draft (`if: false`) and exit 2,
  while imports-only prelude fixtures follow their separate classification
  rule (info-level import finding; no blocker from the imports themselves)**;
  golden outputs for each fixture; all existing 157 tests pass
  unchanged.
- **Acceptance criteria:**
  1. For the five affected sample files' **synthetic equivalents** in
     `synthetic/`: `analyze` no longer emits `PB-SCRIPT` (the four prelude
     files) or the postlude `PB-SYNTAX` (jetty); it emits the declarative
     findings for the `pipeline {}` block (agents, `post`, options, …), the
     new prelude/postlude findings per the classification rules above, and
     the draft lists **every top-level stage**. Deeper enumeration (nested
     parallel branches, per-branch agents) remains deferred as D2.
  2. Every fixture with surrounding executable Groovy still produces a
     **disabled** draft (`if: false`) and exit code 2.
  3. `jenkinsci/jenkins`-style scripted files (probe fixtures) still yield
     `PB-SCRIPT`.
  4. All generated workflows remain valid YAML; no behavior change for pure
     declarative files (kymatio #3, do400 #7 outputs byte-identical).
  5. Full test suite green on Python 3.10 and 3.13; CI green.
- **Out of scope for v0.2.0** (explicitly): translating any of the newly
  visible constructs (post/parallel/agents/…), evaluating any Groovy,
  classifying any initializer as safe, D2's deeper enumeration, and any
  Terraform-specific handling.

## 8. Reproduction

```sh
# tool
python3 -m venv venv && venv/bin/pip install \
  https://github.com/marcelodevops/pipebridge/releases/download/v0.1.0/pipebridge-0.1.0-py3-none-any.whl
# per pipeline (never execute the Jenkinsfile itself):
venv/bin/pipebridge analyze  <Jenkinsfile>
venv/bin/pipebridge convert <Jenkinsfile> --output <scratch-dir>
```

The `synthetic/*.Jenkinsfile` files in this directory reproduce each
original's finding-code profile under 0.1.0 and are the regression baseline
for the v0.2.0 acceptance criteria.
