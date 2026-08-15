# Fas 3 — Coding Agent v0.1 — design

Status: proposed, awaiting operator review
Date: 2026-08-16
Authority: architectural proposal for one bounded vertical slice; does not override `docs/agents/current-operating-model.md`
Related: `docs/architecture/cortxt-agent-platform-target-architecture.md` §13 (Coding Agent), §15 (Tool Gateway och Execution Runtime), §20 (Säkerhetsmodell), §23 (Fas 3 — Coding Agent v0.1), §32 (Tool Platform); `docs/superpowers/specs/2026-08-15-fas2-agent-runtime-v01-design.md` (the phase this builds directly on); ADR-016/ADR-017 (prove the need via one vertical slice before promoting)

> **Hard dependency: Fas 2 must merge first.** Everything below extends
> `agent-platform/runtime/` — `session_state.py`, `text_inference_port.py`,
> `tools.py`, `agent_loop.py`, `research_profile.py` — plus the additive
> `Strategy.MODEL_ASSISTED` extension to `agent-platform/reasoning/kernel/`.
> As of this writing that code is implemented and code-reviewed but **not yet in
> `main`** (branches `agent/fas2-agent-runtime-plan` / `agent/fas2-agent-runtime-impl`).
> No Fas 3 implementation task may start before Fas 2 is merged; this spec was
> written against the Fas 2 *plan document*'s code listings, not against merged
> source.

> **Draft status.** Unlike the Fas 2 spec — which came out of an interactive
> grilling dialogue with the operator — this draft was written from the
> architecture documents alone. Every place where a real fork was resolved by
> the author rather than by the operator is tagged
> **`Assumption, needs operator confirmation:`** inline, and all of them are
> collected in §"Open assumptions" at the end. Nothing here is final.

## Purpose

Prove Fas 3's exit criterion from the target-architecture staircase (§23):

1. **a simple code fixture can be solved and verified without Pi or Hermes**; and
2. **workspace, network and budget ceilings are machine-proven.**

The second half is what makes Fas 3 different from Fas 2. Fas 2's exit criterion
was a capability claim ("a research fixture can be solved"). Fas 3's is a
capability claim *plus a containment claim*, and a containment claim is only
worth what its tests prove. Accordingly this spec treats boundary enforcement as
the primary deliverable and the code fix itself as the smaller half.

The concrete task chosen to prove the criterion: one tiny, self-contained code
fixture (a single-file off-by-one bug with a failing pytest) copied into a
disposable run workspace, fixed by a model-proposed minimal patch, and verified
by actually running the test suite inside a bounded execution sandbox — with the
whole run refusing to succeed if the patch leaves the declared scope.

Same discipline as Fas 2 and as ADR-016/017's vertical slices: build the
smallest real thing that proves the need, not the full Coding Agent from §13.

## Scope decisions

One decision per Fas 3 deliverable in §23, plus the two forks that cut across
them. Recorded so the "why" is not lost.

### 1. Repository discovery — build fresh, and deliberately trivial

**Decision:** a new `runtime/coding/workspace_map.py` that deterministically
enumerates the run workspace: relative path, size, sha256, and (for text files)
line count, bounded by an extension allowlist, a max-file-count and a
max-total-bytes ceiling. No AST parsing, no symbol index, no import/dependency
graph. Output is a plain dict that goes into the prompt and into the session log.

**Why not more:** §13.1 wants "kartlägga filer, symboler och beroenden" and
§13.2 names `build_dependency_map`. On a three-file fixture a dependency map
would be a hollow ceremony — it would be code we wrote to satisfy a bullet, with
no fixture able to falsify it. That is exactly the failure mode Fas 2 avoided
when it refused to force a richer reasoning strategy onto a task that did not
need one (Fas 2 scope decision 6). A symbol index and dependency map become real
deliverables the first time a fixture spans enough files that discovery can
actually be *wrong*.

**Why build fresh rather than reuse:** nothing in the repo enumerates a
workspace today. `runtime/tools.py`'s `ToolGate` gives us the path-sandboxing
primitive; the enumeration on top of it is ~40 lines.

**Deferred:** `locate_ownership`, `build_dependency_map`, symbol indexing,
repository-instruction reading (`AGENTS.md`/`CLAUDE.md` ingestion). All need a
multi-file fixture to be honest.

### 2. read/search/patch/test/diff tools — grow `runtime/tools.py` into a package, additively

**Decision:** convert `agent-platform/runtime/tools.py` into a package
`agent-platform/runtime/tools/` where `tools/__init__.py` re-exports
`ToolGate`, `ToolAdmissionError` and `read_fixture_file` from `tools/gate.py`
and `tools/fixtures.py`. **Fas 2's import path `from runtime.tools import
ToolGate, ToolAdmissionError, read_fixture_file` and Fas 2's tests must continue
to work unchanged** — the conversion is a move plus a re-export, never a
signature change. Fas 3's new tools land as new modules in that package:

| Module | Tool | Effect class (§32.2) |
|---|---|---|
| `tools/gate.py` | `ToolGate` (from Fas 2) + a `WriteGate` subclass adding symlink rejection and existing-file-only admission | — |
| `tools/fixtures.py` | `read_fixture_file` (from Fas 2, unchanged) | `observe` |
| `tools/workspace.py` | `list_workspace`, `read_workspace_file`, `search_workspace` | `observe` |
| `tools/patch.py` | `apply_patch`, `diff_workspace` | `local_mutation` / `observe` |
| `tools/execution.py` | `run_tests` | `bounded_execution` |

**Why a package and not a sixth top-level module:** five more tools in one flat
`tools.py` would put the admission gate, the write policy and the subprocess
launcher in one file — three different trust boundaries in one blast radius.
Splitting them is what lets the boundary tests target one thing each.

**Why not a full §32.1 tool manifest yet:** §32.1 specifies a declarative YAML
tool contract (`id`, `version`, `input_schema`, `effect_class`, `network`,
`timeout_seconds`, …) validated by a Tool Gateway. v0.1 declares those same
fields, but as a Python dict constant per tool consumed by the gate — not as
YAML files with a registry and a schema validator. Rationale: the same
ADR-016 discipline that kept `agent-platform/` untracked until a slice proved
it. One profile with six tools does not yet show which manifest fields are load-
bearing; encoding the first vertical's guesses into a platform contract is the
mistake `docs/architecture/vertical-package-contract.md` explicitly warns
against. The dict-constant form is deliberately shaped so the later YAML
manifest is a serialization change, not a redesign.

**Assumption, needs operator confirmation (A1):** Fas 3 is allowed to *move*
Fas 2's `runtime/tools.py` into `runtime/tools/` — i.e. touch just-merged Fas 2
code — rather than adding a sibling `runtime/coding_tools.py` and leaving Fas 2's
file frozen. The move is behaviour-preserving and keeps one admission gate for
the whole runtime, which is why it is recommended; but it does modify code that
was reviewed under a different phase.

**Deferred:** unified-diff *parsing* (see decision 6), file creation and
deletion, multi-file patches beyond the declared cap, static-analysis/lint tools,
build tools, git operations of any kind (the run workspace in v0.1 is not a git
repo — see decision 4).

### 3. Execution sandbox — build new and simpler; do **not** depend on Pi Builder

**Decision:** v0.1 uses a bounded, in-process-launched subprocess
(`runtime/execution/subprocess_sandbox.py`), not Docker, and does not reuse
`experiments/runtime-pi-builder/`.

Bounds enforced by the sandbox, all before `subprocess.run` is reached:

- **Command allowlist.** The command is chosen from a static allowlist of argv
  *lists*, never a string. v0.1's allowlist has exactly one entry:
  `[<interpreter>, "-m", "pytest", "-q", "<workspace>"]`. `shell=False`
  unconditionally; no user- or model-supplied string ever reaches a shell.
- **cwd pinned** to the resolved run-workspace root; a resolved cwd outside it is
  a launch refusal, not a warning.
- **Environment scrubbed to an allowlist.** The child gets a freshly built env
  dict containing only what the interpreter needs (`PATH`, `SYSTEMROOT`/`COMSPEC`
  on Windows, `PYTHONHASHSEED`, `PYTHONDONTWRITEBYTECODE`), never
  `os.environ.copy()`. This is the credential boundary: `CORTXT_INFERENCE_API_KEY`,
  `KIMI_API_KEY`, `GH_TOKEN` and anything else in the operator's shell are
  structurally absent from the child, and a test asserts their absence.
- **Wall-clock timeout** with kill-on-expiry.
- **Output caps** — stdout/stderr truncated at a byte ceiling; the truncation is
  recorded as a flag in the result, never silently applied.
- **Deterministic cleanup** — the run workspace is a temp-dir copy, removed on
  every exit path including exceptions (§15's "deterministic cleanup").

**Why not Pi Builder — four independent reasons, any one of which is sufficient:**

1. **It is no longer in the repository.** `experiments/runtime-pi-builder/` was
   moved to `archive/` (commit `2dcc5fa`) and `archive/` was then moved out of
   the repository entirely (commit `546750b`, "kept locally, not published").
   Building Fas 3 on it would make a tracked, CI-verified phase depend on
   unpublished local files.
2. **Its own README lists the gaps as open.** Image tags are not digest-pinned;
   there is no measured model-cost ceiling; `depends_on` gives startup order but
   not proxy readiness, so a production dispatcher still needs a readiness check
   and retry policy; and the Squid allowlist does not inspect encrypted request
   content. `docs/agents/current-operating-model.md` records it as "verified as
   a bounded experiment, not yet promoted to the production harness", with the
   Buzz write-approval round trip still broken.
3. **Its topology is the one Fas 3 replaces.** Pi Builder puts the *agent* (Pi +
   Kimi) inside the container and hands it a workspace. §15 requires the opposite
   split: "Reasoning och exekvering ska vara separata failure domains… En
   persistent reasoning-session får inte i sig innebära persistent
   operativsystemsbehörighet." In Fas 3 the agent runs outside and only a single
   validated *command* crosses into the sandbox. Adapting Pi Builder would mean
   inverting its central design choice, which is not reuse.
4. **Docker is not available in default CI.** The exit criterion demands
   machine-proven ceilings. A boundary proof that only runs where Docker Desktop
   happens to be up is a weaker proof than one that runs on every push.

**What is explicitly *not* claimed:** a plain subprocess is not an OS-level
sandbox. It bounds cwd, env, argv, wall-clock and output — it does not bound
memory, CPU, or raw network syscalls. See decision 7 for exactly how far the
network claim goes, and what would have to change to strengthen it.

**Promotion path (named, not built):** when a fixture needs untrusted
dependencies, real network policy, or resource ceilings, the sandbox interface
(`ExecutionSandbox.run(command_id, workspace) -> ExecutionResult`) gets a second
implementation — a container-backed one that *may* legitimately borrow Pi
Builder's proven pieces (the Squid egress allowlist topology and its
allow/deny test pair are genuinely good work). The interface is designed as a
seam for that, so v0.1 is not a dead end.

### 4. Bounded write policy — copy-in workspace, existing-files-only, platform-computed diff

**Decision, in four parts:**

1. **The run workspace is a disposable copy.** The fixture is copied into a temp
   directory at claim time; a second pristine copy is kept read-only alongside it
   as the diff baseline. The agent never has a handle on the repository. A run
   that goes wrong therefore cannot damage the working tree at all — containment
   is structural first and policy second.
2. **Writable scope = exactly that workspace root**, enforced by `WriteGate`:
   the path must resolve inside the root, must already exist, and must not be a
   symlink (checked with `Path.is_symlink()` on the pre-resolution path *and* by
   the post-resolution containment check, so both symlink-to-outside and
   `..`-traversal fail closed). Denied admission happens before any file handle
   is opened.
3. **Quantitative caps**, all fail-closed, all checked before the write: max
   files touched per run, max bytes per file, max total changed lines. A patch
   exceeding any cap is refused whole — never partially applied.
4. **The diff is computed by the platform, not asserted by the model.**
   `diff_workspace` diffs the live workspace against the pristine baseline with
   `difflib`. `inspect_diff_against_scope` (decision 5) then checks *that* diff
   against a declared scope of allowed path globs. The model has no way to
   under-report what it changed.

**Why existing-files-only:** file creation and deletion each need their own
boundary rules (where may a new file be created? does deletion of the baseline
break the diff?). v0.1's fixture needs neither. Adding them would add untested
boundary surface to a phase whose entire point is that its boundaries are tested.

**Why not git:** using git in the workspace would give free diffs, but would
also mean the sandbox's allowlist has to contain `git`, and `git` is a program
with configurable hooks, credential helpers and network subcommands. Trading a
20-line `difflib` diff for that is a bad exchange in the phase where containment
is the deliverable.

**Follows the existing fail-closed discipline** rather than inventing a new one:
same shape as `provider_policy.evaluate_provider` (deny by default, return
machine-readable reasons, never raise on unknown input) and `BudgetGate` (check
before the expensive action, never after).

### 5. Kodspecifika operatorer — three of the ten, added additively like `MODEL_ASSISTED`

**Decision:** add `Strategy.CODING_ASSISTED` to
`agent-platform/reasoning/kernel/strategy.py` and three operators to
`operators.py`, exactly following Fas 2's precedent: purely additive, never
auto-selected by `select_strategy()`, reached only via a new explicit
`Engine.solve_coding_assisted(...)` entry point, and — critically — **taking
injected callables so `reasoning/` gains no new imports** and
`tests/reasoning/test_no_external_deps.py` keeps passing (ADR-016's repository
invariant).

The three, chosen from §13.2 as the minimum that makes the loop honest:

| Operator | Kind | What it does in v0.1 |
|---|---|---|
| `propose_minimal_patch` | model-assisted | Delegates to an injected `propose` callable (the `TextInferencePort` + prompt) and stores the proposed patch on the state. The only model call in the run. |
| `inspect_diff_against_scope` | deterministic | Delegates to an injected `inspect_scope` callable over the *platform-computed* diff; sets confidence 0.0 and records a scope-expansion reason if the diff touches anything outside the declared scope. |
| `falsify_fix` | deterministic | Delegates to an injected `verify` callable that runs the sandboxed test suite. Confidence 1.0 only if the suite passes **with** the patch **and** fails **without** it (see below). |

**`falsify_fix` is a two-sided check, not a green-tick.** Running the tests once
and seeing green proves the tests pass; it does not prove the patch is why. So
the verifier runs the suite twice: once on the patched workspace (must exit 0)
and once on the pristine baseline (must exit non-zero). A patch that "passes"
because it deleted or neutered the test is caught by the second run. This is the
literal reading of the operator's name in §13.2 — falsify the fix, don't
celebrate it — and it is cheap here because the suite is one file.

**Why only three:** `locate_ownership`, `build_dependency_map`,
`form_bug_hypothesis`, `find_minimal_reproduction`,
`compare_contract_to_implementation`, `analyze_blast_radius` and
`generate_regression_test` all require something this slice deliberately does not
have — a multi-file repo, an unknown bug location, a contract to compare against,
or a hypothesis loop with more than one candidate. Implementing them against a
one-line off-by-one would produce operators whose tests can only assert that
they were called. Fas 2 set the precedent by shipping `direct`/`MODEL_ASSISTED`
only and writing down why the richer strategies would have been hollow.

**Deferred, needs an issue** (mirroring Fas 2's issue #138 for its deferral):
the remaining seven §13.2 operators, gated behind a fixture that can falsify
them.

### 6. Cross-cutting: patch representation — structured content, not model-emitted unified diff

**Decision:** the model returns a JSON object
`{"changes": [{"path": "<relative>", "new_content": "<full file text>"}], "rationale": "..."}`
validated against a JSON Schema by the kernel's verify path (same
`jsonschema` dependency Fas 2 already added). `apply_patch` writes the content;
the *diff* is derived afterwards by the platform.

**Why not a unified diff from the model:** applying a model-emitted unified diff
means writing (or vendoring) a hunk applier, and hunk appliers are where fuzzy
matching creeps in — "context didn't match exactly, apply anyway at offset ±3" is
precisely the class of silent, unverified mutation this phase exists to
eliminate. Whole-content replacement inside a capped, existing-files-only,
copy-in workspace is trivially verifiable, and the diff we then compute is
ground truth rather than a model claim.

**Cost of this choice, stated plainly:** it does not scale to large files (the
model must reproduce the whole file) and it postpones the "minimala patchar"
property of §13.1 from *the model produces a minimal patch* to *the platform
measures whether the resulting diff was minimal*. For a v0.1 fixture of a few
dozen lines that is the right trade; for a real repository it is not, and
unified-diff application becomes a Fas 3.1 deliverable with its own boundary
tests.

**Assumption, needs operator confirmation (A2):** that whole-file content plus
platform-computed diff is acceptable for v0.1, rather than requiring real
unified-diff hunk application from the start.

### 7. Cross-cutting: how far the "machine-proven ceilings" claim actually reaches

The exit criterion names three ceilings. They are proven to different depths, and
the spec says so rather than letting one word cover all three:

| Ceiling | v0.1 proof | Strength |
|---|---|---|
| **Workspace** | Real attempted escapes (traversal, absolute path outside root, symlink pointing outside) are executed in tests against a real temp file, and the test asserts both that the call raised **and** that the target file's bytes are unchanged. | **Strong.** Enforced in our own code, on every platform, in default CI. |
| **Budget** | `BudgetGate` (reused unmodified from Fas 1/2) is consulted before any model call; a `max_calls=0` gate makes the run terminate `blocked` with the backend provably never reached (same test shape as Fas 2's `test_invoke_blocked_by_budget_before_any_backend_call`). Sandbox executions are separately capped by a per-run max-execution count. | **Strong for call-count; weak for money** — `BudgetGate` counts calls, not USD (see A3). |
| **Network** | Enforced *at the admission boundary*: the tool manifest declares `network: none`; the sandbox refuses any command not on the one-entry allowlist; the child env contains no credentials or proxy config. A defence-in-depth probe test runs a script in the sandbox that attempts an outbound TCP connect. | **Weakest of the three.** A plain subprocess is not network-isolated by the OS. Nothing stops a *hypothetical* allowlisted command from opening a socket — the guarantee rests on the allowlist containing exactly one command that we control. |

**Assumption, needs operator confirmation (A4):** whether admission-layer network
denial is sufficient to call the network ceiling "maskinellt bevisat" for Fas 3's
exit criterion, or whether the operator requires real OS-level isolation
(container with `--network none`, or the Pi Builder Squid topology) before Fas 3
can be signed off. This is the single most consequential open question in this
draft, because it decides whether the Docker-backed sandbox is Fas 3 scope or
Fas 3.1 scope. The recommendation is: ship the subprocess sandbox, be explicit
in the exit-criterion evidence that the network claim is admission-layer, and
open the container-backed implementation as a tracked follow-up — the same way
Fas 2 shipped without real inference configured and recorded that the actual
exit-criterion run was a separate manual step.

### 8. Cross-cutting: the code fixture has to be authored — nothing in the repo is code-shaped

**Finding:** Fas 2 got lucky. `verticals/vertical-01-ai-act/` already had 12
synthetic classification fixtures, so Fas 2 wrote no domain content. Fas 3 has no
such luck. A sweep of `verticals/` and `fixtures/` found:

- `verticals/vertical-01-ai-act/` — document/JSON classification. Not code-shaped.
- `verticals/provider-resilient-execution/` — six JSON fixtures describing
  *provider failure scenarios* (`timeout.json`, `rate-limited.json`,
  `model-404.json`, …). About inference routing, not about code.
- `verticals/_template/` — README only.
- `fixtures/l0_synthetic_rlm.json` — long-context RLM material.
- `experiments/runtime-pi-builder/` — its "first bounded write test" fixture
  (write `BUILDER_IMPLEMENTED` into `artifact.md`) is a single-file write proof,
  not a solvable code task, and is out of the repository anyway.

**Decision:** author a new minimal fixture as a vertical package,
`verticals/vertical-02-code-fixture/`, following
`docs/architecture/vertical-package-contract.md`:

```text
verticals/vertical-02-code-fixture/
|-- vertical.yaml            # workflow: fix-failing-test
|-- README.md
|-- schemas/
|   |-- patch-request.schema.json    # workspace map + failing-test output
|   `-- patch-proposal.schema.json   # the {changes:[{path,new_content}]} shape
|-- instructions/
|   `-- system-prompt-fix.md
`-- evals/synthetic/
    `-- 001-off-by-one/
        |-- fixture.yaml     # declared scope, caps, expected failing test
        `-- workspace/
            |-- ranges.py            # sum_to(n) is off by one
            `-- test_ranges.py       # one failing assertion
```

The fixture is ~15 lines of Python. It is deliberately boring: one bug, one
file, one failing assertion, one obviously-correct fix. A hard fixture would let
a Fas 3 failure be blamed on task difficulty; an easy one means a failure can
only be the *mechanism*, which is what is under test.

`vertical.yaml` declares the workflow, schemas and eval directory. It declares
**no** sandbox policy, Docker image, mount or timeout — per the vertical package
contract, those belong to the platform, and in Fas 3 they belong to
`runtime/execution/`.

**Assumption, needs operator confirmation (A5):** that the fixture belongs in
`verticals/` as a vertical package at all. The counter-argument is real: "fix a
failing test" is not a customer domain the way AI Act classification is; it is a
platform capability, and it could equally live as
`agent-platform/tests/fixtures/code/`. It is proposed as a vertical because that
is where every other fixture in this repo lives and because it gives Fas 4+ a
place to add harder cases — but this is the author's call, not the operator's.

**Assumption, needs operator confirmation (A6):** the vertical id
`vertical-02-code-fixture`. `vertical-01-ai-act` is the only numbered precedent
and there may be a reserved plan for `vertical-02`.

## Components

New, under `agent-platform/runtime/`:

| File | Responsibility |
|---|---|
| `coding/workspace_map.py` | Bounded, deterministic enumeration of the run workspace (path, size, sha256, line count) under an extension allowlist and file/byte caps. No parsing. |
| `coding/run_workspace.py` | Creates the disposable run workspace: copy fixture → `work/`, copy fixture → `baseline/` (read-only), return both roots. Guarantees cleanup on every exit path. |
| `coding/coding_profile.py` | Static profile config (mirrors Fas 2's `research_profile.py`): `profile_id: coding-v0.1`, allowed tools, workflow ref, caps (max files, max bytes, max changed lines, max executions), declared scope globs, model policy ref. |
| `coding/coding_loop.py` | Orchestrates one coding run end to end; the Fas 3 sibling of `agent_loop.py`. Logs every step to `session_state`. |
| `tools/__init__.py` | Re-exports Fas 2's `ToolGate`, `ToolAdmissionError`, `read_fixture_file` — Fas 2 import paths unchanged. |
| `tools/gate.py` | Fas 2's `ToolGate`, moved verbatim, plus `WriteGate` (symlink rejection, existing-file-only). |
| `tools/fixtures.py` | Fas 2's `read_fixture_file`, moved verbatim. |
| `tools/workspace.py` | `list_workspace`, `read_workspace_file`, `search_workspace` (literal substring, capped result count and line length). |
| `tools/patch.py` | `apply_patch` (validated, capped, all-or-nothing) and `diff_workspace` (`difflib` unified diff vs. baseline). |
| `tools/execution.py` | `run_tests` — the only `bounded_execution` tool; thin wrapper over the sandbox. |
| `execution/subprocess_sandbox.py` | `ExecutionSandbox.run(command_id, workspace) -> ExecutionResult`. Argv allowlist, pinned cwd, scrubbed env, timeout, output cap, no shell. The seam a future container-backed sandbox implements. |
| `execution/write_policy.py` | The quantitative caps and the scope-glob check, as pure functions over a diff — no I/O, so they are trivially testable. |

Modified (additively, following Fas 2's `MODEL_ASSISTED` precedent exactly):

| File | Change |
|---|---|
| `reasoning/kernel/strategy.py` | Add `CODING_ASSISTED = "coding_assisted"` to the `Strategy` enum. `select_strategy()` untouched — never auto-selected. |
| `reasoning/kernel/operators.py` | Add `propose_minimal_patch`, `inspect_diff_against_scope`, `falsify_fix`, all taking injected callables. No new imports. |
| `reasoning/kernel/engine.py` | Add `_solve_coding_assisted` and the public `Engine.solve_coding_assisted(content, propose, inspect_scope, verify) -> Result`. Existing solvers untouched. |

New, under `verticals/`: `vertical-02-code-fixture/` as laid out in decision 8.

Reused unmodified: `runtime/session_state.py`, `runtime/text_inference_port.py`
(both from Fas 2), `adapters/inference/budget_gate.py`,
`agent-platform/inference/provider_policy.py`, `reasoning/kernel/` DM1–DM4
solvers.

## Data flow

1. **Claim.** `coding_loop.run(task_id, fixture_dir)` → `session_state.create(...)`.
   Event `session.created`.
2. **Workspace materialization.** `run_workspace` copies the fixture into
   `work/` and `baseline/` under a temp root. Event `workspace.created` with the
   root path and file count. Nothing outside this temp root is writable for the
   remainder of the run.
3. **Baseline verification.** The sandbox runs the test suite against
   `baseline/`. It **must fail** — if the fixture's test already passes there is
   no bug to fix and the run terminates `blocked` immediately rather than
   producing a meaningless success. Events `execution.requested` /
   `execution.completed` with exit code and truncation flag.
4. **Discovery.** `workspace_map` enumerates `work/`. Event `discovery.completed`
   with the file inventory (paths and hashes, not contents).
5. **Context assembly.** Prompt = system prompt from the vertical + workspace map
   + the baseline test output + the declared scope and caps. The failing-test
   output is treated strictly as data, per §20.2 — anything instruction-shaped
   inside it grants no permission and admits no tool.
6. **Kernel, strategy `CODING_ASSISTED`:**
   a. `propose_minimal_patch` → `text_inference_port.invoke(prompt, patch_schema)`.
      Events `inference.requested` / `inference.completed`. Budget and provider
      policy are checked by the port *before* any HTTP call, unchanged from Fas 2.
   b. Response validated against `patch-proposal.schema.json`.
   c. `apply_patch` — `WriteGate` admits each path; caps checked; all-or-nothing
      write into `work/`. Events `patch.admitted` / `patch.applied`.
   d. `diff_workspace` computes the unified diff `baseline/` → `work/`.
   e. `inspect_diff_against_scope` checks that diff against the declared scope
      globs and the changed-line cap.
   f. `falsify_fix` — sandbox run on `work/` (must exit 0) and the recorded
      baseline result (must be non-zero).
7. **Result envelope.** `{session_id, status, result: {diff, files_changed,
   tests_passed}, cost, reason}` — same envelope discipline as Fas 2 and
   `docs/architecture/dispatch-contract.md`.
8. **Cleanup.** Temp root removed on every path, success or failure, including
   exceptions. The diff and the enumeration survive in the session log; the
   workspace does not.

## Error handling

The governing rule, inherited from Fas 2 and from `dispatcher.py`'s
`resync_pending()` principle: **a boundary violation produces an explicit,
reviewable terminal state, never a guess dressed up as success.** There is no
`failed`-that-might-have-worked; there is `blocked` with a machine-readable
reason.

Every row below names the boundary, the behaviour, and the test that *proves*
the boundary is enforced rather than trusted. "Proves" here has a specific
meaning: the test performs a real attempt and asserts both that the attempt was
refused **and** that the protected resource is byte-for-byte unchanged
afterwards. Asserting only that an exception was raised would prove the code
raised, not that nothing happened.

| Boundary | Behaviour | Proving test |
|---|---|---|
| Patch path traverses out of workspace (`../../x`) | `ToolAdmissionError` before any file handle opens; run → `blocked` | Real file created in a sibling temp dir; assert raise **and** assert the file's sha256 is unchanged |
| Patch path is an absolute path outside workspace | Same | Same shape |
| Patch path is a symlink pointing outside workspace | `WriteGate` rejects on `is_symlink()` **and** on post-resolution containment | Symlink created in the workspace pointing at an outside file; assert raise and outside file unchanged. Skipped where symlink creation needs privileges (Windows without developer mode) — recorded as skipped, never silently passed |
| Patch touches more files than the cap | Whole patch refused, nothing written | Two-file patch against `max_files=1`; assert both files unchanged |
| Patch exceeds max changed lines | Whole patch refused | Oversized content; assert file unchanged |
| Diff touches a path outside the declared scope | `inspect_diff_against_scope` → confidence 0.0 → run `blocked` with reason `scope_expansion` | Patch an in-workspace file that is outside the scope globs; assert `blocked` and that reason |
| Sandbox command not on the allowlist | `ExecutionError` before `subprocess.run` is reached | Monkeypatch `subprocess.run` to append to a list; request a non-allowlisted command; assert raise and the list is empty |
| Sandbox command supplied as a string | Rejected by type check; `shell=False` unconditional | Assert raise; assert no shell metacharacter path exists |
| Credentials leak into the child process | Child env is allowlist-built, never inherited | Set `CORTXT_INFERENCE_API_KEY=canary` in the test process; run a probe that dumps its env into a file in the workspace; assert `canary` absent |
| Sandbox exceeds timeout | Process killed; result `timed_out`; run → `blocked` | Probe script that sleeps past the timeout; assert `timed_out` and bounded elapsed time |
| Sandbox output exceeds cap | Truncated with an explicit `truncated: true` flag | Probe that prints past the cap; assert truncation flag and capped length |
| Max sandbox executions per run exceeded | Refused; run → `blocked` | Loop past the cap; assert refusal |
| Budget exhausted | `BudgetExhausted` before any HTTP call; run → `blocked`, no partial result stored as valid | `max_calls=0` gate; assert backend never reached (Fas 2's test shape) |
| Provider policy denies | `TextInferenceError` at port construction; no call made | Reuse Fas 2's `test_invoke_denied_by_provider_policy` shape |
| Model response fails patch schema | `blocked`, reason `schema`; nothing written to the workspace | Malformed response via `FakePort`; assert workspace unchanged |
| Tests pass but baseline also passed | `blocked` at step 3 — no bug to fix | Fixture variant with a passing test |
| Tests pass because the test was neutered | `falsify_fix` fails the second-sided check → `blocked` | `FakePort` returns a patch that empties `test_ranges.py`; assert `blocked` |
| Crash/interrupt mid-run | Session log is the recovery record: an `execution.requested` or `inference.requested` without its matching `.completed` means the action is treated as **not having happened** and is redone — never assumed successful. Workspace temp root is orphaned but outside the repo, and is not reused | Assert log shape after a simulated interrupt (Fas 2's resume mechanics, unchanged) |

Two failure modes deserve naming because they are the ones that would make the
exit criterion a lie if unhandled:

- **A partially applied patch.** `apply_patch` validates every change and every
  cap first, then writes; a mid-write I/O error still leaves an inconsistent
  workspace, so the run is marked `blocked` with reason `workspace_inconsistent`
  and the workspace is discarded rather than diffed. A diff of a half-applied
  patch is worse than no diff.
- **A "successful" run whose sandbox never actually executed.** If the sandbox
  result is missing, unparsable, or reports an exit code the runner did not
  observe, `falsify_fix` returns confidence 0.0. Absence of evidence is not
  evidence of passing.

## Testing strategy

Mirrors Fas 2's conventions and adds what a containment phase needs.

- **Unit tests (0 cost, always in default CI).** `workspace_map` (caps,
  determinism, hash stability); `WriteGate` (the full escape matrix above);
  `write_policy` pure functions (caps, scope globs); `apply_patch`
  (all-or-nothing, validation order); `diff_workspace` (diff correctness against
  a known baseline); `subprocess_sandbox` (allowlist, env scrubbing, timeout,
  output cap, cwd pinning); the three new kernel operators (delegation only, no
  hidden arithmetic — same assertions Fas 2 used for `inspect_with_model` /
  `verify_against_schema`); and a regression guard that Fas 2's DM1 solvers and
  `MODEL_ASSISTED` are unaffected.
- **Boundary-attempt tests.** The distinguishing suite for this phase. Each
  performs a real escape attempt against real files in `tmp_path` and asserts
  the protected bytes are unchanged. Safe by construction: the "outside" target
  is always inside `tmp_path`, never the repository, so a bug in the code under
  test damages only a temp dir the test owns. These are the literal evidence for
  "workspace-, nätverks- och budgettak är maskinellt bevisade" and should be
  listed by name in the exit-criterion report.
- **Integration test (0 cost, in default CI).** Full `coding_loop` against the
  new fixture with a `FakePort` returning a known-good patch — proves the whole
  mechanism (claim → workspace → baseline-fail → discover → propose → apply →
  diff → scope → falsify → envelope → cleanup) with zero model calls. Plus
  negative variants: scope-expanding patch, test-neutering patch, schema-invalid
  response, budget-exhausted port.
- **`real_inference`-marked test (excluded from default CI).** The actual exit
  criterion: the same fixture solved by a real model call, run manually once
  `cortxt_resilient_inference` is installed and
  `CORTXT_INFERENCE_URL`/`CORTXT_INFERENCE_API_KEY` are configured. Same
  convention and same caveat as Fas 2: **Fas 3 is not "done" until this has been
  run successfully at least once**, and the run's evidence (diff, test output,
  cost, and the boundary-test list) is what closes the phase.
- **`test_no_external_deps.py` must still pass** after the kernel extension —
  the ADR-016 invariant. `reasoning/` gains three operators and zero imports.
- **Marker registration.** If the symlink and sandbox-probe tests need
  conditional skipping, use explicit `pytest.mark.skipif` with a recorded reason
  rather than a silent pass, so a skipped boundary test is visible in CI output.
  A boundary test that skips without anyone noticing is the same as no boundary
  test.

**Assumption, needs operator confirmation (A7):** the sandbox launches
`sys.executable` (the operator's/CI's own interpreter) with a scrubbed env,
rather than a pinned, pre-provisioned virtualenv. Using `sys.executable` keeps
v0.1 dependency-free and makes CI trivial, but it means the fixture's test run
shares the platform's installed packages. A pinned venv per run is more
faithful to §15's isolation intent and is the natural next hardening step.

## Out of scope for this slice

- **Docker/container-backed execution sandbox** — named as the promotion path
  (decision 3), not built. Pending A4.
- **Real OS-level network isolation** — v0.1's network ceiling is admission-layer
  (decision 7). Pending A4.
- **Resource ceilings other than wall-clock and output size** — no memory or CPU
  limits; not portably enforceable for a plain subprocess.
- **The other seven §13.2 coding operators** — deferred with rationale
  (decision 5); needs a tracking issue, like Fas 2's #138.
- **Symbol index, dependency map, repository-instruction ingestion** (decision 1).
- **Unified-diff hunk application, file creation, file deletion, multi-file
  patches beyond the cap, git operations** (decisions 2 and 6).
- **A declarative YAML tool manifest + Tool Gateway registry per §32.1** — the
  fields are declared, the registry is not built (decision 2).
- **Supervisor, child runs, multi-session coordination** — Fas 4.
- **Any wiring into the live dispatch path** — Fas 3 runs from tests only. Nothing
  in `docs/agents/current-operating-model.md` changes as a result of this phase;
  Pi Builder remains the bounded-write experiment it is today until a separate
  operator decision says otherwise.
- **Promoting `agent-platform/runtime/` to Accepted architecture status** — per
  ADR-016/017, that is a separate decision made *after* the slice proves the
  need.

## Open assumptions — the operator-review checklist

Every judgment call this draft made without the operator, in one place.

| # | Assumption | Why it matters |
|---|---|---|
| A0 | **`docs/architecture/cortxt-agent-platform-target-architecture.md` is not on `main`.** It exists only in commit `8dd1048` on branch `agent/reasoning-kernel-dm1`, and `archive/` (which held `experiments/runtime-pi-builder/`) has been moved out of the repository. This spec's §-references are therefore unresolvable for a reader of `main`. | Blocks review, and blocks anyone later checking whether this spec matched the architecture. Needs the target-architecture doc merged (or its location corrected) before Fas 3 implementation starts. |
| A1 | Fas 3 may convert Fas 2's `runtime/tools.py` into a `runtime/tools/` package (behaviour-preserving move + re-export), touching just-merged Fas 2 code. | Alternative is a frozen Fas 2 file and a sibling module, i.e. two admission gates. |
| A2 | Patch representation is whole-file content + platform-computed diff, not model-emitted unified diff. | Trades scalability for verifiability; decides how much of §13.1's "minimala patchar" Fas 3 actually delivers. |
| A3 | Call-count budget (`BudgetGate.max_calls`) satisfies "budgettak maskinellt bevisat". There is no USD ceiling in the platform today, and Pi Builder's own README records observed model cost as `unknown`. | If the operator reads "budgettak" as money, Fas 3 needs cost telemetry first and this spec understates its dependencies. |
| A4 | **Admission-layer network denial is sufficient for "nätverkstak maskinellt bevisat" in v0.1**; real OS-level isolation is a tracked follow-up. | The most consequential open question. Decides whether the container-backed sandbox is Fas 3 scope or Fas 3.1 scope. |
| A5 | The new code fixture belongs in `verticals/` as a vertical package rather than as a plain test fixture under `agent-platform/tests/`. | "Fix a failing test" is a platform capability, not a customer domain; the vertical-package contract may not be the right home. |
| A6 | The vertical id `vertical-02-code-fixture` is free and appropriately named. | `vertical-02` may be reserved for a planned customer domain. |
| A7 | The sandbox may launch `sys.executable` with a scrubbed env rather than a pinned per-run virtualenv. | Fidelity vs. simplicity; affects how strong the isolation claim is. |
| A8 | Deferred items (the seven remaining §13.2 operators, container sandbox, symbol/dependency map, unified-diff application) should get GitHub issues, but **this draft created none** — the controller session owns issue creation. | Fas 2's deferral was captured as issue #138; Fas 3's deferrals currently have no tracking. |
| A9 | The run workspace lives in a system temp dir and is destroyed on every exit path, so a failed run leaves no inspectable artifact beyond the session log's diff and hashes. | If the operator wants post-mortem inspection of failed runs, workspaces need a retained `.runs/` location and a retention policy instead. |
| A10 | No process-level memory/CPU ceiling in v0.1 (wall-clock and output size only). | If "process limits" from §15 is read as mandatory for Fas 3, this is a gap. |
