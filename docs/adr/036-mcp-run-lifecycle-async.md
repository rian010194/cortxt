# ADR-036: MCP run lifecycle asynchronous create and status polling

**Status:** Accepted
**Date:** 2026-08-22
**Deciders:** Rikard Andersson (operator; acceptance approved 2026-08-22)
**Technical Story:** issue #245; accepted after issue #247 dogfood proof

## Context

ADR-034 v1 chose synchronous run creation. Its review trigger named the case where a named consumer needs asynchronous create and polling. That trigger was observed, and the operator selected lifecycle step 3 on 2026-08-22. ADR-034 remains unchanged; this ADR records the trigger-observed follow-up.

## Decision

`cortxt_run_create` durably records the identity, `run.created`, and `run.running`, then returns a running dispatch-contract envelope immediately. An in-process daemon thread owned by `RunLifecycleService` invokes the broker and appends the terminal `run.engine_turn`. Adapter exceptions become failed turns with `adapter_failed` and do not escape into the create request.

Add `cortxt_run_status` as a Tier-0 read-only tool. It requires the lifecycle service but no mandate and returns created, running, or terminal envelope state. Terminal responses include usage, cost, artifacts, evidence, error, and the opaque engine session id. Resume rejects running runs with `run_not_resumable`; callers poll instead. A run stranded by server shutdown remains reported as running with its original `started_at`; there is no stale signal or automatic recovery.

## Consequences

### Positive
- Create no longer waits for adapter completion, while identity and running state are durable before launch.
- Polling has a narrow read-only surface with stable lifecycle errors.
- The worker seam permits deterministic, network-free tests.

### Negative
- Daemon threads are process-local and cannot survive server shutdown.
- Polling adds lifecycle state and client coordination.

### Risks
- The append-only store remains single-process-safe only; concurrent server processes need locking.
- A shutdown can strand a run as running indefinitely, reported as-is.
- A daemon consumer and budget reconciliation do not yet exist.

## Alternatives Considered

1. Keep synchronous create - rejected because the named consumer needs non-blocking creation and polling.
2. Use an out-of-process worker - deferred until durable queue and ownership requirements are defined.
3. Add `stale_after` or automatic recovery - rejected for this step by the operator.
4. Make status Tier 1 - rejected because status is read-only and must not require a mandate.

## Validation

- [x] Async create durably reaches running before worker launch and polling reaches terminal.
- [x] Running resume, claim conflict, adapter failure, and unknown-run boundaries are tested.
- [x] Tier-0 schema, protocol error mapping, and mandate-free audit fields are tested.
- [x] Documentation updated.
- [x] Issue #247 implementation evidence: a real external MCP client drove async create, status polling, and review submission end-to-end over stdio with a deterministic network-free engine; covered by pytest in `agent-platform/tests`.

## Open Questions

- Multi-process locking for the run store.
- Durable daemon consumption and recovery.
- Budget reservation reconciliation against measured cost.

## Expiry/Review Trigger

- Review by: 2026-11-22.
- Trigger: a second server process shares the store, stranded runs require recovery, or durable out-of-process execution is required.
