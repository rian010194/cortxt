# ADR-050: Work-record domain authority — the thinking lives in Core, before any repository or issue

**Status:** Proposal
**Date:** 2026-09-16
**Deciders:** Rikard (operator), Claude (draft)
**Extends:** ADR-048 (same boundary, second domain). ADR-018, ADR-040 and ADR-045 unchanged.
**Technical Story:** B1.3 of the dialogue-to-result series
(`docs/plans/2026-09-16-dialogue-to-result-series-handoff.md`).

## Context

The dialogue-to-result series makes dialogue the entry point to Cortxt. A conversation must be
able to start from a loose idea, produce something the operator can read and revise, and survive
being closed and reopened — **before any repository is chosen and before any GitHub issue
exists.** Analysis or a plan may be the finished result, with no code change at all.

That artefact — observations, proposals, open questions, goals, limits, acceptance criteria — has
no home today.

### What already exists, verified at `f6dba33`

`CONTEXT.md` already grants the shape: *"A workstream may exist without a Git workspace for
research-only work"*, and *"Workspace … is execution metadata, not the workstream's identity."*
**The vocabulary is right; no surface implements it.** W-6's compose form takes `repository` as
its first required field (`agent-platform/widget/app-renderer-start-mission.js:200-214`), which is
the opposite of the rule.

`agent-platform/state/core_store.py` already provides exactly the storage semantics this needs,
and they are tested:

- append-only, with no update and no delete API;
- `supersedes` as a typed envelope field, validated as hex64 and **refused unless it names an
  existing record** (`:446`, `:470-472`); the superseded record stays byte-identical (`:15`);
- CONFLICT-NOT-MERGE: identity conflicts render both digests, never merged, never overwritten;
- **`issue_ref` is optional** (`validate_issue_ref -> str | None`), which is what permits a record
  with no issue at all.

ADR-048 already decided the principle for a neighbouring domain: content-bearing records are
owned by the local append-only Core store, may carry a GitHub issue id as a verbatim correlation
reference, and the store *"never syncs or reconciles with GitHub"*.

### Why a new ADR rather than reading ADR-048 broadly

ADR-048 is explicitly scoped to **product packaging**. Extending local Core authority to a second,
differently-shaped domain is a decision about where the operator's thinking lives. Silently
borrowing another domain's authority is how a boundary stops meaning anything.

## Decision

### D1 — The work record is a distinct domain owned by the local Core store

A **work record** is the content-bearing artefact a dialogue produces: observations, proposals,
open questions, goals, limits, and acceptance criteria. It is owned by a new domain layer over the
unchanged `state/core_store.py`, on ADR-048's terms: append-only, digest-keyed, supersession by a
separate appended record, and **no sync or reconciliation with GitHub, in either direction.**

`core_store.py` is not modified by this decision. It already does what is required.

### D2 — A work record exists before a repository and before an issue

Neither a repository nor a GitHub issue is required to create a work record. `issue_ref` stays
optional and is a verbatim correlation reference when present, exactly as ADR-048 point 2 states.

This is the decision that makes the product rule enforceable rather than aspirational: **work is
the starting point; a repository is a resource the work uses.** A surface that requires a
repository before a record can exist is in violation of this ADR.

### D3 — Revision is supersession, never mutation

Revising a conclusion appends a new record whose `supersedes` names the previous record's digest.
The earlier version remains readable and byte-identical, and the relation between them is visible
to the operator.

The operator must be able to see that they changed their mind, and what they changed it from.
A revision history that quietly replaces its own past is a worse record than none, because it
looks authoritative.

### D4 — Authority is split by kind, not by storage convenience

| Concern | Authority |
|---|---|
| The content of the thinking | **Work record, local Core store** (this ADR) |
| Scope, approval, `workflow:*` | GitHub Issues (ADR-018, ADR-040) — unchanged |
| Permitted effects, isolation, evidence contract | Execution policy profile (ADR-045) — unchanged |
| Run identity, status, evidence | Run registry and evidence ports — unchanged |
| Package revisions, operation/decision records | Product-packaging domain (ADR-048) — unchanged |

No concern gains a second authority. A work record may reference an issue; it never carries
workflow state, and it never becomes a second backlog.

### D5 — The work record is the fluid form; the packaging revision is the frozen form

`schemas/packaging/revision.schema.json` already carries `problem`, `outcome`, `scope`,
`audience`, `features`, `evidence_refs`, `prior_binding_refs`, a parent chain, and
`referenced_repositories` as a required array of `{repo, sha}` with a 40-hex sha.

That is a work record **frozen at the moment a mandate is prepared**, and it is deliberately
unusable earlier: during dialogue a repository is only *possibly* relevant and has no pinned
revision to give.

Preparing a mandate is therefore the transition from the fluid form to the frozen one. **Neither
schema is to be rebuilt into the other.** What the packaging revision cannot express —
permitted effects, limits, isolation, or per-repository change targets — is not added to it here;
approved change targets remain a separate, explicitly approved allowlist, because discovery and
read access never grant write access.

### D6 — A work record can be a finished result

A work record may reach a terminal state with no code change, no issue, and no Run. An analysis
or a plan is a delivery, not an incomplete step toward one.

## Consequences

**Positive.** The operator's thinking becomes durable, revisable and reviewable without a
repository decision up front. Revision history and denied-retry semantics come from mechanisms
that are already built and tested rather than new ones. The dialogue surface gains a storage
model that cannot silently lose an earlier conclusion.

**Negative.** A third durable store now exists alongside GitHub and the packaging domain.
Correlation across them is by recorded reference only, so cross-store queries stay manual until a
read view is built — the same cost ADR-048 accepted, and for the same reason.

**Risk.** A work record referencing an issue that later changes state will not update; the
reference is historical correlation, not live state. This is ADR-048's risk, inherited knowingly.

**Open, and not decided here.** The Core store declares its backup policy an OPEN point
(S4-B6 / P2-9). A work record is the operator's thinking in durable form, so where it is backed up
is a real decision, and it is the operator's.

## Alternatives considered

**Put work records in GitHub Issues.** Rejected. Issues are the authority for scope and approval,
and they handle revision badly: editing a body destroys the prior version, which contradicts D3.
It would also make a repository mandatory before thinking could be recorded, contradicting D2 and
the product rule it enforces.

**Reuse the packaging revision schema directly.** Rejected, per D5. It requires a pinned 40-hex
sha per repository, which does not exist during dialogue, and it has no field for permitted
effects or per-repository change targets.

**Extend ADR-048's scope by reinterpretation.** Rejected. ADR-048 names product packaging
explicitly. A boundary that can be widened by reading it generously is not a boundary.

**Keep work records in memory for the session.** Rejected outright: resuming work with context and
decisions intact after closing Cortxt is a stated product requirement, not an enhancement.

## Validation

- [ ] Implementation matches decision (B1.3)
- [ ] A record with no `issue_ref` and no repository can be created, read back after restart, and
      revised via `supersedes`
- [ ] A revision naming an unknown digest is refused
- [ ] Two concurrent writes to one identity yield re-delivery or conflict, never a double append
- [ ] Live browser acceptance through the operator's own entry point
