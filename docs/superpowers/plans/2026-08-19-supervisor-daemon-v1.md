# Cortxt Supervisor Daemon v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Cortxt Supervisor from an invocation-only mechanism into a
long-running background loop that dispatches already-approved
(`workflow:ready`) GitHub issues through the existing, proven dispatch v0.1
path, gates every result automatically instead of per-commit human review,
and earns unattended autonomy per engine/task-shape class instead of
assuming it.

**Architecture:** A new `agent-platform/daemon/` package adds five small,
independently-testable modules (Evidence Gate, GitHub scanner, session
budget, autonomy tracker, stop-flag) plus a `DaemonLoop` that wires them
together and calls the *existing* `routing.engine_manifest.route()` +
`routing.hermes_invoker.invoke_hermes()` for actual dispatch — not
`supervisor.coordinator.Coordinator`, which is RLM child-recursion
machinery, a different concern out of scope for a flat one-issue-at-a-time
loop. Status is written by extending `cli/status.py`'s existing
`write_snapshot()` with a `daemon` key, reusing its established
merge-preserving convention rather than inventing a second status file.

**Tech Stack:** Python 3.11/3.12 (this repo's existing interpreter split —
see `agent-platform/pyproject.toml`), pytest, `gh` CLI (GitHub issue
scanning, already the pattern `scripts/dispatcher.py` uses), no new
third-party dependencies.

**Spec:** `docs/superpowers/specs/2026-08-19-supervisor-daemon-v1-design.md`

## Global Constraints

- No new third-party dependencies (matches this repo's existing
  two-dependency posture — `pyyaml`, `jsonschema` — per ADR-024's Context).
- Windows is the primary dev/runtime platform (per environment) — the
  emergency-stop mechanism uses a stop-flag file the loop polls each
  iteration, not POSIX signals, since reliable arbitrary-process signaling
  is not available on Windows.
- The daemon must never claim or act on a GitHub issue that isn't already
  labeled `workflow:ready` — no inventing work, no expanding scope (spec's
  Non-goals + Error handling; the #174/#175 failure mode this whole design
  exists to avoid).
- 0 model calls in every test except the one explicit end-to-end proof step
  (Task 11), which is manual and not part of the default `pytest` run —
  matches `reasoning/geometric`'s existing testing discipline referenced in
  the spec.
- Every new module lives under `agent-platform/` (a proper, pytest-discovered
  package per `agent-platform/pyproject.toml`) — not `scripts/`, which has no
  `__init__.py` and is loaded via `importlib.util.spec_from_file_location` in
  its own tests, a packaging boundary `routing/hermes_invoker.py`'s docstring
  already documents avoiding for the same reason.
- Follow this repo's existing dataclass + `from __future__ import
  annotations` style (see `agent-platform/routing/engine_manifest.py`,
  `agent-platform/reasoning/geometric/trajectory.py`).

---

## File Structure

```
agent-platform/daemon/
  __init__.py              # exports
  evidence_gate.py          # GateOutcome, evaluate_gate()
  github_scanner.py         # list_ready_issues()
  budget.py                 # SessionBudget
  autonomy.py                # AutonomyTracker
  stop_flag.py               # request_stop(), is_stop_requested(), clear_stop()
  loop.py                    # DaemonLoop (wires everything together)

agent-platform/tests/daemon/
  test_evidence_gate.py
  test_github_scanner.py
  test_budget.py
  test_autonomy.py
  test_stop_flag.py
  test_loop.py

agent-platform/cli/status.py       # MODIFY: write_snapshot() gains daemon= param
agent-platform/cli/unified_cli.py  # MODIFY: new `daemon` subcommand group
```

---

### Task 1: Evidence Gate

**Files:**
- Create: `agent-platform/daemon/evidence_gate.py`
- Test: `agent-platform/tests/daemon/test_evidence_gate.py`

**Interfaces:**
- Produces: `GateOutcome(decision: str, reason: str)` where `decision` is one
  of `"proceed"`, `"pause"`, `"freeze"`; `evaluate_gate(result_envelope:
  dict, *, checkpoint_required: bool, allowed_artifact_prefixes: tuple[str,
  ...] = ()) -> GateOutcome`.

- [ ] **Step 1: Write the failing tests**

```python
# agent-platform/tests/daemon/test_evidence_gate.py
import pytest

from daemon.evidence_gate import GateOutcome, evaluate_gate


def _envelope(**overrides) -> dict:
    base = {"status": "succeeded", "evidence": [{"kind": "test_run", "detail": "5 passed"}],
            "artifacts": ["session:abc", "engine:hermes"]}
    base.update(overrides)
    return base


def test_non_succeeded_status_freezes():
    outcome = evaluate_gate(_envelope(status="failed"), checkpoint_required=False)
    assert outcome.decision == "freeze"
    assert "failed" in outcome.reason


def test_missing_evidence_freezes_even_if_status_succeeded():
    outcome = evaluate_gate(_envelope(evidence=[]), checkpoint_required=False)
    assert outcome.decision == "freeze"
    assert "evidence" in outcome.reason


def test_artifact_outside_allowed_prefix_freezes():
    outcome = evaluate_gate(
        _envelope(artifacts=["session:abc", "file:/etc/passwd"]),
        checkpoint_required=False,
        allowed_artifact_prefixes=("session:", "engine:"),
    )
    assert outcome.decision == "freeze"
    assert "file:/etc/passwd" in outcome.reason


def test_clean_pass_with_checkpoint_not_required_proceeds():
    outcome = evaluate_gate(_envelope(), checkpoint_required=False)
    assert outcome.decision == "proceed"


def test_clean_pass_with_checkpoint_required_pauses():
    outcome = evaluate_gate(_envelope(), checkpoint_required=True)
    assert outcome.decision == "pause"


def test_no_artifact_prefix_restriction_means_no_scope_check():
    outcome = evaluate_gate(_envelope(artifacts=["anything:goes"]), checkpoint_required=False)
    assert outcome.decision == "proceed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/daemon/test_evidence_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daemon'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/daemon/evidence_gate.py
"""Automated per-run gate (target: docs/superpowers/specs/
2026-08-19-supervisor-daemon-v1-design.md, "Evidence Gate"). Replaces a
human's per-commit review with three checks: terminal status, presence of
real evidence, and artifact-scope match. A self-reported "succeeded" with no
evidence is a gate failure, not a pass (the #174/#175 false-completion
failure mode this exists to catch).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateOutcome:
    decision: str  # "proceed" | "pause" | "freeze"
    reason: str


def evaluate_gate(
    result_envelope: dict,
    *,
    checkpoint_required: bool,
    allowed_artifact_prefixes: tuple[str, ...] = (),
) -> GateOutcome:
    status = result_envelope.get("status")
    if status != "succeeded":
        return GateOutcome("freeze", f"terminal status was {status!r}, not 'succeeded'")

    evidence = result_envelope.get("evidence") or []
    if not evidence:
        return GateOutcome("freeze", "no evidence in result envelope (unverifiable completion)")

    if allowed_artifact_prefixes:
        artifacts = result_envelope.get("artifacts") or []
        for artifact in artifacts:
            if not artifact.startswith(allowed_artifact_prefixes):
                return GateOutcome("freeze", f"artifact outside allowed scope: {artifact}")

    if checkpoint_required:
        return GateOutcome("pause", "clean result, but this engine's checkpoint_required=True")
    return GateOutcome("proceed", "clean result, checkpoint not required")
```

```python
# agent-platform/daemon/__init__.py
"""Cortxt Supervisor Daemon v1 (target: docs/superpowers/specs/
2026-08-19-supervisor-daemon-v1-design.md)."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/daemon/test_evidence_gate.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/daemon/__init__.py agent-platform/daemon/evidence_gate.py agent-platform/tests/daemon/test_evidence_gate.py
git commit -m "daemon: add Evidence Gate (automated pass/pause/freeze decision)"
```

---

### Task 2: GitHub ready-issue scanner

**Files:**
- Create: `agent-platform/daemon/github_scanner.py`
- Test: `agent-platform/tests/daemon/test_github_scanner.py`

**Interfaces:**
- Produces: `list_ready_issues(repo: str, *, label: str = "workflow:ready",
  run_subprocess: Callable[..., subprocess.CompletedProcess] =
  subprocess.run, timeout_seconds: int = 30) -> list[dict]` — each dict has
  at least `number` (int) and `title` (str), from `gh issue list --json`.

- [ ] **Step 1: Write the failing tests**

```python
# agent-platform/tests/daemon/test_github_scanner.py
import json
import subprocess

import pytest

from daemon.github_scanner import list_ready_issues


def _fake_run(returncode=0, stdout="[]", stderr=""):
    def _runner(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)
    return _runner


def test_parses_gh_json_output():
    issues = [{"number": 42, "title": "Fix widget", "labels": [{"name": "workflow:ready"}]}]
    runner = _fake_run(stdout=json.dumps(issues))
    result = list_ready_issues("owner/repo", run_subprocess=runner)
    assert result == issues


def test_passes_correct_gh_args():
    captured = {}

    def _runner(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    list_ready_issues("owner/repo", run_subprocess=_runner)
    assert captured["args"][:3] == ["gh", "issue", "list"]
    assert "--repo" in captured["args"] and "owner/repo" in captured["args"]
    assert "--label" in captured["args"] and "workflow:ready" in captured["args"]


def test_nonzero_exit_raises():
    runner = _fake_run(returncode=1, stderr="gh: authentication required")
    with pytest.raises(RuntimeError, match="authentication required"):
        list_ready_issues("owner/repo", run_subprocess=runner)


def test_custom_label():
    captured = {}

    def _runner(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    list_ready_issues("owner/repo", label="workflow:blocked", run_subprocess=_runner)
    assert "workflow:blocked" in captured["args"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/daemon/test_github_scanner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.github_scanner'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/daemon/github_scanner.py
"""Lists workflow:ready GitHub issues (dispatch-contract.md's source of
truth) via the gh CLI -- same subprocess pattern scripts/dispatcher.py's
GitHubOps uses, reimplemented narrowly here rather than imported across the
scripts/ <-> agent-platform/ packaging boundary routing/hermes_invoker.py's
docstring already documents avoiding.
"""
from __future__ import annotations

import json
import subprocess
from typing import Callable

GhRunner = Callable[..., "subprocess.CompletedProcess[str]"]


def list_ready_issues(
    repo: str,
    *,
    label: str = "workflow:ready",
    run_subprocess: GhRunner = subprocess.run,
    timeout_seconds: int = 30,
) -> list[dict]:
    result = run_subprocess(
        ["gh", "issue", "list", "--repo", repo, "--label", label,
         "--state", "open", "--json", "number,title,labels"],
        capture_output=True, text=True, timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh issue list failed: {result.stderr.strip()}")
    return json.loads(result.stdout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/daemon/test_github_scanner.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/daemon/github_scanner.py agent-platform/tests/daemon/test_github_scanner.py
git commit -m "daemon: add workflow:ready GitHub issue scanner"
```

---

### Task 3: Session budget ceiling

**Files:**
- Create: `agent-platform/daemon/budget.py`
- Test: `agent-platform/tests/daemon/test_budget.py`

**Interfaces:**
- Produces: `SessionBudget(max_cost_usd: float, max_wall_clock_seconds:
  float)` with `.record_cost(cost_usd: float) -> None`, `.exhausted() ->
  bool`, `.spent_usd: float` (readable attribute).

- [ ] **Step 1: Write the failing tests**

```python
# agent-platform/tests/daemon/test_budget.py
import time

from daemon.budget import SessionBudget


def test_starts_not_exhausted():
    b = SessionBudget(max_cost_usd=10.0, max_wall_clock_seconds=3600.0)
    assert not b.exhausted()


def test_cost_ceiling_exhausts():
    b = SessionBudget(max_cost_usd=1.0, max_wall_clock_seconds=3600.0)
    b.record_cost(0.5)
    assert not b.exhausted()
    b.record_cost(0.6)
    assert b.exhausted()
    assert b.spent_usd == 1.1


def test_wall_clock_ceiling_exhausts(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])
    b = SessionBudget(max_cost_usd=1000.0, max_wall_clock_seconds=60.0)
    assert not b.exhausted()
    fake_time[0] += 61.0
    assert b.exhausted()


def test_negative_cost_rejected():
    b = SessionBudget(max_cost_usd=10.0, max_wall_clock_seconds=3600.0)
    try:
        b.record_cost(-1.0)
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/daemon/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.budget'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/daemon/budget.py
"""Daemon-level total budget ceiling (spec: dispatch-contract.md already
requires max_cost_usd/max_runtime_seconds per individual request; this adds
a whole-session ceiling that halts the loop independent of per-run limits).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SessionBudget:
    max_cost_usd: float
    max_wall_clock_seconds: float
    spent_usd: float = 0.0
    _started_at: float = field(default_factory=time.monotonic)

    def record_cost(self, cost_usd: float) -> None:
        if cost_usd < 0:
            raise ValueError(f"cost_usd must be >= 0, got {cost_usd}")
        self.spent_usd += cost_usd

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def exhausted(self) -> bool:
        return self.spent_usd >= self.max_cost_usd or self.elapsed_seconds() >= self.max_wall_clock_seconds
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/daemon/test_budget.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/daemon/budget.py agent-platform/tests/daemon/test_budget.py
git commit -m "daemon: add session-level budget ceiling"
```

---

### Task 4: Autonomy tracker (earn-your-unattended-unlock)

**Files:**
- Create: `agent-platform/daemon/autonomy.py`
- Test: `agent-platform/tests/daemon/test_autonomy.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `AutonomyTracker(unlock_threshold: int = 3)` with
  `.record_pass(engine_id: str, task_shape: str, clean: bool) -> None` and
  `.is_unlocked(engine_id: str, task_shape: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# agent-platform/tests/daemon/test_autonomy.py
from daemon.autonomy import AutonomyTracker


def test_starts_locked():
    t = AutonomyTracker()
    assert not t.is_unlocked("hermes", "research")


def test_unlocks_after_three_consecutive_clean_passes():
    t = AutonomyTracker(unlock_threshold=3)
    t.record_pass("hermes", "research", clean=True)
    t.record_pass("hermes", "research", clean=True)
    assert not t.is_unlocked("hermes", "research")
    t.record_pass("hermes", "research", clean=True)
    assert t.is_unlocked("hermes", "research")


def test_dirty_pass_resets_streak():
    t = AutonomyTracker(unlock_threshold=3)
    t.record_pass("hermes", "research", clean=True)
    t.record_pass("hermes", "research", clean=True)
    t.record_pass("hermes", "research", clean=False)
    t.record_pass("hermes", "research", clean=True)
    assert not t.is_unlocked("hermes", "research")  # only 1 clean since the reset


def test_classes_are_independent():
    t = AutonomyTracker(unlock_threshold=1)
    t.record_pass("hermes", "research", clean=True)
    assert t.is_unlocked("hermes", "research")
    assert not t.is_unlocked("hermes", "coding")
    assert not t.is_unlocked("claude-direct", "research")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/daemon/test_autonomy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.autonomy'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/daemon/autonomy.py
"""Earned unattended autonomy per (engine_id, task_shape) class (spec:
"Autonomy model - earned, not assumed"). Mirrors the N=3
consecutive-clean-runs rule target-architecture.md §23 already applies to
Fas 4+ exit criteria, applied here to the daemon's own track record instead
of a new invented threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AutonomyTracker:
    unlock_threshold: int = 3
    _streaks: dict[tuple[str, str], int] = field(default_factory=dict)

    def record_pass(self, engine_id: str, task_shape: str, clean: bool) -> None:
        key = (engine_id, task_shape)
        self._streaks[key] = (self._streaks.get(key, 0) + 1) if clean else 0

    def is_unlocked(self, engine_id: str, task_shape: str) -> bool:
        return self._streaks.get((engine_id, task_shape), 0) >= self.unlock_threshold
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/daemon/test_autonomy.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/daemon/autonomy.py agent-platform/tests/daemon/test_autonomy.py
git commit -m "daemon: add per-class autonomy tracker (N=3 clean passes to unlock)"
```

---

### Task 5: Stop-flag emergency stop

**Files:**
- Create: `agent-platform/daemon/stop_flag.py`
- Test: `agent-platform/tests/daemon/test_stop_flag.py`

**Interfaces:**
- Produces: `request_stop(state_dir: Path) -> None`,
  `is_stop_requested(state_dir: Path) -> bool`, `clear_stop(state_dir: Path)
  -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# agent-platform/tests/daemon/test_stop_flag.py
from pathlib import Path

from daemon.stop_flag import clear_stop, is_stop_requested, request_stop


def test_not_requested_by_default(tmp_path: Path):
    assert not is_stop_requested(tmp_path)


def test_request_then_detected(tmp_path: Path):
    request_stop(tmp_path)
    assert is_stop_requested(tmp_path)


def test_clear_removes_request(tmp_path: Path):
    request_stop(tmp_path)
    clear_stop(tmp_path)
    assert not is_stop_requested(tmp_path)


def test_clear_when_not_requested_is_noop(tmp_path: Path):
    clear_stop(tmp_path)  # must not raise
    assert not is_stop_requested(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/daemon/test_stop_flag.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.stop_flag'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/daemon/stop_flag.py
"""Emergency stop via a flag file the loop polls each iteration (spec:
Windows is the primary runtime platform -- POSIX signals are not a reliable
cross-process mechanism there, so a polled file is used instead).
"""
from __future__ import annotations

from pathlib import Path

_STOP_FILENAME = "STOP"


def request_stop(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / _STOP_FILENAME).touch()


def is_stop_requested(state_dir: Path) -> bool:
    return (state_dir / _STOP_FILENAME).exists()


def clear_stop(state_dir: Path) -> None:
    (state_dir / _STOP_FILENAME).unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/daemon/test_stop_flag.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/daemon/stop_flag.py agent-platform/tests/daemon/test_stop_flag.py
git commit -m "daemon: add stop-flag-file emergency stop (Windows-safe)"
```

---

### Task 6: Widget snapshot gains a `daemon` section

**Files:**
- Modify: `agent-platform/cli/status.py:110-163` (`write_snapshot`)
- Test: `agent-platform/tests/cli/test_status.py` (extend existing file —
  read it first to match its existing fixture/style before adding)

**Interfaces:**
- Consumes: nothing from earlier tasks (this task is independent; ordered
  here because Task 7 will call the modified `write_snapshot`).
- Produces: `write_snapshot(sessions, snapshot_path, *, runtimes=None,
  credentials=None, daemon: dict | None = None) -> None` — same
  merge-preserving convention as `runtimes`/`credentials`.

- [ ] **Step 1: Read the existing test file to match conventions**

Run: `cd agent-platform && python -c "import pathlib; print(pathlib.Path('tests/cli/test_status.py').read_text()[:2000])"`

(No code here — this step is investigative. Match the fixture/tmp_path
style already used in that file for the new tests below.)

- [ ] **Step 2: Write the failing tests**

```python
# agent-platform/tests/cli/test_status.py (append)
import json


def test_write_snapshot_includes_daemon_section(tmp_path):
    from cli.status import write_snapshot

    snapshot_path = tmp_path / "snapshot.json"
    write_snapshot([], snapshot_path, daemon={"status": "idle", "claimed": []})

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert doc["daemon"] == {"status": "idle", "claimed": []}


def test_write_snapshot_preserves_daemon_when_omitted(tmp_path):
    from cli.status import write_snapshot

    snapshot_path = tmp_path / "snapshot.json"
    write_snapshot([], snapshot_path, daemon={"status": "running", "claimed": ["owner/repo#1"]})
    write_snapshot([], snapshot_path, runtimes=[{"name": "hermes"}])  # daemon omitted this call

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert doc["daemon"] == {"status": "running", "claimed": ["owner/repo#1"]}
    assert doc["runtimes"] == [{"name": "hermes"}]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/cli/test_status.py -k daemon_section -v`
Expected: FAIL with `TypeError: write_snapshot() got an unexpected keyword argument 'daemon'`

- [ ] **Step 4: Modify `write_snapshot`**

In `agent-platform/cli/status.py`, change the signature and body:

```python
def write_snapshot(
    sessions: list[dict[str, Any]],
    snapshot_path: Path,
    *,
    runtimes: list[dict[str, Any]] | None = None,
    credentials: list[dict[str, Any]] | None = None,
    daemon: dict[str, Any] | None = None,
) -> None:
    """... (existing docstring, extend the "not every caller knows about
    both keys" sentence to mention daemon too) ..."""
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    if runtimes is None or credentials is None or daemon is None:
        try:
            existing = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if runtimes is None:
            runtimes = existing.get("runtimes")
        if credentials is None:
            credentials = existing.get("credentials")
        if daemon is None:
            daemon = existing.get("daemon")

    doc: dict[str, Any] = {"generated_at": state.utc_now(), "sessions": sessions}
    if runtimes is not None:
        doc["runtimes"] = runtimes
    if credentials is not None:
        doc["credentials"] = credentials
    if daemon is not None:
        doc["daemon"] = daemon
    descriptor, tmp = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=snapshot_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, snapshot_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/cli/test_status.py -v`
Expected: PASS (all existing tests plus the 2 new ones — existing tests must
still pass unchanged, confirming the new parameter is additive)

- [ ] **Step 6: Commit**

```bash
git add agent-platform/cli/status.py agent-platform/tests/cli/test_status.py
git commit -m "cli(status): write_snapshot gains a daemon section, same merge convention as runtimes/credentials"
```

---

### Task 7: `DaemonLoop` — one dispatch cycle

**Files:**
- Create: `agent-platform/daemon/loop.py`
- Test: `agent-platform/tests/daemon/test_loop.py`

**Interfaces:**
- Consumes: `GateOutcome`/`evaluate_gate` (Task 1), `list_ready_issues`
  (Task 2), `SessionBudget` (Task 3), `AutonomyTracker` (Task 4),
  `is_stop_requested` (Task 5), `write_snapshot` (Task 6),
  `routing.engine_manifest.route`/`DEFAULT_MANIFESTS`,
  `routing.hermes_invoker.invoke_hermes`.
- Produces: `DaemonLoop(*, repo: str, state_dir: Path, snapshot_path: Path,
  budget: SessionBudget, autonomy: AutonomyTracker, supervised: bool = True,
  manifests=DEFAULT_MANIFESTS, list_ready_issues=list_ready_issues,
  invoke_hermes=invoke_hermes, route=route) -> DaemonLoop` with
  `.run_once() -> list[dict]` (one issue processed per call, empty list if
  none ready or nothing unclaimed) and `.claimed_issue_ids: set[str]`
  (readable, persisted to `state_dir/claimed.json`).

**Design notes for the implementer:**
- `run_once()` processes **at most one** unclaimed `workflow:ready` issue
  per call — the smallest testable unit, matching this project's own
  proof-step granularity. `run_forever()` (Task 8) loops calling this.
- Each issue needs `task_tags` and a `prompt` for `route()`/`invoke_hermes`.
  v1 derives `task_tags` from the issue's own GitHub labels intersected with
  known `task_shapes` across `manifests` (issue labels double as dispatch
  tags — no new tagging scheme). `prompt` is the issue title plus body if
  the scanner is extended to fetch it (title alone is sufficient for this
  plan's proof step; do not add body-fetching now — YAGNI until the proof
  step in Task 11 shows it's needed).
- "Clean" for `AutonomyTracker.record_pass`: `decision in ("proceed",
  "pause")` counts as clean (a `"pause"` that is later rejected by the
  operator is out of scope for this plan's automated tracking — noted as an
  Open Question carried over from the spec, not solved here).
- Crash recovery: `claimed_issue_ids` is loaded from `state_dir/claimed.json`
  in `__init__` if the file exists, and written after every claim — so a
  fresh `DaemonLoop` instance pointed at the same `state_dir` will not
  re-claim an issue already marked claimed (Task 9 tests this explicitly).

- [ ] **Step 1: Write the failing tests**

```python
# agent-platform/tests/daemon/test_loop.py
import json
from pathlib import Path

from daemon.autonomy import AutonomyTracker
from daemon.budget import SessionBudget
from daemon.loop import DaemonLoop
from routing.engine_manifest import DEFAULT_MANIFESTS, EngineChoice


def _fake_route(task_tags, manifests, fallback="claude-direct"):
    return EngineChoice(engine_id="hermes", reason="test", matched_tag="research",
                         checkpoint_required=False)


def _fake_invoke_hermes(profile, prompt, *, timeout_seconds, model=None, provider=None):
    return {"status": "succeeded", "profile": profile, "stdout": "", "stderr": ""}


def _make_loop(tmp_path: Path, *, list_ready_issues, route=_fake_route,
                invoke_hermes=_fake_invoke_hermes, supervised=True):
    return DaemonLoop(
        repo="owner/repo",
        state_dir=tmp_path / "state",
        snapshot_path=tmp_path / "snapshot.json",
        budget=SessionBudget(max_cost_usd=100.0, max_wall_clock_seconds=3600.0),
        autonomy=AutonomyTracker(),
        supervised=supervised,
        manifests=DEFAULT_MANIFESTS,
        list_ready_issues=list_ready_issues,
        invoke_hermes=invoke_hermes,
        route=route,
    )


def test_no_ready_issues_returns_empty():
    def _list(repo, **kwargs):
        return []
    loop = _make_loop(Path("/tmp/unused"), list_ready_issues=_list)
    assert loop.run_once() == []


def test_supervised_default_pauses_even_when_engine_does_not_require_it(tmp_path):
    # supervised=True is DaemonLoop's default -- a clean result still pauses
    # for operator review until this (engine, task_shape) class has earned
    # unattended autonomy, regardless of the engine's own checkpoint_required.
    def _list(repo, **kwargs):
        return [{"number": 7, "title": "Fix widget", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    results = loop.run_once()
    assert len(results) == 1
    assert results[0]["issue_id"] == "owner/repo#7"
    assert results[0]["gate_outcome"]["decision"] == "pause"
    assert "owner/repo#7" in loop.claimed_issue_ids


def test_unattended_and_unlocked_class_proceeds(tmp_path):
    # The only combination that reaches "proceed": supervised=False, the
    # engine itself doesn't require a checkpoint, AND this (engine,
    # task_shape) class has already earned its unattended unlock.
    def _list(repo, **kwargs):
        return [{"number": 7, "title": "Fix widget", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list, supervised=False)
    for _ in range(3):
        loop.autonomy.record_pass("hermes", "research", clean=True)
    results = loop.run_once()
    assert results[0]["gate_outcome"]["decision"] == "proceed"


def test_already_claimed_issue_is_skipped(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 7, "title": "Fix widget", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    loop.run_once()
    second = _make_loop(tmp_path, list_ready_issues=_list)  # fresh instance, same state_dir
    assert second.run_once() == []  # already in claimed.json -> skipped, no re-dispatch


def test_checkpoint_required_engine_pauses_even_unattended_and_unlocked(tmp_path):
    # Isolates the engine-level checkpoint_required=True from supervised
    # mode: even with supervised=False AND the class already unlocked, the
    # engine's own flag still forces a pause.
    def _list(repo, **kwargs):
        return [{"number": 8, "title": "Refactor core", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    def _route_checkpointed(task_tags, manifests, fallback="claude-direct"):
        return EngineChoice(engine_id="hermes", reason="test", matched_tag="research",
                             checkpoint_required=True)

    loop = _make_loop(tmp_path, list_ready_issues=_list, route=_route_checkpointed, supervised=False)
    for _ in range(3):
        loop.autonomy.record_pass("hermes", "research", clean=True)
    results = loop.run_once()
    assert results[0]["gate_outcome"]["decision"] == "pause"


def test_snapshot_written_after_run_once(tmp_path):
    def _list(repo, **kwargs):
        return [{"number": 9, "title": "X", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    loop.run_once()
    doc = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    assert "daemon" in doc
    assert doc["daemon"]["claimed"] == ["owner/repo#9"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/daemon/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.loop'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/daemon/loop.py
"""The daemon's core dispatch cycle (spec: "Daemon loop" + "Data flow").
Wires the Evidence Gate, GitHub scanner, budget, and autonomy tracker
around the existing, proven dispatch v0.1 primitives -- routing.
engine_manifest.route() and routing.hermes_invoker.invoke_hermes() -- not
supervisor.coordinator.Coordinator, which is RLM child-recursion machinery
for a different concern (see spec's Architecture section and this plan's
course-correction note).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from daemon.autonomy import AutonomyTracker
from daemon.budget import SessionBudget
from daemon.evidence_gate import evaluate_gate
from daemon.github_scanner import list_ready_issues as _default_list_ready_issues
from routing.engine_manifest import DEFAULT_MANIFESTS, EngineManifest, route as _default_route
from routing.hermes_invoker import invoke_hermes as _default_invoke_hermes
from cli.status import write_snapshot


def _known_task_shapes(manifests: tuple[EngineManifest, ...]) -> set[str]:
    shapes: set[str] = set()
    for m in manifests:
        shapes.update(m.task_shapes)
    return shapes


@dataclass
class DaemonLoop:
    repo: str
    state_dir: Path
    snapshot_path: Path
    budget: SessionBudget
    autonomy: AutonomyTracker
    supervised: bool = True
    manifests: tuple[EngineManifest, ...] = DEFAULT_MANIFESTS
    list_ready_issues: Callable = _default_list_ready_issues
    invoke_hermes: Callable = _default_invoke_hermes
    route: Callable = _default_route
    claimed_issue_ids: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        claimed_path = self.state_dir / "claimed.json"
        if claimed_path.is_file():
            self.claimed_issue_ids = set(json.loads(claimed_path.read_text(encoding="utf-8")))

    def _persist_claimed(self) -> None:
        (self.state_dir / "claimed.json").write_text(
            json.dumps(sorted(self.claimed_issue_ids)), encoding="utf-8"
        )

    def _write_status(self) -> None:
        write_snapshot([], self.snapshot_path, daemon={
            "status": "running",
            "claimed": sorted(self.claimed_issue_ids),
            "budget_spent_usd": self.budget.spent_usd,
        })

    def run_once(self) -> list[dict]:
        issues = self.list_ready_issues(self.repo)
        shapes = _known_task_shapes(self.manifests)
        for issue in issues:
            issue_id = f"{self.repo}#{issue['number']}"
            if issue_id in self.claimed_issue_ids:
                continue

            label_names = {lbl["name"] for lbl in issue.get("labels", [])}
            task_tags = sorted(label_names & shapes)
            if not task_tags:
                continue  # no routable tag on this issue -- skip, don't guess

            choice = self.route(task_tags, self.manifests)
            invoke_result = self.invoke_hermes(
                "researcher" if "research" in task_tags else "builder",
                issue["title"], timeout_seconds=300,
            )
            result_envelope = {
                "status": "succeeded" if invoke_result["status"] == "succeeded" else "failed",
                "evidence": [{"kind": "hermes_result", "detail": invoke_result["status"]}],
                "artifacts": [f"issue:{issue_id}", f"engine:{choice.engine_id}"],
            }
            gate_outcome = evaluate_gate(result_envelope, checkpoint_required=(
                self.supervised or choice.checkpoint_required
                or not self.autonomy.is_unlocked(choice.engine_id, task_tags[0])
            ))
            self.autonomy.record_pass(choice.engine_id, task_tags[0],
                                       clean=gate_outcome.decision in ("proceed", "pause"))

            self.claimed_issue_ids.add(issue_id)
            self._persist_claimed()
            self._write_status()

            return [{"issue_id": issue_id, "engine_id": choice.engine_id,
                      "gate_outcome": {"decision": gate_outcome.decision, "reason": gate_outcome.reason}}]
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/daemon/test_loop.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/daemon/loop.py agent-platform/tests/daemon/test_loop.py
git commit -m "daemon: add DaemonLoop.run_once() — one gated dispatch cycle"
```

---

### Task 8: `run_forever` + interval/stop wiring

**Files:**
- Modify: `agent-platform/daemon/loop.py` (add `run_forever` method)
- Test: `agent-platform/tests/daemon/test_loop.py` (append)

**Interfaces:**
- Consumes: `is_stop_requested`/`clear_stop` (Task 5), `SessionBudget.
  exhausted()` (Task 3).
- Produces: `DaemonLoop.run_forever(*, poll_interval_seconds: float = 30.0,
  sleep: Callable[[float], None] = time.sleep, max_iterations: int | None =
  None) -> str` — returns the stop reason: `"stop_requested"`,
  `"budget_exhausted"`, or `"max_iterations"` (test-only escape hatch so
  tests never actually loop forever).

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/daemon/test_loop.py (append)
from daemon.stop_flag import request_stop


def test_run_forever_stops_on_stop_flag(tmp_path):
    def _list(repo, **kwargs):
        return []  # nothing to dispatch -- isolates the stop-loop behavior

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    request_stop(loop.state_dir)
    reason = loop.run_forever(poll_interval_seconds=0.0, sleep=lambda s: None, max_iterations=5)
    assert reason == "stop_requested"


def test_run_forever_stops_on_budget_exhausted(tmp_path):
    def _list(repo, **kwargs):
        return []

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    loop.budget.record_cost(loop.budget.max_cost_usd)  # pre-exhaust
    reason = loop.run_forever(poll_interval_seconds=0.0, sleep=lambda s: None, max_iterations=5)
    assert reason == "budget_exhausted"


def test_run_forever_hits_max_iterations_when_neither_stop_nor_exhausted(tmp_path):
    def _list(repo, **kwargs):
        return []

    loop = _make_loop(tmp_path, list_ready_issues=_list)
    reason = loop.run_forever(poll_interval_seconds=0.0, sleep=lambda s: None, max_iterations=3)
    assert reason == "max_iterations"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && python -m pytest tests/daemon/test_loop.py -k run_forever -v`
Expected: FAIL with `AttributeError: 'DaemonLoop' object has no attribute 'run_forever'`

- [ ] **Step 3: Add `run_forever` to `DaemonLoop`**

Add to `agent-platform/daemon/loop.py`, alongside the existing imports add
`import time` and `from daemon.stop_flag import is_stop_requested`:

```python
    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        max_iterations: int | None = None,
    ) -> str:
        iterations = 0
        while True:
            if is_stop_requested(self.state_dir):
                return "stop_requested"
            if self.budget.exhausted():
                return "budget_exhausted"
            self.run_once()
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return "max_iterations"
            sleep(poll_interval_seconds)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/daemon/test_loop.py -v`
Expected: PASS (9 tests total)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/daemon/loop.py agent-platform/tests/daemon/test_loop.py
git commit -m "daemon: add run_forever() with stop-flag and budget-ceiling exit"
```

---

### Task 9: Crash-recovery test (explicit, spec-required)

**Files:**
- Test: `agent-platform/tests/daemon/test_loop.py` (append — this task is
  test-only: Task 7's `claimed.json` persistence already implements the
  behavior; this task proves it against a simulated crash, per the spec's
  explicit "Crash-recovery test" requirement)

**Interfaces:**
- Consumes: `DaemonLoop` (Task 7), nothing new produced.

- [ ] **Step 1: Write the test**

```python
# agent-platform/tests/daemon/test_loop.py (append)
def test_crash_then_restart_does_not_redispatch(tmp_path):
    dispatch_count = {"n": 0}

    def _list(repo, **kwargs):
        return [{"number": 11, "title": "X", "labels": [{"name": "workflow:ready"}, {"name": "research"}]}]

    def _counting_invoke(profile, prompt, *, timeout_seconds, model=None, provider=None):
        dispatch_count["n"] += 1
        return {"status": "succeeded", "profile": profile, "stdout": "", "stderr": ""}

    first = _make_loop(tmp_path, list_ready_issues=_list, invoke_hermes=_counting_invoke)
    first.run_once()
    assert dispatch_count["n"] == 1

    # Simulate a crash: `first` is discarded without cleanup, a brand-new
    # DaemonLoop is constructed against the same state_dir (the only thing
    # that survives a real process crash).
    second = _make_loop(tmp_path, list_ready_issues=_list, invoke_hermes=_counting_invoke)
    second.run_once()
    assert dispatch_count["n"] == 1  # still 1 -- no duplicate dispatch
```

- [ ] **Step 2: Run test**

Run: `cd agent-platform && python -m pytest tests/daemon/test_loop.py -k crash -v`
Expected: PASS immediately (Task 7's `__post_init__`/`_persist_claimed`
already implements this — this step is confirmation, not new code; if it
fails, the bug is in Task 7's persistence, fix there, not here)

- [ ] **Step 3: Commit**

```bash
git add agent-platform/tests/daemon/test_loop.py
git commit -m "daemon: add explicit crash-recovery regression test"
```

---

### Task 10: CLI wiring — `cortxt daemon start|stop|status`

**Files:**
- Modify: `agent-platform/cli/unified_cli.py` (add `_run_daemon` handler +
  `daemon` subparser, following the existing `runtimes`/`credentials`
  pattern at lines 402-488 and 665-689)
- Test: `agent-platform/tests/cli/test_unified_cli_daemon.py` (new — check
  `agent-platform/tests/cli/` for the existing test-invocation pattern used
  for other subcommands, e.g. `test_unified_cli_widget.py`, and match it)

**Interfaces:**
- Consumes: `DaemonLoop` (Task 7/8), `request_stop` (Task 5).
- Produces: three new argparse subcommands under `daemon`.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/cli/test_unified_cli_daemon.py
import json
import subprocess
import sys
from pathlib import Path


def test_daemon_stop_touches_stop_flag(tmp_path):
    from unified_cli import main

    state_dir = tmp_path / "daemon-state"
    exit_code = main(["daemon", "stop", "--state-dir", str(state_dir)])
    assert exit_code == 0
    assert (state_dir / "STOP").exists()


def test_daemon_status_reports_no_snapshot(tmp_path, capsys):
    from unified_cli import main

    snapshot_path = tmp_path / "snapshot.json"  # does not exist yet
    exit_code = main(["daemon", "status", "--snapshot", str(snapshot_path)])
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "succeeded"  # a missing snapshot is not an error -- daemon just hasn't run yet
    assert out["evidence"][0]["daemon"] is None


def test_daemon_status_reads_existing_snapshot(tmp_path, capsys):
    from unified_cli import main
    from cli.status import write_snapshot

    snapshot_path = tmp_path / "snapshot.json"
    write_snapshot([], snapshot_path, daemon={"status": "running", "claimed": ["owner/repo#1"]})

    exit_code = main(["daemon", "status", "--snapshot", str(snapshot_path)])
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "succeeded"
    assert out["evidence"][0]["daemon"]["claimed"] == ["owner/repo#1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/cli/test_unified_cli_daemon.py -v`
Expected: FAIL (`daemon` is not a recognized subcommand — argparse error)

- [ ] **Step 3: Add the handler and subparser**

In `agent-platform/cli/unified_cli.py`, add near the other `_run_*`
functions (following `_run_runtimes`'s shape at line 402):

```python
def _run_daemon(args: argparse.Namespace) -> ResultEnvelope:
    from daemon.stop_flag import request_stop

    if args.daemon_command == "stop":
        request_stop(Path(args.state_dir))
        return ResultEnvelope(status="succeeded", evidence=[{"stopped": args.state_dir}])

    if args.daemon_command == "status":
        snapshot_path = Path(args.snapshot)
        try:
            doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        return ResultEnvelope(status="succeeded", evidence=[{"daemon": doc.get("daemon")}])

    if args.daemon_command == "start":
        from daemon.autonomy import AutonomyTracker
        from daemon.budget import SessionBudget
        from daemon.loop import DaemonLoop

        loop = DaemonLoop(
            repo=args.repo,
            state_dir=Path(args.state_dir),
            snapshot_path=Path(args.snapshot),
            budget=SessionBudget(max_cost_usd=args.max_cost_usd, max_wall_clock_seconds=args.max_wall_clock_seconds),
            autonomy=AutonomyTracker(),
            supervised=not args.unattended,
        )
        max_iterations = 1 if args.once else None
        reason = loop.run_forever(poll_interval_seconds=args.poll_interval, max_iterations=max_iterations)
        return ResultEnvelope(status="succeeded", evidence=[{"stop_reason": reason}])

    return ResultEnvelope(status="failed", error={"category": "invalid_args", "message": "unknown daemon_command"})
```

In `main()`, alongside the existing `runtimes_parser`/`credentials_parser`
block (around line 665):

```python
    daemon_parser = sub.add_parser("daemon", help="Background Supervisor Daemon (workflow:ready dispatch loop)")
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_command", required=True)

    daemon_start = daemon_sub.add_parser("start", help="Start the dispatch loop")
    daemon_start.add_argument("--repo", required=True, help="owner/repo to scan for workflow:ready issues")
    daemon_start.add_argument("--state-dir", required=True)
    daemon_start.add_argument("--snapshot", required=True)
    daemon_start.add_argument("--max-cost-usd", type=float, default=10.0)
    daemon_start.add_argument("--max-wall-clock-seconds", type=float, default=6 * 3600.0)
    daemon_start.add_argument("--poll-interval", type=float, default=30.0)
    daemon_start.add_argument("--once", action="store_true", help="Run a single iteration and exit (testing/proof-step)")
    daemon_start.add_argument("--unattended", action="store_true", help="Skip forced supervised-mode pausing (only after a class has earned autonomy)")
    daemon_start.set_defaults(func=_run_daemon)

    daemon_stop = daemon_sub.add_parser("stop", help="Request the running daemon to stop")
    daemon_stop.add_argument("--state-dir", required=True)
    daemon_stop.set_defaults(func=_run_daemon)

    daemon_status = daemon_sub.add_parser("status", help="Print the daemon section of the widget snapshot")
    daemon_status.add_argument("--snapshot", required=True)
    daemon_status.set_defaults(func=_run_daemon)
```

Confirm `main()`'s dispatch loop at the bottom of the file already calls
`args.func(args)` generically (check the existing pattern before assuming —
if it switches on `args.command` instead, add `"daemon": _run_daemon` to
that mapping instead of using `set_defaults(func=...)`, matching whichever
convention the file already uses).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/cli/test_unified_cli_daemon.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/cli/unified_cli.py agent-platform/tests/cli/test_unified_cli_daemon.py
git commit -m "cli: add 'cortxt daemon start|stop|status' subcommands"
```

---

### Task 11: Full suite regression check + manual proof-step run

**Files:** none (verification task)

- [ ] **Step 1: Run the full test suite**

Run: `cd agent-platform && python -m pytest -q`
Expected: all previously-passing tests still pass, plus this plan's ~30 new
tests (Tasks 1-10 combined). Compare the total count against the baseline
noted in the spec/ADR-025 commit (514 passed, 14 skipped) — the new total
should be baseline + this plan's new test count, 0 regressions.

- [ ] **Step 2: Manual proof-step — one real dispatch through the daemon**

This is the project's own required proof-step before any escalation
(per `docs/superpowers/specs/2026-08-19-v02-swarm-orchestration-model-
design.md`) — **not** part of the automated suite, run manually, once, by
the operator, against one real `workflow:ready` issue:

```bash
cd agent-platform
python -m cli.unified_cli daemon start \
  --repo <owner/repo> \
  --state-dir .daemon-state \
  --snapshot widget/snapshot.json \
  --once
python -m cli.unified_cli daemon status --snapshot widget/snapshot.json
```

Verify by hand: the target issue's label flips as expected (or the daemon's
"no routable tag" skip fires correctly if the issue lacks a matching label —
confirm which, don't assume), `widget/snapshot.json`'s `daemon` section
shows the issue as claimed, and the gate's decision (`proceed`/`pause`/
`freeze`) matches what a human reviewing the same result would have decided.
Record the outcome in a short note (where this project already tracks
proof-step evidence — check `.hermes/plans/` for the pattern this session's
earlier tracks used) before considering this daemon eligible for its first
autonomy-unlock class.

- [ ] **Step 3: Commit the proof-step evidence note**

```bash
git add <the proof-step evidence file>
git commit -m "daemon: record manual proof-step evidence (one real workflow:ready dispatch)"
```
