# Dispatch contract

Status: active normative
Authority: control-plane contract
Last verified: 2026-08-11

## Purpose

This contract keeps GitHub task state independent from the worker runtime. A
manual operator, a native delegation tool, Hermes Kanban, or a future n8n
dispatcher may execute the work, but all paths must expose the same observable
identity and lifecycle.

GitHub Issues/Projects are the source of truth. Runtime task lists are execution
ledgers only.

## Dispatch request

Every approved dispatch must define:

| Field | Requirement |
|---|---|
| `issue_id` | Stable GitHub owner/repository/issue reference |
| `workflow` | Versioned workflow or vertical capability identifier |
| `worker_role` | Allowed role such as `researcher` or `builder` |
| `scope` | Immutable task statement derived from the approved issue |
| `acceptance_criteria` | Deterministic completion conditions |
| `max_runtime_seconds` | Hard execution deadline |
| `max_cost_usd` | Approved cost ceiling or explicit `unknown-not-allowed` |
| `max_parallel_workers` | Hard concurrency ceiling; initially `2` |
| `delegation_depth` | Hard ceiling; initially `1` |
| `artifact_policy` | Allowed output locations and content restrictions |
| `approval_ref` | Evidence that the issue was approved for dispatch |

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

The result may link to protected artifacts but must not place secrets, private
documents, prompts, raw reasoning, or unrestricted logs in GitHub.

## State transitions

- A valid claim moves the GitHub item from `Ready` to `In progress`.
- A complete result with required evidence moves it to `Review`.
- A structured non-recoverable result moves it to `Blocked`.
- Only independent review plus human approval moves it to `Done`.
- Retry creates a new `run_id`; it never overwrites prior run evidence.

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
