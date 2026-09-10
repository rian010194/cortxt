# Goal operating model

Status: target state, not current reality
Authority: synthesis of Accepted ADRs and operator direction; it creates no
decision and accepts no ADR
Last reconciled: 2026-09-10

## What this file is for

[`current-operating-model.md`](current-operating-model.md) describes what is
supported now. This file describes the **stable direction**: the shape of the
thing when it works. It is not a schedule, not a commitment with dates, and not
a delivery ledger. Where it says something the ADRs do not, that is an open
question, not a decision made by writing it down.

Update this file when a decision changes the destination — not when a work item
moves. For navigation, see [`../README.md`](../README.md).

## Destination

The operator creates, steers, resumes and verifies durable work while retaining
ownership of mandate, state, memory, tools and evidence. Agent harnesses, models
and inference providers are replaceable execution resources behind Cortxt-owned
ports and contracts (ADR-014/016/042). Cortxt OS is the general shell; Work is
its first principal app (ADR-044). The CLI and the MCP surface expose the same
authority to their respective consumers.

Coding, research, analysis and compliance exist as versioned domain **profiles**
over one shared core — not four products, and not a boundary the platform is
defined by (ADR-014 non-goal 3). Cortxt does not train a foundation model, does
not compete as an inference provider, and is not defined by any one profile's
domain. (This is the *vertical* sense of "profile"; the *runtime configuration
profile* and the *execution policy profile* below are different objects — see
[`../../CONTEXT.md`](../../CONTEXT.md).)

## Surfaces and the control-plane boundary

Direction, not a description of what ships today. What already rests on Accepted
ADRs is marked; the rest is an open decision (Proposed **ADR-047**), not a
commitment made by writing it here.

- **One shared operation contract.** The CLI, the MCP surface and Cortxt OS
  invoke the *same* operations with the *same* mandate and approval checks. That
  is what "surface parity" means — a common contract and common controls, **not**
  that every surface exposes every feature at the same time. The CLI stays the
  most complete surface; a thin OS flow is kept deliberately so a real user can
  verify the journey end to end. *(Accepted basis: ADR-024/032/041 for the MCP
  surface, ADR-042/044 for OS and Work, ADR-038 for the widget/action-port
  contract. The single-contract requirement across all three surfaces is the new
  part.)*
- **MCP is not a shortcut past human approval.** The external surface carries the
  mandate envelope (ADR-032) and the same operator gate over irreversible
  effects; it never has a path that a human sign-off does not also govern.
  *(Accepted basis: ADR-032/034/037.)*
- **The deterministic control plane owns authority.** Mandate, policy, run
  identity, budget and evidence stay in Cortxt's deterministic control plane
  (GitHub Issues + `workflow:*` state per ADR-018; dispatch contract; Evidence
  Gate). *(Accepted basis: ADR-018/040 and the dispatch contract.)*
- **A coordinator agent is optional.** A future orchestrating agent may help the
  operator break work down and follow it through the OS. It is engaged per work
  need, **never mandatorily per runtime**, and holds no platform authority.
  *(New: ADR-047 Proposed.)*
- **Native runtime delegation must be qualified.** A runtime's own child
  delegation is a separate capability to qualify before use — parent/child
  identity correlation, queryable status, inherited-or-stricter rights, aggregate
  budget accounting, cancellation, and complete child evidence — and never
  bypasses Cortxt's controls. *(New: ADR-047 Proposed; consistent with ADR-039
  execution-map claims.)*

## Runtimes, adapters and profiles

Direction. Today's implementation and its limits are in
[`current-operating-model.md`](current-operating-model.md); the two must not be
read as the same thing.

- **One engine adapter per runtime**, against the shared Cortxt contracts.
  Several profiles may drive one adapter. **Hermes is the first runtime whose
  adapter/wrapper support is taken to completion.** Codex, GitHub Copilot, Claude
  Code, Deepseek Harness and Pi are the other current candidates behind the same
  contracts. Naming a runtime here confers no integration, reliability or paid
  authorization, and **no runtime and no model holds a permanent role** as
  planner, builder or reviewer — earlier session-specific choices (a Claude
  coordinator, Copilot review) are history, not product roles. *(Accepted basis:
  ADR-019 permanent multi-engine routing, ADR-022 capability manifest + `route()`,
  ADR-026/027 adapter registry separate from selection.)*
- **Cortxt starts the right Hermes profile explicitly.** There are, per the
  operator, 12 named Hermes profiles plus `default`. `default` must be able to
  delegate to the right profile **without needing a model call**. Profile
  selection, effective rights, model/provider route, fallback chain and cost
  limits are handled consistently, bound into the approval digest (ADR-046
  mechanism) and checked against run evidence.
- **A profile name is not an immutable configuration.** The execution-relevant
  fields a profile resolves to (model, provider, base URL, API mode, fallback)
  can change between preview, confirm and start. The direction binds those fields
  to the confirmed revision and refuses a start whose profile changed since
  approval; a profile that cannot be pinned to the approved route refuses rather
  than runs unpinned.
- **"Execution policy profile" (ADR-045) is a different object** from a runtime
  configuration profile. ADR-045 (Proposed, issue #495 in review) governs
  permitted effects, isolation, artifact scope and the evidence contract. A
  Hermes configuration profile is a concrete model/provider/toolset config the
  platform *selects and starts*. Tool rights and delegation limits belong to the
  ADR-045 domain, not to the profile-route revision.
- **Hermes's own implementation study is separate.** A local Hermes-side
  investigation of profile-driven dispatch exists; its not-yet-confirmed
  conclusions (an init-time fallback hypothesis, a CLI override hypothesis) are
  not adopted here as fact. The `dispatch.request.v1` vs `v2` question — the live
  confirm/launch path still reads v1 while ADR-046 decided v2, and a W13 evidence
  note claims a v2 digest bound model/provider — is recorded as **UNRESOLVED**
  pending a source-attributed re-derivation.

## What stays true at every milestone

- A durable issue record holds scope, evidence and approval. Today that is
  GitHub Issues with `workflow:*` as the state carrier (ADR-018); Atlas maps and
  runtime queues stay derived views or execution ledgers. Changing that
  authority requires its own explicit decision.
- The operator retains mandate over irreversible decisions. Broader autonomy is
  about routine throughput, never about removing the human from consequential
  decisions.
- No worker approves, merges, deploys, publishes or closes its own work.
- Provider neutrality and data-class gating are load-bearing: no profile,
  however mature, bypasses the assurance gate InferencePort enforces (ADR-016).

## How work should flow

1. The operator states the outcome and its constraints. Preparation resolves
   scope, acceptance criteria, dependencies, permitted effects, evidence and
   budget into an approved mandate. A `workflow:ready` label alone never
   authorizes execution.
2. Cortxt selects an eligible combination of harness, model, context and tools
   for a coherent work unit, respecting the mandate and demonstrated suitability
   for the task — not token price alone.
3. Workers execute and verify their units in the permitted workspace.
   Independent units may run in parallel when authorized; dependent units get
   explicit handoffs carrying artifact references, open questions and evidence.
4. Mechanical checks, status collection and result correlation run without a
   premium model interpreting every routine event. Agents are engaged at useful
   boundaries: execution, a concrete blocker, a decision, or review.
5. Evidence and any required independent review establish whether the result
   satisfies the mandate. A retry or reassignment preserves prior Run evidence,
   stays within approved limits, and never silently changes the allowed route.
6. The operator approves merge, publication, deployment and final completion.

## What a cost-effective combination means

The objective is **accepted delivery at the lowest total cost** under the
operator's quality, time and policy constraints — not the cheapest model first.
A more capable, more expensive model is the right choice when it avoids rework
or reduces review effort. No harness or model holds a permanent role as planner,
implementer or reviewer by brand.

Evaluate the whole delivery: provider charges, subscription quota consumption,
latency, operator attention, coordination, retries and review effort. These stay
separate measurements and constraints rather than one fabricated figure, and
unknown cost or missing provenance stays explicit. Quality and evidence gates
are constraints, not something traded for a lower price.

Build evidence for **task shape x harness x model x verification approach**, and
compare accepted outcomes and failure modes including handoff overhead. A strong
model may own a difficult unit end to end while another combination handles a
well-specified change more efficiently. A separate reviewer is warranted by risk
or the approved workflow — not as automatic duplicate processing of every task
by every available agent.

Claude Code, Codex, Hermes, DSH and possible additions such as Copilot are
candidates behind contracts. Naming one here establishes no integration,
reliability or authorization to call a paid provider. Routing and fallback must
never silently consume a different subscription or cost route.

The scoring method, telemetry coverage, retry thresholds and the degree of
automatic selection remain open design questions. Nothing here claims that a
learned cost optimizer or a seamless cross-harness session transfer exists.
Portable work context and evidence are not portable hidden reasoning or native
runtime session formats.

## Stages between here and there

The current operator-designated plan establishes the practical foundations. The
sequencing below reflects the operator's 2026-09-10 direction: finish the narrow
live proof, then the shared operations and explicit profile selection, before
broader OS build-out.

1. **Finish the narrow Milestone A live proof (W13 / #547).** One real
   already-approved Issue carried through OS -> WorkLauncher -> Dispatcher on a
   live host, with the remaining acceptance rows evidenced. Nothing below is a
   prerequisite for it, and the execution-policy-profile decision (#495) must not
   become a gate in front of it.
2. **Shared operations and explicit profile selection.** A shared profile
   resolver and start operation the CLI, MCP and OS all use; the profile's
   execution-relevant route bound to the approval digest; `default` delegating
   without a model call. Delivered as bounded, separately-approved steps
   (issue draft: "select and start an approved Hermes profile directly"),
   informed by but not equal to ADR-045 / #495.
3. **Milestone B — originate, prepare and approve new mandates in the OS
   (#501).** Sequenced after step 1; explicitly not a prerequisite for it.
4. **Broader OS build-out** — the typed renderer / app-manifest and TypeScript
   foundation work (ADR-046 frontend; #503/#504) and cross-engine continuity
   (S8; #477–#481).
5. **W14** — a deferred item whose original scope could not be recovered from
   any tracked source. It stays recorded as unresolved; its contents are not
   invented.
6. **W15 — Supervisor Daemon dispatch adaptation.** Deferred outside Milestone A.
   It reuses the same approved-mandate -> configuration digest -> claim ->
   isolated Run -> Evidence Gate -> review chain and the profile materialization
   from step 2. Required review-sync stays in scope throughout; finishing
   Milestone A does not imply unattended orchestration.

Supporting contracts that each still need their own decision and budget: a common
versioned worker instruction/result contract with usage/cost capture from the
route that already reports it; binding an approval to the actual execution
configuration (ADR-046, Accepted); charge-policy route eligibility (#548).

Once the relevant contract and launch path are verified, bounded comparisons of
harness/model combinations can inform routing without waiting for every deferred
feature. A new adapter needs evidence for isolation, limits, cancellation,
result correlation and failure behavior — not only useful output.

ADR-015's validation criteria (T1-T5), provider and data-class assurance, and
cross-user validation keep their own acceptance requirements. OS delivery does
not declare them met.

## Open question: the wedge after B

ADR-015 names compliance and gap analysis (wedge C, via proof environment B) as
"a natural second step", but this is explicitly **not decided**. The next wedge
follows from what T1-T5 actually prove, not from a pre-commitment here. Do not
treat wedge C as roadmap until a new ADR says so.

## Relationship to authority

- [`current-operating-model.md`](current-operating-model.md) — what is supported
  now. Where the two files disagree about the present, that file wins; this one
  speaks only about the destination.
- Accepted ADRs — normative, including 014-018, 040, 042, 043 and 044. Where
  this file and an ADR conflict, the ADR is authoritative and this file is wrong
  and should be fixed.
- **ADR-045 is Proposed**, not Accepted. Neither it nor any profile or
  confirmation design becomes accepted by being described here as a goal.
- **ADR-047 is Proposed**, not Accepted. The surface operation-contract parity
  and the control-plane / coordinator-agent boundary described above are a
  direction awaiting that decision, not a settled one.
- The operator-designated plan and subsequent issue evidence determine
  implementation sequencing — not a stale status table and not this file.
