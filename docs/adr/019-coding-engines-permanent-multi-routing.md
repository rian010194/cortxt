# ADR-019: Coding execution — permanent multi-engine routing, not Pi/Hermes replacement

**Status:** Accepted
**Date:** 2026-08-16
**Deciders:** Rikard (operator)
**Technical Story:** Operator discussion 2026-08-16 (no GitHub issue created before this ADR)

## Context

`docs/architecture/cortxt-agent-platform-target-architecture.md` §22.3 describes Hermes,
Pi and Prime Agent as roles **during migration** (benchmark, fallback, adapter), and
§24.2 defines explicit "replacement criteria" for when "Pi can leave the main path".
Phase 3 (Coding Agent v0.1) is written against the exit criterion that a code fixture should be solved
**without** Pi or Hermes — i.e. as a step toward making them unnecessary.

The operator clarified on 2026-08-16 that this is not the intention: the goal is to continue
using Pi, Hermes and Codex, and add GitHub Copilot, while Cortxt builds its
own coding capability for certain task classes. Asked to choose between (a) an own Coding
Agent replaces external engines, (b) Cortxt becomes only an orchestrator without its own
coding runtime, or (c) both in parallel, the operator chose **(c)**.

This is an actual direction choice that `target-architecture.md` (a description file) in its
current wording contradicts, and it needs a record per the repo's own rule for
decision notices before the description file is corrected.

## Decision

**Cortxt's own Coding Agent (Phase 3 and beyond) is a permanent addition to the
routing policy, not a replacement path.** Pi, Hermes and Codex remain permanent
routing choices; GitHub Copilot is added as a future adapter candidate. No external
coding engine is being phased out as a consequence of Phase 3.

The routing policy selects the engine per task class (cost, capability, data class,
availability) — not according to a migration plan where external engines become unnecessary.
`target-architecture.md` §24 ("replacement criteria for Hermes/Pi") does not apply
to coding engines after this decision; it remains unchanged for Hermes' coordinating
role (Supervisor, §24.1), which is not covered by this ADR.

## Consequences

### Positive
- Preserves access to the best available external tools (Copilot, Codex) without
  Phase 3 being forced to become "good enough to replace Pi" before it can be used.
- Reduces time pressure and scope risk on Phase 3 — it needs to prove its own capability for
  bounded task classes, not general parity with Pi.
- Opens the door to Copilot as an additional adapter without it being interpreted as a deviation from the plan.

### Negative
- Two parallel maintenance lines: an own coding runtime (Phase 3+) and adapters for
  several external engines (Pi, Hermes, Codex, future Copilot).
- The routing policy becomes more complex — requires explicit decision logic for which
  task class goes to the own Coding Agent versus an external engine.

### Risks
- Without clear selection criteria, own Coding Agent development may lack direction
  (no "done" line corresponding to the earlier replacement criterion).
- Adapter maintenance for several external engines (especially a future Copilot adapter)
  is unproven and can become a hidden cost.

## Alternatives Considered
1. **Full replacement (original §24.2 wording)** — rejected: no longer matches
   the operator's intention, and would mean forgoing the best available external
   tools unnecessarily.
2. **Orchestration only, no own Coding Agent** — rejected: the operator wants
   both; certain task classes can benefit from tight integration with Cortxt's own
   Problem State, reasoning and evidence layers in a way external engines cannot provide.

## Validation
- [x] Operator approval registered (2026-08-16, this conversation).
- [ ] `target-architecture.md` §22.3 and §24.2 updated in the same commit as this ADR.
- [ ] Selection criteria (which task class → own Coding Agent vs external engine)
      defined — tracked as an open decision, not settled by this ADR.
- [ ] Copilot adapter evaluated and added to the `adapters/` structure when prioritized.

## Expiry/Review Trigger
- Review by: 2026-11-16
- Trigger: selection criteria for engine-per-task-class are implemented, or
  the maintenance cost of parallel coding adapters proves disproportionate to
  the benefit of own Coding Agent capability.
