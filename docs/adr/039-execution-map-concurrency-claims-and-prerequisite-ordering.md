# ADR-039: Execution Map Concurrency Claims and Prerequisite Ordering

**Status:** Accepted
**Date:** 2026-08-22
**Deciders:** Rikard Andersson (operator acceptance 2026-08-22)
**Technical Story:** issue #251 (widget platform design), issue #265 (materialization); source: `lab/widget-platform/track-c-execution-map.md` + `synthesis.md` §2/§5 (ADR number resolved from the provisional ADR-038 to ADR-039 per synthesis §2)

## Context

The operator wants to run several approved candidates in parallel without
colliding and in the right order. Today the parallel-dispatcher workflow
(issue #257) gives each build an isolated git worktree, but dispatch
authority and ordering are still sequential and single-process: the
dispatcher's `Dispatcher.claim` is an in-memory/single-process guard,
`cortxt work` and the daemon and the MCP lifecycle tools mutate overlapping
stores (RunRegistry, `claimed.json`, session_state, labels, branches,
worktrees), and ADR-018/032/034/037 explicitly limit the current stores to
single-process safety. Nothing proves that two concurrent launches touch
disjoint resources, and nothing enforces prerequisite order (an issue
blocked by an unfinished prerequisite could be launched).

Track C of the widget-platform design defines the execution map: a
deterministic, fail-closed layer that derives prerequisite order from the
durable GitHub issue record, inventories every collision identity, and
performs pre-flight validation before any launch side effect. This ADR
locks the execution-map concurrency and ordering model, leaving the
specific durable multi-writer store and the implementation to the
operator-approved build (issue #261).

## Decision

### 1. Collision model by canonical resource key

Every active attempt publishes the complete set of resources it claims. A
new attempt is rejected if any exclusive key intersects an unexpired
active claim. The exact collision resources: issue
(`owner/repo#number`), run identity (`run_id`, model-external, globally
unique within the configured state domain), branch (`work/<run_id>`),
normalized worktree path (`.worktrees/<run_id>`), durable session-state
identity (store session id), opaque engine `session_id`, and the one
`workflow:*` label on an open work issue.

`run_id`, store session id, and engine `session_id` remain distinct
identities and may never be substituted for another. Concurrent edits to
the same workflow label collide when expected prior state or intended next
state differs; an issue with zero or multiple `workflow:*` labels is drift
and fails pre-flight.

The writer collision set includes every process sharing any of these
resources: `Dispatcher`/`cortxt work`, the daemon (claims, branches,
worktrees, ADR-037 review sync), MCP lifecycle tools (nonce/budget, durable
run/session store), and the coordinator. Atomic file replacement prevents
torn files but is not a cross-process conditional claim; GitHub label plus
comment mutation is not a distributed transaction. Parallel writers
against one state directory are unsafe until a shared multi-writer claim
mechanism exists. The map reports this as `shared_store_writer_conflict`
and fails closed rather than inferring serialization.

Collision policy is conservative: read-only observers may run
concurrently; exactly one designated driver may mutate a given
claim/store domain under current storage limits; independent runs execute
in parallel only after disjoint exclusive claims are durably established;
unknown ownership, malformed records, stale-but-unresolved claims, or an
unavailable store are collisions for launch purposes; existing resources
are never deleted or adopted automatically during validation.

### 2. Prerequisite ordering from the durable issue record

The map derives a directed graph from the durable GitHub issue record
using the Atlas relation contract — never from rendered Atlas prose.
Containment: `Part of: #<parent>` (+ native sub-issue data when
available); at most one immediate parent; containment groups but never
creates prerequisite authority. Prerequisites: `Blocked by: #<prereq>`
on the blocked issue; `Depends on:` is a legacy read alias with identical
meaning; native/text representations of the same edge are deduplicated
retaining source evidence.

Drift codes: `missing_target`, `self_edge`, `duplicate_edge`,
`containment_cycle`, `prerequisite_cycle`, `multiple_parents`,
`native_text_parent_mismatch`, `cross_repo_target`,
`missing_area_or_milestone`, `workflow_label_cardinality`. Cycles report a
deterministic witness path starting at the lowest canonical issue id;
drift output is stable-sorted by code, issue id, edge kind, and target.
Fatal ordering drift (self-edge, prerequisite cycle, missing prerequisite
target, ambiguous prerequisite identity) makes affected nodes
non-launchable without mutating source data.

A blocker is satisfied only when its issue is closed or carries
`workflow:done`; `workflow:ready`/`in-progress`/`review`/`blocked`,
missing-label, and multi-label blockers remain unsatisfied. The gate is
checked at plan time, claim time, and immediately before launch. The
workflow-label sequence (`workflow:ready -> in-progress -> review ->
done`) is the ordering skeleton; the map never skips, reverses, or
synthesizes a transition.

Topological ordering uses canonical issue id as the deterministic
tie-breaker; nodes with no unsatisfied prerequisites form a parallel wave;
later waves become eligible only when all incoming prerequisites are
satisfied in a fresh durable snapshot. Wave number is descriptive and
grants no claim priority or authority.

### 3. Durable conditional claims and pre-flight receipts

A claim record represents one issue and one workflow attempt:
`claim_version`, `claim_id`, `issue_id`, `workflow`, `run_id`,
`branch_ref`, `worktree_path`, `store_session_id`, `engine_id`,
`engine_session_id`, `driver_id`, `state`, `acquired_at`, `heartbeat_at`,
`lease_expires_at`, `released_at`, `release_reason`,
`expected_workflow_label`, `claim_generation`. `engine_session_id` may
initially be null and binds once the engine returns it, conditionally on
the same active `claim_id`/`run_id`/generation. One active claim per
issue/run; each exclusive resource is unique across active claims.

Pre-flight validation occurs before branch creation, worktree creation,
label mutation, adapter invocation, or MCP engine invocation, and is
distinct from the in-memory `Dispatcher.claim` guard — the launcher must
pass BOTH the execution-map gate and the dispatch-contract claim. The
pre-flight sequence: parse/validate canonical issue id and approved
dispatch request; verify open + exactly `workflow:ready` + not
`atlas:map`; verify every prerequisite closed or `workflow:done`; reject
fatal relation drift; allocate a unique model-external `run_id` without
creating resources; derive branch/worktree keys; read active claims,
dispatcher registry, daemon claims, Git worktrees/refs, lifecycle sessions
through injected ports; reject every collision; verify the designated
driver is the only writer per single-process-safe store domain;
conditionally acquire the durable claim with an expected store generation;
re-read the issue label immediately before the authorized claim
transition; return a content-free validation receipt binding snapshot
fingerprint, claim id, run id, expiry, and decision.

A successful receipt is short-lived, single-use, and invalidated when the
issue or claim generation changes before launch. A receipt is evidence
that collision and order checks passed; it is not approval and cannot
invoke an executor.

Claim lifecycle `acquire -> hold -> release`: acquire is an all-or-nothing
conditional insert for every resource key; hold covers setup, execution,
resume eligibility, result submission, and any bounded review-handoff
period chosen by policy; heartbeats extend the lease only for the same
driver, claim id, and generation; normal release occurs after a terminal
run record is durable and no resume/resource mutation is pending; release
records a reason and retains immutable history.

On process crash the claim remains held until lease expiry — no second run
may adopt it merely because a process is absent. After expiry the claim
becomes `expired_pending_reconciliation`, not immediately free.
Reconciliation checks the issue label, dispatcher registry, durable
session, engine status if injectable, Git branch, and Git worktree. Only
an operator-approved or policy-authorized recovery may mark it released or
renew it for the same run. Retry after release uses a new `run_id` and
claim record. Ambiguous recovery fails closed and reports the exact
residual resources.

### 4. Driver/observer separation and authority boundary

The launcher (`cortxt work`) and the coordinator are DRIVERS — the sole
initial mutation driver is the coordinator through registered `cortxt
work` services. Atlas and widgets are OBSERVERS of the same read-only
projection and never become claim drivers. The execution map observes
review submissions, sync state, and workflow labels but does not duplicate
ADR-037 label writes; if the daemon and another label writer are active
over the same store/issue, pre-flight reports a writer collision.
ADR-037 review sync remains the sole mechanical review transition and runs
before candidate evaluation; it never approves, merges, closes, or moves
an issue to `workflow:done`.

Graph position and frontier/wave membership NEVER grant dispatch
authority. Eligibility is derived only; approved immutable scope,
acceptance criteria, role, limits, artifact policy, approval reference,
applicable mandate, and a successful authoritative claim remain required
under the dispatch contract. A map receipt is a gate, not approval or
execution authority.

### 5. Storage boundary

Current JSON stores and process-local guards do not qualify as
multi-process coordination. The durable multi-writer claim store and lock
scope are an explicit operator decision (no silent default) because they
fix deployment and recovery semantics; the ADR recommends, not silently
chooses, the database, file-lock, or service implementation.

## Consequences

### Positive

- Safe parallel dispatch: two approved disjoint issues can execute
  concurrently only after exclusive claims; overlapping resources yield
  one launch and one deterministic rejection.
- Prerequisite order is enforced before launch; blocked work cannot start
  before its blockers are closed/done.
- The candidates widget (Track B) and any map view share one read-only
  projection; the widget never gains dispatch authority.

### Negative

- A durable multi-writer claim store must be selected, built, and proven
  (crash-recovery semantics) before parallel drivers are enabled
  (build #261).
- Pre-flight adds a validation step before every launch; the launcher must
  pass both the map gate and the dispatch-contract claim.
- Lease/reconciliation state adds operational surface (expiry, recovery
  policy).

### Risks

- A claim-store bug could silently allow a collision — mitigated by
  all-or-nothing conditional acquisition and multi-process tests before
  parallel drivers are enabled.
- Recovery ambiguity could strand resources — mitigated by
  `expired_pending_reconciliation` and operator-only release.
- Over-generalizing the map before real parallel evidence exists (the
  vertical-package-contract caution applies).

## Alternatives Considered

1. **Keep the single-process dispatcher guard only** — rejected: it cannot
   coordinate concurrent daemon/MCP/coordinator writers over the same
   stores and cannot enforce prerequisite order.
2. **File-lock or JSON-append claims as the durable store** — rejected as
   insufficient for cross-process conditional uniqueness (ADR-018/032/034/
   037 single-process limitation); the store choice is an explicit
   operator decision, not a silent pick.
3. **Graph position grants dispatch authority** — rejected: eligibility is
   never authorization; the dispatch contract and mandate/approval remain
   the sole authority.
4. **The widget/Atlas as drivers** — rejected: driver/observer separation
   keeps mutation in registered `cortxt work`/coordinator surfaces.

## Validation

- [ ] Implementation matches decision (build issue #261 after ADR-039
      acceptance + store choice).
- [ ] Tests cover decision boundaries (track-c AC1-AC30 draft): graph
      derivation/drift, topological waves, collision normalization,
      all-or-nothing acquisition, receipt binding/invalidation, lease
      expiry/reconciliation, `shared_store_writer_conflict`, multi-process
      uniqueness/crash recovery.
- [ ] Documentation updated (this ADR; index; review log).

## Open Questions

- Which durable multi-writer claim store and lock scope are approved
  (track-c Q1)? No silent default.
- What lease, heartbeat, and review-handoff durations apply (track-c Q2)?
- May valid graph components launch when unrelated components contain
  drift (track-c Q3)?
- Which component is the sole initial mutation driver (track-c Q5)?

## Expiry/Review Trigger

- Review by: 2026-11-22, or on the first real parallel dispatch of two
  approved disjoint issues, whichever comes first.
- Trigger: a second MCP server process shares the same state directory; a
  widget or map view needs to invoke execution; or the operator selects a
  durable multi-writer store and enables parallel drivers.
