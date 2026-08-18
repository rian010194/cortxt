# Capability-manifest extension points for Fas 3 — research inventory

**Task:** t_a8edd6ca  
**Source issue:** rian010194/cortxt#159 (research/inventory only, no code changes)  
**Date:** 2026-08-18  
**Status:** Draft findings  

---

## 1. Context: what "capability manifest" means here

In this codebase, "capability manifest" is not a single file or schema. It is a family of declaration shapes that let a vertical package, an agent profile, a tool, or a skill describe **what it needs, what it provides, and what effects it is allowed to have** — without hard-coding provider selection, dispatch, sandbox policy, or approval state. The harness reads these declarations and maps them to platform policy.

This inventory maps the existing manifest/extension shapes, what Fas 3 (Coding Agent v0.1) adds to them, what Fas 3 deliberately defers, and where the extension points cross phases.

---

## 2. Manifest shapes in the codebase today

### 2.1 Vertical package manifest — `vertical.yaml`

**Shape.** `verticals/<id>/vertical.yaml` declares:

| Field | Purpose |
|---|---|
| `vertical_id` | Stable vertical identifier |
| `package_version` | Semantic package version |
| `contract_version` | Manifest contract version (currently `0.1.0`, not yet a stable schema) |
| `supported_workflows` | Workflow ids + input/output schema URIs + capability tags |
| `capability_tags` | Package-level capability tags (e.g. `structured-output`, `code-reading`) |
| `required_schemas` | Schemas the package needs present |
| `instructions_index` | Named instructions (system prompts) by key |
| `eval_suite` | Fixture directory + minimum fixture count |
| `artifact_policy` | Allowed MIME types, max size, retention class |
| `non_goals` | Explicit non-goals (sandbox, credentials, dispatch — owned by harness) |

**Example in repo:** `verticals/vertical-02-code-fixture/vertical.yaml` (Fas 3's code fixture package) and `verticals/vertical-01-ai-act/vertical.yaml` (Fas 2's research vertical, not in this worktree but described in its README).

**Contract stabilization rule (vertical-package-contract.md):** The first manifests may be documented examples. JSON Schema files belong in `contracts/` only after at least one real workflow has shown which fields are necessary. Encoding the first vertical's guesses into a platform contract is the mistake the contract explicitly warns against.

**Extension point.** A future platform schema for `vertical.yaml` is the natural extension point, but it is **not** built in Fas 3. The current Fas 3 manifest is deliberately a documented example shaped so a later schema is a serialization change, not a redesign.

---

### 2.2 Tool contract — §32.1 of target architecture

**Shape.** Each tool declares (currently as a Python dict constant per tool, not YAML files):

```yaml
id: repository.run_tests
version: 1.0.0
input_schema: contract-ref
output_schema: contract-ref
effect_class: bounded_execution
filesystem: current-run-workspace
network: none
credentials: []
timeout_seconds: 600
idempotency: repeatable
artifact_policy: result-and-summary
```

**Fas 3 decision (spec decision 2):** v0.1 declares those same fields, but as a Python dict constant per tool consumed by the gate — **not** as YAML files with a registry and schema validator. Rationale: one profile with six tools does not yet show which manifest fields are load-bearing; encoding the first vertical's guesses into a platform contract is the ADR-016 mistake. The dict-constant form is deliberately shaped so the later YAML manifest is a serialization change, not a redesign.

**Extension point.** The Tool Gateway (§32.1) is the future single admission point that validates schema, profile permission, dataklass, declared effects, budget, and runtime eligibility before every tool call. In Fas 3 this is still a Python dict + `ToolGate` class, not a YAML registry. The extension point is the **gap between the declared shape and the implemented gate**.

---

### 2.3 Skill manifest — `schemas/skill-manifest.schema.json`

**Shape (§31):** A skill is a first-class object containing:

- manifest, identity, semantic version
- instructions and examples
- input/output schemas
- dependencies and compatible agent profiles
- fixtures, tests, evals
- declared tools and highest allowed effect class
- provenance, changelog, rollback info
- optional granskat executable helpers

**Extension point.** Skills are the mechanism for reusable work patterns that compose reasoning operators and tools. Skill evolution (§31.1) is the future pipeline: trajectory observation → pattern detection → skill candidate → sandboxed evaluation → regression and safety comparison → promotion decision → canary/active or rejected. This is **Fas 8 scope**, not Fas 3.

**Fas 3 relationship:** Fas 3 does not create or extend skills. The coding profile is a static Python config, not a skill. The extension point exists in the platform but is not exercised by Fas 3.

---

### 2.4 Profile manifest — `schemas/profile-manifest.schema.json`

**Shape (§8.1):** An agent profile is versioned config:

```yaml
agent_profile:
  id: coding-v1
  reasoning_strategies: [direct, recursive, geometric]
  operator_set: coding-core-v1
  tools: [repository_search, file_read, patch, shell, tests, diff]
  permissions: bounded-workspace-write
  memory_policy: session-plus-run-state
  model_policy: coding-balanced-v1
  verification_policy: tests-plus-independent-review-v1
```

**Fas 3 implementation:** `coding_profile.py` (new in Fas 3) is a static Python config mirroring Fas 2's `research_profile.py`: `profile_id: coding-v0.1`, allowed tools, workflow ref, caps (max files, max bytes, max changed lines, max executions), declared scope globs, model policy ref.

**Extension point.** The profile manifest schema is the future machine-readable form of what is now a Python constant. The extension point is: which profile fields need to be in the manifest vs. stay in code? Not answered in Fas 3.

---

### 2.5 Capability tags

**Shape:** Free-form tags on verticals and workflows (e.g. `structured-output`, `code-reading`). The harness maps declared capabilities to platform policy.

**Extension point.** Capability tags are the lightweight extension mechanism: a vertical declares what it needs, the harness decides eligibility. The tag set is not normalized or schema'd in Fas 3 — it is a typed-from-above convention, not a platform contract.

---

### 2.6 Effect classes — §32.2

**Shape:** A closed taxonomy of what a tool can do:

| Class | Example | Control |
|---|---|---|
| `observe` | Read file or search code | Read scope and dataklass |
| `local_mutation` | Apply patch in run workspace | Writable scope and diff control |
| `bounded_execution` | Run test or build in sandbox | Allowlist, resources, timeout |
| `external_mutation` | Create issue or send message | Explicit mandate and read-back |
| `irreversible` | Merge, deploy, delete | Operator gate |
| `credential` | Create or rotate secret | Separate trust-boundary decision |

**Fas 3 tools mapped to effect classes:**

| Fas 3 tool | Effect class |
|---|---|
| `list_workspace`, `read_workspace_file`, `search_workspace` | `observe` |
| `apply_patch` | `local_mutation` |
| `diff_workspace` | `observe` |
| `run_tests` | `bounded_execution` |

**Extension point.** Effect classes are the extension point for **permission granularity**: a profile declares which effect classes it may use, the gate checks each tool call against the profile's allowed effects. New effect classes are a platform decision, not a vertical decision.

---

## 3. Fas 3-specific extension points

### 3.1 Reasoning strategy extension — additive enum values

**What exists:** `Strategy` enum in `agent-platform/reasoning/kernel/strategy.py` with `direct`, `recursive`, `geometric`, and (from Fas 2) `MODEL_ASSISTED`. `select_strategy()` is untouched — never auto-selects new values.

**Fas 3 extension:** Add `CODING_ASSISTED = "coding_assisted"` — purely additive, reached only via a new explicit `Engine.solve_coding_assisted(...)` entry point, taking injected callables so `reasoning/` gains no new imports (ADR-016 invariant, guarded by `test_no_external_deps.py`).

**Extension point.** The strategy enum is the extension point for **reasoning approaches**. New strategies are added as enum values + explicit entry points, never auto-selected. The capsule is: does the new strategy take injected callables (no new imports) or does it break the ADR-016 invariant?

---

### 3.2 Operator extension — additive operators

**What exists:** Ten operators in `operators.py` from the reasoning kernel (inspect, decompose, integrate, verify, etc.).

**Fas 3 extension:** Three new operators, all taking injected callables:

| Operator | Kind | What it does in v0.1 |
|---|---|---|
| `propose_minimal_patch` | model-assisted | Delegates to injected `propose` callable (TextInferencePort + prompt); stores proposed patch on state. Only model call in the run. |
| `inspect_diff_against_scope` | deterministic | Delegates to injected `inspect_scope` callable over platform-computed diff; sets confidence 0.0 + scope-expansion reason if diff touches outside declared scope. |
| `falsify_fix` | deterministic | Delegates to injected `verify` callable that runs sandboxed test suite. Confidence 1.0 only if suite passes **with** patch **and** fails **without** it. |

**Extension point.** Operators are the extension point for **domain-specific reasoning steps**. The rule: each new operator takes injected callables, adds zero imports to `reasoning/`, and is reached only via an explicit engine entry point. The other seven §13.2 coding operators are deferred — they need a multi-file fixture that can falsify them.

---

### 3.3 Tool extension — new modules in `runtime/tools/`

**Fas 3 tools (new):**

| Module | Tool | Effect class |
|---|---|---|
| `tools/workspace.py` | `list_workspace`, `read_workspace_file`, `search_workspace` | `observe` |
| `tools/patch.py` | `apply_patch`, `diff_workspace` | `local_mutation` / `observe` |
| `tools/execution.py` | `run_tests` | `bounded_execution` |

**Fas 3 structural extension:** Convert `runtime/tools.py` into a package `runtime/tools/` where `__init__.py` re-exports `ToolGate`, `ToolAdmissionError`, `read_fixture_file` from `gate.py` and `fixtures.py`. Fas 2 import paths must continue to work unchanged. New tools land as new modules in that package.

**Extension point.** The `runtime/tools/` package is the extension point for **new tools**. Each tool is a new module with a dict constant declaring its contract fields. The gate (`ToolGate`/`WriteGate`) is the single admission point. The deferred extension is: unified-diff parsing, file creation/deletion, multi-file patches beyond the cap, static-analysis/lint tools, build tools, git operations of any kind.

---

### 3.4 Execution sandbox extension — `subprocess_sandbox.py`

**Fas 3 extension:** New `runtime/execution/subprocess_sandbox.py` with `ExecutionSandbox.run(command_id, workspace) -> ExecutionResult`. Bounds enforced before container launch + container boundary itself:

- Command allowlist (argv lists, never strings; `shell=False` unconditional)
- cwd pinned to resolved run-workspace root
- Environment scrubbed to allowlist (never `os.environ.copy()`)
- Wall-clock timeout with kill-on-expiry
- Output caps with explicit truncation flag
- Deterministic cleanup (temp-dir copy, removed on every exit path)
- Real network isolation: `docker run --network none` against pinned digest base image

**Extension point.** The sandbox is the extension point for **bounded execution**. The v0.1 allowlist has exactly one entry: `[<interpreter>, "-m", "pytest", "-q", "<workspace>"]`. Extending the allowlist is the future mechanism for adding more command types, but each addition is a trust-boundary decision.

---

### 3.5 Vertical package extension — `vertical-02-code-fixture`

**Fas 3 extension:** New vertical package `verticals/vertical-02-code-fixture/` following the vertical-package contract:

```
verticals/vertical-02-code-fixture/
|-- vertical.yaml
|-- README.md
|-- schemas/
|   |-- patch-request.schema.json
|   `-- patch-proposal.schema.json
|-- instructions/
|   `-- system-prompt-fix.md
`-- evals/synthetic/
    `-- 001-off-by-one/
        |-- fixture.yaml
        `-- workspace/
            |-- ranges.py
            `-- test_ranges.py
```

**Extension point.** The vertical package is the extension point for **new domain workflows**. The fixture is ~15 lines of Python, deliberately boring (one bug, one file, one failing assertion, one obviously-correct fix). A hard fixture would let a Fas 3 failure be blamed on task difficulty; an easy one means a failure can only be the mechanism.

---

### 3.6 Patch representation — structured content, not unified diff

**Fas 3 decision (spec decision 6):** The model returns a JSON object `{"changes": [{"path": "<relative>", "new_content": "<full file text>"}], "rationale": "..."}` validated against a JSON Schema by the kernel's verify path. `apply_patch` writes the content; the diff is derived afterwards by the platform.

**Extension point.** This is a deliberate trade-off: verifiability over scalability. Whole-content replacement inside a capped, existing-files-only, copy-in workspace is trivially verifiable. The extension point for the future is: unified-diff hunk application becomes a Fas 3.1 deliverable with its own boundary tests.

---

## 4. What Fas 3 deliberately does NOT extend (deferred)

| Deferred item | Why deferred | Extension point when it arrives |
|---|---|---|
| YAML tool manifest + Tool Gateway registry | One profile with six tools doesn't show which fields are load-bearing; dict-constant form is shaped for later serialization change | §32.1 Tool Gateway |
| Unified-diff hunk application | Not needed for a one-file fixture; hunk appliers are where fuzzy matching creeps in | Fas 3.1, own boundary tests |
| File creation and deletion | Each needs its own boundary rules (where may a new file be created? does deletion of baseline break diff?) | Future write-policy extension |
| Symbol index, dependency map, repository-instruction ingestion | Need a multi-file fixture to be honest | Fas 3.1+ |
| The other seven §13.2 coding operators | Need a fixture that can falsify them | Needs tracking issue |
| Supervisor, child runs, multi-session coordination | Fas 4 | §7 of target architecture |
| Any wiring into live dispatch path | Fas 3 runs from tests only | Later phase |
| Promoting `agent-platform/runtime/` to Accepted architecture status | Separate decision after slice proves need (ADR-016/017 pattern) | Future ADR |
| Memory/CPU ceilings for sandbox | Not portably enforceable in a way this spec verifies; fixture doesn't need them | Future sandbox hardening |
| Pinned per-run virtualenv (sandbox launches `sys.executable`) | Fidelity vs. simplicity; A7 open | Future hardening |
| Retained `.runs/` location for post-mortem inspection | A9 open | Future retention policy |

---

## 5. Cross-phase integration points (from Fas 8 close-out doc)

The Fas 8 integration-points doc (`docs/superpowers/2026-08-18-fas8-integration-points.md`) identifies two integration points that touch manifest/extension machinery:

### 5.1 Supervisor (Fas 4) → active policy

- **Now:** `learning.resolve_active_policy(registry, "policy", "geo")` returns the active `CandidatePathScore` (or None → default), but Supervisor (Fas 4) does not read it at session-start.
- **Integration step (v1.x):** Supervisor fetches active policy via `resolve_active_policy()` at session-start, so the versioned policy is visible for dispatch (not just internally in `score_path`).
- **Why v1.x:** The mechanism exists (proven in Fas 8); connecting the Supervisor read is a Fas 4-layer integration change, not a Fas 8 core change.

**Manifest relevance:** This is the extension point where an active/approved policy version becomes dispatch-visible. The policy is a versioned artifact; the Supervisor reads it at session-start. This connects the learning-loop manifest machinery (Fas 8) to the dispatch contract (Fas 4+).

### 5.2 ToolGate (Fas 3) → tool candidate

- **Now:** `ToolCandidateAdapter` registers tool candidates and gates them per effect class (external-mutation/credential → always AWAIT_OPERATOR). Fas 3's `ToolGate` (path-sandboxing) does not use a promoted tool version.
- **Integration step (v1.x):** Document where a future promoted tool version replaces `ToolGate` logic. Tool promotion is always operator-gated (§32.2), so no tool version can activate without a human.
- **Why v1.x:** Full §32.3 security checklist (credential/network isolation, dependency scanning) is a separate v1.x security delivery (P1.6).

**Manifest relevance:** This is the extension point where tool evolution (Fas 8 §32.3) connects to the Fas 3 ToolGate. A promoted tool version replaces the current gate logic; the gate becomes a consumer of promoted tool manifests rather than inline dict constants.

---

## 6. How the manifest shapes connect

```
vertical.yaml (vertical package)
  ├── supported_workflows[].capability_tags  ──→ harness maps to platform policy
  ├── instructions_index                      ──→ system prompts for model
  ├── eval_suite                             ──→ fixtures for verification
  └── artifact_policy                        ──→ allowed output shapes

agent_profile (Python constant today, schema tomorrow)
  ├── reasoning_strategies        ──→ Strategy enum values (extension point)
  ├── operator_set                ──→ operators (extension point)
  ├── tools                       ──→ tool IDs (extension point)
  ├── permissions                 ──→ effect-class eligibility
  ├── memory_policy               ──→ context/compaction policy
  ├── model_policy                ──→ InferencePort routing
  └── verification_policy        ──→ verify operator selection

tool dict constant (today) → YAML tool manifest (future, §32.1)
  ├── id / version                ──→ tool identity
  ├── input_schema / output_schema ──→ contract refs
  ├── effect_class                ──→ §32.2 taxonomy (extension point)
  ├── filesystem / network / credentials ──→ boundary declarations
  ├── timeout_seconds             ──→ sandbox bounds
  ├── idempotency                ──→ repeatability contract
  └── artifact_policy            ──→ output capture policy

skill manifest (§31, future use)
  ├── manifest / identity / version ──→ skill identity
  ├── instructions / examples      ──→ reusable prompts
  ├── input/output schemas         ──→ contracts
  ├── dependencies / compatible profiles ──→ composition
  ├── declared tools / max effect class ──→ tool + permission bounds
  ├── fixtures / tests / evals     ──→ verification
  └── executable helpers (optional) ──→ sandboxed helpers
```

---

## 7. Open questions for the extension-point design

These are research findings, not answers — they flag where the manifest/extension design is still open:

1. **When does the dict-constant tool form become a YAML manifest?** The spec says "the later YAML manifest is a serialization change, not a redesign," but doesn't say what triggers the change. Is it "when we have ≥N profiles"? "When we add a second vertical"? "When Tool Gateway registry is built"?

2. **Which profile fields belong in the manifest schema vs. stay in code?** `coding_profile.py` today has caps (max files, max bytes, max changed lines, max executions), declared scope globs, model policy ref. The profile-manifest schema exists but is not populated. Which of these become manifest fields?

3. **Are capability tags normalized?** They are free-form today (`structured-output`, `code-reading`). Is there a registry of approved tags, or are they open? If open, how does the harness reject unknown tags — fail closed or pass through?

4. **What is the promotion path for a tool from dict constant to promoted tool version?** Fas 8 §32.3 describes tool evolution (candidate → isolated run → security checklist → regression → promotion), but the connection from Fas 3's `ToolGate` to a promoted tool version is documented as a v1.x integration step, not built.

5. **How do effect classes extend?** The taxonomy is closed today (6 classes). If a new effect class is needed (e.g. a future `read_only_network` for fetch-only tools), is that a platform decision requiring a new ADR, or can a vertical propose one?

6. **How does the reasoning strategy extension connect to the profile manifest?** `CODING_ASSISTED` is added to the Strategy enum today, but the profile's `reasoning_strategies: [direct, recursive, geometric]` list doesn't yet include it. When does the profile manifest gain a `reasoning_strategies` field that lists allowed strategies, and how does that connect to `select_strategy()` never auto-selecting?

7. **What is the minimal machine-readable schema version for `vertical.yaml`?** The contract says `contract_version: 0.1.0` but also says the schema is not yet stable. When does it become stable enough to validate against?

---

## 8. Summary

Fas 3's capability-manifest extension points are **additive and deliberately narrow**:

- **Reasoning:** one new strategy enum value (`CODING_ASSISTED`) + three new operators, all taking injected callables, all reaching the kernel only via explicit entry points.
- **Tools:** three new tool modules in a converted `runtime/tools/` package, each with a dict constant declaring §32.1 fields; `ToolGate` remains the single admission point.
- **Execution:** one new sandbox module with a single-command allowlist + real OS-level network isolation.
- **Vertical:** one new vertical package (`vertical-02-code-fixture`) following the vertical-package contract.
- **Patch representation:** structured JSON content + platform-computed diff (verifiability over scalability).

What Fas 3 does **not** extend is equally important: no YAML tool registry, no unified-diff application, no file creation/deletion, no symbol index, no Supervisor wiring, no live dispatch integration, no promotion of `runtime/` to Accepted architecture status. Each deferred item has a named extension point in a later phase (Fas 3.1, Fas 4, Fas 8, v1.x).

The cross-phase integration points from the Fas 8 close-out doc show where the manifest machinery will eventually connect: Supervisor reading active policy at session-start (Fas 4 → Fas 8), and ToolGate consuming promoted tool versions (Fas 3 → Fas 8 §32.3). Both are documented as v1.x integration steps, not built in the current phases.

The open questions (§7) flag where the manifest/extension design still needs decisions before a platform schema can be stabilized: trigger for YAML manifest, profile field ownership, capability tag normalization, tool promotion path, effect-class extensibility, strategy-profile connection, and vertical.yaml schema stabilization.
