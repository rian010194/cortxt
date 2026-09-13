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

## Distribution step 2 (VLT-D-007, issue #604)

The worker-facing pair is additionally packaged verbatim at
`cortxt_contracts/schemas/dispatch-request.schema.json` and
`result-envelope.schema.json` (copied by `scripts/export_contracts.py` -- the
`--check` mode fails closed on drift), so a consumer validates against the
*pinned* package instead of reading a core checkout.

Version surface (`contracts/cortxt_contracts/version.py`):

- `CONTRACT_PACKAGE_VERSION` -- the version the tag cut for a release must
  equal (`contracts/vX.Y.Z`, strict semver).
- `SUPPORTED_CONTRACT_VERSIONS` -- the N/N-1 window (exactly two entries,
  newest first). N-1 support is retired only when `agents.yaml` records full
  migration at N (VLT-D-007 §2).
- `contract_tag()` / `parse_contract_tag()` -- the tag round-trip.

Producer CI gate (`scripts/contract_version_gate.py`, run by CI):

1. no `contracts/v*` tag yet -> green (first distribution);
2. package version unchanged since the latest tag + packaged schema bytes
   changed -> **red** (a contract change requires a version bump);
3. MAJOR bump without extending `SUPPORTED_CONTRACT_VERSIONS` -> red;
   window not exactly N/N-1 (newest first) -> red.

`contracts/agents.yaml` is a **pure catalog** of consumers and their pins
(VLT-D-007 §2). It is read by the operator and the N/N-1 retirement decision,
never by `route()` -- routing must never reference it (ADR-026 boundary,
enforced by test).

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
