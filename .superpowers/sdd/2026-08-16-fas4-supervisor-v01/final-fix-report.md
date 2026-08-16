# Final Fix Report: Fas 4 Supervisor v0.1

**Date:** 2026-08-17  
**Branch:** worktree-fas4-supervisor  
**Working Directory:** `C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane\.claude\worktrees\fas4-supervisor\agent-platform`

## Summary

All five findings from the final whole-branch review have been fixed in `coordinator.py`. A sixth documentation-only fix was applied to `process_spawner.py`. All 264 regression tests pass.

## Changes Made

### Fix 1: `_wait_for_terminal` timeout leaves root session non-terminal

**File:** `agent-platform/supervisor/coordinator.py`

**Problem:** When `_wait_for_terminal` raised a `CoordinatorError("timeout", ...)` on deadline expiry, the exception propagated out of `run_m1`/`run_m2` without writing a terminal event to the root session.

**Solution:** 
- Modified `run_m1` to catch `CoordinatorError` around each `_wait_for_terminal` call
- Modified `run_m2` to catch `CoordinatorError` when waiting for child1 and child2
- On timeout: write `session.terminal {status: "blocked", reason: "child session did not reach a terminal state within the timeout"}` to the ROOT session log
- Return structured envelope with status "blocked" instead of letting exception escape

### Fix 2: `ProcessSpawnError` uncaught in `_spawn_child`

**File:** `agent-platform/supervisor/coordinator.py`

**Problem:** If `self._spawner.spawn(...)` raised `ProcessSpawnError`, the exception propagated uncaught out of `run_m1`/`run_m2`, leaving no session event recorded at all.

**Solution:**
- Modified `_spawn_child` to wrap the `self._spawner.spawn(...)` call in a try/except
- On `ProcessSpawnError`: write `spawn_failed` event to the ROOT session log with error details, then re-raise
- Modified `run_m1` to catch `ProcessSpawnError` around `_spawn_child` calls; treat child as failed (no session_id = None)
- Modified `run_m2` to catch `ProcessSpawnError` when spawning child1 and child2; write appropriate terminal events

### Fix 3: `recover()` aborts on one corrupt/missing child record

**File:** `agent-platform/supervisor/coordinator.py`

**Problem:** `state.load()` and direct `event["payload"]["session_id"]`/`event["payload"]["pid"]` accesses were unguarded, causing one broken child record to abort `recover()` for every root session.

**Solution:**
- Wrapped per-child processing in `recover()` with comprehensive exception guards
- Catch `state.SessionError` for missing/corrupt child session files
- Catch `KeyError`, `TypeError`, `ValueError`, `AttributeError` for malformed payloads
- On any such error: mark that specific child as "lost" with a descriptive reason (e.g., "child session record is corrupt or missing: ...")
- Continue processing remaining roots and children instead of aborting

### Fix 4: `run_m2` leaks `handoff_dir` on `apply_incoming_changes` failure

**File:** `agent-platform/supervisor/coordinator.py`

**Problem:** The existing `try/finally` around spawning-and-waiting-for child 2 only wrapped code AFTER `apply_incoming_changes` succeeded. If `apply_incoming_changes` itself raised, the finally's `shutil.rmtree` was bypassed.

**Solution:**
- Added `handoff_dir_cleaned = False` flag
- Added `shutil.rmtree(handoff_dir, ignore_errors=True)` inside the `except Exception as error:` block that handles `apply_incoming_changes` failure
- Set `handoff_dir_cleaned = True` after cleanup
- Changed the finally block to only cleanup if `handoff_dir_cleaned` is still False

### Fix 5: `_spawn_child`'s temp config file is never deleted

**File:** `agent-platform/supervisor/coordinator.py`

**Problem:** The temp config JSON file was created via `tempfile.mkstemp` and passed to child via `--config-json`, but the FILE ITSELF was never deleted.

**Solution:**
- Modified `_spawn_child` signature to return a third element: `Path | None` (the config path)
- Child processes need the config file to exist at startup and while running, so it cannot be deleted immediately after `_spawn_child` returns
- Modified `run_m1` to track config paths in a dict keyed by session_id; delete config file after `_wait_for_terminal` returns (success OR timeout)
- Modified `run_m2` to track child1_config_path and child2_config_path; delete each after `_wait_for_terminal` returns for that child
- Cleanup happens even on timeout/spawn-failure paths

**Design choice:** I returned the config path alongside session_id and ChildProcess (signature change) rather than using a dict keyed by session_id internally. This keeps the tracking explicit in the return values and makes the code more readable.

### Fix 6: Windows "graceful" termination doesn't reach detached children

**File:** `agent-platform/supervisor/process_spawner.py`

**Problem:** `GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pgid)` cannot reach a process spawned with `DETACHED_PROCESS` (it has no console to receive the signal).

**Solution:** Added a comment above the `GenerateConsoleCtrlEvent` call clarifying that:
- It does not reach `DETACHED_PROCESS` children on Windows
- It is effectively a no-op kept for forward-compatibility/documentation of intent
- The real termination happens via the `TerminateProcess` fallback below

## Test Results

```
264 passed, 4 skipped, 18 deselected, 4 subtests passed in 67.59s
```

Specifically verified:
- `tests/integration/test_recovery.py::test_recover_reattaches_a_still_running_child` - PASSED
- `tests/integration/test_recovery.py::test_recover_marks_a_dead_child_as_lost` - PASSED
- `tests/supervisor/` - All 14 tests PASSED

## Self-Review

The fixes compose coherently:

1. **Config file cleanup interacts correctly with timeout paths:** Fix 5 ensures config files are deleted in `run_m1` after `_wait_for_terminal` returns (whether successfully or with timeout). The timeout branch explicitly calls `config_path.unlink()` before returning. This is safe because:
   - On timeout: we explicitly delete the config file
   - On successful terminal: the config file is also deleted at the end of the loop iteration
   - On spawn failure: `_spawn_child` cleans up the config file before re-raising

2. **Error handling is consistent across run_m1 and run_m2:** Both methods catch both `ProcessSpawnError` and `CoordinatorError("timeout")`, write appropriate terminal events, and return structured envelopes with status "blocked".

3. **The recover() fix maintains backward compatibility:** The exception guards add safety without changing the happy path. Children that were already terminal continue to be skipped; children that are alive continue to get reattached; dead children continue to be marked lost.

## Commit

All fixes applied in a single commit covering the entire review.

**Status:** COMPLETE
