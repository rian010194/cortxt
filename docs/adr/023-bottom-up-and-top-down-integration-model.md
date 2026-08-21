# ADR-023: Cortxt supports both bottom-up and top-down integration, not one exclusively

**Status:** Accepted
**Date:** 2026-08-19
**Deciders:** Rikard (operator), Claude Code (draft)
**Technical Story:** Operator discussion 2026-08-19 (comparison with [Hindsight](https://hindsight.vectorize.io/)); the v.02 vision's §6 ((internal design archive), addendum 2026-08-19)

## Context

Cortxt's README tagline ("Users own the work's state, memory, tools, evidence, and
evolution; models, inference providers, and external agent engines remain replaceable
resources behind Cortxt-owned contracts") describes a **top-down** architecture: Cortxt
owns the control plane, external engines (Hermes, Pi, Codex, Claude Code) are
replaceable resources behind Cortxt-owned contracts. Every pattern built in the
v.02 milestone so far (routing/`engine_manifest.py`, `credential_broker.py`,
`addon_review.py`) assumes that direction — they only work because Cortxt owns the
orchestration loop.

The operator compared against Hindsight on 2026-08-19, a specialized memory service
for AI agents. Hindsight's integration structure is the opposite: **bottom-up** — a
narrow, well-defined service that *other* frameworks (LangGraph/LangChain, CrewAI,
Vercel AI SDK) and coding agents (Claude Code, Codex CLI, Cursor CLI, etc.) hook into,
without Hindsight owning their orchestration.

The comparison surfaced a real trade-off, not just a matter of style:

- **Bottom-up** wins on adoption speed (add an integration, no stack swap) and low
  lock-in for whoever integrates — but can never guarantee whole-system properties
  (mandate, audit, no-self-approval) across a task's entire lifecycle, only within its
  own slice.
- **Top-down** wins on being able to hold together exactly the invariants ADR-019 and
  ADR-022 already build on — but requires a much larger surface built correctly before
  anything is usable, and a heavier first ask of a new user.

This is not a trade-off that must be resolved in one direction. Nothing prevents Cortxt
from being top-down internally (toward the engines it manages) while also being offered
bottom-up externally (to other frameworks/agents that want to consume its control plane
as a service) — the same way Hindsight itself is offered to Claude
Code/Cursor/CrewAI today, except with Cortxt as the service instead of the memory.

## Decision

**Cortxt is top-down internally, permanently — that is not changed by this decision.**
The control plane owns routing, mandate, audit, and contracts toward all engines it
manages (ADR-019, ADR-022). None of this is opened up.

**Cortxt also deliberately becomes consumable bottom-up externally, as a second,
parallel integration path — not a replacement for the first.** Other frameworks
(LangGraph/LangChain, CrewAI, Vercel AI SDK, etc.) or other coding agents should in
time be able to call into Cortxt's control plane as a service (e.g. "give me
mandate-verified routing/audit for this task"), without having to move their own
orchestration to Cortxt themselves.

**This ADR decides the direction, not the surface.** What concrete form the
bottom-up-facing integration takes (Python/TypeScript/Go SDK, MCP server, REST API) is
**not** decided here — it is the same open question that Phase 6's "installable
packages" (§4.1 in the vision document) already wrestles with, and it is resolved
there, not here. This ADR only ensures that work is designed with an external consumer
in mind, not just the local CLI/widget operator.

## Consequences

### Positive
- Resolves a false dichotomy: the v.02 work so far (routing, credential broker,
  addon gate) does not need to be abandoned or compromised to also support external
  consumers — they are orthogonal, not competing, directions.
- Opens an adoption path that does not require anyone to move their existing
  LangGraph/CrewAI stack to Cortxt to benefit from its mandate/audit guarantees.
- Provides a concrete framework for evaluating future API design decisions: "does
  this work for an external consumer, not just the internal CLI?" becomes a real
  question to ask, not an afterthought.

### Negative
- Two integration surfaces to maintain over time (internal control-plane API +
  external consumer surface) instead of one.
- Risk that the external surface is built too narrowly (only what the internal CLI
  happens to need) if it is not designed deliberately — the same type of mistake
  ADR-016 already warned about at another layer (coding a single user's assumptions
  in as a platform contract).

### Risks
- Without a clear priority order, "build in both directions" could be read as
  "build everything at once" — not the intent. The phase sequence (the top-down work
  is already underway, Phases 4/5/6) continues ahead of the external surface; this
  ADR does not change the order, only confirms that the external direction is not
  dismissed.
- The external surface's security model (who/what may call into the control plane
  from outside, with what mandate) is not specified here — it requires its own
  section when the work actually begins, the same discipline the credential-broker
  threat model (Phase 1) held for the internal surface.

## Alternatives Considered
1. **Top-down only, dismiss external consumption** — rejected: closes off an
   adoption path with no real cost to keep open right now (no code needs to be
   written just to *not close the door*), and does not match the operator's stated
   intention to work in both directions.
2. **Bottom-up only, rebuild Cortxt as a service others orchestrate** —
   rejected: tears up the entire v.02 milestone's founding premise (the control
   plane owns mandate/audit) and makes already-built patterns (ADR-019, ADR-022,
   the credential broker) meaningless.
3. **Wait with the decision until Phase 6's packaging question is resolved** —
   rejected: the direction (both) affects how the Phase 6 work is designed; waiting
   would only move the same decision to a point where more code already assumes
   top-down-only.

## Validation
- [ ] Phase 6's "installable packages" work (§4.1) references this ADR when
      the external integration surface's form is specified.
- [ ] No future control-plane API is designed without explicitly asking "what
      does this look like for an external consumer?"
- [ ] A dedicated security/mandate section is written for the external surface
      before it is implemented, not afterwards.

## Expiry/Review Trigger
- Review by: 2026-11-19
- Trigger: Phase 6's packaging work reaches a point where the external surface's
  concrete form (SDK/MCP/REST) must be chosen, OR an external integration request
  (e.g. someone wants to connect LangGraph to Cortxt) makes the question urgent
  earlier.
