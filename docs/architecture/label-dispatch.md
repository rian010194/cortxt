# Label to dispatch design and read-only notice scaffold

Status: Proposed (design record, issue #330)  
Owner: coordinator  
Last updated: 2026-08-23  

## Purpose

This document specifies the future path from an inbound GitHub `workflow:ready`
label event to an authorized worker dispatch. It establishes the prerequisite
gate sequence, operator authorization requirements, execution-map validation,
and idempotency guarantees required before any worker task can be launched.

Today, worker dispatch is governed by the dispatch contract
(`docs/architecture/dispatch-contract.md`), the current operating model
(`docs/agents/current-operating-model.md`), and ADR-039 / ADR-040. Inbound label
events indicate task readiness but do not themselves grant dispatch authority.
This design defines how future webhook and event infrastructure connects GitHub
label events to the execution engine while keeping the mandatory operator gate
fully preserved.

## Trigger

The trigger source is an inbound GitHub `issues` event with action `labeled`,
where the added label is `workflow:ready`:

- **Event source**: GitHub Actions `issues` event (`types: [labeled]`) or a
  loopback webhook payload delivered to the event surface (`github.issue`
  inbound envelope per `docs/architecture/event-surface.md`).
- **Filter condition**: `label.name == 'workflow:ready'`.
- **Actor guard**: Events emitted by automated bots (`github-actions[bot]`,
  `cortxt-atlas[bot]`) are filtered out to prevent recursive trigger loops.

## Gate sequence

An incoming `workflow:ready` label event initiates verification across a
strict, fail-closed three-stage gate sequence:

```text
[ GitHub labeled event: workflow:ready ]
                 │
                 ▼
┌────────────────────────────────────────┐
│ 1. Issue Completeness Gate             │
│    - Approved scope                    │
│    - Acceptance criteria (AC)          │
│    - Runtime limits (cost, role, time) │
│    - Authoritative workflow:ready      │
└──────────────────┬─────────────────────┘
                   │ Pass
                   ▼
┌────────────────────────────────────────┐
│ 2. Execution-Map Pre-flight Gate       │
│    (ADR-039, cortxt work plan)         │
│    - Dependency graph validation       │
│    - Blocker satisfaction (closed/done)│
│    - Zero exclusive resource collision │
│    - Produces valid execution receipt  │
└──────────────────┬─────────────────────┘
                   │ Pass
                   ▼
┌────────────────────────────────────────┐
│ 3. Mandatory Operator Approval Gate    │
│    - Explicit human operator approval  │
│    - NO auto-claim                     │
│    - NO auto-run                       │
│    - NO auto-merge                     │
└──────────────────┬─────────────────────┘
                   │ Approved
                   ▼
[ Execution via cortxt work resume ]
```

### 1. Issue completeness gate

Before an issue is eligible for dispatch consideration, its durable GitHub
issue body and metadata must satisfy all definition-of-ready requirements:
- Approved task scope;
- Deterministic acceptance criteria (AC);
- Explicit runtime limits (`worker_role`, `max_runtime_seconds`,
  `max_cost_usd`, `max_parallel_workers`, `delegation_depth`, `artifact_policy`);
- Authoritative `workflow:ready` label without conflicting workflow labels.

### 2. Execution-map pre-flight gate (ADR-039)

The execution map inspects the global task graph and resource allocations
(exercised via `cortxt work plan`):
- **Prerequisite satisfaction**: Every blocking prerequisite (`Blocked by: #<id>`)
  must be closed or carry `workflow:done`. Open prerequisites at `workflow:ready`,
  `workflow:in-progress`, or `workflow:review` fail the pre-flight gate.
- **Resource collision check**: The issue must not collide on canonical
  exclusive keys (issue ID, branch name, worktree path, session store ID, or
  active run identity).
- **Graph consistency**: The issue must not participate in cyclic dependencies,
  orphan references, or malformed hierarchy.
- **Pre-flight receipt**: Successful evaluation produces a deterministic
  execution-map receipt required for downstream execution.

### 3. Mandatory operator approval gate

Automated triggers never grant autonomous execution authority:
- **Operator approval remains mandatory**: Worker dispatch is never
  unconditionally triggered by a label change alone.
- **No auto-claim**: The system does not automatically create a claim or mutate
  workflow labels upon receiving the event.
- **No auto-run**: No external agent model or runtime adapter is invoked without
  explicit operator approval.
- **No auto-merge**: Completed work requires independent review and human operator
  approval before landing in trunk.
- **Claim and run identity**: When approved, dispatch creates an atomic claim and
  unique `run_id` per ADR-018 and the dispatch contract.

## Execution path

Once operator approval is provided, execution proceeds through the
execution-map-gated launcher:

1. **Inspection**: The operator or orchestrator runs `cortxt work plan` to
   inspect the execution map, wave ordering, and collision status.
2. **Launch command**: Execution is initiated via `cortxt work resume`
   (or the widget candidates claim-run action with explicit approval).
3. **State re-read and receipt validation**: The launcher re-reads durable
   GitHub state, verifies the execution-map receipt, and validates that no
   concurrent claims have been established since pre-flight.
4. **Claim and isolation**: An atomic claim is recorded, the label transitions
   from `workflow:ready` to `workflow:in-progress`, an isolated git worktree
   is provisioned (`scripts/parallel_dispatch.py`), and the worker is launched.

## Idempotency and replay handling

Inbound webhook events and GitHub Actions triggers are delivered with
at-least-once semantics. Repeated or duplicate label events must be handled
safely without double-claiming or duplicated side effects.

### Event-surface v1 integration (Issue #328)

Once the event-surface v1 (#328) is merged, label events will be processed
through the standardized inbound envelope:
- Deduplication by event ID within an idempotency time window (5-minute default);
- Payload hash verification for retried events outside the window;
- Transition locks ensuring that an issue already in `workflow:in-progress`
  or claimed in the local run registry rejects duplicate dispatch requests.

### Self-contained fallback dedupe (Notice scaffold)

For the non-mutating scaffold (`.github/workflows/label-dispatch-notice.yml`),
deduplication is handled directly through a marker-based comment check:
- Before posting a notice comment, the workflow inspects existing comments on
  the issue via the GitHub API.
- If a comment containing the hidden HTML marker `<!-- cortxt-dispatch-notice -->`
  is already present, the workflow terminates immediately as a no-op.
- If absent, exactly one content-free notice comment containing the marker is
  posted.

## What this does NOT do

To preserve strict control-plane boundaries and safety invariants, this design
and its scaffold explicitly define what is never performed automatically:

1. **Never claims**: Inbound label events do not claim issues or reserve
   execution leases.
2. **Never dispatches**: No subagent or external runtime (Hermes, Pi,
   Codex, DSH) is dispatched by the receipt of a label event.
3. **Never labels**: The notice scaffold does not add, remove, or edit
   `workflow:*` labels.
4. **Never merges or closes**: Pull requests and issues are never merged or
   closed by the event trigger.
5. **Never deploys**: No deployment or publication pipeline is triggered.
6. **Never approves**: Graph readiness and label state alone never grant dispatch
   authority; operator approval is always required.
