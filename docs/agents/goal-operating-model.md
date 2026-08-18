# Goal operating model

Status: target state, not current reality
Authority: describes the destination defined by ADR-014/015; does not itself
create or override decisions
Last reconciled: 2026-08-15

## Why this file exists

`current-operating-model.md` describes what is verified today. The accepted
ADRs (014, 015, 016, 017, 018) each decide one bounded question — vision,
wedge, bounded context, reasoning acceptance, workflow-state carrier — but no
single file reads as "what does it look like when this works." This file is
that synthesis. It creates no new authority: where it says something the
ADRs do not, that is marked explicitly as open, not decided by writing it
here.

Update this file when an ADR changes the destination. Do not treat it as a
schedule or a commitment with dates — it describes shape, not timing.

## Milestone 1 — F1: Wedge B validated

The nearer milestone. Reached when the validation plan in ADR-015 (T1–T5) is
complete: Rikard uses it, a second developer uses it, it generalizes beyond
proof environment B, it demonstrates provider neutrality, and provider assurance is
verified for the data classes it actually handles.

**What the product does:** delivers a provider-/data-class-governed,
long-running research and analysis session as an auditable capability —
resumable, evidenced, verified — through a repository-native + CLI surface.
Not a chat window and not a revived Operator Cockpit/web surface (ADR-015
premise 11).

**How work flows at this point:**

- The operator states intent in natural language; the coordinator turns it
  into a scoped GitHub issue with acceptance criteria and budget, same as
  today (`current-operating-model.md`).
- The difference from today: once an issue is `workflow:ready`, agents
  dispatch, run, and move work through review themselves. The operator is
  not asked to approve each individual step.
- The operator is pulled back in only when a decision is irreversible (push
  to main, deploy, delete data), the cost crosses an explicit threshold, or
  policy requires an explicit gate (a data-class boundary, a provider not yet
  assured for the material in question). This matches the escalation
  boundaries AGENTS.md already states as control-plane rules — the goal
  state does not loosen them, it just means routine work no longer needs a
  human in the loop to reach them.
- No agent approves its own work, merges, deploys, publishes, or closes its
  own issue. That constraint holds at every milestone, not just today's.

**Evidence that this milestone is real, not aspirational:** T1–T5 passing,
each with recorded evidence in its GitHub issue — not a demo, not a single
successful run.

## Milestone 2 — F0: the full vision realized

The longer-horizon milestone. Cortxt is a provider-neutral platform on which
the user (or organization) owns the working capability's state, reasoning,
memory, tools, evidence, and evolution. Models, inference providers, and
external agent engines are replaceable resources behind Cortxt-owned ports
and contracts, not the product itself.

Coding, research, analysis, and compliance exist as versioned **profiles**
on top of one shared core — not four separate products, and not a boundary
the platform is defined by (ADR-014 non-goal 3). Wedge B (Milestone 1) is
the first proof of that core; later profiles reuse it rather than
reimplementing owned state, reasoning, and evidence per domain.

**What stays true at this milestone, not just at Milestone 1:**

- GitHub Issues (or their successor durable record) remain the source of
  truth for scope, evidence, and approval — Cortxt does not invent a second
  backlog to feel more like a platform.
- The operator retains mandate over irreversible decisions. Broader
  autonomy at Milestone 1 is about routine throughput, not about removing
  the human from consequential decisions at any milestone.
- Provider neutrality and data-class gating are load-bearing, not
  aspirational: no profile, however mature, gets to bypass the assurance
  gate InferencePort enforces (ADR-016).

**What this milestone explicitly is not** (ADR-014 non-goals, not repeated
here — see that ADR): Cortxt does not train its own foundation model, does
not compete as a GPU marketplace or inference provider, and is not defined
by any single profile's problem domain.

## Open question: the wedge after B

ADR-015 names compliance/gap-analysis (wedge C, via proof environment B) as "a
natural second step," but this is explicitly **not decided**. The next
wedge is chosen by what T1–T5 actually prove about Milestone 1, not
pre-committed now. Do not treat wedge C as roadmap until a new ADR says so.

## Relationship to other documents

- **`current-operating-model.md`** — today's verified reality. Where the two
  files disagree about what is true *now*, that file wins; this file only
  speaks about the target.
- **ADR-014 / ADR-015** — the decisions this file synthesizes. Where this
  file and an ADR conflict, the ADR is authoritative and this file is wrong
  and should be fixed.
- **ADR-016 / ADR-017 / ADR-018** — the architectural decisions (bounded
  context, reasoning acceptance, workflow-state carrier) that Milestone 1
  and 2 depend on operationally.
