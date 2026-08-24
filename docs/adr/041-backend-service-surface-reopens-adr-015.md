# ADR-041: Backend Service Surface Reopens ADR-015 (Surface Dimension Only)

**Status:** Accepted  
**Date:** 2026-08-24  
**Deciders:** Rikard (operator)  
**Technical Story:** Design spec `docs/superpowers/specs/2026-08-24-cortxt-backend-service-design.md`

## Context

ADR-015 decided "repository-native + CLI (primarily)" as the product surface
and left an explicit review trigger for future surface change. ADR-021
already exercised that trigger once, narrowly, to permit a widget UI and
admin surface as a **complement** to the CLI — "the CLI remains the source of
truth; the widget mirrors its state."

Today all durable state the CLI produces (session/agent-state, widget-state,
Atlas-derived caches, and other local artifacts) is written as JSON files on
the operator's own machine. This creates three concrete problems the
operator has confirmed:

1. Multi-device / multi-operator sharing is impossible — state is pinned to
   one filesystem.
2. A widget or future web surface that wants live state must poll or mirror
   a file written by a process on the same machine; it cannot show state
   from a run happening elsewhere.
3. Concurrent writers (multiple agent processes) to the same local JSON file
   risk races and inconsistency.

The operator's own stack changes frequently, and other developers run
different stacks — the fix needs to be portable across environments, not
tied to one machine's filesystem, and it needs to work for developers who
never touch the operator's specific setup.

Unlike ADR-021 (widget as a *mirror* of CLI-owned state), the operator has
confirmed the goal here is a **real server-side API surface**: CLI, widget,
and future clients (including a future web surface) all become clients of a
backend service for state that has been opted into remote storage. This is a
larger reopening of ADR-015 than ADR-021 was, because it changes who owns
state, not just who displays it.

This question was independently raised in a parallel session while
brainstorming the widget host's side panel (`lab/HANDOFF-2026-08-24-hosted-backend-vs-static-json.md`),
which surfaced two boundaries this ADR must explicitly reconcile with rather
than quietly cross:

- **ADR-038** gave the widget host a deliberate, reviewed security posture:
  loopback-only, no CORS, read-only by default. A network-reachable CBS is
  not an incremental extension of that posture — it is a different trust
  boundary and needs its own threat model, not inherited scrutiny from
  ADR-038's review.
- **ADR-024** already named the MCP server as *the* external integration
  surface. Adding CBS as a second, separately-authenticated network surface
  risks becoming an uncoordinated fourth product surface (alongside CLI,
  widget, MCP) rather than a reconciled extension of the existing ones. This
  ADR must say explicitly why CBS is not simply new endpoints on the
  existing MCP server — see Decision and Alternatives Considered.

## Decision

**ADR-015's CLI-primary decision remains Accepted for interaction — the CLI
is still the primary way an operator drives Cortxt.** This ADR reopens only
the **state-ownership dimension**: whether state may be read from and
written to a server-side API surface — the Cortxt Backend Service (CBS) —
that CLI, widget, and future clients can all reach as peers, instead of a
local JSON file that only one process on one machine can see.

The narrow decision is:

- Yes — a Cortxt Backend Service (CBS) capability, with a defined API
  contract, is permitted to exist as a per-state-category, opt-in-only,
  pluggable-deployment persistence and access layer. Local JSON remains the
  default for every state category until the operator explicitly opts a
  category into remote.
- **CBS is a new route family on the existing MCP server (ADR-024, `cortxt
  mcp serve`), not a fourth standalone product surface.** This is the
  specific reconciliation ADR-024 requires: rather than standing up a
  separately-deployed, separately-authenticated service, state-sync
  endpoints are added to the surface ADR-024 already designated as
  "the external integration surface." This keeps the count of network
  surfaces at CLI (interaction) + widget (loopback mirror, ADR-038) + MCP
  server (external integration, now including state sync) — not a new
  fourth thing.
- CBS reuses the existing mandate envelope model (ADR-032, key rotation
  ADR-033) for authentication/authorization, which is already the MCP
  server's auth model — no new auth mechanism, and no second auth model to
  reconcile against the first.
- **ADR-038's loopback-only, no-CORS, read-only-by-default posture is
  unaffected and not extended by this ADR.** The widget host stays exactly
  as ADR-038 scoped it. A widget that wants remote state talks to the MCP
  server's new state-sync endpoints directly (as a client, over the network,
  under its own mandate token) — it does not gain new privileges over the
  local loopback surface, and the loopback surface does not become
  network-reachable by extension.
- CBS deployment is pluggable behind one API contract: self-hosted (operator
  runs their own MCP server instance) or Cortxt-hosted (SaaS). The client
  selects an endpoint; no code path differs between the two.
- This ADR does **not** authorize implementation. It clears the ADR-level
  gate, following the same Phase-0-first discipline ADR-021 established. The
  design spec referenced above defines the phased build; each phase remains
  separately gated by its own review.
- This ADR does not decide the wire protocol, the specific state-category
  taxonomy, or the multi-tenant isolation model for the SaaS deployment
  mode — those are implementation-spec and later-ADR questions, deliberately
  out of scope here to avoid overloading a surface-gate ADR (the same
  discipline ADR-021 applied to naming/security/pricing).

## Consequences

### Positive
- Addresses a confirmed, concrete operator pain point (multi-device,
  multi-operator, concurrent-writer problems with local JSON) rather than
  speculative future-proofing alone.
- Reuses the already-accepted mandate envelope model instead of inventing a
  new auth surface — the largest single risk reducer available for this
  change.
- Preserves ADR-015's CLI-primary interaction decision and ADR-021's
  "complement, not replacement" discipline; only the state-ownership
  dimension moves.
- Per-category opt-in keeps the default (local-only, nothing leaves disk)
  unchanged for any operator who never opts in.

### Negative
- A third reopening of ADR-015's surface question (after ADR-021) increases
  the surface area of "what does CLI-primary still mean" that future readers
  must reconcile across three documents.
- Grows the MCP server's operational burden and blast radius: it now carries
  state persistence in addition to tool-call integration, and any operator
  who runs `cortxt mcp serve` self-hosted takes on securing state storage,
  not just a stateless integration endpoint. A Cortxt-hosted deployment
  carries the same growth on Cortxt's side, plus eventual multi-tenant
  storage.

### Risks
- **Silent scope creep from "persistence backend" to "system of record."**
  If CBS implementation drifts toward becoming the only place state can be
  read reliably, the "local remains default, remote is opt-in" invariant
  erodes in practice even though this ADR states it. Later phases must be
  checked against this invariant explicitly, not assumed safe because the
  opt-in flag exists.
- **Multi-tenant isolation for the SaaS deployment mode is unsolved by this
  ADR.** Reusing the mandate envelope model secures one operator's data; it
  does not by itself guarantee tenant boundaries in a shared-hosting mode.
  This is called out as explicitly out of scope and must be resolved by a
  dedicated ADR before any SaaS deployment ships.
- **No silent degradation is a design intent stated in the spec, not yet an
  enforced property.** If a remote-opted category becomes unreachable, the
  spec requires CLI fallback-to-local plus a visible out-of-sync flag; this
  ADR does not itself guarantee that behavior is implemented correctly.

## Alternatives Considered

1. **Leave ADR-015/ADR-021 untouched; treat CBS as an unrelated new
   project.** — Rejected: CBS directly changes who may read/write
   CLI-produced state, which is exactly the dimension ADR-015 already
   governs. Building it without a gate would repeat the drift ADR-021 was
   created to prevent.
2. **Reopen ADR-015 fully (wedge + surface + state ownership together).** —
   Rejected: the wedge B decision (ADR-015) is unrelated to this question
   and has its own accepted evidence trail; reopening it would create
   needless review churn, as ADR-021 already argued for its own scope.
3. **Scope CBS as a mirror only (ADR-021 pattern), not a real API peer.** —
   Rejected: the operator explicitly confirmed the goal is a real
   server-side surface other clients talk to directly, not a mirror of
   CLI-owned state. A mirror-only scope would misrepresent the actual
   decision and require a second reopening later.
4. **Make CBS mandatory (CLI always requires a reachable backend).** —
   Rejected: contradicts the confirmed requirement that remote storage is
   opt-in per state category and that local-only operation must remain the
   trustworthy default.
5. **Stand up CBS as a wholly separate deployable service, independent of
   the MCP server.** — Rejected: this was the original draft of this ADR
   before the parallel side-panel brainstorming session's handoff
   (`lab/HANDOFF-2026-08-24-hosted-backend-vs-static-json.md`) flagged that
   it would create an uncoordinated fourth product surface alongside CLI,
   widget, and MCP — exactly the drift ADR-024 exists to prevent by naming
   MCP as *the* external integration surface. Extending the MCP server
   instead reuses its existing auth model, deployment story, and review
   history rather than duplicating all three.
6. **Extend ADR-038's widget host itself to be network-reachable.** —
   Rejected: ADR-038's loopback-only, no-CORS, read-only-by-default posture
   was a deliberate, separately-reviewed security decision. Crossing it
   would require its own threat-modeling pass and was never what the
   operator asked for — the operator wants a real server surface distinct
   from the widget host, with the widget as one more client of it.

## Validation
- [ ] Design spec exists and is committed
      (`docs/superpowers/specs/2026-08-24-cortxt-backend-service-design.md`)
- [ ] Operator sets Status: Accepted before any Phase 1+ implementation work
      is treated as authoritative
- [ ] Phase 1 (contract-only) reviewed before any server code is written
- [ ] Multi-tenant isolation ADR exists before SaaS deployment mode ships

## Expiry/Review Trigger
- Review by: 2026-12-01
- Trigger: Phase 1 (API contract) design changes the state-category
  taxonomy or auth model assumed here; or a SaaS deployment is proposed
  before the multi-tenant isolation ADR exists.
