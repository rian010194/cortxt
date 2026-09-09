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

Coding, research, analysis and compliance exist as versioned **profiles** over
one shared core — not four products, and not a boundary the platform is defined
by (ADR-014 non-goal 3). Cortxt does not train a foundation model, does not
compete as an inference provider, and is not defined by any one profile's domain.

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

The current operator-designated plan establishes the practical foundations:

- **Milestone A** — start, follow, review and retry already-approved work
  through OS -> WorkLauncher -> Dispatcher, verified by a scoped live acceptance
  proof.
- **Milestone B** — originate, prepare and approve new mandates in the OS.
- A common versioned worker instruction/result contract, and usage/cost capture
  from the route that already reports it, make execution comparable and
  diagnosable.
- Binding an approval to the actual execution configuration, and charge-policy
  route eligibility, each require their own contract and budget decisions.
- Daemon adaptation is deferred outside Milestone A. Required review-sync
  remains in scope. Finishing Milestone A does not imply unattended
  orchestration.

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
- The operator-designated plan and subsequent issue evidence determine
  implementation sequencing — not a stale status table and not this file.
