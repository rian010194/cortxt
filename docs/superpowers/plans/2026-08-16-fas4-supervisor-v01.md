# Fas 4 — Supervisor v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Fas 4's exit criterion (two bounded child runs carried out and integrated without Hermes) by building a Cortxt Supervisor that spawns detached child processes, tracks them via a derived run-tree index, handles dependency joins and budget rollover, and recovers after a process interruption — staged as M1 (two independent child runs) then M2 (sequential dependency with workspace handoff).

**Architecture:** Supervisor and children communicate exclusively through `session_state.py`'s existing hash-chained per-session logs (file-based IPC, no new transport). Children are detached OS processes running a new `coding_loop_cli.py` entry point that wraps Fas 3's unmodified `CodingLoop`. A derived, structurally-unwritable `RunTreeIndex` is rebuilt from session logs on every query — never itself authoritative.

**Tech Stack:** Python 3.11+, pytest, `runtime.session_state` (Fas 2), `runtime.coding.coding_loop.CodingLoop` and `runtime.tools` (Fas 3), `subprocess`/platform APIs for process control, Docker (via Fas 3's `ExecutionSandbox`) for sandboxed test execution in end-to-end tests.

**Spec:** `docs/superpowers/specs/2026-08-16-fas4-supervisor-v01-design.md`

## Global Constraints

- **Precondition:** Fas 3 (`agent/fas3-coding-agent-plan`) must be merged to `main` before Task 1 starts. This plan assumes `runtime/coding/coding_loop.py`, `runtime/tools/`, `runtime/execution/` are present on `main`.
- `session_state.py` is never modified except where a task explicitly says so (Task 4's one-line additive change to `coding_loop.py`, which is a *different* file).
- `CodingLoop`'s control flow, error handling, and existing behavior are never changed — only the one additive `file_contents` capture in Task 4.
- No new IPC transport (sockets/pipes). All Supervisor↔child communication is through `session_state.py` session logs.
- `RunTreeIndex` has exactly one constructor (`build_index`) and no mutation API — enforced by a test, not just a convention.
- Every new module lives under `agent-platform/supervisor/` (Supervisor-specific) or `agent-platform/runtime/` (reusable runtime primitives) per the spec's Components table.
- Platform: Windows 11 primary; POSIX branches are written but only exercised on whichever OS the test runner is.
- Tests requiring Docker use the existing `sandbox_image` fixture (`agent-platform/tests/runtime/conftest.py`), marked `docker_required`, and skip loudly (not silently) when Docker is unreachable — same convention as Fas 3.

---

### Task 1: `SessionWriter` — serialized per-session writes

**Files:**
- Create: `agent-platform/runtime/session_writer.py`
- Test: `agent-platform/tests/runtime/test_session_writer.py`

**Interfaces:**
- Produces: `SessionWriter(store: Path, session_id: str)` with methods `.load() -> dict`, `.latest_sequence() -> int`, `.append(event_type: str, payload: dict) -> dict`. All three serialize through the same `threading.RLock`.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/runtime/test_session_writer.py
from __future__ import annotations

import threading

from runtime import session_state as state
from runtime.session_writer import SessionWriter


def test_concurrent_appends_from_two_threads_never_lose_events(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="writer-race")
    session_id = session["session_id"]
    writer = SessionWriter(store, session_id)

    errors: list[Exception] = []

    def _write_many(prefix: str, count: int) -> None:
        try:
            for i in range(count):
                writer.append(f"{prefix}.tick", {"i": i})
        except Exception as error:  # pragma: no cover - failure path under test
            errors.append(error)

    t1 = threading.Thread(target=_write_many, args=("work", 50))
    t2 = threading.Thread(target=_write_many, args=("heartbeat", 50))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors == []
    doc = state.load(store, session_id)
    assert len(doc["events"]) == 101  # session.created + 100 appended events
    assert [e["sequence"] for e in doc["events"]] == list(range(101))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/runtime/test_session_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'runtime.session_writer'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/runtime/session_writer.py
"""SessionWriter: a per-session, in-process single-writer over session_state.py.

Fas 4 needs a child process's own coding work and its heartbeat timer thread to
both write to the same session log without racing on session_state.append()'s
optimistic-concurrency check (expected_sequence). session_state.py stays a
simple, lock-free primitive (Fas 2 design); SessionWriter is the process-local
serialization point in front of it — one instance per session, shared by every
thread in that process that needs to write.
"""
from __future__ import annotations

import threading
from pathlib import Path

from runtime import session_state as state


class SessionWriter:
    def __init__(self, store: Path, session_id: str) -> None:
        self._store = Path(store)
        self._session_id = session_id
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            return state.load(self._store, self._session_id)

    def latest_sequence(self) -> int:
        with self._lock:
            return state.latest_sequence(state.load(self._store, self._session_id))

    def append(self, event_type: str, payload: dict) -> dict:
        with self._lock:
            seq = state.latest_sequence(state.load(self._store, self._session_id))
            return state.append(self._store, self._session_id, seq, event_type, payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/runtime/test_session_writer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/session_writer.py agent-platform/tests/runtime/test_session_writer.py
git commit -m "feat(runtime): add SessionWriter for serialized per-session writes (Fas 4)"
```

---

### Task 2: `ProcessSpawner` — cross-platform detached process lifecycle

**Files:**
- Create: `agent-platform/supervisor/__init__.py` (empty)
- Create: `agent-platform/supervisor/process_spawner.py`
- Create: `agent-platform/tests/supervisor/__init__.py` (empty)
- Test: `agent-platform/tests/supervisor/test_process_spawner.py`

**Interfaces:**
- Produces: `ChildProcess` (frozen dataclass: `pid: int`, `pgid: int`, `session_id: str`, `start_time: float`); `ProcessSpawner` with `.spawn(session_id: str, args: list[str]) -> ChildProcess`, `.is_alive(child: ChildProcess) -> bool`, `.terminate_gracefully(child: ChildProcess, timeout: float = 5.0) -> bool`; `ProcessSpawnError(reason, message)`.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/supervisor/test_process_spawner.py
from __future__ import annotations

import sys
import time

from supervisor.process_spawner import ProcessSpawner


def test_spawn_is_alive_and_terminate_gracefully_cycle(tmp_path):
    spawner = ProcessSpawner()
    script = tmp_path / "sleeper.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    child = spawner.spawn(session_id="session_test", args=[sys.executable, str(script)])
    try:
        assert spawner.is_alive(child)
        assert spawner.terminate_gracefully(child, timeout=5.0)
        assert not spawner.is_alive(child)
    finally:
        if spawner.is_alive(child):
            spawner.terminate_gracefully(child, timeout=1.0)


def test_is_alive_is_false_once_a_short_lived_process_exits(tmp_path):
    spawner = ProcessSpawner()
    script = tmp_path / "quick.py"
    script.write_text("pass\n", encoding="utf-8")

    child = spawner.spawn(session_id="session_test", args=[sys.executable, str(script)])
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and spawner.is_alive(child):
        time.sleep(0.1)
    assert not spawner.is_alive(child)


def test_start_time_mismatch_is_treated_as_not_alive(tmp_path):
    from dataclasses import replace

    spawner = ProcessSpawner()
    script = tmp_path / "sleeper2.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    child = spawner.spawn(session_id="session_test", args=[sys.executable, str(script)])
    try:
        stale = replace(child, start_time=child.start_time - 999999)
        assert not spawner.is_alive(stale)
    finally:
        spawner.terminate_gracefully(child, timeout=1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/supervisor/test_process_spawner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'supervisor'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/supervisor/process_spawner.py
"""ProcessSpawner: cross-platform detached-process lifecycle for Supervisor.

Hides Windows vs POSIX process-group and signal handling behind one API
(design spec decisions 2 and 8). A detached child must survive its parent's
death — Windows achieves that with CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS;
POSIX with start_new_session=True (setsid). Graceful termination is likewise
platform-specific: CTRL_BREAK_EVENT then TerminateProcess on Windows, SIGTERM
then SIGKILL to the whole process group on POSIX. Liveness is checked via PID
+ process start-time (not PID alone) so a PID reused by an unrelated process
after a long outage is never misread as the original child (decision 6).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


class ProcessSpawnError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class ChildProcess:
    pid: int
    pgid: int
    session_id: str
    start_time: float


def _process_start_time(pid: int) -> float | None:
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wintypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            ok = kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(exit_time),
                ctypes.byref(kernel_time), ctypes.byref(user_time),
            )
            if not ok:
                return None
            value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            return float(value)
        finally:
            kernel32.CloseHandle(handle)
    else:
        stat_path = Path(f"/proc/{pid}/stat")
        if not stat_path.is_file():
            return None
        try:
            fields = stat_path.read_text(encoding="utf-8").split(")")[-1].split()
            return float(fields[19])  # starttime is field 22, 0-indexed after "comm"
        except (OSError, IndexError, ValueError):
            return None


class ProcessSpawner:
    def spawn(self, session_id: str, args: list[str]) -> ChildProcess:
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            process = subprocess.Popen(
                args, creationflags=creationflags, close_fds=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
            pgid = process.pid
        else:
            process = subprocess.Popen(
                args, start_new_session=True, close_fds=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
            pgid = os.getpgid(process.pid)

        start_time = _process_start_time(process.pid)
        if start_time is None:
            raise ProcessSpawnError("spawn_failed", f"could not read start time for pid {process.pid}")
        return ChildProcess(pid=process.pid, pgid=pgid, session_id=session_id, start_time=start_time)

    def is_alive(self, child: ChildProcess) -> bool:
        current = _process_start_time(child.pid)
        return current is not None and current == child.start_time

    def terminate_gracefully(self, child: ChildProcess, timeout: float = 5.0) -> bool:
        if not self.is_alive(child):
            return True
        if sys.platform == "win32":
            import ctypes

            try:
                ctypes.windll.kernel32.GenerateConsoleCtrlEvent(signal.CTRL_BREAK_EVENT, child.pgid)
            except OSError:
                pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not self.is_alive(child):
                    return True
                time.sleep(0.1)
            try:
                PROCESS_TERMINATE = 1
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, child.pid)
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    ctypes.windll.kernel32.CloseHandle(handle)
            except OSError:
                pass
        else:
            try:
                os.killpg(child.pgid, signal.SIGTERM)
            except ProcessLookupError:
                return True
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not self.is_alive(child):
                    return True
                time.sleep(0.1)
            try:
                os.killpg(child.pgid, signal.SIGKILL)
            except ProcessLookupError:
                return True
        return not self.is_alive(child)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/supervisor/test_process_spawner.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/supervisor/__init__.py agent-platform/supervisor/process_spawner.py agent-platform/tests/supervisor/__init__.py agent-platform/tests/supervisor/test_process_spawner.py
git commit -m "feat(supervisor): add cross-platform ProcessSpawner (Fas 4)"
```

---

### Task 3: `coding_loop_cli.py` — child entry point (heartbeat + monkeypatch scope)

**Files:**
- Create: `agent-platform/runtime/coding_loop_cli.py`
- Test: `agent-platform/tests/runtime/test_coding_loop_cli.py`

**Interfaces:**
- Consumes: `runtime.session_writer.SessionWriter` (Task 1); `runtime.coding.coding_loop.CodingLoop` (Fas 3, unmodified); `runtime.coding.coding_profile.CODING_PROFILE` (Fas 3).
- Produces: `run_child(store, session_id, task_id, fixture_dir, port, patch_schema, system_prompt, sandbox_factory=None, profile=None, heartbeat_interval=5.0) -> dict` (the same envelope shape `CodingLoop.run()` returns); `main(argv=None) -> int` (CLI entry point read by `ProcessSpawner.spawn`'s `args`).

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/runtime/test_coding_loop_cli.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime import session_state as state
from runtime.coding.coding_profile import CODING_PROFILE
from runtime.coding_loop_cli import run_child
from runtime.execution.subprocess_sandbox import ExecutionSandbox

VERTICAL = Path(__file__).resolve().parents[2] / "verticals" / "vertical-02-code-fixture"
FIXTURE_DIR = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
PATCH_SCHEMA = json.loads((VERTICAL / "schemas" / "patch-proposal.schema.json").read_text(encoding="utf-8"))
SYSTEM_PROMPT = (VERTICAL / "instructions" / "system-prompt-fix.md").read_text(encoding="utf-8")

_FIXED_RANGES_PY = (
    '"""Small numeric helpers."""\n\n\n'
    'def sum_to(n):\n'
    '    """Return the sum of all integers from 1 to n, inclusive."""\n'
    '    total = 0\n'
    '    for i in range(1, n + 1):\n'
    '        total += i\n'
    '    return total\n'
)


class _ScriptedPort:
    """Stub with CodingLoop's expected .invoke(prompt, schema) -> dict shape,
    returning the known-correct fix. Proves coding_loop_cli's wiring without a
    live model call."""

    def invoke(self, prompt: str, schema: dict) -> dict:
        return {"changes": [{"path": "ranges.py", "new_content": _FIXED_RANGES_PY}],
                "rationale": "range() excluded n; widen to n + 1"}


@pytest.mark.docker_required
def test_run_child_emits_heartbeats_and_a_result_available_event(tmp_path, sandbox_image):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="fas4-cli-wiring")
    session_id = session["session_id"]
    sandbox = ExecutionSandbox(image=sandbox_image, max_executions=4)

    envelope = run_child(
        store=store, session_id=session_id, task_id="fas4-cli-wiring",
        fixture_dir=FIXTURE_DIR, port=_ScriptedPort(), patch_schema=PATCH_SCHEMA,
        system_prompt=SYSTEM_PROMPT, sandbox_factory=lambda caps: sandbox,
        profile=CODING_PROFILE, heartbeat_interval=0.05,
    )

    assert envelope["status"] == "succeeded", envelope.get("reason")
    doc = state.load(store, session_id)
    event_types = [e["event_type"] for e in doc["events"]]
    assert "heartbeat.ping" in event_types
    assert "result.available" in event_types
    # session.create is never called a second time -- exactly one session.created
    assert event_types.count("session.created") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/runtime/test_coding_loop_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'runtime.coding_loop_cli'`
(or SKIPPED with a Docker-unreachable message if no daemon is running — both are
expected states before Task 4/implementation; a skip here is not a pass, per the
`docker_required` convention.)

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/runtime/coding_loop_cli.py
"""Child-process entry point for a Fas 4 Supervisor-spawned coding run.

Fas 3's CodingLoop is used completely unmodified. This module supplies the two
things CodingLoop was never designed to need on its own: (1) a heartbeat signal
a Supervisor process can observe from outside, and (2) a way for that heartbeat
to share CodingLoop's own session log without racing on
session_state.append()'s optimistic concurrency (design spec decision 9's
"Implementation refinement"). Both are achieved by monkeypatching
runtime.session_state's module-level functions, scoped to this process only,
for the duration of the run. CodingLoop's source is never modified.

Supervisor pre-creates the child's session (session_state.create()) before
spawning this process and passes the resulting session_id via --session-id, so
the patched state.create() below returns that existing session rather than
creating a second one.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from runtime import session_state as state
from runtime.session_writer import SessionWriter

HEARTBEAT_INTERVAL_SECONDS = 5.0


def _start_heartbeat(writer: SessionWriter, interval: float) -> threading.Event:
    stop = threading.Event()

    def _tick() -> None:
        while not stop.wait(interval):
            try:
                writer.append("heartbeat.ping", {})
            except Exception:
                # A failed heartbeat write is itself the signal: Supervisor will
                # see a stale heartbeat and treat the child as stuck.
                return

    thread = threading.Thread(target=_tick, daemon=True)
    thread.start()
    return stop


@contextmanager
def _session_writer_scope(writer: SessionWriter):
    original = {
        "create": state.create,
        "load": state.load,
        "latest_sequence": state.latest_sequence,
        "append": state.append,
    }

    def _patched_create(store, task_id):  # noqa: ARG001 - session pre-created by Supervisor
        return writer.load()

    def _patched_load(store, session_id):  # noqa: ARG001
        return writer.load()

    def _patched_latest_sequence(session_doc):  # noqa: ARG001
        return writer.latest_sequence()

    def _patched_append(store, session_id, expected_sequence, event_type, payload):  # noqa: ARG001
        return writer.append(event_type, payload)

    state.create = _patched_create
    state.load = _patched_load
    state.latest_sequence = _patched_latest_sequence
    state.append = _patched_append
    try:
        yield
    finally:
        state.create = original["create"]
        state.load = original["load"]
        state.latest_sequence = original["latest_sequence"]
        state.append = original["append"]


def run_child(store: Path, session_id: str, task_id: str, fixture_dir: Path,
              port, patch_schema: dict, system_prompt: str,
              sandbox_factory=None, profile: dict | None = None,
              heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS) -> dict:
    writer = SessionWriter(store, session_id)
    stop_heartbeat = _start_heartbeat(writer, heartbeat_interval)
    try:
        with _session_writer_scope(writer):
            from runtime.coding.coding_loop import CodingLoop

            loop = CodingLoop(store=store, port=port, patch_schema=patch_schema,
                               system_prompt=system_prompt, sandbox_factory=sandbox_factory,
                               profile=profile)
            envelope = loop.run(task_id=task_id, fixture_dir=fixture_dir)
        if envelope["status"] == "succeeded" and "file_contents" in envelope.get("result", {}):
            writer.append("result.available", {"file_contents": envelope["result"]["file_contents"],
                                                 "cost": envelope.get("cost", {})})
        return envelope
    finally:
        stop_heartbeat.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fas 4 child-process coding run")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--config-json", required=True, type=Path)
    args = parser.parse_args(argv)

    config = json.loads(args.config_json.read_text(encoding="utf-8"))

    from adapters.inference.budget_gate import BudgetGate
    from runtime.coding.coding_profile import CODING_PROFILE
    from runtime.text_inference_port import TextInferencePort

    budget_gate = BudgetGate(max_calls=config.get("max_calls", 1),
                              db_path=args.store / args.session_id / "spend.db")
    port = TextInferencePort(
        model=config["model"], budget_gate=budget_gate,
        provider_evidence=config.get("provider_evidence", {"approved": True}),
        data_class=config.get("data_class", "L0"),
    )
    fixture_dir = Path(config["fixture_dir"])
    patch_schema = json.loads(Path(config["patch_schema_path"]).read_text(encoding="utf-8"))
    system_prompt = Path(config["system_prompt_path"]).read_text(encoding="utf-8")

    envelope = run_child(
        store=args.store, session_id=args.session_id, task_id=config["task_id"],
        fixture_dir=fixture_dir, port=port, patch_schema=patch_schema,
        system_prompt=system_prompt, profile=CODING_PROFILE,
    )
    print(json.dumps({"status": envelope["status"]}))
    return 0 if envelope["status"] == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/runtime/test_coding_loop_cli.py -v -m docker_required`
Expected: PASS if a Docker daemon is reachable; SKIP with a loud reason otherwise
(this is a `docker_required`-gated boundary-adjacent test, same convention as
Fas 3's own sandbox tests — a skip must be followed up in an environment with
Docker before this task can be called verified, not treated as a pass).

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/coding_loop_cli.py agent-platform/tests/runtime/test_coding_loop_cli.py
git commit -m "feat(runtime): add coding_loop_cli child entry point with heartbeat (Fas 4)"
```

---

### Task 4: additive `file_contents` capture in `CodingLoop.run()` (M2 dependency)

**Files:**
- Modify: `agent-platform/runtime/coding/coding_loop.py` (the `_inspect_scope` closure and the `"succeeded"` return statement inside `CodingLoop.run()`)
- Test: `agent-platform/tests/runtime/test_coding_loop_file_contents.py`

**Interfaces:**
- Produces: `CodingLoop.run()`'s returned `result` dict gains one new key on success: `result["file_contents"]: dict[str, str]` (relative path → the file's actual current content in the run workspace, for every path in `result["files_changed"]`).

**Why this is safe:** `_inspect_scope` already computes `captured["files_changed"]` via `diff_workspace` before the `with run_workspace(...) as ws:` block exits. This step captures each changed file's content at the same point — read-only, additive, no control-flow change. See design spec decision 5's "Implementation refinement."

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/runtime/test_coding_loop_file_contents.py
from __future__ import annotations

import json
from pathlib import Path

from adapters.inference.budget_gate import BudgetGate
from runtime.coding.coding_loop import CodingLoop
from runtime.coding.coding_profile import CODING_PROFILE
from runtime.execution.subprocess_sandbox import ExecutionSandbox
import pytest

VERTICAL = Path(__file__).resolve().parents[2] / "verticals" / "vertical-02-code-fixture"
FIXTURE_DIR = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
PATCH_SCHEMA = json.loads((VERTICAL / "schemas" / "patch-proposal.schema.json").read_text(encoding="utf-8"))
SYSTEM_PROMPT = (VERTICAL / "instructions" / "system-prompt-fix.md").read_text(encoding="utf-8")

_FIXED_RANGES_PY = (
    '"""Small numeric helpers."""\n\n\n'
    'def sum_to(n):\n'
    '    """Return the sum of all integers from 1 to n, inclusive."""\n'
    '    total = 0\n'
    '    for i in range(1, n + 1):\n'
    '        total += i\n'
    '    return total\n'
)


class _ScriptedPort:
    def invoke(self, prompt: str, schema: dict) -> dict:
        return {"changes": [{"path": "ranges.py", "new_content": _FIXED_RANGES_PY}],
                "rationale": "range() excluded n; widen to n + 1"}


@pytest.mark.docker_required
def test_succeeded_result_includes_file_contents_for_changed_files(tmp_path, sandbox_image):
    sandbox = ExecutionSandbox(image=sandbox_image, max_executions=4)
    loop = CodingLoop(store=tmp_path / "sessions", port=_ScriptedPort(),
                       patch_schema=PATCH_SCHEMA, system_prompt=SYSTEM_PROMPT,
                       sandbox_factory=lambda caps: sandbox, profile=CODING_PROFILE)

    envelope = loop.run(task_id="file-contents-check", fixture_dir=FIXTURE_DIR)

    assert envelope["status"] == "succeeded"
    assert envelope["result"]["files_changed"] == ["ranges.py"]
    assert envelope["result"]["file_contents"] == {"ranges.py": _FIXED_RANGES_PY}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/runtime/test_coding_loop_file_contents.py -v -m docker_required`
Expected: FAIL with `KeyError: 'file_contents'`

- [ ] **Step 3: Make the additive change**

In `agent-platform/runtime/coding/coding_loop.py`, inside `CodingLoop.run()`'s
`_inspect_scope` closure, change:

```python
                def _inspect_scope(proposal) -> bool:
                    written = apply_patch(write_gate, ws.work, proposal["changes"], caps)
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "patch.admitted", {"paths": written})
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "patch.applied", {"paths": written})
                    diff_text, changed = diff_workspace(ws.baseline, ws.work)
                    captured["diff"] = diff_text
                    captured["files_changed"] = changed
                    return out_of_scope_paths(changed, declared_scope) == []
```

to:

```python
                def _inspect_scope(proposal) -> bool:
                    written = apply_patch(write_gate, ws.work, proposal["changes"], caps)
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "patch.admitted", {"paths": written})
                    seq_ = state.latest_sequence(state.load(self._store, session_id))
                    state.append(self._store, session_id, seq_, "patch.applied", {"paths": written})
                    diff_text, changed = diff_workspace(ws.baseline, ws.work)
                    captured["diff"] = diff_text
                    captured["files_changed"] = changed
                    captured["file_contents"] = {
                        path: (ws.work / path).read_text(encoding="utf-8") for path in changed
                    }
                    return out_of_scope_paths(changed, declared_scope) == []
```

And change the success-path return statement from:

```python
                return {
                    "session_id": session_id,
                    "status": "succeeded",
                    "result": {
                        "diff": captured["diff"],
                        "files_changed": captured["files_changed"],
                        "tests_passed": captured["tests_passed"],
                    },
                    "reason": None,
                    "cost": {"sandbox_executions_used": sandbox.executions_used},
                }
```

to:

```python
                return {
                    "session_id": session_id,
                    "status": "succeeded",
                    "result": {
                        "diff": captured["diff"],
                        "files_changed": captured["files_changed"],
                        "file_contents": captured["file_contents"],
                        "tests_passed": captured["tests_passed"],
                    },
                    "reason": None,
                    "cost": {"sandbox_executions_used": sandbox.executions_used},
                }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/runtime/test_coding_loop_file_contents.py -v -m docker_required`
Expected: PASS. Also re-run Fas 3's existing coding-loop tests to confirm no regression:
`pytest agent-platform/tests/runtime/ -v -k coding_loop`

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/coding/coding_loop.py agent-platform/tests/runtime/test_coding_loop_file_contents.py
git commit -m "feat(runtime): capture changed-file content in CodingLoop result (Fas 4 M2 dependency)"
```

---

### Task 5: `run_tree.py` — derived, structurally-unwritable index

**Files:**
- Create: `agent-platform/supervisor/run_tree.py`
- Test: `agent-platform/tests/supervisor/test_run_tree.py`

**Interfaces:**
- Produces: `ChildStatus` (frozen dataclass: `session_id`, `pid`, `pgid`, `start_time`, `allocated_budget`, `status`, `reason`); `RunTreeIndex` (frozen dataclass: `root_session_id`, `root_status`, `children: tuple[ChildStatus, ...]`, `total_budget`, `allocated_budget`, `join_satisfied`); `build_index(root_session_doc: dict, child_session_docs: dict[str, dict], total_budget: int) -> RunTreeIndex` — the sole constructor.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/supervisor/test_run_tree.py
from __future__ import annotations

from supervisor.run_tree import RunTreeIndex, build_index


def _event(event_type: str, payload: dict) -> dict:
    return {"sequence": 0, "event_type": event_type, "payload": payload,
            "previous_hash": "0" * 64, "timestamp": "2026-08-16T00:00:00Z", "hash": "x"}


def test_build_index_reflects_spawned_children_and_budget():
    root = {
        "session_id": "session_root",
        "events": [
            _event("session.created", {"task_id": "t"}),
            _event("child.spawned", {"session_id": "session_c1", "pid": 111, "pgid": 111,
                                      "start_time": 1.0, "allocated_budget": 5}),
        ],
    }
    child1 = {
        "session_id": "session_c1",
        "events": [
            _event("session.created", {"task_id": "t"}),
            _event("session.terminal", {"status": "succeeded"}),
        ],
    }

    index = build_index(root, {"session_c1": child1}, total_budget=10)

    assert index.root_session_id == "session_root"
    assert index.allocated_budget == 5
    assert index.total_budget == 10
    assert len(index.children) == 1
    assert index.children[0].status == "succeeded"
    assert index.children[0].pid == 111
    assert index.join_satisfied is False


def test_join_satisfied_reflects_the_event():
    root = {
        "session_id": "session_root",
        "events": [
            _event("session.created", {"task_id": "t"}),
            _event("join.satisfied", {"child_session_id": "session_c2"}),
        ],
    }
    index = build_index(root, {}, total_budget=10)
    assert index.join_satisfied is True


def test_no_mutation_api_exists():
    import supervisor.run_tree as run_tree_module

    assert not hasattr(run_tree_module, "update_index")
    assert not hasattr(RunTreeIndex, "update")
    # frozen dataclass: attribute assignment must fail
    root = {"session_id": "session_root", "events": [_event("session.created", {"task_id": "t"})]}
    index = build_index(root, {}, total_budget=10)
    import dataclasses
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        index.root_status = "tampered"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/supervisor/test_run_tree.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'supervisor.run_tree'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/supervisor/run_tree.py
"""RunTreeIndex: a derived, rebuildable, structurally-unwritable projection of a
root session and its children's session logs (design spec decision 4). The
only constructor is build_index(); there is no mutation API, so "always
rebuildable from session-log events" is a structural guarantee, not a
convention to remember.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChildStatus:
    session_id: str
    pid: int | None
    pgid: int | None
    start_time: float | None
    allocated_budget: int
    status: str
    reason: str | None


@dataclass(frozen=True)
class RunTreeIndex:
    root_session_id: str
    root_status: str
    children: tuple[ChildStatus, ...]
    total_budget: int
    allocated_budget: int
    join_satisfied: bool


def _child_status_from_events(session_doc: dict, allocated_budget: int) -> ChildStatus:
    session_id = session_doc["session_id"]
    pid = pgid = start_time = None
    status = "running"
    reason = None
    for event in session_doc["events"]:
        if event["event_type"] == "child.spawned":
            pid = event["payload"].get("pid")
            pgid = event["payload"].get("pgid")
            start_time = event["payload"].get("start_time")
        elif event["event_type"] == "session.terminal":
            status = event["payload"]["status"]
            reason = event["payload"].get("reason")
        elif event["event_type"] == "session.reattached":
            status = "running"
    return ChildStatus(session_id=session_id, pid=pid, pgid=pgid, start_time=start_time,
                        allocated_budget=allocated_budget, status=status, reason=reason)


def build_index(root_session_doc: dict, child_session_docs: dict[str, dict],
                 total_budget: int) -> RunTreeIndex:
    root_status = "running"
    allocated = 0
    spawned: dict[str, int] = {}

    for event in root_session_doc["events"]:
        if event["event_type"] == "child.spawned":
            spawned[event["payload"]["session_id"]] = event["payload"].get("allocated_budget", 0)
            allocated += event["payload"].get("allocated_budget", 0)
        elif event["event_type"] == "budget.transferred":
            allocated += event["payload"].get("amount", 0)
        elif event["event_type"] == "session.terminal":
            root_status = event["payload"]["status"]

    children = tuple(
        _child_status_from_events(child_session_docs[sid], budget)
        for sid, budget in spawned.items()
        if sid in child_session_docs
    )

    join_satisfied = any(e["event_type"] == "join.satisfied" for e in root_session_doc["events"])

    return RunTreeIndex(
        root_session_id=root_session_doc["session_id"],
        root_status=root_status,
        children=children,
        total_budget=total_budget,
        allocated_budget=allocated,
        join_satisfied=join_satisfied,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/supervisor/test_run_tree.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-platform/supervisor/run_tree.py agent-platform/tests/supervisor/test_run_tree.py
git commit -m "feat(supervisor): add derived, structurally-unwritable RunTreeIndex (Fas 4)"
```

---

### Task 6: `budget.py` — post-hoc rollover

**Files:**
- Create: `agent-platform/supervisor/budget.py`
- Test: `agent-platform/tests/supervisor/test_budget.py`

**Interfaces:**
- Produces: `reclaimable_surplus(child_allocated: int, child_spent: int) -> int`; `next_child_budget(base_allocation: int, reclaimed_surplus: int) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/supervisor/test_budget.py
from __future__ import annotations

from supervisor.budget import next_child_budget, reclaimable_surplus


def test_reclaimable_surplus_is_the_unused_portion():
    assert reclaimable_surplus(child_allocated=10, child_spent=6) == 4


def test_reclaimable_surplus_is_zero_when_fully_spent_or_overspent():
    assert reclaimable_surplus(child_allocated=10, child_spent=10) == 0
    assert reclaimable_surplus(child_allocated=10, child_spent=11) == 0


def test_next_child_budget_adds_reclaimed_surplus_to_base():
    assert next_child_budget(base_allocation=5, reclaimed_surplus=4) == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/supervisor/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'supervisor.budget'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/supervisor/budget.py
"""Post-hoc budget rollover between sequential children (design spec decision
7). Only unused surplus from an already-terminal child rolls forward; there is
no mid-flight borrowing, since Fas 4 v0.1's M1/M2 scenarios never run two
children that both need to draw against the same pool concurrently.
"""
from __future__ import annotations


def reclaimable_surplus(child_allocated: int, child_spent: int) -> int:
    if child_spent >= child_allocated:
        return 0
    return child_allocated - child_spent


def next_child_budget(base_allocation: int, reclaimed_surplus: int) -> int:
    return base_allocation + reclaimed_surplus
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/supervisor/test_budget.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-platform/supervisor/budget.py agent-platform/tests/supervisor/test_budget.py
git commit -m "feat(supervisor): add post-hoc budget rollover (Fas 4)"
```

---

### Task 7: `workspace_handoff.py` — M2 changed-file handoff via `apply_patch`

**Files:**
- Create: `agent-platform/supervisor/workspace_handoff.py`
- Test: `agent-platform/tests/supervisor/test_workspace_handoff.py`

**Interfaces:**
- Consumes: `runtime.tools.apply_patch`, `runtime.tools.WriteGate`, `runtime.tools.PatchError` (Fas 3, unmodified); `runtime.execution.write_policy.WriteCaps`, `runtime.execution.write_policy.WritePolicyViolation` (Fas 3, unmodified).
- Produces: `apply_incoming_changes(work_root: Path, file_contents: dict[str, str], caps: WriteCaps) -> list[str]` (the list of written relative paths, same shape `apply_patch` returns).

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/supervisor/test_workspace_handoff.py
from __future__ import annotations

import pytest

from runtime.execution.write_policy import WriteCaps, WritePolicyViolation
from supervisor.workspace_handoff import apply_incoming_changes


def test_applies_incoming_file_contents_to_an_existing_file(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "ranges.py").write_text("def sum_to(n):\n    return 0\n", encoding="utf-8")

    written = apply_incoming_changes(
        work_root=work_root,
        file_contents={"ranges.py": "def sum_to(n):\n    return n\n"},
        caps=WriteCaps(max_files=1, max_bytes_per_file=1024, max_changed_lines=10, max_executions=4),
    )

    assert written == ["ranges.py"]
    assert (work_root / "ranges.py").read_text(encoding="utf-8") == "def sum_to(n):\n    return n\n"


def test_raises_when_incoming_changes_exceed_caps(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "ranges.py").write_text("x = 1\n", encoding="utf-8")
    (work_root / "stats.py").write_text("y = 2\n", encoding="utf-8")

    with pytest.raises((WritePolicyViolation, Exception)):
        apply_incoming_changes(
            work_root=work_root,
            file_contents={"ranges.py": "x = 2\n", "stats.py": "y = 3\n"},
            caps=WriteCaps(max_files=1, max_bytes_per_file=1024, max_changed_lines=10, max_executions=4),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/supervisor/test_workspace_handoff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'supervisor.workspace_handoff'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/supervisor/workspace_handoff.py
"""M2 workspace handoff: reshape child 1's file_contents into Fas 3's
apply_patch changes schema and apply it to child 2's fresh copy-in workspace,
before child 2 starts. No new patch-application logic — Fas 3's apply_patch is
reused unmodified (design spec decision 5's "Implementation refinement").
"""
from __future__ import annotations

from pathlib import Path

from runtime.execution.write_policy import WriteCaps
from runtime.tools import WriteGate, apply_patch


def apply_incoming_changes(work_root: Path, file_contents: dict[str, str],
                            caps: WriteCaps) -> list[str]:
    work_root = Path(work_root)
    gate = WriteGate(allowed_roots=[work_root])
    changes = [{"path": path, "new_content": content} for path, content in file_contents.items()]
    return apply_patch(gate, work_root, changes, caps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/supervisor/test_workspace_handoff.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-platform/supervisor/workspace_handoff.py agent-platform/tests/supervisor/test_workspace_handoff.py
git commit -m "feat(supervisor): add M2 workspace handoff via unmodified apply_patch (Fas 4)"
```

---

### Task 8: two new fixtures — M1's independent second child, M2's dependent child

**Files:**
- Create: `verticals/vertical-02-code-fixture/evals/synthetic/002-independent-strings/fixture.yaml`
- Create: `verticals/vertical-02-code-fixture/evals/synthetic/002-independent-strings/workspace/strings_util.py`
- Create: `verticals/vertical-02-code-fixture/evals/synthetic/002-independent-strings/workspace/test_strings_util.py`
- Create: `verticals/vertical-02-code-fixture/evals/synthetic/003-stats-depends-on-ranges/fixture.yaml`
- Create: `verticals/vertical-02-code-fixture/evals/synthetic/003-stats-depends-on-ranges/workspace/ranges.py`
- Create: `verticals/vertical-02-code-fixture/evals/synthetic/003-stats-depends-on-ranges/workspace/stats.py`
- Create: `verticals/vertical-02-code-fixture/evals/synthetic/003-stats-depends-on-ranges/workspace/test_stats.py`
- Test: `agent-platform/tests/runtime/test_fas4_fixtures.py`

**Design:**
- **002 (M1's independent second child):** a standalone off-by-one-style bug, unrelated to 001, with its own declared_scope. Proves M1's two children are genuinely independent.
- **003 (M2's dependent child):** ships the *same unfixed* `ranges.py` as 001 (M2 overwrites it via the handoff before this fixture's baseline check runs), plus a new `stats.py` with its own independent bug (`average_to` divides by `n - 1` instead of `n`) whose `declared_scope` is `stats.py` only — `ranges.py` is deliberately **out of scope**, so this child cannot fix `ranges.py` itself. `test_stats.py::test_average_to_five` can only pass once *both* child 1's `ranges.py` fix (via handoff) *and* child 2's own `stats.py` fix are applied — this is what makes the join a real dependency, not just sequencing.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/runtime/test_fas4_fixtures.py
from __future__ import annotations

from pathlib import Path

import yaml

VERTICAL = Path(__file__).resolve().parents[2] / "verticals" / "vertical-02-code-fixture"


def test_002_fixture_is_genuinely_broken_and_independent_of_001():
    fixture_dir = VERTICAL / "evals" / "synthetic" / "002-independent-strings"
    fixture = yaml.safe_load((fixture_dir / "fixture.yaml").read_text(encoding="utf-8"))
    assert fixture["declared_scope"] == ["strings_util.py"]

    source = (fixture_dir / "workspace" / "strings_util.py").read_text(encoding="utf-8")
    namespace: dict = {}
    exec(compile(source, "strings_util.py", "exec"), namespace)  # noqa: S102 - fixture is repo-owned
    assert namespace["last_word"]("the quick brown fox") != "fox"


def test_003_fixture_cannot_pass_without_the_ranges_handoff():
    """Proves the join is real: stats.py's own fix alone is not enough while
    ranges.py is still buggy (as shipped, matching 001's unfixed state)."""
    fixture_dir = VERTICAL / "evals" / "synthetic" / "003-stats-depends-on-ranges"
    fixture = yaml.safe_load((fixture_dir / "fixture.yaml").read_text(encoding="utf-8"))
    assert fixture["declared_scope"] == ["stats.py"]

    namespace: dict = {"__name__": "ranges"}
    ranges_source = (fixture_dir / "workspace" / "ranges.py").read_text(encoding="utf-8")
    exec(compile(ranges_source, "ranges.py", "exec"), namespace)  # noqa: S102
    assert namespace["sum_to"](5) != 15, "ranges.py must ship broken, exactly like 001"

    stats_source = (fixture_dir / "workspace" / "stats.py").read_text(encoding="utf-8")
    stats_ns: dict = dict(namespace)
    exec(compile(stats_source, "stats.py", "exec"), stats_ns)  # noqa: S102
    # Fixing only the n - 1 bug in stats.py, with ranges.py still broken, must
    # still fail -- this is the whole point of the dependency.
    def _average_to_if_stats_fixed(n):
        total = stats_ns["sum_to"](n)
        return total / n
    assert _average_to_if_stats_fixed(5) != 3.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/runtime/test_fas4_fixtures.py -v`
Expected: FAIL (fixture files don't exist yet)

- [ ] **Step 3: Author the fixtures**

```yaml
# verticals/vertical-02-code-fixture/evals/synthetic/002-independent-strings/fixture.yaml
fixture_id: v02-syn-code-002
fixture_type: positive
description: >
  Single-file bug, independent of 001: last_word returns the wrong token
  (off-by-one index into the split words list). Used as M1's second,
  independent child run.
workspace_dir: ./workspace
declared_scope:
  - strings_util.py
caps:
  max_files: 1
  max_bytes_per_file: 16384
  max_changed_lines: 20
  max_executions: 4
expected_failing_test: test_strings_util.py::test_last_word
human_review_required: false
```

```python
# verticals/vertical-02-code-fixture/evals/synthetic/002-independent-strings/workspace/strings_util.py
"""Small string helpers."""


def last_word(sentence):
    """Return the last word of a space-separated sentence."""
    words = sentence.split(" ")
    return words[len(words) - 2]
```

```python
# verticals/vertical-02-code-fixture/evals/synthetic/002-independent-strings/workspace/test_strings_util.py
from strings_util import last_word


def test_last_word():
    assert last_word("the quick brown fox") == "fox"


def test_last_word_single_word():
    assert last_word("hello") == "hello"
```

```yaml
# verticals/vertical-02-code-fixture/evals/synthetic/003-stats-depends-on-ranges/fixture.yaml
fixture_id: v02-syn-code-003
fixture_type: positive
description: >
  Ships the same unfixed ranges.py as 001-off-by-one, plus stats.py with its
  own independent bug (divides by n - 1 instead of n). declared_scope
  DELIBERATELY excludes ranges.py -- this child cannot fix ranges.py itself,
  so test_average_to_five can only pass once Fas 4's M2 handoff has already
  applied child 1's ranges.py fix. Used as M2's dependent second child.
workspace_dir: ./workspace
declared_scope:
  - stats.py
caps:
  max_files: 1
  max_bytes_per_file: 16384
  max_changed_lines: 20
  max_executions: 4
expected_failing_test: test_stats.py::test_average_to_five
human_review_required: false
```

```python
# verticals/vertical-02-code-fixture/evals/synthetic/003-stats-depends-on-ranges/workspace/ranges.py
"""Small numeric helpers."""


def sum_to(n):
    """Return the sum of all integers from 1 to n, inclusive."""
    total = 0
    for i in range(1, n):
        total += i
    return total
```

```python
# verticals/vertical-02-code-fixture/evals/synthetic/003-stats-depends-on-ranges/workspace/stats.py
"""Small statistics helpers built on ranges.sum_to."""
from ranges import sum_to


def average_to(n):
    """Return the mean of the integers from 1 to n, inclusive."""
    return sum_to(n) / (n - 1)
```

```python
# verticals/vertical-02-code-fixture/evals/synthetic/003-stats-depends-on-ranges/workspace/test_stats.py
from stats import average_to


def test_average_to_five():
    assert average_to(5) == 3.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/runtime/test_fas4_fixtures.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add verticals/vertical-02-code-fixture/evals/synthetic/002-independent-strings verticals/vertical-02-code-fixture/evals/synthetic/003-stats-depends-on-ranges agent-platform/tests/runtime/test_fas4_fixtures.py
git commit -m "feat(verticals): add Fas 4 M1/M2 fixtures (002-independent, 003-dependent)"
```

---

### Task 9: `coordinator.py` — M1 flow (two independent child runs)

**Files:**
- Create: `agent-platform/supervisor/coordinator.py`
- Test: `agent-platform/tests/integration/test_m1_independent_children.py`

**Interfaces:**
- Consumes: `supervisor.process_spawner.ProcessSpawner` (Task 2); `supervisor.run_tree.build_index` (Task 5); `runtime.session_state` (Fas 2); `runtime.coding_loop_cli` (Task 3, launched as a subprocess via `[sys.executable, "-m", "runtime.coding_loop_cli", ...]`).
- Produces: `Coordinator(store: Path, spawner: ProcessSpawner | None = None)` with `.run_m1(task_id: str, child_specs: list[dict], total_budget: int, poll_interval: float = 0.5, timeout: float = 120.0) -> dict` — `child_specs` is `[{"fixture_dir": Path, "config": dict, "allocated_budget": int}, ...]`; returns a merged result envelope: `{"run_id", "status", "children": [...]}`.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/integration/test_m1_independent_children.py
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from supervisor.coordinator import Coordinator

VERTICAL = Path(__file__).resolve().parents[2] / "verticals" / "vertical-02-code-fixture"
FIXTURE_1 = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
FIXTURE_2 = VERTICAL / "evals" / "synthetic" / "002-independent-strings"
PATCH_SCHEMA_PATH = VERTICAL / "schemas" / "patch-proposal.schema.json"
SYSTEM_PROMPT_PATH = VERTICAL / "instructions" / "system-prompt-fix.md"


@pytest.mark.real_inference
@pytest.mark.docker_required
def test_m1_two_independent_children_succeed_and_merge(tmp_path):
    model = os.environ.get("CORTXT_INFERENCE_MODEL")
    if not model:
        pytest.skip("CORTXT_INFERENCE_MODEL not set")

    store = tmp_path / "sessions"
    coordinator = Coordinator(store=store)

    def _config(fixture_dir: Path, task_id: str) -> dict:
        return {
            "task_id": task_id, "model": model, "fixture_dir": str(fixture_dir),
            "patch_schema_path": str(PATCH_SCHEMA_PATH), "system_prompt_path": str(SYSTEM_PROMPT_PATH),
        }

    envelope = coordinator.run_m1(
        task_id="fas4-m1-exit-criterion",
        child_specs=[
            {"fixture_dir": FIXTURE_1, "config": _config(FIXTURE_1, "m1-child-1"), "allocated_budget": 1},
            {"fixture_dir": FIXTURE_2, "config": _config(FIXTURE_2, "m1-child-2"), "allocated_budget": 1},
        ],
        total_budget=2, timeout=180.0,
    )

    assert envelope["status"] == "succeeded", envelope
    assert len(envelope["children"]) == 2
    assert {c["status"] for c in envelope["children"]} == {"succeeded"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/integration/test_m1_independent_children.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'supervisor.coordinator'`
(or SKIP if `CORTXT_INFERENCE_MODEL` is unset — expected before this is wired
into CI/manual verification, same convention as Fas 3's real_inference tests).

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/supervisor/coordinator.py
"""Coordinator: root-session lifecycle, spawning, joins, integration
(design spec §7.2 state machine, decision 5's M1/M2 staging).
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from runtime import session_state as state
from supervisor.process_spawner import ChildProcess, ProcessSpawner
from supervisor.run_tree import build_index


class CoordinatorError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


TERMINAL_CHILD_STATUSES = {"succeeded", "blocked", "failed", "cancelled", "lost"}


class Coordinator:
    def __init__(self, store: Path, spawner: ProcessSpawner | None = None) -> None:
        self._store = Path(store)
        self._spawner = spawner or ProcessSpawner()

    def _spawn_child(self, root_session_id: str, config: dict, allocated_budget: int) -> tuple[str, ChildProcess]:
        child_session = state.create(self._store, task_id=config["task_id"])
        child_session_id = child_session["session_id"]

        config_path = Path(tempfile.mkstemp(prefix="fas4-child-config-", suffix=".json")[1])
        config_path.write_text(json.dumps(config), encoding="utf-8")

        args = [sys.executable, "-m", "runtime.coding_loop_cli",
                "--session-id", child_session_id, "--store", str(self._store),
                "--config-json", str(config_path)]
        child_process = self._spawner.spawn(session_id=child_session_id, args=args)

        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "child.spawned", {
            "session_id": child_session_id, "pid": child_process.pid, "pgid": child_process.pgid,
            "start_time": child_process.start_time, "allocated_budget": allocated_budget,
        })
        return child_session_id, child_process

    def _wait_for_terminal(self, session_id: str, poll_interval: float, deadline: float) -> dict:
        while time.monotonic() < deadline:
            doc = state.load(self._store, session_id)
            for event in doc["events"]:
                if event["event_type"] == "session.terminal":
                    return doc
            time.sleep(poll_interval)
        raise CoordinatorError("timeout", f"child session {session_id} never reached a terminal state")

    def run_m1(self, task_id: str, child_specs: list[dict], total_budget: int,
               poll_interval: float = 0.5, timeout: float = 120.0) -> dict:
        root_session = state.create(self._store, task_id=task_id)
        root_session_id = root_session["session_id"]

        child_processes: list[tuple[str, ChildProcess]] = []
        for spec in child_specs:
            session_id, process = self._spawn_child(root_session_id, spec["config"], spec["allocated_budget"])
            child_processes.append((session_id, process))

        deadline = time.monotonic() + timeout
        results = []
        for session_id, _process in child_processes:
            doc = self._wait_for_terminal(session_id, poll_interval, deadline)
            terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
            results.append({"session_id": session_id, "status": terminal["payload"]["status"],
                             "reason": terminal["payload"].get("reason")})

        root_doc = state.load(self._store, root_session_id)
        child_docs = {sid: state.load(self._store, sid) for sid, _ in child_processes}
        index = build_index(root_doc, child_docs, total_budget=total_budget)

        overall_status = "succeeded" if all(c["status"] == "succeeded" for c in results) else "blocked"
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "session.terminal", {"status": overall_status})

        return {"run_id": root_session_id, "status": overall_status, "children": results,
                "budget": {"total": index.total_budget, "allocated": index.allocated_budget}}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
export CORTXT_INFERENCE_MODEL=<a configured model>
pytest agent-platform/tests/integration/test_m1_independent_children.py -v -m "real_inference and docker_required"
```
Expected: PASS in an environment with Docker and inference credentials configured
(manual verification step, same convention as Fas 3's exit-criterion test — a
skip is not a pass for this criterion).

- [ ] **Step 5: Commit**

```bash
git add agent-platform/supervisor/coordinator.py agent-platform/tests/integration/test_m1_independent_children.py
git commit -m "feat(supervisor): add Coordinator.run_m1 for two independent child runs (Fas 4)"
```

---

### Task 10: `coordinator.py` — M2 flow (sequential dependency + workspace handoff)

**Files:**
- Modify: `agent-platform/supervisor/coordinator.py` (add `run_m2`)
- Test: `agent-platform/tests/integration/test_m2_sequential_handoff.py`

**Interfaces:**
- Consumes: `supervisor.workspace_handoff.apply_incoming_changes` (Task 7); `supervisor.budget.reclaimable_surplus`/`next_child_budget` (Task 6); `runtime.coding.run_workspace.run_workspace`, `runtime.execution.write_policy.WriteCaps` (Fas 3, unmodified, for materializing child 2's writable copy before spawning).
- Produces: `Coordinator.run_m2(task_id: str, child1_spec: dict, child2_spec: dict, total_budget: int, poll_interval: float = 0.5, timeout: float = 120.0) -> dict` — same envelope shape as `run_m1`.

**Design note:** child 2's fixture directory is copied to a Supervisor-owned
temp directory before spawning, and `apply_incoming_changes` is applied to that
copy's `workspace/` subdirectory — so when `coding_loop_cli`'s `CodingLoop.run()`
does its own internal copy-in from that directory, both `ws.work` and
`ws.baseline` already contain child 1's fix, exactly as if the fixture had
shipped that way. This mutates a *copy*, never the original fixture files
under `verticals/`.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/integration/test_m2_sequential_handoff.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

from supervisor.coordinator import Coordinator

VERTICAL = Path(__file__).resolve().parents[2] / "verticals" / "vertical-02-code-fixture"
FIXTURE_1 = VERTICAL / "evals" / "synthetic" / "001-off-by-one"
FIXTURE_2 = VERTICAL / "evals" / "synthetic" / "003-stats-depends-on-ranges"
PATCH_SCHEMA_PATH = VERTICAL / "schemas" / "patch-proposal.schema.json"
SYSTEM_PROMPT_PATH = VERTICAL / "instructions" / "system-prompt-fix.md"


@pytest.mark.real_inference
@pytest.mark.docker_required
def test_m2_child_two_only_succeeds_because_of_the_handoff(tmp_path):
    model = os.environ.get("CORTXT_INFERENCE_MODEL")
    if not model:
        pytest.skip("CORTXT_INFERENCE_MODEL not set")

    store = tmp_path / "sessions"
    coordinator = Coordinator(store=store)

    def _config(fixture_dir: Path, task_id: str) -> dict:
        return {
            "task_id": task_id, "model": model, "fixture_dir": str(fixture_dir),
            "patch_schema_path": str(PATCH_SCHEMA_PATH), "system_prompt_path": str(SYSTEM_PROMPT_PATH),
        }

    envelope = coordinator.run_m2(
        task_id="fas4-m2-exit-criterion",
        child1_spec={"fixture_dir": FIXTURE_1, "config": _config(FIXTURE_1, "m2-child-1"), "allocated_budget": 1},
        child2_spec={"fixture_dir": FIXTURE_2, "config": _config(FIXTURE_2, "m2-child-2"), "allocated_budget": 1},
        total_budget=2, timeout=180.0,
    )

    assert envelope["status"] == "succeeded", envelope
    assert len(envelope["children"]) == 2
    assert envelope["children"][0]["status"] == "succeeded"
    assert envelope["children"][1]["status"] == "succeeded"


def test_m2_child_two_never_spawned_if_child_one_fails(tmp_path):
    """child 1's fixture_dir points at an empty workspace, so run_workspace()
    raises RunWorkspaceError("source_empty", ...) before any inference call or
    sandbox use (confirmed against CodingLoop.run()'s actual source: the
    fixture.yaml read and the `with run_workspace(source) as ws:` block both
    happen before self._sandbox_factory(caps) or any port.invoke() call) --
    CodingLoop.run() returns status "blocked" deterministically, with no
    Docker daemon or real model needed. Proves the join-failure path without
    depending on real_inference/docker_required at all."""
    store = tmp_path / "sessions"
    coordinator = Coordinator(store=store)

    broken_fixture_dir = tmp_path / "broken-fixture"
    (broken_fixture_dir / "workspace").mkdir(parents=True)
    (broken_fixture_dir / "fixture.yaml").write_text(
        "fixture_id: broken\nfixture_type: positive\ndescription: deliberately empty\n"
        "workspace_dir: ./workspace\ndeclared_scope: []\n"
        "caps: {max_files: 1, max_bytes_per_file: 1024, max_changed_lines: 10, max_executions: 1}\n"
        "expected_failing_test: none\nhuman_review_required: false\n",
        encoding="utf-8",
    )
    # workspace/ deliberately left empty -> run_workspace() raises source_empty

    broken_config = {"task_id": "m2-child-1-broken", "model": "unused",
                      "fixture_dir": str(broken_fixture_dir), "patch_schema_path": str(PATCH_SCHEMA_PATH),
                      "system_prompt_path": str(SYSTEM_PROMPT_PATH)}
    good_config = {"task_id": "m2-child-2", "model": "unused",
                   "fixture_dir": str(FIXTURE_2), "patch_schema_path": str(PATCH_SCHEMA_PATH),
                   "system_prompt_path": str(SYSTEM_PROMPT_PATH)}

    envelope = coordinator.run_m2(
        task_id="fas4-m2-join-failure",
        child1_spec={"fixture_dir": broken_fixture_dir, "config": broken_config, "allocated_budget": 1},
        child2_spec={"fixture_dir": FIXTURE_2, "config": good_config, "allocated_budget": 1},
        total_budget=2, timeout=60.0,
    )

    assert envelope["status"] == "blocked"
    assert len(envelope["children"]) == 1  # child 2 never spawned
    assert envelope["children"][0]["status"] == "blocked"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/integration/test_m2_sequential_handoff.py -v`
Expected: FAIL with `AttributeError: 'Coordinator' object has no attribute 'run_m2'`

- [ ] **Step 3: Write minimal implementation**

Add to `agent-platform/supervisor/coordinator.py`:

```python
import shutil

from runtime.execution.write_policy import WriteCaps
from supervisor.budget import next_child_budget, reclaimable_surplus
from supervisor.workspace_handoff import apply_incoming_changes


class Coordinator:
    # ... (existing __init__, _spawn_child, _wait_for_terminal, run_m1 unchanged) ...

    def run_m2(self, task_id: str, child1_spec: dict, child2_spec: dict, total_budget: int,
               poll_interval: float = 0.5, timeout: float = 120.0) -> dict:
        root_session = state.create(self._store, task_id=task_id)
        root_session_id = root_session["session_id"]

        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "join.waiting", {"waiting_on": "child_1"})

        deadline = time.monotonic() + timeout
        child1_session_id, _ = self._spawn_child(root_session_id, child1_spec["config"],
                                                   child1_spec["allocated_budget"])
        child1_doc = self._wait_for_terminal(child1_session_id, poll_interval, deadline)
        child1_terminal = next(e for e in child1_doc["events"] if e["event_type"] == "session.terminal")
        child1_status = child1_terminal["payload"]["status"]

        results = [{"session_id": child1_session_id, "status": child1_status,
                    "reason": child1_terminal["payload"].get("reason")}]

        if child1_status != "succeeded":
            seq = state.latest_sequence(state.load(self._store, root_session_id))
            state.append(self._store, root_session_id, seq, "session.terminal",
                         {"status": "blocked", "reason": f"child_1 terminated as {child1_status}; join cannot succeed"})
            return {"run_id": root_session_id, "status": "blocked", "children": results,
                    "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"]}}

        result_event = next(e for e in child1_doc["events"] if e["event_type"] == "result.available")
        file_contents = result_event["payload"]["file_contents"]

        spent = result_event["payload"].get("cost", {}).get("sandbox_executions_used", 0)
        surplus = reclaimable_surplus(child1_spec["allocated_budget"], spent)
        child2_budget = next_child_budget(child2_spec["allocated_budget"], surplus)
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "budget.reclaimed", {"amount": surplus})
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "budget.transferred", {"amount": surplus})

        handoff_dir = Path(tempfile.mkdtemp(prefix="fas4-m2-handoff-"))
        shutil.copytree(child2_spec["fixture_dir"], handoff_dir, dirs_exist_ok=True)
        try:
            apply_incoming_changes(
                work_root=handoff_dir / "workspace", file_contents=file_contents,
                caps=WriteCaps(max_files=len(file_contents) or 1, max_bytes_per_file=65536,
                                max_changed_lines=1000, max_executions=4),
            )
        except Exception as error:
            seq = state.latest_sequence(state.load(self._store, root_session_id))
            state.append(self._store, root_session_id, seq, "session.terminal",
                         {"status": "blocked", "reason": f"patch handoff failed: {error}"})
            return {"run_id": root_session_id, "status": "blocked", "children": results,
                    "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"]}}

        child2_config = dict(child2_spec["config"], fixture_dir=str(handoff_dir))
        child2_session_id, _ = self._spawn_child(root_session_id, child2_config, child2_budget)
        child2_doc = self._wait_for_terminal(child2_session_id, poll_interval, deadline)
        child2_terminal = next(e for e in child2_doc["events"] if e["event_type"] == "session.terminal")
        child2_status = child2_terminal["payload"]["status"]
        results.append({"session_id": child2_session_id, "status": child2_status,
                         "reason": child2_terminal["payload"].get("reason")})

        if child2_status == "succeeded":
            seq = state.latest_sequence(state.load(self._store, root_session_id))
            state.append(self._store, root_session_id, seq, "join.satisfied", {"child_session_id": child2_session_id})

        overall_status = "succeeded" if child2_status == "succeeded" else "blocked"
        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "session.terminal", {"status": overall_status})

        return {"run_id": root_session_id, "status": overall_status, "children": results,
                "budget": {"total": total_budget, "allocated": child1_spec["allocated_budget"] + child2_budget}}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
export CORTXT_INFERENCE_MODEL=<a configured model>
pytest agent-platform/tests/integration/test_m2_sequential_handoff.py -v -m "real_inference and docker_required"
```
Expected: PASS in an environment with Docker and inference credentials configured.

- [ ] **Step 5: Commit**

```bash
git add agent-platform/supervisor/coordinator.py agent-platform/tests/integration/test_m2_sequential_handoff.py
git commit -m "feat(supervisor): add Coordinator.run_m2 for sequential dependency + handoff (Fas 4)"
```

---

### Task 11: cancellation — operator CLI + auto-cancel

**Files:**
- Create: `agent-platform/supervisor/supervisor_cli.py`
- Modify: `agent-platform/supervisor/coordinator.py` (add `cancel_root`)
- Test: `agent-platform/tests/supervisor/test_cancellation.py`

**Interfaces:**
- Produces: `Coordinator.cancel_root(root_session_id: str, poll_interval: float = 0.5, timeout: float = 30.0) -> dict` (propagates `terminate_gracefully` to every non-terminal child recorded in the root session's `child.spawned` events, returns `{"cancelled": [session_id, ...]}`); `supervisor_cli.py` with `run`/`status`/`cancel` subcommands (operator entry point — proves the exit criterion is reachable "without Hermes").

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/supervisor/test_cancellation.py
from __future__ import annotations

import sys
import time

from runtime import session_state as state
from supervisor.coordinator import Coordinator
from supervisor.process_spawner import ProcessSpawner


def test_cancel_root_terminates_a_running_child(tmp_path):
    store = tmp_path / "sessions"
    coordinator = Coordinator(store=store)
    root_session = state.create(store, task_id="cancel-test")
    root_session_id = root_session["session_id"]

    child_session = state.create(store, task_id="cancel-test-child")
    child_session_id = child_session["session_id"]
    script = tmp_path / "sleeper.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=child_session_id, args=[sys.executable, str(script)])
    coordinator._spawner = spawner

    seq = state.latest_sequence(state.load(store, root_session_id))
    state.append(store, root_session_id, seq, "child.spawned", {
        "session_id": child_session_id, "pid": child.pid, "pgid": child.pgid,
        "start_time": child.start_time, "allocated_budget": 1,
    })

    assert spawner.is_alive(child)
    result = coordinator.cancel_root(root_session_id)
    assert child_session_id in result["cancelled"]

    time.sleep(0.5)
    assert not spawner.is_alive(child)
    doc = state.load(store, child_session_id)
    terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
    assert terminal["payload"]["status"] == "cancelled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/supervisor/test_cancellation.py -v`
Expected: FAIL with `AttributeError: 'Coordinator' object has no attribute 'cancel_root'`

- [ ] **Step 3: Write minimal implementation**

Add to `agent-platform/supervisor/coordinator.py`:

```python
    def cancel_root(self, root_session_id: str, poll_interval: float = 0.5, timeout: float = 30.0) -> dict:
        root_doc = state.load(self._store, root_session_id)
        cancelled: list[str] = []
        for event in root_doc["events"]:
            if event["event_type"] != "child.spawned":
                continue
            child_session_id = event["payload"]["session_id"]
            child_doc = state.load(self._store, child_session_id)
            already_terminal = any(e["event_type"] == "session.terminal" for e in child_doc["events"])
            if already_terminal:
                continue
            child = ChildProcess(pid=event["payload"]["pid"], pgid=event["payload"]["pgid"],
                                  session_id=child_session_id, start_time=event["payload"]["start_time"])
            self._spawner.terminate_gracefully(child, timeout=timeout)
            seq = state.latest_sequence(state.load(self._store, child_session_id))
            state.append(self._store, child_session_id, seq, "session.terminal", {"status": "cancelled"})
            cancelled.append(child_session_id)

        seq = state.latest_sequence(state.load(self._store, root_session_id))
        state.append(self._store, root_session_id, seq, "session.terminal", {"status": "cancelled"})
        return {"cancelled": cancelled}
```

```python
# agent-platform/supervisor/supervisor_cli.py
"""Operator entry point for Fas 4 Supervisor -- proves the exit criterion is
reachable without Hermes as an intermediary."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime import session_state as state
from supervisor.coordinator import Coordinator
from supervisor.run_tree import build_index


def _status(store: Path, root_session_id: str) -> dict:
    root_doc = state.load(store, root_session_id)
    child_ids = [e["payload"]["session_id"] for e in root_doc["events"]
                 if e["event_type"] == "child.spawned"]
    child_docs = {sid: state.load(store, sid) for sid in child_ids}
    index = build_index(root_doc, child_docs, total_budget=0)
    return {"root_status": index.root_status,
            "children": [{"session_id": c.session_id, "status": c.status} for c in index.children]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fas 4 Supervisor operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    status_parser = sub.add_parser("status")
    status_parser.add_argument("--store", required=True, type=Path)
    status_parser.add_argument("--root-session-id", required=True)

    cancel_parser = sub.add_parser("cancel")
    cancel_parser.add_argument("--store", required=True, type=Path)
    cancel_parser.add_argument("--root-session-id", required=True)

    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(_status(args.store, args.root_session_id)))
    elif args.command == "cancel":
        coordinator = Coordinator(store=args.store)
        result = coordinator.cancel_root(args.root_session_id)
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/supervisor/test_cancellation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-platform/supervisor/coordinator.py agent-platform/supervisor/supervisor_cli.py agent-platform/tests/supervisor/test_cancellation.py
git commit -m "feat(supervisor): add cancel_root and operator CLI (Fas 4)"
```

---

### Task 12: recovery — PID + start-time reattach, `lost` status

**Files:**
- Modify: `agent-platform/supervisor/coordinator.py` (add `recover`)
- Test: `agent-platform/tests/integration/test_recovery.py`

**Interfaces:**
- Produces: `Coordinator.recover() -> list[dict]` — scans the store for root sessions without a terminal `session.terminal` event, and for each non-terminal `child.spawned` entry, checks `ProcessSpawner.is_alive`; reattaches (`session.reattached` event) or marks `lost` (`session.terminal {status: "lost", reason: ...}`). Returns one summary dict per root session processed.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/integration/test_recovery.py
from __future__ import annotations

import sys
import time

from runtime import session_state as state
from supervisor.coordinator import Coordinator
from supervisor.process_spawner import ProcessSpawner


def test_recover_reattaches_a_still_running_child(tmp_path):
    store = tmp_path / "sessions"
    root_session = state.create(store, task_id="recovery-test")
    root_session_id = root_session["session_id"]
    child_session = state.create(store, task_id="recovery-test-child")
    child_session_id = child_session["session_id"]

    script = tmp_path / "sleeper.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=child_session_id, args=[sys.executable, str(script)])

    seq = state.latest_sequence(state.load(store, root_session_id))
    state.append(store, root_session_id, seq, "child.spawned", {
        "session_id": child_session_id, "pid": child.pid, "pgid": child.pgid,
        "start_time": child.start_time, "allocated_budget": 1,
    })

    try:
        # simulate a brand-new Supervisor process (fresh Coordinator instance)
        coordinator = Coordinator(store=store, spawner=ProcessSpawner())
        summaries = coordinator.recover()

        assert any(s["root_session_id"] == root_session_id for s in summaries)
        child_doc = state.load(store, child_session_id)
        event_types = [e["event_type"] for e in child_doc["events"]]
        assert "session.reattached" in event_types
    finally:
        spawner.terminate_gracefully(child, timeout=5.0)


def test_recover_marks_a_dead_child_as_lost(tmp_path):
    store = tmp_path / "sessions"
    root_session = state.create(store, task_id="recovery-lost-test")
    root_session_id = root_session["session_id"]
    child_session = state.create(store, task_id="recovery-lost-test-child")
    child_session_id = child_session["session_id"]

    script = tmp_path / "quick.py"
    script.write_text("pass\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=child_session_id, args=[sys.executable, str(script)])

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and spawner.is_alive(child):
        time.sleep(0.1)

    seq = state.latest_sequence(state.load(store, root_session_id))
    state.append(store, root_session_id, seq, "child.spawned", {
        "session_id": child_session_id, "pid": child.pid, "pgid": child.pgid,
        "start_time": child.start_time, "allocated_budget": 1,
    })

    coordinator = Coordinator(store=store, spawner=ProcessSpawner())
    coordinator.recover()

    child_doc = state.load(store, child_session_id)
    terminal = next(e for e in child_doc["events"] if e["event_type"] == "session.terminal")
    assert terminal["payload"]["status"] == "lost"

    root_doc = state.load(store, root_session_id)
    root_terminal = next(e for e in root_doc["events"] if e["event_type"] == "session.terminal")
    assert root_terminal["payload"]["status"] == "blocked"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/integration/test_recovery.py -v`
Expected: FAIL with `AttributeError: 'Coordinator' object has no attribute 'recover'`

- [ ] **Step 3: Write minimal implementation**

Add to `agent-platform/supervisor/coordinator.py`:

```python
    def recover(self) -> list[dict]:
        summaries: list[dict] = []
        if not self._store.is_dir():
            return summaries

        for session_dir in self._store.iterdir():
            if not session_dir.is_dir():
                continue
            session_id = session_dir.name
            try:
                doc = state.load(self._store, session_id)
            except state.SessionError:
                continue

            is_root = any(e["event_type"] == "child.spawned" for e in doc["events"])
            if not is_root:
                continue
            already_terminal = any(e["event_type"] == "session.terminal" for e in doc["events"])
            if already_terminal:
                continue

            any_lost = False
            for event in doc["events"]:
                if event["event_type"] != "child.spawned":
                    continue
                child_session_id = event["payload"]["session_id"]
                child_doc = state.load(self._store, child_session_id)
                if any(e["event_type"] == "session.terminal" for e in child_doc["events"]):
                    continue

                child = ChildProcess(pid=event["payload"]["pid"], pgid=event["payload"]["pgid"],
                                      session_id=child_session_id, start_time=event["payload"]["start_time"])
                if self._spawner.is_alive(child):
                    seq = state.latest_sequence(state.load(self._store, child_session_id))
                    state.append(self._store, child_session_id, seq, "session.reattached", {})
                else:
                    any_lost = True
                    seq = state.latest_sequence(state.load(self._store, child_session_id))
                    state.append(self._store, child_session_id, seq, "session.terminal",
                                 {"status": "lost", "reason": "child lost during supervisor outage"})

            if any_lost:
                seq = state.latest_sequence(state.load(self._store, session_id))
                state.append(self._store, session_id, seq, "session.terminal",
                             {"status": "blocked", "reason": "child lost during supervisor outage"})

            summaries.append({"root_session_id": session_id, "any_lost": any_lost})
        return summaries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/integration/test_recovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-platform/supervisor/coordinator.py agent-platform/tests/integration/test_recovery.py
git commit -m "feat(supervisor): add PID+start-time recovery reattach and lost status (Fas 4)"
```

---

### Task 13: heartbeat staleness detection — auto-cancel a stuck child

**Files:**
- Modify: `agent-platform/supervisor/run_tree.py` (add `last_heartbeat_at` to `ChildStatus`)
- Modify: `agent-platform/supervisor/coordinator.py` (`_wait_for_terminal` gains a staleness check; `run_m1`/`run_m2` pass the spawned `ChildProcess` through)
- Test: `agent-platform/tests/supervisor/test_heartbeat_staleness.py`

**Why this task exists:** the design spec's Error handling table commits to
"heartbeat missing beyond `N × interval` → Supervisor auto-cancels" as an
in-scope v0.1 behavior. Tasks 1 and 3 built heartbeat *emission* only; nothing
yet reads it back. This closes that gap (found during this plan's self-review)
before implementation starts.

**Interfaces:**
- Produces: `ChildStatus.last_heartbeat_at: str | None` (ISO8601 timestamp of the child's most recent `heartbeat.ping` event, or `None` if it has never pinged). `Coordinator._wait_for_terminal(self, session_id: str, child: ChildProcess, poll_interval: float, deadline: float, heartbeat_interval: float = 5.0, stale_multiplier: int = 3) -> dict` (signature change — now takes `child` and `heartbeat_interval`).

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/supervisor/test_heartbeat_staleness.py
from __future__ import annotations

import sys
import time

from runtime import session_state as state
from supervisor.coordinator import Coordinator, CoordinatorError
from supervisor.process_spawner import ProcessSpawner


def test_wait_for_terminal_cancels_a_child_with_no_recent_heartbeat(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="stale-heartbeat-test")
    session_id = session["session_id"]

    script = tmp_path / "silent_sleeper.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=session_id, args=[sys.executable, str(script)])

    coordinator = Coordinator(store=store, spawner=spawner)
    try:
        doc = coordinator._wait_for_terminal(
            session_id, child, poll_interval=0.05, deadline=time.monotonic() + 5.0,
            heartbeat_interval=0.1, stale_multiplier=2,
        )
        terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
        assert terminal["payload"]["status"] == "blocked"
        assert terminal["payload"]["reason"] == "heartbeat timeout"
        assert not spawner.is_alive(child)
    finally:
        if spawner.is_alive(child):
            spawner.terminate_gracefully(child, timeout=1.0)


def test_wait_for_terminal_does_not_cancel_a_child_with_recent_heartbeats(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="fresh-heartbeat-test")
    session_id = session["session_id"]
    from runtime.session_writer import SessionWriter

    writer = SessionWriter(store, session_id)
    writer.append("heartbeat.ping", {})

    script = tmp_path / "quick2.py"
    script.write_text("pass\n", encoding="utf-8")
    spawner = ProcessSpawner()
    child = spawner.spawn(session_id=session_id, args=[sys.executable, str(script)])

    seq = state.latest_sequence(state.load(store, session_id))
    state.append(store, session_id, seq, "session.terminal", {"status": "succeeded"})

    coordinator = Coordinator(store=store, spawner=spawner)
    doc = coordinator._wait_for_terminal(
        session_id, child, poll_interval=0.05, deadline=time.monotonic() + 5.0,
        heartbeat_interval=10.0, stale_multiplier=3,
    )
    terminal = next(e for e in doc["events"] if e["event_type"] == "session.terminal")
    assert terminal["payload"]["status"] == "succeeded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/supervisor/test_heartbeat_staleness.py -v`
Expected: FAIL with `TypeError: _wait_for_terminal() missing 1 required positional argument: 'child'`

- [ ] **Step 3: Write minimal implementation**

In `agent-platform/supervisor/run_tree.py`, add the field to `ChildStatus` and populate it:

```python
@dataclass(frozen=True)
class ChildStatus:
    session_id: str
    pid: int | None
    pgid: int | None
    start_time: float | None
    allocated_budget: int
    status: str
    reason: str | None
    last_heartbeat_at: str | None
```

```python
def _child_status_from_events(session_doc: dict, allocated_budget: int) -> ChildStatus:
    session_id = session_doc["session_id"]
    pid = pgid = start_time = None
    status = "running"
    reason = None
    last_heartbeat_at = None
    for event in session_doc["events"]:
        if event["event_type"] == "child.spawned":
            pid = event["payload"].get("pid")
            pgid = event["payload"].get("pgid")
            start_time = event["payload"].get("start_time")
        elif event["event_type"] == "heartbeat.ping":
            last_heartbeat_at = event["timestamp"]
        elif event["event_type"] == "session.terminal":
            status = event["payload"]["status"]
            reason = event["payload"].get("reason")
        elif event["event_type"] == "session.reattached":
            status = "running"
    return ChildStatus(session_id=session_id, pid=pid, pgid=pgid, start_time=start_time,
                        allocated_budget=allocated_budget, status=status, reason=reason,
                        last_heartbeat_at=last_heartbeat_at)
```

In `agent-platform/supervisor/coordinator.py`, add the staleness helper and update
`_wait_for_terminal`'s signature, plus its two call sites:

```python
from datetime import datetime, timezone

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0
DEFAULT_STALE_MULTIPLIER = 3


def _parse_event_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _is_heartbeat_stale(doc: dict, heartbeat_interval: float, stale_multiplier: int) -> bool:
    last_heartbeat_ts = None
    created_ts = None
    for event in doc["events"]:
        if event["event_type"] == "heartbeat.ping":
            last_heartbeat_ts = event["timestamp"]
        elif event["event_type"] == "session.created":
            created_ts = event["timestamp"]
    reference = last_heartbeat_ts or created_ts
    if reference is None:
        return False
    age = (datetime.now(timezone.utc) - _parse_event_timestamp(reference)).total_seconds()
    return age > heartbeat_interval * stale_multiplier
```

```python
    def _wait_for_terminal(self, session_id: str, child: ChildProcess, poll_interval: float,
                            deadline: float, heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
                            stale_multiplier: int = DEFAULT_STALE_MULTIPLIER) -> dict:
        while time.monotonic() < deadline:
            doc = state.load(self._store, session_id)
            for event in doc["events"]:
                if event["event_type"] == "session.terminal":
                    return doc
            if _is_heartbeat_stale(doc, heartbeat_interval, stale_multiplier):
                self._spawner.terminate_gracefully(child, timeout=5.0)
                seq = state.latest_sequence(state.load(self._store, session_id))
                return state.append(self._store, session_id, seq, "session.terminal",
                                     {"status": "blocked", "reason": "heartbeat timeout"})
            time.sleep(poll_interval)
        raise CoordinatorError("timeout", f"child session {session_id} never reached a terminal state")
```

Update `run_m1`'s call site from:

```python
        for session_id, _process in child_processes:
            doc = self._wait_for_terminal(session_id, poll_interval, deadline)
```

to:

```python
        for session_id, process in child_processes:
            doc = self._wait_for_terminal(session_id, process, poll_interval, deadline)
```

Update `run_m2`'s two call sites similarly: `self._wait_for_terminal(child1_session_id, poll_interval, deadline)` becomes `self._wait_for_terminal(child1_session_id, child1_process, poll_interval, deadline)` (capture `child1_process` from `_spawn_child`'s return value instead of discarding it), and the same for child 2.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/supervisor/test_heartbeat_staleness.py -v`
Expected: PASS. Then re-run Tasks 9–12's tests to confirm the signature change
didn't break them: `pytest agent-platform/tests/integration/ agent-platform/tests/supervisor/ -v`

- [ ] **Step 5: Commit**

```bash
git add agent-platform/supervisor/run_tree.py agent-platform/supervisor/coordinator.py agent-platform/tests/supervisor/test_heartbeat_staleness.py
git commit -m "feat(supervisor): auto-cancel a child whose heartbeat has gone stale (Fas 4)"
```

---

### Task 14: full regression pass

**Files:** none new — verification only.

- [ ] **Step 1: Run the full agent-platform test suite**

Run: `pytest agent-platform/ -v` (default markers — `docker_required` and
`real_inference` tests will skip without Docker/credentials, same as always)
Expected: all non-skipped tests PASS, zero regressions in Fas 2/Fas 3 tests.

- [ ] **Step 2: Run the Docker-gated and real-inference-gated tests manually**

Run (with Docker running and `CORTXT_INFERENCE_MODEL`/credentials set):
```bash
pytest agent-platform/ -v -m docker_required
pytest agent-platform/ -v -m "real_inference and docker_required"
```
Expected: all PASS. This is the actual Fas 4 v0.1 exit-criterion proof — a
skip here is not a pass, per the same convention `test_coding_loop_real_inference.py`
established for Fas 3.

- [ ] **Step 3: Commit a checklist note (optional, if any manual step above needs follow-up)**

If Docker or inference credentials were unavailable in this environment, record
that explicitly (mirroring `docs/superpowers/plans/2026-08-16-fas3-exit-criterion-checklist.md`'s
pattern) rather than silently treating skipped tests as verified.

```bash
git add docs/superpowers/plans/2026-08-16-fas4-exit-criterion-checklist.md
git commit -m "docs(supervisor): record Fas 4 exit-criterion verification status"
```
