# ADR-022: Phase 3 v0.1 — capability manifest shape and engine-selection criteria

**Status:** Accepted
**Date:** 2026-08-18
**Deciders:** Rikard (operator), Claude Code (draft)
**Technical Story:** rian010194/cortxt#166 (Phase 2, done), the v.02 milestone's Phase 3 (`.hermes/plans/2026-08-18-v02-milestone-wayfinder.md`)

## Context

ADR-019 (Accepted 2026-08-16) decided that routing between coding engines should be
dynamic and per task class (cost, capability, data class, availability) — not
a migration plan toward a single engine. Its own validation checklist, however,
explicitly left open: *"Selection criteria (which task class → own Coding Agent vs
external engine) defined — tracked as an open decision, not settled by this ADR."* A
search across the whole repo (2026-08-18) confirms that no selection mechanism,
capability manifest, or routing function exists yet — only the open question in the
v.02 vision's §6 (commit `7ea503c`, pure documentation) and ADR-019's unchecked
checklist item.

That same evening, two Hermes dispatches on the same task (issues #165, #166) provided
concrete evidence of why static assumptions about "which engine" are dangerous:
`deepseek-v4-flash` was periodically idle (429 "all replicas at capacity"), a Hermes
worktree branched off the wrong base due to a tool error, and a dispatch attempt built
the wrong surface despite a detailed task description. The operator has expressed that
the end goal is considerably broader than a static choice between two engines: the
routing decision should in time be able to choose Hermes, Pi, Claude directly, or a
chain of several engines in different orders, depending on task class — and that
today's Hermes profiles (set up before worktree support existed) may rest on outdated
assumptions.

This ADR does **not** decide the full vision (chained multi-engine orchestration).
It decides the narrow v0.1 slice that Phase 3 can build now, without locking in a
design that must be torn up when chaining/learned reliability is added later.

**Important not to lose sight of:** target-architecture.md §29 point 5 already
establishes that "RLM and geometric reasoning are owned by Cortxt Agent Core" — the
orchestrator's routing decision is thus not intended to forever be the deterministic
`route()` function below. Phase 5 (RLM v1) and Phase 6 (Geometric Reasoning v1)
already have design/implementation in `agent-platform/reasoning/geometric/` and
corresponding specs (internal design archive). When v0.1's static
pattern matching proves insufficient, the intended successor is *the existing*
Geometric Reasoning engine in this codebase — not a new, uninvented ML mechanism. This
ADR builds v0.1 as a deliberate bootstrap toward that goal, not as a competing
permanent solution.

## Decision

**v0.1 scope (Phase 3):**

1. **Capability manifest — engine-agnostic format.** Each registered engine declares:
   - `engine_id` (str) — e.g. `claude-direct`, `hermes`
   - `task_shapes` (list[str]) — free-form tags the engine handles, e.g. `tdd`,
     `widget-ui`, `research`, `security-review`. Not NLP-classified — the task is
     tagged by the sender (the same pattern as the Phase 3 research document's §2.5
     "capability tags": typed from the top, not yet a platform contract).
   - `cost_class` (str: `free` | `cheap` | `metered`)
   - `reliability_class` (str: `verified` | `unverified` | `degraded`) — set manually,
     not learned in v0.1. Tonight's `deepseek-v4-flash` incident is the example: an
     engine can be marked `degraded` by hand without a code change.
   - `notes` (str, optional) — free text for operator context (e.g. "profiles set up
     before worktree support existed, verify before trust").

2. **Routing function — simple, deterministic pattern matching.**
   `route(task_tags: list[str]) -> EngineChoice` selects among manifests whose
   `task_shapes` intersect `task_tags`, filters out `degraded`, sorts by `cost_class`
   (free before cheap before metered), and returns the first match plus the reason
   (which tag matched, which were excluded and why). No match → deterministic fallback
   to `claude-direct` (tonight's experience: the only engine that didn't need a
   restart or produce the wrong surface), with the reason logged, not silently.

3. **Two registered engines in v0.1:** `claude-direct` and `hermes`. Pi, Codex,
   Copilot are added as adapters when they are actually wired in (ADR-019 keeps them
   as permanent routing choices, but "adapter exists" ≠ "adapter registered in the
   v0.1 manifest" — guessing their `task_shapes`/`reliability_class` before they have
   actually run would be coding in assumptions no one has verified).

**Explicitly not v0.1 (to avoid building the wrong abstraction now):**
- Chaining multiple engines in sequence for one task.
- Learned/dynamic `reliability_class` based on actual track record (requires Phase 8's
  learning-loop mechanics, not reinvented here).
- ML- or embedding-based task classification (the same "don't build speculatively"
  rule that the Phase 3 research document's §3.1 already applies to task-shape
  recognition).
- Pi/Codex/Copilot manifest (the adapters are not wired in yet).

## Consequences

### Positive
- Resolves ADR-019's open point with a slice small enough to verify tonight, without
  guessing at chaining or learning for which no data exists yet.
- The manifest format is engine-agnostic from the start — adding Pi/Codex later is
  adding an entry, not a redesign (the same pattern as the Phase 3 research's
  dict-constant-to-YAML-serialization reasoning, applied to routing instead of tool
  contracts).
- `reliability_class: degraded` provides a concrete, code-free way to act on tonight's
  Hermes experience without waiting for a learning mechanism.

### Negative
- Statically/manually set `reliability_class` fields require someone (the operator or
  Claude) to actually update them when an engine proves unreliable — no automatic
  ground truth yet.
- Fallback-to-`claude-direct` means the routing decision in practice favors one engine
  until more are verified — a deliberate bias, not a neutral algorithm.

### Risks
- If Pi/Codex are added without honestly updating `task_shapes` (guessed tags instead
  of verified ones), the same "coded-in guesses as contracts" mistake ADR-016 already
  warned about at another layer recurs.
- Free-text `task_shapes` without normalization (the same open question as the Phase 3
  research's §7 point 3, inherited here) can drift toward inconsistent tags across
  senders.

## Alternatives Considered
1. **Build chained multi-engine orchestration directly** — rejected: no verified data
   on which task classes actually benefit from chaining; it would guess an architecture
   ADR-019 itself warns against locking in too early.
2. **Keep the status quo (everything via Hermes profiles)** — rejected: exactly what
   ADR-019 decided against, and tonight's two failed dispatches are direct evidence
   against trusting a single engine blindly.
3. **Learned routing (embeddings/ML) from the start** — rejected: the same
   don't-build-speculatively rule that already applies to task-shape recognition in
   the Phase 3 research document; no training data exists.

## Validation
- [ ] Manifest schema implemented and tested (at least `claude-direct` + `hermes`)
- [ ] `route()` function has test coverage for: match, no match (fallback), degraded
      engine excluded, cost sorting
- [ ] Tonight's Hermes attempt-1/attempt-2 experience manually coded as an example in
      the `hermes` manifest's `notes` field (traceability, not just in the memory log)
- [ ] Documentation updated: `.hermes/plans/2026-08-18-v02-milestone-wayfinder.md`
      Phase 3 section points here instead of at `ADAPTER_REGISTRY`

## Expiry/Review Trigger
- Review by: 2026-09-18
- Trigger: a third engine (Pi, Codex, or Copilot) is actually wired in and needs a
  real manifest, OR track-record data shows that static `reliability_class` is not
  enough and a learning mechanism (Phase 8 pattern) is needed, OR the Geometric
  Reasoning engine (Phase 5/6) is ready to take over `route()`'s role — see the
  Context note about target-architecture.md §29 point 5.
