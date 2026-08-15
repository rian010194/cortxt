# Fas 2 — Agent Runtime v0.1 — design

Status: proposed, awaiting operator review
Date: 2026-08-15
Authority: architectural proposal for one bounded vertical slice; does not override `docs/agents/current-operating-model.md`
Related: `docs/architecture/cortxt-agent-platform-target-architecture.md` §23 (Fas 2 — Agent Runtime v0.1), issue #101 (Foundation), issue #138 (deferred strategy-portability idea)

## Purpose

Prove Fas 2's exit criterion from the target architecture staircase: **a research fixture can be solved without Hermes.** This is a bounded vertical slice, in the same spirit as the reasoning-kernel (DM1–DM4, ADR-017) and T1 (#107/#110/#111) slices already proven in this repo — build the smallest real thing that proves the need, not the full target architecture.

The concrete task chosen to prove the criterion: one synthetic fixture from the existing `verticals/vertical-01-ai-act` `classify` workflow, solved end-to-end by a new Agent Runtime, with real inference (once credentials are configured separately).

## Scope decisions made during grilling

These were explicit forks resolved with the operator (Rikard) before writing this spec — recorded here so the "why" isn't lost:

1. **Session state is new code, not a reuse of `agent-platform/state/ledger.py`.** Per the target architecture's own component model (§8.2), "session persistence and resume" is Agent Runtime's own responsibility, not a separate bounded-context module. The T1 ledger was a standalone vertical-slice proof (validating that resumability itself was achievable), not the permanent owner of this responsibility — it isn't named anywhere in the target architecture's concept model (§4). The new module ports the T1 ledger's *proven primitives* (atomic write, hash-chain tamper-evidence, optimistic concurrency via expected-sequence) rather than reinventing them, but as Agent Runtime's own code.
2. **Real inference from the start**, not synthetic-only. This surfaced a real gap: the existing `InferencePort` (`adapters/inference/resilient_inference_port.py`) has signature `invoke(content) -> int`, built specifically for the reasoning kernel's abstract DM1–DM4 proof — it cannot carry real text/structured JSON output. A new port is needed. Decision: build a new port on top of the *same underlying machinery* (`cortxt_resilient_inference`, `BudgetGate`, `provider_policy` — all fail-closed, already proven), not a from-scratch reimplementation and not an overloaded shared abstraction with the reasoning kernel's int-only port.
3. **Real inference is not currently configured in this environment** — `cortxt_resilient_inference` isn't installed, `CORTXT_INFERENCE_URL`/`CORTXT_INFERENCE_API_KEY` aren't set. Decision: build the real path fully, but the actual exit-criterion run (real fixture, real cost) happens as a separate manual step once credentials exist. This spec and its implementation plan are not blocked on that.
4. **Research task reuses `vertical-01-ai-act`'s `classify` workflow** (existing schemas, instructions, 12 synthetic fixtures) rather than authoring a new fixture. No new domain content needs to be written.
5. **Tool admission is exercised for real**, not stubbed. Even though the classify workflow's input is a self-contained JSON object (no external file needs reading for the schema itself), a minimal real tool (`read_fixture_file`) is added so the admission gate is genuinely proven, not an empty pass-through. This also matches the "read-only research profile" framing from the target architecture.
6. **The reasoning kernel is wired in from the start, via a new additive `MODEL_ASSISTED` strategy** — not the existing `direct` strategy. **Correction (discovered while writing the implementation plan):** the kernel's existing `inspect`/`verify` operators (`reasoning/kernel/operators.py`) are hardcoded to numeric summation (`_flatten`/`sum`) with no model-injection point — `Engine.solve()` never calls any inference port in the current code. AI Act classification is not an exploration problem (no decompose/recursive/geometric branching to choose between), so forcing the existing `direct` strategy onto it would either be false (claiming integration that doesn't exist) or require breaking DM1's numeric solvers. Resolution: add `Strategy.MODEL_ASSISTED` plus two new, purely additive operators (`inspect_with_model`, `verify_against_schema`) and a new `Engine.solve_model_assisted()` entry point, never auto-selected by `select_strategy()` and never touching `_solve_direct`/`_solve_recursive`/`_solve_geometric` or their existing tests. This is a genuine integration point, not a bypass of the kernel and not a forced complexity it doesn't need — see `docs/superpowers/plans/2026-08-15-fas2-agent-runtime-v01.md` Task 2 for the exact diff.
7. **A related idea surfaced and was deliberately deferred**: reasoning strategies evolving/versioning like skills do (tied to vertical profiles), mirroring the `agent-platform/portability/skills/` pattern (PR #135). This maps to Fas 8 ("Kontrollerad learning loop") in the target architecture, not Fas 2. Captured as issue #138 and a project memory; not part of this implementation.

## Components

New, under `agent-platform/runtime/`:

| File | Responsibility |
|---|---|
| `session_state.py` | Session lifecycle, append-only hash-chained event log, atomic writes, optimistic concurrency (expected-sequence), resume-from-disk. Owns Agent Runtime's own persistence — does not import `agent-platform/state/`. |
| `text_inference_port.py` | `invoke(prompt: str, output_schema: dict) -> dict`. `output_schema` is passed to the provider as a best-effort structured-output hint only (when the provider supports it) — it is never the authority on validity. The kernel's new `verify_against_schema` operator (step 4 below) is the sole authority: it re-validates the raw response against `ai-act-assessment-output.schema.json` regardless of what the provider claims to have enforced. Built on `cortxt_resilient_inference` + `BudgetGate` + `provider_policy` (fail-closed on missing budget/policy approval, same as Fas 1/2A). Distinct from the reasoning kernel's `InferencePort` (`invoke(content) -> int`) — no shared abstraction. |
| `tools.py` | Tool admission gate + `read_fixture_file` tool. Path-sandboxed to `verticals/vertical-01-ai-act/evals/synthetic/`; rejects traversal before any read happens. |
| `agent_loop.py` | Orchestrates one run: claim → admit+run tool → reasoning kernel (new `MODEL_ASSISTED` strategy via `Engine.solve_model_assisted()`, `text_inference_port` as the `invoke` callable, `classify.yaml`'s deterministic checks as the `validate` callable) → result envelope. Logs every step to `session_state` for resume. |
| `research_profile.py` | Static config for this profile: allowed tools (`read_fixture_file` only), target workflow (`vertical-01-ai-act/classify`), model policy reference. |

Reused, with one additive extension: `agent-platform/reasoning/` — the kernel's existing DIRECT/RECURSIVE/GEOMETRIC solvers, `select_strategy()`, and their tests are untouched; a new `MODEL_ASSISTED` strategy + two new operators are added alongside them (see scope decision 6 above). Unchanged, reused as-is: `verticals/vertical-01-ai-act/` (schemas/instructions/fixtures), `cortxt_resilient_inference`/`BudgetGate`/`provider_policy` (underlying machinery).

## Data flow

1. `agent_loop.claim(task_id, fixture_path)` — `session_state` creates a new resumable session (`run_id`, hash-chained log), status `admitted`.
2. **Tool admission**: loop requests `read_fixture_file(fixture_path)`. Gate checks the path resolves inside `verticals/vertical-01-ai-act/evals/synthetic/` (no traversal) before the tool runs. Logs `tool.admitted` / `tool.completed`.
3. **Reasoning kernel, `MODEL_ASSISTED` strategy**: the new `inspect_with_model` operator calls `text_inference_port.invoke(prompt, output_schema)` with `system-prompt-classify.md` + fixture input. Session logs `inference.requested` / `inference.completed` (with cost from `BudgetGate`) around the call.
4. **`verify_against_schema` operator**: runs `classify.yaml`'s `classification_review` deterministic checks (schema validation, required fields, enum checks, prohibited-empty-obligations) against the model's response.
5. **Result envelope**: assembled (status, result, cost, session reference); session marked terminal.

## Error handling

- **Budget exhausted** (`BudgetExhausted`): caught before any HTTP call; session → `blocked` with reason. No partial result is stored as if valid.
- **Response fails schema validation**: `verify_against_schema` fails → session → `blocked`, not a silently-successful `failed`. Mirrors `dispatcher.py`'s `resync_pending()` principle: an explicit, reviewable terminal state, never a guess dressed up as success.
- **Tool admission denied** (path outside sandbox): fail-closed before any model call — no cost incurred for an invalid attempt.
- **Crash/interrupt mid-run**: same resume mechanics T1 proved — reload session from disk; if `inference.requested` was logged but no matching `inference.completed`, treat the call as not-happened and redo it, never assume success.

## Testing

- **Unit tests** (0 cost, always in CI): tool-admission gate (traversal rejected / valid path admitted); `session_state` (create/append/resume/hash-chain/optimistic concurrency — mirrors the T1 ledger's test suite shape); `text_inference_port` against a fake backend (budget exhausted, malformed response, success).
- **Integration test** (0 cost, in CI): full `agent_loop` against one synthetic fixture with a mocked `text_inference_port` — proves the mechanism (claim→tool→kernel→verify→envelope→resume) without real calls.
- **`real_inference`-marked test** (excluded from default CI, needs credentials): same fixture against the real endpoint — the actual exit-criterion proof, run manually once `CORTXT_INFERENCE_URL`/`CORTXT_INFERENCE_API_KEY` are configured and `cortxt_resilient_inference` is installed.

## Out of scope for this slice

- Reasoning strategies other than the new `MODEL_ASSISTED` one (no task here needs `direct`/`recursive`/`geometric`).
- Strategy portability/versioning (issue #138, deferred to Fas 8).
- Any tool beyond `read_fixture_file` (no coding/shell/patch tools — that's Fas 3, Coding Agent).
- Supervisor / child runs / multi-session coordination (Fas 4).
- Promoting `agent-platform/runtime/` to any wider "Accepted" architecture status — per the ADR-016/017 pattern, that's a separate decision made *after* this vertical slice proves the need, not before.
