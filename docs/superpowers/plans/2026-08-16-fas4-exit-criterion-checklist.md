# Fas 4 — Supervisor v0.1 — exit-criterion verification status

Verified 2026-08-17, on branch `worktree-fas4-supervisor` (base: `main` @
`3c515c4`, after PR #148/#149). 20 commits, 13 plan tasks (dispatch order
1, 2, 4, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13), executed via subagent-driven
development: implementers on `Qwen3-Coder-Next-FP8` (InferX), reviewer
Kimi K2.7-code (Kimi provider) on every task plus every fix round.

## What is verified, and how

| Check | Command | Result |
|---|---|---|
| Default suite (no Docker, no real inference) | `pytest agent-platform/ -q -m "not docker_required and not real_inference"` | **264 passed, 4 skipped, 0 failed** |
| Docker-gated suite (container sandbox boundary + child-process wiring) | `pytest agent-platform/ -v -m docker_required` | **10 passed, 4 skipped, 0 failed** (Docker Desktop reachable in this environment) |
| Real-inference-gated suite (M1/M2 true end-to-end, live model) | `pytest agent-platform/ -m "real_inference and docker_required"` | **SKIPPED — `CORTXT_INFERENCE_MODEL` not set in this environment.** Not run. This is the actual exit-criterion proof and a skip here is **not** a pass, per the same convention Fas 3's own `test_coding_loop_real_inference.py` established. |

## What IS empirically proven in this environment

- M1's process/IPC mechanics: two children spawn as real detached OS
  processes, heartbeat, and are joined/merged (`test_coding_loop_cli.py`,
  `test_cancellation.py`, `test_recovery.py`, `test_heartbeat_staleness.py` —
  all real subprocess spawns, no Docker or model needed).
- M2's join-failure path: a real `Coordinator.run_m2` call, with a real
  spawned child that fails fast (empty workspace), correctly blocks without
  ever spawning child 2 (`test_m2_child_two_never_spawned_if_child_one_fails`
  — genuinely PASSED, not skipped).
- The Docker-backed execution sandbox and its full boundary-test suite
  (network isolation, credential absence, timeout, output truncation,
  workspace isolation) — unaffected by Fas 4, still green.
- `CodingLoop`'s additive `file_contents` capture (Task 4) and
  `coding_loop_cli`'s heartbeat/monkeypatch wiring (Task 3) — both proven with
  the real container sandbox and a scripted (non-live-model) inference port.

## What is NOT empirically proven in this environment

- **The true M1 exit-criterion scenario** (two independent live-model coding
  runs, merged) — `test_m1_two_independent_children_succeed_and_merge`.
- **The true M2 exit-criterion scenario** (child 2's live-model fix depends on
  child 1's live-model fix via the workspace handoff) —
  `test_m2_child_two_only_succeeds_because_of_the_handoff`.

Both require `CORTXT_INFERENCE_MODEL`/`CORTXT_INFERENCE_URL`/
`CORTXT_INFERENCE_API_KEY` set and `cortxt_resilient_inference` installed —
exactly the same precondition Fas 3's own exit-criterion test needed. **Run
these manually in an environment with real inference credentials before
calling Fas 4 v0.1's exit criterion fully proven** — a skip is not a pass.

## Real bugs found and fixed during this run (not in the original plan text)

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
   fixed-depth assumption was fragile to file moves — both Important, both
   fixed (commit `95e9c75`).

## Ledger

Full task-by-task ledger, including the preflight conflict scan and every
ruling made during execution: `.superpowers/sdd/2026-08-16-fas4-supervisor-v01/progress.md`
