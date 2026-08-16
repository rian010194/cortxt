# Task 3 Report: `coding_loop_cli.py` Implementation

## Summary

Successfully implemented the `coding_loop_cli.py` child entry point for Fas 4 Supervisor. The implementation provides:

1. **Heartbeat mechanism**: A background thread that periodically writes `heartbeat.ping` events to the session log
2. **Session writer monkeypatching**: Scopes `runtime.session_state` function monkeypatching to ensure CodingLoop's session writes are serialized through a single `SessionWriter` instance
3. **CLI entry point**: `main()` function that parses arguments and invokes `run_child()`

## Implementation Details

### Key Design Decisions

The brief's original implementation had a subtle issue with recursion that required correction:

**Problem**: The brief's `_session_writer_scope` context manager monkeypatches `state.create`, `state.load`, `state.latest_sequence`, and `state.append`. However, `SessionWriter` methods like `load()`, `latest_sequence()`, and `append()` all call these same `state.*` functions. When the monkeypatches are applied, calling `writer.load()` inside a patched function causes infinite recursion.

**Solution**: Captured the original `state.*` functions before monkeypatching and used them inside the patched functions:
```python
store_path = writer._store
session_id = writer._session_id

def _patched_create(store, task_id):
    return original["load"](store_path, session_id)

def _patched_load(store, sid):
    return original["load"](store_path, session_id)

# etc.
```

This ensures that `writer.load()`-equivalent operations use the original unpatched `state.load`, avoiding the recursion while still returning the pre-created session from the Supervisor.

### File: `agent-platform/runtime/coding_loop_cli.py`

- `HEARTBEAT_INTERVAL_SECONDS = 5.0`: Default heartbeat interval
- `_start_heartbeat(writer, interval)`: Starts a daemon thread that writes heartbeat events
- `_session_writer_scope(writer)`: Context manager that temporarily monkeypatches session_state functions
- `run_child(...)`: Main entry point that:
  1. Creates a `SessionWriter` for the session
  2. Starts the heartbeat thread
  3. Enters the monkeypatch scope
  4. Creates and runs a `CodingLoop` instance
  5. Appends `result.available` event if the run succeeded and file contents are present
  6. Stops the heartbeat thread in a finally block
- `main(argv)`: CLI entry point that parses arguments and invokes `run_child()`

### File: `agent-platform/tests/runtime/test_coding_loop_cli.py`

- Uses a `_ScriptedPort` stub that returns a known-correct fix for the off-by-one fixture
- Creates a session manually before calling `run_child` to simulate Supervisor behavior
- Verifies:
  - `heartbeat.ping` events are emitted during the run
  - `result.available` event is emitted with file contents
  - Exactly one `session.created` event exists (proving no duplicate session creation)

## Test Results

Test passes successfully:
```
tests/runtime/test_coding_loop_cli.py::test_run_child_emits_heartbeats_and_a_result_available_event PASSED
```

The test uses Docker (`docker_required` marker) and runs against the real `ExecutionSandbox` with a real fixture. The `sandbox_image` fixture handles Docker daemon availability gracefully, skipping with a clear message if Docker is not available.

## Verification

- Test imports `runtime.coding_loop_cli` successfully after implementation
- Test creates session manually and passes `session_id` to `run_child`
- Test verifies heartbeat events and result events are emitted
- Test confirms exactly one `session.created` event (no duplicate creation)

## Commit

```
ad1a27b feat(runtime): add coding_loop_cli child entry point with heartbeat (Fas 4)
```

## Files Modified

1. `agent-platform/runtime/coding_loop_cli.py` - New file (implementation)
2. `agent-platform/tests/runtime/test_coding_loop_cli.py` - New file (test)

## Notes

The implementation differs slightly from the brief in the monkeypatch functions to avoid recursion. The brief's version:
```python
def _patched_load(store, session_id):
    return writer.load()  # This causes recursion
```

The corrected version:
```python
def _patched_load(store, sid):
    return original["load"](store_path, session_id)  # Uses original, no recursion
```

This change is load-bearing for correct operation and does not affect the semantic behavior - it still returns the pre-created session from the Supervisor, which is the key requirement for the Supervisor's "pre-create-then-spawn" design pattern.

---

# Task 3 Fix 1 Report: SessionWriter Lock Fix

## Summary
Fixed Critical finding: the monkeypatched `state.*` functions in `_session_writer_scope` were bypassing `SessionWriter`'s lock, reintroducing the race condition that Task 3 was designed to prevent.

## Problem
The original implementation called `session_state` primitives directly without acquiring `writer._lock`:

```python
def _patched_append(store, sid, expected_sequence, event_type, payload):
    doc = original["load"](store_path, session_id)
    current = original["latest_sequence"](doc)
    return original["append"](store_path, session_id, current, event_type, payload)
```

This allowed two code paths to write to the session log:
- `CodingLoop`'s writes via patched `state.append` — **NO LOCK**
- Heartbeat thread via `writer.append()` — **WITH LOCK**

Both paths could race on `session_state.append()`'s optimistic-concurrency `expected_sequence` check.

## Solution
Wrapped all four patched functions with `writer._lock`:

```python
def _patched_create(store, task_id):
    with writer._lock:
        return original["load"](store_path, session_id)

def _patched_load(store, sid):
    with writer._lock:
        return original["load"](store_path, session_id)

def _patched_latest_sequence(session_doc):
    with writer._lock:
        return original["latest_sequence"](original["load"](store_path, session_id))

def _patched_append(store, sid, expected_sequence, event_type, payload):
    with writer._lock:
        doc = original["load"](store_path, session_id)
        current = original["latest_sequence"](doc)
        return original["append"](store_path, session_id, current, event_type, payload)
```

Using `writer._lock` directly is acceptable here since this module is tightly coupled to `SessionWriter`'s internals by design.

## Test Command and Output
```bash
cd agent-platform && python -m pytest tests/runtime/test_coding_loop_cli.py -v -m docker_required
```

```
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0
configfile: pyproject.toml
collected 1 item

tests/runtime/test_coding_loop_cli.py::test_run_child_emits_heartbeats_and_a_result_available_event PASSED [100%]

============================= 1 passed in 10.90s ==============================
```

## Regression Analysis
The existing test does **not** stress concurrent writes and would not catch this specific bug:
- Test verifies `heartbeat.ping` and `result.available` events exist
- Test verifies `session.created` appears exactly once
- Test does NOT perform stress testing of concurrent writes

The bug was a design-level issue where the monkeypatched functions were bypassing the lock entirely. The test passed because it's a sequential test that doesn't create race conditions — the bug only manifests under concurrent write pressure from the heartbeat thread and CodingLoop.

## Commit
```
08f9e85 fix(runtime): acquire SessionWriter lock in all monkeypatched state functions
```

## Files Modified
- `agent-platform/runtime/coding_loop_cli.py` — Added `with writer._lock:` to all four patched functions
