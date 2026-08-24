# Contracts

This directory will contain versioned, domain-neutral schemas exchanged among
the control plane, harness, vertical packages, and reviewers.

Contracts that exist today:

- `dispatch-request.schema.json` -- shape of a worker dispatch request (issue,
  workflow, worker role, scope, budget/runtime caps, approval reference).
- `result-envelope.schema.json` -- shape of a worker's result envelope
  (status, runtime, usage/cost, artifacts, evidence) reported back after a run.
- `state-categories.json` (validated by
  `../schemas/state-category-registry.schema.json`) -- the CBS Phase 1
  (ADR-041) registry of state categories (`session-state`, `widget-state`,
  `atlas-cache`), their backend eligibility, and mandate scope.
- `state-sync-contract.schema.json` -- CBS Phase 1 (ADR-041) request/response
  shapes for the state-sync MCP tools (`state_read`, `state_write`,
  `state_delete`, `state_since`).

Further candidate contracts (task, run, artifact, review, and approval records
beyond the two above) are not created yet: fields and lifecycle rules must
first be validated by real runs. Contracts must never contain provider
credentials, customer documents, or vertical-specific conclusions.

The state-sync contract is delivered as MCP tool call arguments/results
rather than REST or gRPC routes, per ADR-041 and the decision recorded in
[issue #371](https://github.com/rian010194/cortxt/issues/371): CBS Phase 1
rides the existing MCP tool-call transport (`agent-platform/cortxt_mcp/tools.py`
is transport-agnostic and tool-call based, with no HTTP route table to
extend) rather than introducing a new wire protocol.

See [Vertical package contract](../docs/architecture/vertical-package-contract.md).
