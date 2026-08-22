# ADR-034: MCP run lifecycle tools -- mandate-bound create/resume/submit_for_review

**Status:** Accepted
**Date:** 2026-08-22
**Deciders:** Rikard Andersson (operator), scope approved 2026-08-22 (session); design by the parallel MCP-step-2 session, operator adopted the Q1-Q12 recommendations ("run with the recommendations on Q1-Q12"); remaining open questions Q3/Q4/Q9/Q17-Q20/Q22/Q24 resolved by operator recommendation in issue #230
**Technical Story:** issue #230; proposal documents `lab/parallel-mcp-step2/step2-scope.md`, `step2-spec.md`, `step2-decisions-q1-12-2026-08-22.md`, `step2-questions.md` (workspace-local, not tracked in this repo)

## Context

ADR-032 (Accepted 2026-08-22) protects every Tier-1+ MCP mutation with a
signed, nonce-bound mandate envelope, verified inside `call_tool` before the
handler runs. Its Expiry/Review Trigger names the next step: "step 2
(`create_run`/`resume_run`/`submit_for_review`) depends on this slice being
in place first." This ADR is that step: it records the ADR-032 review the
trigger requires, as a strengthening, and defines the three run-lifecycle
tools built on the mandate mechanism (per operator decision Q12, ADR-032
itself is amended only if a later step needs the general mechanism, not just
the run tools).

Today's Tier-1 surface has only the broad `cortxt_dispatch` entry point. It
routes tags, invokes work, and returns a `ResultEnvelope` in one shot; it has
no explicit create/resume/review lifecycle boundary, and its caller cannot
durably resume a specific engine-native conversation or hand a complete
result to independent review. A minimal skeleton (commit `a3e128c`,
2026-08-22) registered the three tool names against a local JSON store, but
did not implement the approved lifecycle: no `EngineContext` broker
invocation, no `session_state` run store, no strict schemas, no `-32003`
error mapping, no idempotency, no audit of lifecycle rejections. This ADR and
issue #230 complete that work to the approved specification.

## Decision

### 1. Three Tier-1 tools, strict schemas, authoritative context

Register `cortxt_run_create`, `cortxt_run_resume`, and
`cortxt_run_submit_for_review` at `TIER_DISPATCH` (1), behind the existing
`--allow-dispatch` flag (Q2), hidden from discovery unless the flag is
active. Each tool advertises a strict per-tool JSON schema
(`additionalProperties: false`, required fields, numeric bounds) and the
handler runs only after both the tier check and ADR-032 mandate verification
pass.

For these tools, authoritative call context is derived from validated
arguments and durable state -- never from the client-supplied
`mandate_context` (Q7). `call_tool` builds the `CallContext` via the
lifecycle service before verification: `issue_ref`, `data_class`,
`estimated_cost_usd`, `estimated_runtime_seconds`, and
`expected_scope_fingerprint` are taken from the validated arguments (create)
or from the durable run (resume/submit bind to the stored original create
scope fingerprint; no replacement scope from the caller). Omission cannot
skip issue or scope validation (AC3), closing ADR-032's documented
"omit to skip" gap for run creation.

### 2. Run lifecycle service (`run_lifecycle.py`)

Lifecycle logic lives in a dedicated module (`run_lifecycle.py`, Q11) with
injectable `EngineContext`, store path, and clock, behind thin `tools.py`
handlers. The run store is `runtime.session_state` (Q14): each run is one
session created with `run_id`/`issue_id` in the `session.created` payload,
followed by `run.created`, `run.engine_turn`, and `run.review_submitted`
events carrying envelope-derived limits and engine results. No new
repository, no launcher-state coupling.

`run_id` is server-generated in `scripts/dispatcher.py` format
(`%Y%m%dT%H%M%SZ_<8-hex>`) and is distinct from both the session_state
session id and the opaque engine `session_id` (Q15). The engine
`session_id` is opaque engine-native conversation identity (ADR-028): it is
stored and replayed, never parsed.

- `cortxt_run_create` (AC5): takes an explicit `engine_id` (no hidden
  routing, Q6), validates all dispatch-contract limits against the verified
  envelope binding, creates exactly one durable run identity outside the
  model, and invokes the engine broker synchronously (Q3 recommendation:
  create returns the terminal envelope; no `running` polling response and no
  new status tool for v1, Q4). Claim conflict (an existing active run for
  the same issue) is rejected before adapter invocation.
- `cortxt_run_resume` (AC6): loads the named `run_id` read-only to build
  context, rejects an unknown or non-resumable run (resumable = fresh or
  last turn `blocked`/`failed`/`timed_out`, Q12), verifies the same issue
  and bound scope, and calls the stored engine broker with the stored
  opaque `session_id`. It never substitutes a client-provided engine,
  profile, or session id; the engine is locked from the run's first turn.
- `cortxt_run_submit_for_review` (AC7): accepts only a complete
  dispatch-contract result envelope whose `issue_id`/`run_id` match durable
  state and whose status is terminal, records a local review-request event
  returning a `review_submission_id`, and never marks the issue or run done
  (Q5). Submission is idempotent via caller-supplied `idempotency_key`
  (Q17/Q18 recommendation): same key + same canonical payload returns the
  prior submission; same key + different payload returns
  `idempotency_conflict`.

### 3. Result envelope, errors, audit

Responses use the dispatch-contract envelope shape (AC8) with additive
`session_id` (resume), `review` (submit), and `cost_status`
(`measured|estimated|unknown`, Q20 recommendation); artifacts are
structured `{ref, sha256}` (Q19 recommendation), accepting plain strings as
legacy input and normalizing. No prompt, signature, secret, or raw reasoning
is returned.

Lifecycle failures use JSON-RPC `-32003` with a stable code in
`error.data.code` (`run_not_found`, `issue_ref_mismatch`, `claim_conflict`,
`run_not_resumable`, `session_id_unavailable`, `engine_not_registered`,
`adapter_failed`, `result_envelope_invalid`, `result_not_terminal`,
`result_correlation_mismatch`, `review_already_submitted`,
`idempotency_conflict`, and the server-configuration code
`lifecycle_not_configured`); invalid arguments use `-32602` (AC10). Existing
codes `-32601`/`-32001`/`-32002`/`-32000` are unchanged.

Every lifecycle attempt produces one `mcp.tool_call` audit event (AC9):
accepted rows carry `mandate_id` + `mandate_decision="accepted"`, mandate
denials `rejected:<reason>`, tier locks `tier_locked`, argument failures
`rejected:invalid_arguments`, and lifecycle rejections
`rejected:lifecycle:<code>`. `run_id` and `issue_ref` are additive top-level
audit fields (Q22 recommendation). Sensitive content keys
(`prompt`, `scope`, `acceptance_criteria`, `result`, `artifacts`,
`evidence`, plus `mandate`/`mandate_context` as defense in depth) are
redacted in the ledger; the mandate envelope is never copied.

### 4. `cortxt_dispatch` stays separate (legacy)

Keep `cortxt_dispatch` registered and unchanged this step as the legacy
single-call path; mark it legacy in its description (Q1). New launchers use
`cortxt_run_create`; continuation and review use their exact tools. Removal
or conversion into a compatibility facade is a separate operator decision
once the lifecycle is proven.

### 5. Runtime-limit enforcement (ADR-032 review record)

ADR-032's `max_runtime_seconds` is an enforced v1 authorization bound.
Requested timeout above the envelope cap is rejected as `runtime_exceeded`
before the handler runs; zero/negative/boolean/non-integer values fail
closed as `malformed_envelope` (envelope) or `invalid_arguments`
(argument). `estimated_runtime_seconds` is carried in the authoritative
`CallContext` for the run tools; per-call runtime cap is enforced (Q11),
cumulative elapsed-time policy across create+resume is deferred (not built).

## Consequences

### Positive
- Completes the ADR-032 Expiry/Review Trigger: the MCP research lifecycle
  now has explicit, mandate-bound, durable create/resume/review operations
  instead of the single broad `cortxt_dispatch` entry point.
- Every lifecycle mutation inherits ADR-032 protection by construction
  (verification lives inside `call_tool`), and the authoritative-context
  derivation closes the "omit to skip" issue/scope gap for these tools.
- Durable run state in the proven `session_state` ledger gives resume and
  review a real identity story without a second backlog or a new store.
- Strict schemas + stable `-32003` codes give MCP clients a deterministic
  error surface for lifecycle operations.

### Negative
- `run_id` lookup scans the session store (O(n) in total session history);
  fine at v0.1 scale, a candidate to revisit with an index if the store
  grows large.
- No budget reconciliation (Q9 recommendation: mandate debits are reserved
  budget, never refunded) -- documented limitation, matches ADR-032.
- `cortxt_dispatch` and the lifecycle tools are deliberately parallel for a
  compatibility period; keeping both surfaces in sync is a maintenance
  cost until a later decision retires the legacy path.

### Risks
- The MCP server records a local review-request event only; the
  `workflow:review` GitHub transition happens out-of-band by the
  operator/daemon (Q5). A future daemon sync pass may consume
  `review_submission_id` without a schema change; until then a submission
  with no daemon consumer is inert local state.
- The run store is single-process-safe (one MCP server process per state
  directory), same limitation ADR-032 documents for the nonce/budget
  stores; a multi-process deployment needs real file locking.
- `lifecycle_not_configured` is a server-configuration code beyond the
  original spec's stable list; documented here so clients can rely on it.

## Alternatives Considered

1. **Extend `cortxt_dispatch` with lifecycle flags instead of new tools** --
   rejected (Q1): dispatch's argument, state, nonce, and timing semantics
   would change inside issue #230; a separate lifecycle surface keeps the
   legacy path stable during the compatibility period.
2. **Asynchronous create with a `running` response and a new
   `cortxt_run_status` tool** -- rejected for v1 (Q3/Q4): synchronous create
   matches the existing dispatch shape, avoids inventing a polling protocol
   without a status tool, and existing `cortxt_status` (Tier 0) already
   surfaces session state.
3. **Server-side canonical idempotency instead of caller-supplied
   `idempotency_key`** -- deferred (Q17/Q18): caller-supplied key with
   canonical-payload comparison is adopted for v1; server-side canonical
   hashing remains an option if a later step needs it.

## Validation

- [x] Implementation matches decision -- builder ran the focused
      run-lifecycle suite (115 passed in `tests/cortxt_mcp/`) and the full
      `agent-platform` suite (889 passed, 5 skipped) locally; coordinator
      independently confirmed CI before acceptance (PR #231: all 6 checks
      green, including agent-platform-tests, agent-platform-docker-tests,
      dco-signoff, adr-doc-currency).
- [x] Tests cover decision boundaries -- registration/schemas, rejection
      before handler/adapter, runtime cap, claim conflict, resume
      non-resumable paths, review idempotency replay/conflict, audit
      decisions, and `-32003`/`-32602` protocol mapping (covered by
      `tests/cortxt_mcp/test_run_lifecycle_tools.py` and confirmed by the
      coordinator CI run).

## Open Questions (deferred, not blocking this ADR)

- **Budget reconciliation.** Actual spend below the debited estimate is
  never refunded (Q9). Whether a later event should reconcile the budget
  store is open.
- **`cost_status` on the shared CLI `ResultEnvelope`.** Added only to
  lifecycle responses for v1 (Q20); whether the shared envelope gains it
  later is open.
- **Daemon consumption of `review_submission_id`.** The local review record
  has no consumer yet (Q5); a daemon sync pass is a future step.
- **Run-store indexing.** O(n) session scan for `run_id` lookup is accepted
  at v0.1 scale; a dedicated index is a candidate if the store grows.
- **Deprecation of `cortxt_dispatch`.** After production evidence, a later
  decision may make dispatch a compatibility facade or deprecate it (Q1).

## Expiry/Review Trigger

- Review by: the first real use of the run-lifecycle tools in a dispatched
  build, or 2026-11-22, whichever comes first.
- Trigger: a named consumer needs asynchronous create/polling, a second MCP
  server process against the same state directory, or evidence that the
  lifecycle surface should absorb or replace `cortxt_dispatch`.
- Accepted 2026-08-22 (PR #231 merged): implementation and tests confirmed
  by the coordinator CI run; acceptance covers the current
  single-stdio-process, loopback/stdio deployment (see Open Questions on
  multi-process state and daemon consumption of review submissions).
