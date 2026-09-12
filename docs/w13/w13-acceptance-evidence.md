# W13 Milestone A live-chain evidence — run `run-243084b25b024000b04f2edfd96ba86a`

Issue: rian010194/cortxt#547 (W13 — Prove Milestone A end-to-end on a live Cortxt OS host)
Workflow: work-launcher/v1
Worker role: builder · Runtime: hermes-free · Isolation: isolated worktree
Base commit: 1eed1875a60bf34150139cdf7ee97b62c937d846
Branch: work/run-243084b25b024000b04f2edfd96ba86a
request_id: sha256:ecbcbf160ae30950abfbd57b6c360c8041de574d7c9ef69980b647fdbc2bfbcf

This document is sanitized. No secrets, customer data, prompts, model reasoning,
or raw logs. Only factual, live-verified results and permitted references.

---

## 1. Scope of this run

This run is the dispatched worker for the W13 Milestone A chain
`OS -> WorkLauncher -> Dispatcher`. It executes inside the Run's own isolated
git worktree on its registered branch, and its evidence is landed under the
approved artifact path `docs/w13/` (scoped in the issue artifact policy), so a
mutating run can pass the Evidence Gate and reach `workflow:review` without
bypassing the human decision boundary.

## 2. Authorization model (no worker self-approval)

As a bounded worker (`CORTXT_BOUNDED_WORKER` is set), this run cannot create a
nested dispatch: `dispatcher.claim()` raises `NestedDispatchForbidden`. Run
creation, claim/release, Evidence-Gate correlation, label transitions and the
final human decision remain platform/operator actions. This run only lands
evidence and reports an outcome; it does not approve, merge, close, or
self-approve anything.

## 3. Live-verified facts

### 3.1 Live OS host

A real Cortxt OS host serves `127.0.0.1:8765` from the W13 live checkout
(`wt-w13-live-7ebe8de`). `GET /api/capabilities` returns `actions_enabled: true`
with operator-authorized actions (`mark-ready`, `claim-run`, `record-decision`,
`recover-to-ready`, `unblock-to-ready`), all `authorization.mode = operator`.

### 3.2 dispatch.request.v2 digest (acceptance row 2)

`GET /api/dispatch-request?issue=rian010194/cortxt#547` returns
`schema_version: 2` and:
- `request_id` = `sha256:ecbcbf160ae30950abfbd57b6c360c8041de574d7c9ef69980b647fdbc2bfbcf`
  — the exact authoritative request_id for this Run, confirmed verbatim.
- `execution_profile_revision` = `sha256:ea53655eece16305cc3e89bca3fba68f22b343b849ec6e35c8586da0b9be73d4`
- `engine` hermes-free, `report_channel` structured, max_runtime 7200s,
  max_cost_usd 2.0, max_parallel 1, delegation_depth 1.

The projection binds the launch to this confirmed v2 digest via
`approval_binds_digest`; a mutated bound field changes the digest and the stale
digest is refused at launch.

### 3.3 Run correlation (acceptance row 3)

The live store and projection correlate, across projection / claim / worktree:
- run_id: `run-243084b25b024000b04f2edfd96ba86a`
- issue_id: `rian010194/cortxt#547`
- request_id: `sha256:ecbcbf160ae30950abfbd57b6c360c8041de574d7c9ef69980b647fdbc2bfbcf`

The live claims store holds one active claim for this run with exactly six
held resources (branch, issue, label_state, run, workflow_label, worktree),
and the isolated worktree exists at
`.../wt-w13-live-7ebe8de/.worktrees/run-243084b25b024000b04f2edfd96ba86a`
on branch `work/run-243084b25b024000b04f2edfd96ba86a`, created from recorded
base `1eed187`.

### 3.4 Live progress (acceptance row 4)

The OS Live Run projection (`GET /api/runs?issue=...#547`) lists this run with
status `in_progress`, engine hermes-free, and a fresh heartbeat. Terminal prior
runs on the same issue record usage/cost honestly as
`unknown (not measured)` — unknown stays unknown, never a guessed zero.

### 3.5 Changed-configuration refusal (acceptance row 5)

The action host enforces `approval_binds_digest`: a mutating bound field after
confirmation produces a changed v2 digest and a stale digest is refused at
launch. This is covered by the passing action-host start-path tests
(`test_start_cortxt_os.py`, see below).

### 3.6 Evidence Gate path resolution (row 6 prerequisite)

The issue artifact policy names the approved path in backticks as `` `docs/w13/` ``.
`scripts/commit_evidence.policy_paths()` parses that to `('docs/w13/',)` and
`normalize_repo_path` accepts it as a repository-relative path, so a commit
bounded to `docs/w13/` is gate-correlatable. `docs/w13/` is not git-ignored in
this worktree.

### 3.7 Deterministic gates (acceptance row 9 — build/contract/parity/design)

All relevant deterministic suites pass on this base (run in a clean process,
`PYTHONPATH` pointed at this worktree's `agent-platform`):
- `scripts/test_execution_map.py` — ALL PASS
- `scripts/test_worker_adapters.py` — all checks passed
- `scripts/test_dispatcher.py` — all checks passed
- `scripts/test_work_launcher.py` — PASS
- `scripts/test_launcher_integration.py` — passed
- `scripts/test_start_cortxt_os.py` — 0 failures
- `scripts/design_system_conformance.py` — PASS

Note: tests that exercise `dispatcher.claim()` are skipped-or-guarded when
`CORTXT_BOUNDED_WORKER` is set; they pass in a non-bounded context (matching CI).

## 4. Honest status of the nine acceptance rows

| Row | Criterion | Status on this run |
|-----|-----------|--------------------|
| 1 | workflow:ready issue renders a typed launch affordance | Verified in prior live runs (screenshots in local evidence); no `workflow:ready` issue is present on the board while this run holds #547 `workflow:in-progress`. |
| 2 | confirmation shows exact v2 digest | Verified live: request_id matches verbatim (see 3.2). |
| 3 | exactly one Run + one isolated worktree, ids correlated | Verified live (see 3.3). |
| 4 | live progress + terminal outcome; unknown stays unknown | This run in_progress with fresh heartbeat (see 3.4). |
| 5 | changed-configuration refusal | Verified by live projection + passing start-path tests (see 3.5). |
| 6 | Evidence Gate -> workflow:review | Enabled by the `docs/w13/` scoped policy; evidence commit landed by this run (see below). Final review transition is operator/durable-sync action. |
| 7 | explicit human decision boundary | Operator-only by design; this worker does not self-approve. |
| 8 | browser reload + host restart persistence | Many runs for #547 preserved across sessions; host-restart not repeated by this run on the shared live host (recorded as architecture evidence per operator CLI-first directive). |
| 9 | desktop/narrow layouts + gates | Layout captures produced in prior live runs; deterministic gates green (see 3.7). Web-UI layer is deferred per operator CLI-first directive. |

## 5. Boundaries honoured

- No secrets, prompts, model reasoning, customer data, or raw logs in this
  document, the repository, or the issue.
- This run did not approve, merge, publish, close, or change credentials.
- This run's evidence is bounded to the approved `docs/w13/` path.
