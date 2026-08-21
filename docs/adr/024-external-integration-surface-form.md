# ADR-024: External integration surface takes the form of an MCP server

**Status:** Accepted
**Date:** 2026-08-19
**Deciders:** Rikard (operator) — via this session's explicit, time-boxed
autonomy grant, not a synchronous round-trip; Claude Code (draft)
**Technical Story:** v.02 swarm orchestration, Track 3
((internal design archive));
spike (internal design archive)

> **Acceptance provenance:** this ADR was self-accepted by the Claude Code
> session that drafted it, under an explicit, time-boxed full-autonomy grant
> documented in
> (internal design archive)
> section "Session authorization (explicit, time-boxed)". That section states
> the operator granted full autonomy for this session only, including
> accepting ADRs without a per-step confirmation gate, superseding the
> standing "never accept an ADR without being asked" rule for this session's
> swarm work only — it does not carry into future sessions. This is not a
> general precedent for ADR self-acceptance; it is recorded here so a future
> reader, including the operator reviewing after the fact, can see exactly
> what authorized it.

## Context

ADR-023 (Accepted, 2026-08-19,
`docs/adr/023-bottom-up-and-top-down-integration-model.md`) decided that
Cortxt should be bottom-up-consumable externally: other frameworks
(LangGraph/LangChain, CrewAI, Vercel AI SDK) and other coding agents should be
able to call into Cortxt's control plane as a service, without adopting
Cortxt's own orchestration loop. ADR-023 explicitly left the concrete form of
that surface undecided: SDK, MCP server, or REST API was named as a later
question, not resolved there. ADR-023 assigned this form question to Phase 6's
installable-package work ('resolved there, not here'); this ADR answers it earlier
than that, for the reasons given in the Alternatives Considered section,
without changing ADR-023's direction decision.

ADR-022 (Accepted, 2026-08-18,
`docs/adr/022-fas3-capability-manifest-and-engine-selection-criteria.md`)
introduced the capability-manifest pattern this ADR builds on: each engine
self-declares `task_shapes`, `cost_class`, and `reliability_class`
(`agent-platform/routing/engine_manifest.py`), and `route()` picks among
them. An external caller asking "what can this control plane do, and which
engine should handle my task" maps naturally onto that same
declare-then-select shape, which is also the shape MCP's tool-list-then-call
convention is built around.

The spike doc
((internal design archive))
compared SDK, REST API, and MCP server against: (a) what the control plane's
surface concretely is today (`engine_manifest.route()` plus
`unified_cli.py`'s admin subcommands, both already returning structured
`ResultEnvelope` results), (b) the codebase's current dependency posture (no
HTTP framework; two dependencies total: `pyyaml`, `jsonschema`), and (c) who
the concretely-named external consumers actually are — not hypothetical
polyglot application code, but agent runtimes: Pi and the operator's own
coding agent (both named in
(internal design archive)
section "Engine expansion: Pi and the own coding agent"), plus the frameworks
named in ADR-023 itself (LangGraph, CrewAI, Vercel AI SDK).

## Decision

**The external integration surface takes the form of an MCP server**, not a
language-specific SDK and not a REST API, for the initial slice. A REST
facade over the same underlying functions remains a small, non-redesign
addition later if a genuinely non-agent consumer needs one.

The MCP server wraps the existing control-plane functions as tools rather
than inventing new logic:
- `agent-platform/routing/engine_manifest.py`'s `DEFAULT_MANIFESTS` and
  `route()` become capability-listing and routing tools.
- `agent-platform/cli/unified_cli.py`'s admin subcommands (`runtimes`,
  `credentials`, `addons`, etc.) become further tools, each returning the
  existing `ResultEnvelope.to_dict()` shape rather than a newly-invented
  response schema.

This decision is scoped to *form*, per the spike's own explicit boundary:
which specific tools ship first, authentication/mandate-verification for
external MCP calls (ADR-023's own flagged open risk, still unresolved by this
ADR), and packaging/distribution are left to a future implementation plan,
not decided here.

## Consequences

### Positive
- Resolves ADR-023's deliberately-deferred form question with a concrete,
  reasoned choice, unblocking a future implementation plan for the external
  surface.
- Zero new protocol-adapter code needed on the side of the two
  concretely-named consumers (Pi, the operator's own coding agent) — both are
  MCP-capable agent runtimes already, by construction.
- Lowest implementation cost of the three options against this specific
  codebase: no new HTTP-framework dependency (stdio-transport MCP needs none,
  compatible with the current two-dependency posture), no new
  hosting/networking surface, and tool discovery is native to the protocol
  rather than a schema layer that would need to be hand-built (as REST would
  require).
- Directly reuses ADR-022's capability-manifest pattern and
  `unified_cli`'s already-structured `ResultEnvelope` results — no redesign
  of either to fit the new surface.

### Negative
- MCP is a narrower-audience protocol than plain HTTP: a consumer that is
  not itself an agent runtime (a plain web dashboard, a CI system) cannot
  call it without an MCP client library, whereas REST would need only an
  HTTP client. This is accepted as a deliberate scoping choice (serve the
  consumers that are actually named first) rather than an oversight.
- Adds a second surface to maintain in the CLI/admin layer
  (`unified_cli.py`'s subcommands and the MCP tools wrapping them can drift
  out of sync if not kept deliberately parallel).

### Risks
- ADR-023's own Risks section already flagged that the external surface's
  security model (who or what may call into the control plane externally,
  with what mandate) is unspecified. Choosing MCP does not resolve this — it
  is still an open item that must be specified before the server is actually
  implemented and exposed beyond a purely local/loopback context, with the
  same discipline ADR-023 points to (the Phase 1 credential-broker threat
  model).
- If the MCP tool surface is built to mirror only what the local CLI happens
  to need today, it risks the same "coded a single consumer's assumptions in
  as a platform contract" mistake ADR-016 already warned about on a different
  layer. The spike's explicit deferral of "which tools ship first" to a
  future implementation plan is meant to keep that decision deliberate, not
  a default.

## Alternatives Considered
1. **Language-specific SDK(s) (Python/TypeScript/Go)** — rejected: highest
   ongoing cost (a separate packaging/versioning/CI surface per language,
   permanently), and poor fit to ADR-023's "service" framing since an SDK
   means the consumer links Cortxt into their own process rather than
   calling out to it — the control plane cannot itself enforce
   mandate/audit guarantees on a call it never received as a distinct
   invocation. Neither of the two concretely-named consumers (Pi, the
   operator's own coding agent) integrates via package import.
2. **REST API** — rejected for the initial slice, not permanently: genuinely
   language-agnostic, but requires standing up a web framework the codebase
   doesn't currently have, a hosting/networking story the loopback-only
   widget server doesn't provide a precedent for, hand-built
   auth/discovery/schema layers, and leaves every consumer writing bespoke
   HTTP-calling glue with no shared discovery convention. The operational
   cost is not yet justified by a concrete non-agent consumer; kept open as
   a future addition once one exists.
3. **Defer the form decision further, wait for an actual external
   integration request** — rejected: the same reasoning ADR-023 itself used
   to reject waiting on Phase 6 packaging applies here — waiting only moves
   the same decision to a point where more code already assumes no external
   form, and the spike already produced a groundable, non-speculative
   comparison (this is a form choice grounded in the existing codebase and
   named consumers, not a guess about undetermined future integrations).

## Validation
- [ ] A future implementation plan for the external surface references this
      ADR when choosing which specific tools to expose first, rather than
      re-litigating SDK/REST/MCP.
- [ ] The MCP server's authentication/mandate-verification model is
      specified as its own section before implementation begins, per this
      ADR's Risks section and ADR-023's own flagged gap.
- [ ] `unified_cli.py`'s admin subcommands and the MCP tools wrapping them
      are kept deliberately parallel (a subcommand added without a
      corresponding tool, or vice versa, is a signal to revisit, not a
      silent drift).

## Expiry/Review Trigger
- Review by: 2026-11-19 (aligned with ADR-023's own review date, since this
  ADR is a direct child decision of it)
- Trigger: implementation of the MCP server actually begins and surfaces a
  concrete reason the form choice doesn't hold (e.g. a named consumer turns
  out not to be MCP-capable after all), OR a concrete non-agent consumer
  (dashboard, CI system) appears and needs the deferred REST facade sooner
  than expected.
