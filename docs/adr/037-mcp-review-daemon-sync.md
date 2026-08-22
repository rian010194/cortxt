# ADR-037: MCP review submission daemon synchronization

**Status:** Accepted
**Date:** 2026-08-22
**Deciders:** Rikard Andersson (operator acceptance 2026-08-22)
**Technical Story:** issue #249; live acceptance proof issue #252

## Context

ADR-034 Q5 left `run.review_submitted` events as inert local state because no daemon consumer existed. Issue #247 dogfood proof produced real submissions and observed that gap. The run store already carries `review_submission_id` and the `session.created` issue identifier, so consumption requires no schema change.

## Decision

Add a daemon review-sync pass that derives the GitHub issue from `session.created.issue_id` and mechanically swaps its current `workflow:*` label or labels to `workflow:review`. It runs before dispatch in each daemon iteration and on demand through `cortxt daemon sync-review`.

The pass records successfully transitioned submission identifiers in an atomically replaced `review_sync.json` marker. A marked submission is not transitioned again. A crash after GitHub succeeds but before marker persistence causes a retry that observes the idempotent GitHub state. Closed issues and issues labeled `workflow:done` are never reopened or downgraded; issues already at `workflow:review` are skipped. This closes ADR-034 Q5 without changing the session schema.

The pass performs only the mechanical label transition. It does not approve, merge, close, or grant review authority.

## Consequences

### Positive

- Durable review submissions now reach the established GitHub workflow state from both continuous and operator-triggered paths.
- Atomic dedupe markers avoid duplicate transitions during normal single-process operation.
- Exactly-one-workflow-label discipline from ADR-018 is preserved.

### Negative

- GitHub CLI availability and credentials are required at synchronization time.
- A crash window can cause a harmless repeated observation or label command.

### Risks

- The run store and marker remain single-process-safe only.
- Label changes outside the pass can race its view/edit sequence.
- This mechanism is not an approval authority and must not evolve into one implicitly.

## Alternatives Considered

1. Add `workflow:review` without removing the current workflow label - rejected because it violates ADR-018 discipline.
2. Omit deduplication - rejected because normal daemon polling would repeat transitions.
3. Keep operator-only manual transition - rejected because it preserves the inert-state gap this decision closes.

## Validation

- [x] AC1-AC5: event discovery, issue derivation, transition, atomic dedupe, safe skips, and content-free reporting are implemented.
- [x] AC6: daemon ordering, failure isolation, and status counts are implemented and tested.
- [x] AC7: the one-shot CLI command returns content-free counts.
- [x] AC8: network-free boundary tests use a fake run store, GitHub runner, and fixed clock.
- [x] AC9: ADR index and architecture review log are updated; ADR-034 Q5 is closed here.
- [x] AC10: focused and full regression suites plus repository hygiene checks are required before handoff.
- [x] Issue #252 live arm: a real GitHub fixture issue was transitioned to `workflow:review` through the real daemon review-sync pass with the real `gh` CLI, covered by network-free pytest.

## Open Questions

- Multi-process locking for shared stores and marker files.
- Daemon consumption beyond review synchronization.
- Budget reservation reconciliation against measured cost.

## Expiry/Review Trigger

- Review by: 2026-11-22, or on first real use against a live submission.
- Trigger: a second server process shares the store, or the pass must do more than the mechanical `workflow:review` transition.
