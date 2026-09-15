# ADR-048: Product-packaging domain authority — local Core store, GitHub as reference only

**Status:** Accepted (2026-09-14, operator; registered in the Swarm 5 checkpoint)
**Date:** 2026-09-15
**Deciders:** Rikard (operator; Swarm 3 decision 00:17:13Z point 4 + Swarm 5 B-1/B-8/B-9a/B-9b)
**Technical Story:** #606 (W-2a product-packaging core modules), #609 (W-2b A4b Core store)

## Context

The frozen 4a contract (§7.1 A4b / §7.2 EVP-A) makes a local, append-only, digest-keyed
Core store the authoritative home for NEW product-packaging objects: product-package
revisions, operation records, review/decision records, and evidence entries. GitHub
remains the durable source of truth for scope, workflow state and approval (ADR-018,
ADR-040): packaging records must carry an issue id as a correlation REFERENCE only —
never synced or reconciled with GitHub — and packaging decisions are `decision_records`
(frozen 4a §5.1), not `workflow:*` labels. Without a recorded boundary, the new domain
layer risks being read as either a second workflow-state carrier (forbidden by ADR-018)
or as GitHub-coupled state (forbidden by ADR-045's writer separation for evidence).

## Decision

1. The product-packaging domain layer (`agent-platform/widget_contract/product_packaging/`
   plus the A4b `agent-platform/state/core_store.py` built by #609) is the authority for
   NEW package-domain records. Append-only; supersession via separate appended records,
   never in-place mutation; identity by content digest.
2. A record MAY carry a GitHub issue id as a verbatim correlation reference. The store
   never reads back, syncs, or reconciles with GitHub, and GitHub stays the unchanged
   authority for issues and `workflow:*` labels (ADR-018, ADR-040 unchanged).
3. Packaging decisions are decision records per frozen 4a §5.1 (D5-Alt-1); they never
   mutate workflow labels.
4. Evidence records follow EVP-A (frozen 4a §7.2): writer is the evidence-output port
   only; insert-if-absent/CAS; deterministic REDELIVERY/CONFLICT/NEW-EVIDENCE-VERSION.
5. Workstream projection remains the shared Work Console view over GitHub Issues
   (ADR-018); packaging objects are a distinct domain layer under Core, referencing
   GitHub identity without replacing it.

## Consequences
### Positive
- New package domain records survive engine replacement and stay locally verifiable
  (digest-chained), without a second workflow-state source.
- The GitHub-coupling surface is explicit and minimal (reference-only), so ADR-018's
  single-carrier invariant cannot drift.
- Evidence writes stay behind the single output port (ADR-045 alignment).

### Negative
- Two durable stores now exist (GitHub + local Core); correlation is by recorded
  reference only, so cross-store queries are manual until a read view is built (W-3+).

### Risks
- A record referencing a GitHub issue that later changes state will not auto-update;
  the reference is historical correlation, not live state.

## Alternatives Considered
1. Make GitHub Issues the authority for packaging records too — Rejected: freezes the
   domain model to issue semantics and re-introduces the coupling ADR-045 removed.
2. A second GitHub Project for packaging state — Rejected: forbidden by ADR-018
   (single workflow-state carrier; Project 4 frozen legacy).

## Validation
- [x] Implementation matches decision (W-2a #606: append-only module layer; W-2b #609
      A4b store with atomic insert-if-absent, conflict-not-merge, GitHub-reference-only)
- [x] Tests cover decision boundaries (test_product_packaging_*; state/test_core_store.py)
