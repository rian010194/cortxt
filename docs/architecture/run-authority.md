# Run authority boundary (S7a, extended S7c)

Status: accepted baseline for the S7 real operator-governed Workstream loop
Last reconciled: 2026-08-31

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
- A Run present in both stores that disagrees on `status` or on a shared
  terminal `finished_at` is rendered as `status: "conflict"` with both values
  listed under `conflict.values` — never resolved, never silently merged.
- Runs are immutable summaries: a retry creates a new `run_id` and never
  overwrites an earlier record.

The canonical-writer decision is deliberately deferred to S7b (launch), which
creates the durable Run and owns the write path. This slice only reads.

## Shape

- `workstream.detail.v1` — one Workstream's full mandate and Run history
  (`widget_contract/detail.py`), registered in `widget_contract/registry.py`.
- `run.summaries.v1` — content-free, provenance-tagged Run summaries
  (S7c adds a nullable `heartbeat_at`).
- `run.terminal.v1` / `run.activity.v1` / `run.review.v1` — S7c content-free
  live-Run projections. `run.terminal.v1` also carries the Evidence Gate's
  verdict (`evidence_gate`) and its correlated `commit_evidence` record (#499).
- `run.diff.v1` — the change one Run contributed, read for operator review
  (#499). The single read in this module that returns run-produced content.
- Same-origin read endpoints in `widget/action_host.py` (loopback, read-only,
  fail-closed): `GET /api/workstream-detail?issue=owner/repo#N`,
  `GET /api/runs?issue=owner/repo#N`, and the S7c
  `GET /api/run-freshness`, `GET /api/run-terminal`, `GET /api/run-activity`,
  `GET /api/run-review`, and `GET /api/run-diff`.

## Live Run status, evidence, and review loop (S7c, #472)

S7c connects real execution truth to Cortxt OS after an operator starts a Run,
without a canonical-writer decision and without any new mutation surface.

- **Freshness.** `run_authority.compute_run_freshness(summaries, now_iso=...)`
  classifies an issue's correlated summaries as `fresh` / `stale` /
  `stranded_running` / `terminal` / `unavailable` from a bounded `heartbeat_at`
  (dispatcher `heartbeat_at`, else the newest session event). `unavailable`
  is the fail-closed reading when `now` cannot be resolved. The Work renderer
  polls `GET /api/run-freshness` every 5s while non-terminal and stops at
  `terminal` (bounded frequency; explicit age).
- **Terminal envelope.** `run.terminal.v1`
  (`GET /api/run-terminal?issue=owner/repo#N&run=<run_id>`) is a content-free
  projection of the last durable `run.engine_turn` for one exact issue+run:
  provider, model, usage, `{ref, sha256}` artifacts, redacted evidence
  (`kind`/`ref`/`sha256` only), structured error, and `incomplete` /
  `conflicting` flags. Missing cost is `cost: null` with
  `cost_status: "unknown"` — never `0` by assumption.
- **Safe activity.** `run.activity.v1`
  (`GET /api/run-activity?issue=...&run=<run_id>`) is a timeline of the four
  durable run event types with a whitelisted `detail` (status, `cost_status`,
  artifact/evidence counts, `review_kind`, `result_status`, engine). No
  prompt, reasoning, secret, raw log, or artifact body is ever read.
- **Readable change.** `run.diff.v1`
  (`GET /api/run-diff?issue=owner/repo#N&run=<run_id>`) returns the diff the Run
  contributed, so the operator decides on the change rather than on a hash
  (#499). It is the one read that returns content, and every bound on it comes
  from the durable record, not the request: the request schema is exactly
  `{issue_ref, run_id}`, so the browser can never name a path; commit, base,
  branch and worktree are read from the `commit_evidence` record the Evidence
  Gate wrote onto the **durable Run**, never from the worker's result envelope
  (a refused Run's envelope is copied forward verbatim by
  `Dispatcher._gate_commit`, so a worker-authored `commit_evidence` key would
  otherwise have chosen the worktree the read runs `git` in); the envelope must
  additionally carry `evidence_gate: "commit_correlated"`, so a Run the gate
  refused serves no content at all; the record must name this exact Run and
  Issue, and a record missing either identifier is refused rather than assumed
  to match; the commit must still be an ancestor of the registered branch;
  and a patch is returned only for a file that is both in `contributed_files`
  and inside the approved artifact policy, judged by the gate's own
  `commit_evidence._within` / `normalize_repo_path`. Any other file is a
  `withheld` entry carrying its reason and no content, and every failure is
  `available: false` with a stable reason — never an empty diff, so "nothing
  changed" and "not allowed to show" can never be read as the same answer.
  Patches are capped per file (60 000 characters) and per response (400 000);
  a capped patch is marked `truncated`, never silently shortened. The whole
  review costs exactly one `git diff` -- the host is single-threaded, so one
  subprocess per contributed file would let a single Run hold it.

  Cortxt OS names the Run the panel is showing and, when a Workstream has more
  than one, lets the operator pick it. The projection is bound to an exact
  issue+run pair; a surface that silently rendered a different Run's diff than
  the one under decision would be worse than rendering none.
- **Exact correlation.** Every S7c read is bound to an exact `issue_ref` +
  `run_id`; a pair with no correlated summary fails closed
  (`RunNotCorrelated` → HTTP 404), never a fallback to another run.
- **Immutable history.** Retry creates a new `run_id`; prior summaries and
  their terminal projections (artifacts, accepted evidence) stay readable
  unchanged (S7a immutability, re-covered by S7c tests).
- **Sanctioned review path.** `widget_contract/adapters/review_ports.py` is a
  thin re-export: `submit_run_for_review` delegates verbatim to
  `run_lifecycle.RunLifecycleService.submit_for_review` (idempotent by
  `idempotency_key` + canonical payload hash; complete correlated envelope
  only; no `gh` call) and `sync_run_review_submissions` **is**
  `daemon.review_sync.sync_review_submissions` (identity asserted in tests).
  GitHub `in-progress -> review` happens only through that sync contract. The
  OS never marks work done or edits arbitrary `workflow:*` labels;
  `run.review.v1` (`GET /api/run-review`) is a read-only view of durable
  `run.review_submitted` facts.

## Field discipline

Every detail field derives from an explicit source (issue record, explicit body
section/field, explicit relation line, or a Run record). A missing authoritative
value stays missing — nothing is inferred from title, branch, browser state, or
free text. Synthetic (public) mode uses the exact same schema with deterministic
fixture data and no mutation.
