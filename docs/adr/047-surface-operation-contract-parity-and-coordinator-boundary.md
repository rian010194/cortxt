# ADR-047: Surface operation-contract parity and the control-plane / coordinator-agent boundary

**Status:** Proposed
**Date:** 2026-09-10
**Deciders:** Operator approval required
**Technical Story:** operator direction 2026-09-10 (points 1 and 4); reconciled in
issue #534's sibling documentation-direction issue; informs the Hermes
profile-selection issue and #495 without gating either

## Context

The operator restated the near-term direction on 2026-09-10:

1. Prioritise stable shared application logic — verified through the CLI and
   exposed through MCP — ahead of broader Cortxt OS build-out. The CLI, MCP and
   OS must use the same operations and the same mandate checks. MCP is not a
   shortcut past human approval. A thin OS flow is kept for real user
   verification.
2. A future orchestrating agent may help the operator break work down and follow
   it through the OS, but Cortxt's deterministic control plane owns mandate,
   policy, run identity, budget and evidence. Coordinator agents are optional per
   work need, not mandatory per runtime. Native runtime delegation requires
   explicit qualification and must not bypass Cortxt controls.

Several boundaries this touches are already decided and are **referenced, not
re-decided**, here:

- The external integration surface is an MCP server (ADR-024); Tier-1+ calls
  require a signed, nonce-bound mandate envelope verified before execution
  (ADR-032), with key rotation (ADR-033) and mandate-bound run-lifecycle tools
  (ADR-034) and review-sync (ADR-037).
- Opt-in remote state sits behind that same MCP surface while CLI-primary
  interaction and the loopback widget boundary are preserved (ADR-041).
- Cortxt is work- and mandate-first (ADR-042); Cortxt OS is a general first-party
  app runtime and Work is its first principal app (ADR-044).
- The declarative widget contract routes named reads and named action requests
  through `cli` / `mcp` / `github-transition` ports with no widening and
  action-time authorization (ADR-038).
- GitHub Issues plus exactly one `workflow:*` label carry workflow state
  (ADR-018); the three sanctioned delivery paths uphold the label invariant
  (ADR-040); the dispatch contract and Evidence Gate govern claims and evidence.
- Agent runtimes are replaceable resources behind Cortxt-owned ports
  (ADR-014/016); coding engines are a permanent multi-routing set, never a
  replacement path (ADR-019); adapter registration is separate from `route()`
  selection (ADR-026/027).
- Execution-map claims and prerequisite ordering are fail-closed over issue /
  run / branch / worktree / label / session / engine-session resources
  (ADR-039).

What is **not** yet decided, and what this ADR proposes, is (a) that the three
surfaces are bound to one shared operation contract rather than merely
"exposing the same authority", and (b) an explicit statement of the
control-plane / coordinator-agent / native-delegation boundary so a future
orchestrating agent cannot be read as a required component or as an authority
holder.

## Decision

### 1. One shared operation contract across CLI, MCP and OS

Every operator-visible operation that mutates Cortxt state or advances a
Workstream (compose/prepare a mandate, mark ready, claim a run, submit for
review, record a decision, retry) is defined once as a shared operation with a
single set of mandate, approval and evidence checks. The CLI, the MCP surface and
Cortxt OS are **consumers** of that contract; none of them re-implements the
check logic or reaches state by a private path.

"Surface parity" means the shared operation contract and the shared mandate
controls — **not** that every surface must expose every feature at the same time.
Surfaces may differ in coverage and maturity: the CLI remains the most complete
surface, and a deliberately thin OS flow is maintained so a real user can verify
the end-to-end journey. A surface may lag in what it exposes; it may not diverge
in what a given operation checks or is allowed to do.

MCP has no operation path that a human sign-off does not also govern. The mandate
envelope (ADR-032) and the operator gate over irreversible effects apply to MCP
exactly as to the CLI and OS. Remote state (ADR-041) does not change this.

### 2. Control plane, coordinator agent, native delegation

- **The deterministic control plane owns authority.** Mandate, policy, run
  identity, budget and evidence are held by Cortxt's deterministic control plane
  (GitHub Issues + `workflow:*` per ADR-018, the dispatch contract, the Evidence
  Gate, ADR-039 claims). No agent holds or delegates this authority.
- **A coordinator (orchestrator) agent is optional.** An agent that helps the
  operator decompose and follow work through the OS may be added. It is engaged
  per work need and is **never a mandatory component per runtime**. It produces
  proposals, structure and status; it does not approve, merge, deploy, publish,
  close, or widen limits, and it is not on the authorization path for any
  operation in section 1.
- **Native runtime delegation must be explicitly qualified.** A runtime's own
  child-delegation feature is a distinct capability that must be qualified before
  use, demonstrating at least: parent/child identity correlation, queryable child
  status, inherited-or-stricter permissions, aggregate budget accounting,
  cancellation, and complete child evidence. Until qualified for a given runtime,
  Cortxt dispatches one bounded unit per claim and native delegation stays off.
  Qualification never lets a child escape the parent mandate or the ADR-039
  claim set.

### 3. Relationship to other work

- This ADR sets a boundary; it does not schedule delivery. The near-term order
  (finish W13, then shared operations + explicit profile selection, then
  Milestone B, then broader OS build-out) lives in
  `docs/agents/goal-operating-model.md`.
- It does not decide execution policy profiles or evidence contracts (ADR-045,
  Proposed; issue #495) and must not become a gate in front of #495, #498 or
  #497.
- It does not decide the request-digest field set (ADR-046, Accepted) or the
  `dispatch.request.v1` vs `v2` wiring question, which is tracked as an open
  reconciliation.

## Consequences

### Positive

- A surface cannot silently acquire a weaker check than another; a new surface
  starts from the shared contract instead of a fresh implementation.
- A future orchestrating agent has an unambiguous, bounded place: helpful, never
  required, never an authority.
- "MCP as a bypass" is explicitly closed.

### Negative

- Existing surface-specific code paths that duplicate check logic must be
  refactored onto the shared contract, which is work that delivers no new
  user-visible feature.
- Keeping a thin OS flow in step with the shared contract is ongoing cost.

### Risks

- The shared operation contract could ossify prematurely if it is specified
  before the OS flow has exercised it; mitigation is to grow it from the
  operations W13 and #501 actually need, not speculatively.
- "Parity" could still be misread as "feature-simultaneity"; the wording in
  section 1 is deliberate and the CONTEXT.md entry reinforces it.

## Alternatives Considered

1. **Leave it at "the CLI and MCP expose the same authority" (status quo
   wording).** Rejected: it does not prevent a surface from re-implementing a
   check differently, and it says nothing about a coordinator agent, which the
   operator's direction explicitly calls out.
2. **Make the coordinator agent a first-class required component of the OS
   loop.** Rejected: it contradicts the mandate-first model (ADR-042) and the
   operator's direction that coordinator agents are optional per work need.
3. **Allow native runtime delegation once a runtime advertises it.** Rejected:
   advertising is not qualification; ADR-039 and the dispatch contract require
   demonstrated identity, budget and evidence behaviour first.

## Validation

- [ ] Implementation matches decision
- [ ] Tests cover decision boundaries
- [ ] Documentation updated (`docs/agents/goal-operating-model.md`,
      `docs/agents/current-operating-model.md`, `CONTEXT.md`)

## Expiry/Review Trigger

- Review by: 2026-12-31
- Trigger: the shared operation contract is first implemented, a coordinator
  agent is proposed for build, or a runtime's native delegation is put forward
  for qualification.
