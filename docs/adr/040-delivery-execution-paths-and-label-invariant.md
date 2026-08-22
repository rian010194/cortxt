# ADR-040: Delivery execution paths and workflow-label invariant

**Status:** Proposed
**Date:** 2026-08-22
**Deciders:** Rikard Andersson (operator acceptance pending)
**Technical Story:** issues #259-#262 (coordinator-direct builds); operator question 2026-08-22; see also #257 (fast fix) and #265 (docs materialization)

## Context

ADR-018 designates `workflow:*` labels as the single workflow-state carrier,
and the dispatch contract documents one canonical execution path (dispatcher
claim -> runtime build -> review -> done). During the widget-platform build
(#259-#262) the coordinator built directly on feature branches and merged via
pull requests, but the issues' `workflow:*` labels were not advanced, leaving
them at `workflow:inbox` after their work had already merged. The repo already
contains legitimate non-dispatched deliveries: coordinator-direct "fast fix"
builds (#257) and docs-only ADR materialization (#265).

The gap is not that more than one way of executing work exists — it is that
the alternatives are undocumented and the label state is not kept in sync by
them.

## Decision

Three delivery execution paths are sanctioned. All preserve ADR-018 as the
single state carrier.

1. **Dispatched runtime build** — the full claim lifecycle
   (`ready -> in-progress -> review -> done`) per the dispatch contract.
2. **Coordinator-direct build** (fast fix) — feature branch plus pull
   request; the pull request's CI plus the operator merge are the review and
   approval gate; the issue marks work started and completes at merge.
3. **Docs/ADR materialization** — no code; feature branch plus pull request
   plus operator merge; the issue moves to done in step with the merge.

**Label invariant (hard rule):** an open issue whose delivery pull request
merges must never remain at `workflow:inbox`. It moves to `workflow:done` at
merge time via the state its path prescribes.

The Atlas `Work kind` field (`delivery` / `fast-fix` / `docs` / `research` /
`decision`) records the kind for rendering only, never as a second state
carrier. The execution map (ADR-039) pre-flight is required for parallel
dispatched runs; the sequential coordinator-direct and docs paths may omit it,
but must still record state so `cortxt work plan` and the candidates widget
observe reality.

## Consequences

### Positive

- Merged work is always reflected in workflow state, regardless of path.
- Lightweight paths (fast fix, docs) are first-class rather than ad-hoc.

### Negative

- Coordinator-direct and docs paths must remember to advance labels at merge
  (a future launcher or CI check can enforce this).

### Risks

- The label invariant could drift again unless enforced by tooling rather than
  memory.

## Alternatives Considered

1. Keep only the dispatched path — rejected: forces full dispatch ceremony on
   docs and one-file fixes.
2. Leave the direct path undocumented/ad-hoc — rejected: that is what caused
   the observed label drift.
3. Drop `workflow:*` for coordinator-direct work — rejected: ADR-018 remains
   the single state carrier.

## Validation

- [ ] `dispatch-contract.md` documents the three paths and the label invariant.
- [ ] Subsequent coordinator-direct and docs deliveries advance labels at merge.

## Open Questions

- Should a CI or launcher check enforce the label invariant automatically
  (reject a merged PR whose issue is still `workflow:inbox`)?

## Expiry/Review Trigger

- Review by: 2026-11-22, or on the next coordinator-direct delivery that
  forgets to advance labels.