# Contracts

This directory contains versioned, domain-neutral schemas exchanged among
the control plane, harness, vertical packages, and reviewers.

## Single-source rule (VLT-D-007, operator-adjusted step 1)

The embedded schema dicts in `agent-platform/widget_contract/registry.py`
(`DISPATCH_REQUEST_SCHEMA`, `DISPATCH_REQUEST_V2_SCHEMA`) are the
**authoritative production source** — the confirm/launch path validates
against them. The files below are **generated exports** of exactly those
dicts and must never be hand-edited:

- `dispatch-request.v1.schema.json` -- generated export of
  `DISPATCH_REQUEST_SCHEMA` (dispatch.request.v1 projection).
- `dispatch-request.v2.schema.json` -- generated export of
  `DISPATCH_REQUEST_V2_SCHEMA` (dispatch.request.v2 projection).

Regenerate with `python scripts/export_contracts.py`; CI (and
`tests/widget_contract/test_schema_source.py`) fail closed on drift.

The hand-written `dispatch-request.schema.json` / `result-envelope.schema.json`
describe the *worker-facing* envelope/request vocabulary (a related but
distinct contract object; the projection schemas above are a superset with a
different field set). Known drift between `result-envelope.schema.json` and
code is tracked for the VLT-D-006 evidence pass and must not be "fixed" by
hand here.

## Packaging

`pyproject.toml` in this directory defines the `cortxt-contracts` package
(version-stamped exports under `cortxt_contracts/schemas/`), consumed by
agent repositories as
`cortxt-contracts @ git+https://github.com/rian010194/cortxt@<tag>#subdirectory=contracts`
(VLT-D-007 §1). The tag `contracts/vX.Y.Z` is cut from the core repo when the
first consuming agent repository exists.

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
