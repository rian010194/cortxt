# Run authority boundary (S7a)

Status: accepted baseline for the S7 real operator-governed Workstream loop
Last reconciled: 2026-08-29

## Why this exists

Two Run stores currently overlap for the same Workstream:

- **Dispatcher `runs.json`** (`scripts/dispatcher.py` `RunRegistry`) — claim/run
  identity created by the dispatcher and the `cortxt work` launcher.
- **MCP/session-event store** (`cortxt_mcp/run_lifecycle.py` writing into the
  append-only session store via `runtime/session_state`) — Run lifecycle
  created by the mandate-bound `cortxt_run_*` MCP tools.

Both use the same server-generated `run_id` format, so the same logical Run can
appear in both stores. Until S7b (launch) designates the canonical writer,
S7a's read model must not silently prefer one store over the other.

## Decision (S7a)

The detail read model uses a **provenance-preserving adapter**, not a canonical
writer:

- `widget_contract/run_authority.py` correlates Run summaries from both stores
  by exact `issue_ref`, preserving each record's `sources`.
- A Run present in both stores and in agreement merges provenance only.
- A Run present in both stores that disagrees on `status` is rendered as
  `status: "conflict"` with both statuses listed under `conflict.values` —
  never resolved, never silently merged.
- Runs are immutable summaries: a retry creates a new `run_id` and never
  overwrites an earlier record.

The canonical-writer decision is deliberately deferred to S7b (launch), which
creates the durable Run and owns the write path. This slice only reads.

## Shape

- `workstream.detail.v1` — one Workstream's full mandate and Run history
  (`widget_contract/detail.py`), registered in `widget_contract/registry.py`.
- `run.summaries.v1` — content-free, provenance-tagged Run summaries.
- Same-origin read endpoints in `widget/action_host.py`:
  `GET /api/workstream-detail?issue=owner/repo#N` and
  `GET /api/runs?issue=owner/repo#N` (loopback, read-only, fail-closed).

## Field discipline

Every detail field derives from an explicit source (issue record, explicit body
section/field, explicit relation line, or a Run record). A missing authoritative
value stays missing — nothing is inferred from title, branch, browser state, or
free text. Synthetic (public) mode uses the exact same schema with deterministic
fixture data and no mutation.
