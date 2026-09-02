# Dispatch contract

## Purpose

This contract keeps GitHub task state independent from the worker runtime. A
manual operator, a native delegation tool, Hermes Kanban, or a future n8n
dispatcher may execute the work, but all paths must expose the same observable
identity and lifecycle.

GitHub Issues are the durable source of truth. Workflow state is carried by
GitHub Issue labels `workflow:inbox`/`ready`/`in-progress`/`review`/`blocked`/`done`
(ADR-018); Project 4 is frozen legacy. Runtime task lists are execution ledgers only.

## Dispatch request

Every approved dispatch must define:

| Field | Requirement |
|---|---|
| `issue_id` | Stable GitHub owner/repository/issue reference |
| `workflow` | Versioned workflow or vertical capability identifier (declared as `Workflow:` in the issue's `Worker role and limits` section; distinct from the `workflow:ready` state label) |
| `worker_role` | Allowed role such as `researcher` or `builder` |
| `scope` | Immutable task statement derived from the approved issue |
| `acceptance_criteria` | Deterministic completion conditions (ordered `1.` or bulleted `-` Markdown list items under `Deterministic acceptance criteria`) |
| `max_runtime_seconds` | Hard execution deadline |
| `max_cost_usd` | Approved cost ceiling or explicit `unknown-not-allowed` |
| `max_parallel_workers` | No fixed ceiling (operator decision 2026-08-15); still required per request |
| `delegation_depth` | No fixed ceiling (operator decision 2026-08-15); still required per request |
| `artifact_policy` | Allowed output locations and content restrictions |
| `approval_ref` | Positive evidence that the issue was approved for this exact dispatch. A negated statement (e.g. "Implementation start is not approved") is not approval |
| `engine_policy` | Explicit approval of the routed engine and/or its minimum reliability class, declared as `## Engine policy` (or `## Routing policy`) with `Reliability:` and/or `Engine:` lines. Routing may select a cheap engine only when the approved policy permits its reliability/task shape |

The dispatch-request projection (`dispatch.request.v1`, S7b #471) renders every
field above plus a server-derived `request_id` digest of the immutable request
snapshot. A confirmation binds to that digest and to the issue-derived approval
reference; a changed Issue between preview and confirmation requires a fresh
confirmation and is never silently launched as a different mandate.

Secrets, customer content, prompts, and model reasoning must not be embedded in
the request or copied into GitHub comments.

## Claim and run identity

Before model execution, the dispatcher must atomically establish:

- one active claim per `issue_id` and workflow attempt;
- a unique `run_id` generated outside the model;
- the selected runtime and worker profile;
- claim time and lease/timeout;
- the transition from `Ready` to `In progress`.

After dispatch, the adapter must provide a query operation by `run_id` or child
delegation identifier. It must return status, start time, last heartbeat/update,
elapsed time, and the terminal result when available. A handle that can only
emit an unsolicited completion message does not satisfy this contract for
unattended automation.

If the runtime creates child tasks, every child must carry the same `issue_id`
and parent `run_id`, plus its own child run identifier. Runtime-generated cards
must not become independent backlog items.

## Result envelope

Every terminal result must return:

| Field | Requirement |
|---|---|
| `issue_id` | Exact request correlation |
| `run_id` | Exact claimed run |
| `status` | `succeeded`, `failed`, `timed_out`, `budget_exceeded`, `blocked`, or `cancelled` |
| `runtime` | Runtime and version |
| `worker_role` | Executing role/profile |
| `started_at` / `finished_at` | UTC timestamps |
| `model` | Provider and model identifier |
| `usage` | Input, output, cache, and reasoning tokens when available |
| `cost` | Amount and confidence/status; never silently assume zero |
| `artifacts` | Content-free references plus hashes where applicable |
| `evidence` | Tests, sources, assertions, or review inputs |
| `error` | Structured category and recovery suggestion when not successful |
| `commit` | **Mutating runs only.** The full SHA of the commit the run landed |

A **mutating run** — one whose approved mandate expects it to change the
repository — must return `commit`. Self-reported status is not evidence: the
Evidence Gate (`scripts/commit_evidence.py`, applied in
`Dispatcher.complete()`) verifies that the commit exists, correlates to this
`run_id`, `issue_id` and `request_id` — all three required in the envelope, so
a worker cannot skip a check by omitting a field — sits on the run's registered
isolated worktree branch, was made **strictly after** the second the run was
claimed, carries a DCO trailer, and stays inside the approved artifact scope,
which resolves fail-closed and never to "unrestricted". It then writes that correlation onto the
durable Run record as `commit_evidence`. A missing, unverifiable or
non-correlating commit converts the claimed `succeeded` into a structured
`blocked` — it is never relayed onward as success (#490).

The result may link to protected artifacts but must not place secrets, private
documents, prompts, raw reasoning, or unrestricted logs in GitHub.

## State transitions

These transitions are contractual and now executable via the designated
`workflow:*` label carrier (ADR-018), implemented by
`scripts/dispatcher.py` (claim/run identity and label transitions; see also
`docs/agents/work-launcher.md` for the parallel `cortxt work` entry point).
The dispatcher's atomic-claim guarantee is single-process; concurrent
dispatcher processes remain an open race risk (ADR-018 clarification,
2026-08-22).

- A valid claim moves the GitHub item from `Ready` to `In progress`.
- A complete result with required evidence moves it to `Review` — but a
  terminal worker status never performs that move by itself (#493). The order
  is: the worker reaches a terminal candidate status; the Evidence Gate
  verifies the result and, for a mutating run, the commit correlation above; a
  complete and idempotent `run.review_submitted` is written to the session
  store (`agent-platform/daemon/review_submission.py`); and only then does
  `cortxt daemon sync-review`
  (`agent-platform/daemon/review_sync.py`, ADR-037) apply
  `in-progress -> review` from that durable submission. Missing or incorrect
  evidence blocks the transition; the issue stays `In progress`.
- A structured non-recoverable result moves it to `Blocked`.
- Only independent review plus human approval moves it to `Done`.
- Retry creates a new `run_id`; it never overwrites prior run evidence.

## Delivery execution paths

The `workflow:*` label sequence marks state regardless of how the delivery is
executed. Three execution paths are sanctioned; every path upholds the label
invariant below, and `workflow:*` remains the single durable state signal
(ADR-018). Only the execution mechanism and review gate differ.

1. **Dispatched runtime build** — the canonical path above: dispatcher claim
   (`ready -> in-progress`), isolated worktree, agent runtime, result
   envelope, then `review -> done` on independent review plus operator
   approval.
2. **Coordinator-direct build** (fast fix) — the coordinator or operator
   builds directly on a feature branch; the pull request's CI plus the
   operator merge are the review and approval gate. The issue marks work
   started (`ready -> in-progress`) and completes at merge (`-> done`).
3. **Docs/ADR materialization** — no code; feature branch plus pull request
   plus operator merge. The issue moves to `review -> done` in step with the
   merge.

**Label invariant (hard rule):** an open issue whose delivery pull request
merges must never remain at `workflow:inbox`. It moves to `workflow:done` at
merge time via the state its path prescribes. The Atlas `Work kind` field
(`delivery` / `fast-fix` / `docs` / `research` / `decision`) records the kind
for rendering only, never as a second state carrier. The execution map
(ADR-039) pre-flight is required for parallel dispatched runs; the sequential
coordinator-direct and docs paths may omit it, but must still record state so
`cortxt work plan` and the candidates widget observe reality.

## Runtime adapters

An adapter for `delegate_task`, a direct Hermes profile, or Hermes Kanban is
acceptable only if it can produce this contract without simulated identifiers
or inferred status. Hermes Kanban is required only when durable dependencies,
heartbeats, retries, or recovery justify it.

The 2026-08-02 Buzz test proved that `delegate_task` can return two real child
handles, but the available tool surface could not poll either handle. This
adapter remains discovery-only until `delegate_status`/`delegate_poll` or a
verified queryable process/session mapping exists.

The first Vertical 01 discovery run should use the smallest adapter that can
prove two real parallel workers, return both child identifiers, enforce the
limits, and publish a complete result envelope.
