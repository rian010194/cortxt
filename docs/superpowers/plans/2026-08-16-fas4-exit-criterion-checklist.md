# Fas 4 — Supervisor v0.1 — exit-criterion verification status

Verified 2026-08-17, on branch `worktree-fas4-supervisor` (base: `main` @
`3c515c4`, after PR #148/#149). 25 commits, 13 plan tasks (dispatch order
1, 2, 4, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13), executed via subagent-driven
development: implementers on `Qwen3-Coder-Next-FP8` (InferX), reviewer
Kimi K2.7-code (Kimi provider) on every task plus every fix round.

## What is verified, and how

| Check | Command | Result |
|---|---|---|
| Default suite (no Docker, no real inference) | `pytest agent-platform/ -q -m "not docker_required and not real_inference"` | **264 passed, 4 skipped, 0 failed** |
| Docker-gated suite (container sandbox boundary + child-process wiring) | `pytest agent-platform/ -v -m docker_required` | **10 passed, 4 skipped, 0 failed** (Docker Desktop reachable in this environment) |
| **Real-inference-gated suite (M1/M2 true end-to-end, live model) — RUN FOR REAL** | `pytest agent-platform/ -m "real_inference and docker_required"` | **BOTH PASSED**, against a live `Qwen3-Coder-Next-FP8` model on InferX (`CORTXT_INFERENCE_URL=https://model.inferx.net/endpoints/v1`). See below — this is the actual exit-criterion proof, and it is no longer a skip. |

## The exit criterion is now empirically proven, not just structurally proven

- **`test_m1_two_independent_children_succeed_and_merge`** — PASSED. Two
  independent child runs, each a real live-model coding fix, spawned as
  detached OS processes, joined, merged into one result envelope.
- **`test_m2_child_two_only_succeeds_because_of_the_handoff`** — PASSED. A
  real live-model fix in child 1, handed off via the workspace-patch
  mechanism to child 2, whose own live-model fix could only make its test
  pass because of that handoff (verified arithmetic in Task 8's fixture
  design — see the plan).
- **`test_m2_child_two_never_spawned_if_child_one_fails`** — PASSED
  (previously verified, no credentials needed).

All three M1/M2 scenario tests are now green for real. Combined with the full
non-docker (264 passed) and docker-gated (10 passed) suites, this is the
complete Fas 4 v0.1 exit-criterion proof: two bounded child runs can be
carried out and integrated without Hermes.

## Two real bugs found only by running this for real (not caught by any earlier review or test)

1. **`ProviderEvidence` missing `provider_id`.** `coding_loop_cli.main()`'s
   default `provider_evidence` fallback (`{"approved": True}`, used whenever
   a child's config JSON doesn't specify one — true for every test in this
   plan) was missing the required `provider_id` field, so the first real
   `TextInferencePort.invoke()` call failed immediately with a schema error.
   Every earlier test either used a scripted/stub port (no real
   `ProviderEvidence` construction) or skipped before reaching this code path
   for lack of credentials — so this was never exercised until this run.
   Fixed: `{"approved": True, "provider_id": "inferx"}` (commit `f33c4c5`).
2. **Interpreter mismatch for `cortxt_resilient_inference`.** The package is
   `pip install -e`-editable-installed under
   `C:\Users\rikar\AppData\Local\Programs\Python\Python312\python.exe`, not
   the `hermes-agent` venv interpreter that `pytest`/`sys.executable` resolve
   to by default in this environment. Since `Coordinator._spawn_child` spawns
   children via `sys.executable`, running the top-level `pytest` invocation
   itself under the Python312 interpreter was required so its own
   `sys.executable` (inherited by spawned children) pointed at an interpreter
   that actually has the package installed. This is an environment-setup
   fact, not a code bug — noted here for whoever runs this again.

## What is NOT tested here

- Real inference model routing/selection across multiple models — out of
  scope for Fas 4's exit criterion (see conversation: M1/M2 only need one
  live model call to prove the coordination mechanics, not routing policy).
- Anything beyond the two-child-run M1/M2 scenarios — recursion depth > 1,
  more than two children, etc. — explicitly out of scope per §25 of the
  target architecture.

## Real bugs found and fixed during this run (chronological)

1. `apply_patch` crash on binary files, sandbox-image build gap, UTF-8 decode
   risk in `subprocess_sandbox.py` — found by an earlier Kimi review of Fas
   1-3, fixed in PR #149 (prerequisite to this plan, not part of it).
2. Task 3: heartbeat writes raced with `CodingLoop`'s own writes, bypassing
   `SessionWriter`'s lock — Critical, fixed (commit `c789a82`).
3. Task 9: temp config file descriptor leak in `_spawn_child` — Important,
   fixed (commit `5378df7`).
4. Task 10: two independent, real bugs discovered via controller-level
   debugging of a BLOCKED implementer — (a) `ProcessSpawner.spawn()` never set
   `PYTHONPATH`, so subprocess children couldn't import `runtime`/`adapters`
   (commit `844df1d`); (b) a `parents[2]`/`parents[3]` path-resolution bug in
   the plan's own brief text, present in both M1's and M2's integration test
   files (fixed as part of commit `1e68595`). Both were independently
   necessary — reverting either alone still reproduced a failure.
5. Task 10 fix round: M2's handoff temp directory leaked; `_build_pythonpath`'s
   fixed-depth assumption was fragile to file moves — both fixed (commit `95e9c75`).
6. Final whole-branch review (5 Important findings, all fixed, commit
   `a04203e`): `_wait_for_terminal` timeout left the root session
   non-terminal; `ProcessSpawnError` was uncaught in `_spawn_child`;
   `recover()` aborted entirely on one corrupt/missing child record; `run_m2`
   leaked its handoff directory on a specific failure path; `_spawn_child`'s
   temp config file was never deleted.
7. CI (Linux) caught what Windows-only testing throughout this branch's
   development could not: `ProcessSpawner` never reaped spawned children, so
   on Linux every exited child became a permanent zombie whose `/proc/pid/stat`
   entry persisted — `is_alive()` reported dead children as alive forever.
   Fixed (commit `4ba850e`), verified in a real `python:3.12-slim` container.
8. This manual real-inference run caught two more: the `ProviderEvidence`
   default (commit `f33c4c5`, see above) and the interpreter-mismatch
   environment fact (see above).

## Ledger

The SDD execution ledger (per-task rulings, preflight conflict scan, final
whole-branch review) has been cleaned up per the finishing-a-development-branch
skill, since the review came back clean and the branch has been pushed as
PR #150 (https://github.com/rian010194/cortxt/pull/150). Full history is in
the branch's commit log and the PR description.
