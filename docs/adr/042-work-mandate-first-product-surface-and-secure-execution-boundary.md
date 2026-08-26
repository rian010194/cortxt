# ADR-042: Work- and Mandate-First Product Surface with Replaceable Secure Execution

**Status:** Accepted (2026-08-26, including the pre-acceptance amendment below)  
**Date:** 2026-08-26  
**Deciders:** Rikard (operator; approved 2026-08-26)  
**Technical Story:** Product-positioning and UI-direction review; no implementation issue assigned

## Context

Cortxt already owns durable scope, workflow state, dispatch/run identity,
provider policy, evidence, review, and approval across replaceable external
agent engines. The current product surface, however, is CLI-primary and its
visible examples emphasize sessions, agents, pipelines, widgets, terminal
panes, and execution maps. This makes Cortxt liable to be understood as
another agent cockpit even though its stronger architectural boundary is the
durable work and authority that survive any one execution engine.

Adjacent products reinforce the need for a precise boundary:

- OpenHands is centered on agents, conversations, and local or remote
  workspaces.
- NVIDIA OpenShell is centered on secure agent execution: sandbox lifecycle,
  process/filesystem/network enforcement, credential delivery, and inference
  routing.
- NemoClaw is a reference stack on OpenShell for onboarding and operating
  supported agents with managed inference, policy, snapshots, and lifecycle
  operations.

Calling Cortxt merely a provider-neutral control plane is therefore
insufficient differentiation. OpenShell also has a gateway/control plane,
durable runtime state, providers, policies, authorization, and inference
configuration. Cortxt needs to make the higher-level boundary explicit:
durable authority and work continuity across replaceable execution.

This proposal does not create a new backlog, workflow-state carrier, or
domain object named "Work Ledger." The existing Workstream remains the
operator-visible unit of work, normally correlated to one durable GitHub
Issue under ADR-018. "Work Ledger" is only a candidate product presentation
of that existing authority.

## Decision

We propose the following product and architecture direction:

1. **Cortxt is work- and mandate-first.** The primary product object is the
   durable Workstream and its authorized outcome, not an Agent Session,
   Workspace, sandbox, model, provider, or runtime.
2. **The governing principle is "durable authority, replaceable
   execution."** Scope, acceptance criteria, workflow state, mandate,
   provider policy, evidence, review history, and reserved human decisions
   remain stable when a new Run uses a different engine, model, provider, or
   secure execution backend.
3. **Execution remains a subordinate but first-class diagnostic surface.**
   Existing cockpit, session, pipeline, agent, usage, terminal, and execution-
   map capabilities are retained and reframed as an Execution/Operations or
   Run Inspector view inside a Workstream. They are not the default product
   home or the primary category signal.
4. **CLI and MCP remain core product surfaces.** The CLI remains the power-
   user, local, automation, and bootstrap surface under ADR-015/021. MCP
   remains the external integration surface under ADR-024 and the mandate-
   protected programmable port under ADR-032--037. A future web/admin surface
   is a client of the same work, mandate, run, and evidence contracts, not a
   competing source of truth.
5. **The declarative widget contract is retained but repositioned.** Widgets
   are safe, composable projections and authorized actions over Cortxt-owned
   state under ADR-038. Widget composition is an implementation capability,
   not Cortxt's primary product identity.
6. **Cortxt does not build a competing general-purpose sandbox runtime.**
   OpenShell may be integrated behind a generic secure-execution capability
   or adapter when a concrete data-class or isolation requirement justifies
   it. Cortxt owns the Workstream mandate, dispatch decision, evidence, and
   human decision boundary; OpenShell owns enforcement inside its sandbox.
7. **NemoClaw is not adopted as Cortxt's foundation.** It may be evaluated as
   a reference stack or a runtime-specific adapter for a supported agent, but
   Cortxt must not depend on NemoClaw semantics for its durable work model.
8. **General cockpit expansion pauses until a continuity proof exists.** New
   cockpit work should advance mandate visibility, work continuity, evidence,
   decisions, policy explanation, or run diagnostics. Generic agent cards,
   panes, layouts, live-activity visualizations, and war-room composition do
   not receive product priority without a validated work-level need.

This proposal does not authorize a broad UI rewrite, CLI command migration,
OpenShell integration, or removal of an existing surface. Those require
separately scoped delivery decisions after validation.

## Amendment (2026-08-26, pre-acceptance)

Item 3 above ("Execution/Operations or Run Inspector") is superseded by this
amendment before any acceptance decision. The amendment makes explicit how
the work- and mandate-first hierarchy sits inside Cortxt's existing canvas
product, which the original decision text did not state precisely enough to
prevent it being read as authorizing a new standalone surface:

A. **Cortxt OS retains its existing canvas/window/app-shell model.** The
   work- and mandate-first hierarchy in items 1–8 is expressed *inside* that
   model, not by replacing it with a new standalone dashboard, a second
   backlog, or an unrelated admin surface. The app shell is presentation and
   composition only: it owns no independent authority, mandate, evidence, or
   workflow state — GitHub Issues and `workflow:*` labels (ADR-018) remain
   the sole workflow-state carrier, and the app shell may only read and
   project Cortxt-owned state, never fork or duplicate it.
B. **Work Console is Cortxt OS's default app**, opened automatically inside
   the existing canvas — not a separate product, a new landing surface
   outside the OS model, or a rename of the whole product. Work Console shows
   active Workstreams, desired outcomes, pending human decisions,
   mandate/policy blocks, and evidence requiring review, and is the entry
   point into a given Workstream's mandate, progress, evidence, decisions,
   and execution.
C. **Decisions, Evidence, Policies, Atlas, Connections, and Execution
   Inspector are related apps over the same Workstream state**, opened as
   separate windows on the same canvas — not disconnected dashboards, and not
   forks of Workstream/mandate/evidence/decision state. A Decision made in
   one app is visible in Work Console and any other open app without
   redefining the Workstream.
D. **The existing cockpit is preserved and reframed as Execution Inspector**
   — this is the canonical name, superseding item 3's working name "Run
   Inspector." It retains agent/runtime participants, sessions,
   terminals/logs, pipelines, execution timelines, workspaces/worktrees/
   sandboxes, provider/engine detail, and cost/usage — available from a
   Workstream, not deleted, and not the product's entry point.
E. **Widgets and compositions remain the safe UI substrate** used to build
   Work Console, Decisions, Evidence, Policies, Atlas, Connections, and
   Execution Inspector under ADR-038's declarative contract. They are
   building material for coherent default apps, not Cortxt's primary product
   category, and are not led with a widget builder or uncurated widget
   gallery on the public surface.
F. **Public demo mode and real workspace mode share the same app model,
   canvas, apps, and widget contracts.** The public demo differs only in
   using deterministic, clearly labeled synthetic Workstream/mandate/evidence
   state with no account and no real external mutation — it must not diverge
   into a separate one-off dashboard design.

The operator accepted this amended text on 2026-08-26. This ADR is now
Accepted, superseding item 3's original "Run Inspector" naming and any
reading of the Decision section that would authorize a new standalone
surface outside the existing Cortxt OS canvas.

## Consequences

### Positive

- Differentiates Cortxt from agent/workspace products and sandbox/runtime
  products using a boundary already present in its contracts.
- Preserves the dispatch, mandate, provider-policy, evidence, CLI, MCP,
  widget, and cockpit investments instead of replacing them.
- Gives the product information architecture a stable hierarchy: Workstream
  -> mandate/outcome/state/evidence/decisions -> Runs -> engines/providers/
  workspaces/sandboxes/sessions.
- Allows OpenHands, Codex, Hermes, OpenShell, and future engines or runtimes to
  be complementary execution resources rather than category competitors.
- Creates a falsifiable product claim: execution can be replaced without
  reconstructing authority or losing accepted evidence.

### Negative

- The current landing page, navigation, onboarding, CLI topology, and widget
  examples do not consistently express this hierarchy and will need gradual
  reconciliation if the proposal is accepted.
- Some cockpit and widget work may be deprioritized even when technically
  mature.
- "Human mandate" remains abstract unless the product shows concrete scope,
  limits, expiry, provider rules, reserved decisions, and evidence gates.
- An OpenShell adapter adds a second policy domain whose mapping to Cortxt
  data classes and authority must be explicit and fail closed.

### Risks

- "Work Ledger" could accidentally become a second backlog or workflow-state
  carrier instead of a projection over GitHub Issues and `workflow:*` labels.
- Cortxt could overclaim runtime replacement before state portability and
  cross-engine resume are proven for a real workstream.
- A mandate-first UI could drift into generic governance or access-management
  language and obscure the outcome users are trying to achieve.
- Treating OpenShell as an implementation detail could hide material semantic
  differences between Cortxt provider policy and sandbox enforcement.
- Pausing broad cockpit expansion without delivering a convincing work-first
  slice could leave the product with neither a polished cockpit nor a proven
  replacement.

## Alternatives Considered

1. **Continue agent-cockpit-first positioning.** Rejected because it makes
   agents, sessions, terminals, and layouts the category signal and places
   Cortxt in direct comparison with stronger agent/workspace products.
2. **Freeze or remove the cockpit and widgets.** Rejected because their state,
   diagnostics, composition, and action contracts remain useful within a
   Workstream; the problem is hierarchy, not the existence of the capability.
3. **Replace the CLI with a web-first product immediately.** Rejected because
   it would reopen ADR-015/021 broadly before the work-continuity wedge has
   been validated and would risk creating a second source of truth.
4. **Implement a Cortxt-native general sandbox.** Rejected because isolation,
   network/process/filesystem enforcement, credential injection, and runtime
   portability are a distinct product boundary already addressed by
   OpenShell and other runtimes.
5. **Adopt OpenShell or NemoClaw as the Cortxt core.** Rejected because their
   sandbox and agent-lifecycle semantics do not own Cortxt's outcome,
   acceptance criteria, cross-run evidence, or reserved human decisions and
   would weaken provider/runtime neutrality.
6. **Use "human mandate" only as messaging while retaining the existing UI
   hierarchy.** Rejected because the claim would remain governance language
   rather than an observable product behavior.

## Validation

- [ ] One real Workstream is created with approved outcome, acceptance
      criteria, mandate, budget, provider policy, and reserved human decisions.
- [ ] Its first Run is interrupted, blocked by policy, or otherwise made
      unable to continue through its original execution path.
- [ ] A fresh Run resumes the same Workstream using a different engine,
      provider, or secure execution backend without overwriting the earlier
      run or redefining the mandate.
- [ ] Previously accepted evidence remains attributable and reusable while
      incomplete or conflicting evidence remains visible.
- [ ] The work reaches independent review and an explicit human decision gate.
- [ ] The complete journey is inspectable through the existing CLI/MCP
      contracts and one thin work-first projection.
- [ ] A bounded OpenShell spike documents the mapping and non-mapping between
      Cortxt data-class/provider policy and OpenShell sandbox policy before an
      adapter is approved.
- [ ] User testing can distinguish Cortxt from an agent workspace and a secure
      sandbox after a short product introduction without relying on the term
      "control plane."

## Expiry/Review Trigger

- Review by: 2026-11-26.
- Trigger: completion of the continuity proof; approval of a broad web/admin
  surface; an OpenShell adapter proposal; evidence that users primarily need
  a cockpit rather than durable work continuity; or a change to ADR-015,
  ADR-021, ADR-024, ADR-032, or ADR-038 that conflicts with this boundary.

