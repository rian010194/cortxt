"""S7b (#471): the launcher carries and enforces the full dispatch request.

The dispatch request's limits (cost ceiling, parallel-worker ceiling,
delegation depth, artifact policy, request snapshot id) must reach the
claim/run record and be enforced, never display-only (review blocker 1).
These tests exercise `WorkLauncher` directly through the real execution-map
gate with injected fakes for the dispatcher, GitHub, and worker adapter.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from execution_map import SqliteClaimStore  # noqa: E402
from work_launcher import ExecutionGateError, LauncherDispatchError, WorkLauncher  # noqa: E402
from worker_adapters import UnknownRuntimeError  # noqa: E402


class _FakeRegistry:
    def __init__(self):
        self._runs: dict[str, dict] = {}

    def active_issue_ids(self) -> set[str]:
        return {r["issue_id"] for r in self._runs.values() if r.get("status") == "in_progress"}

    def update(self, run_id, **fields):
        self._runs[run_id].update(fields)

    def get(self, run_id):
        # Real RunRegistry.get returns a Run object with attribute fields;
        # mirror that shape for the launcher's limit reads.
        value = self._runs.get(run_id)
        return SimpleNamespace(**value) if value else None


class _FakeDispatcher:
    def __init__(self):
        self.registry = _FakeRegistry()
        self.completed = []

    def claim(self, issue_id, workflow, worker_role, runtime, lease_seconds, *, run_id):
        run = {"run_id": run_id, "issue_id": issue_id, "workflow": workflow,
               "worker_role": worker_role, "runtime": runtime, "claimed_at": 100.0,
               "heartbeat_at": 100.0, "lease_seconds": lease_seconds, "status": "in_progress"}
        self.registry._runs[run_id] = run
        return SimpleNamespace(**run)

    def complete(self, run_id, status, result):
        run = self.registry._runs[run_id]
        run["status"] = status
        run["result"] = result
        self.completed.append((run_id, status, result))
        return SimpleNamespace(run_id=run_id, issue_id=run["issue_id"], status=status)


def _issue(issue_id="acme/repo#1"):
    return {"issue_id": issue_id, "body": "", "state": "open",
            "labels": ("workflow:ready",), "area": "dispatch", "milestone": "m1"}


def _launcher(tmp_path, *, dispatcher=None, dispatch=None, store=None):
    store = store or SqliteClaimStore(tmp_path / "claims.sqlite3")
    dispatcher = dispatcher or _FakeDispatcher()
    events = []

    def record(dispatcher, run, prompt, worktree=None):
        events.append(("engine", run.run_id))

    return WorkLauncher(
        dispatcher, SimpleNamespace(get_issue=lambda i: _issue(i)),
        dispatch=dispatch or record,
        worktree_root=tmp_path / "trees",
        run_worktree=lambda *a, **k: SimpleNamespace(returncode=0),
        claim_store=store,
        issue_reader=lambda issue_id: _issue(issue_id),
        inventory_readers={name: (lambda: ()) for name in WorkLauncher.INVENTORY_NAMES},
        clock=lambda: 100.0,
        id_generator=iter(("run-1", "run-2")).__next__,
        store_session_id="store-session-1", engine_session_id="engine-session-1",
    ), events


def test_resume_carries_every_dispatch_limit_onto_the_run_record(tmp_path):
    app, _ = _launcher(tmp_path)
    result = app.resume(
        "acme/repo#1", runtime="hermes-free", worker_role="builder",
        workflow="work-launcher/v1", max_runtime_seconds=5400, prompt="bounded",
        max_cost_usd=8.0, max_parallel_workers=2, delegation_depth=1,
        artifact_policy="isolated worktree only", request_id="sha256:abc")
    assert result["run_id"] == "run-1"
    record = app.dispatcher.registry.get("run-1")
    assert record.max_cost_usd == 8.0
    assert record.max_parallel_workers == 2
    assert record.delegation_depth == 1
    assert record.artifact_policy == "isolated worktree only"
    assert record.request_id == "sha256:abc"


def test_submit_enforces_cost_ceiling_as_budget_exceeded(tmp_path):
    app, _ = _launcher(tmp_path)
    app.resume("acme/repo#1", runtime="hermes-free", worker_role="builder",
               workflow="work-launcher/v1", max_runtime_seconds=5400, prompt="bounded",
               max_cost_usd=8.0, max_parallel_workers=2, delegation_depth=1,
               artifact_policy="policy", request_id="sha256:abc")
    result = app.submit("run-1", {"status": "succeeded", "cost": 12.5})
    assert result["status"] == "budget_exceeded"
    assert app.dispatcher.completed[-1][1] == "budget_exceeded"
    assert app.dispatcher.completed[-1][2]["error"]["category"] == "budget_exceeded"
    assert app.dispatcher.completed[-1][2]["error"]["recovery"]


def test_submit_accepts_cost_within_ceiling(tmp_path):
    app, _ = _launcher(tmp_path)
    app.resume("acme/repo#1", runtime="hermes-free", worker_role="builder",
               workflow="work-launcher/v1", max_runtime_seconds=5400, prompt="bounded",
               max_cost_usd=8.0, max_parallel_workers=2, delegation_depth=1,
               artifact_policy="policy", request_id="sha256:abc")
    result = app.submit("run-1", {"status": "succeeded", "cost": 4.2})
    assert result["status"] == "succeeded"


def test_max_parallel_workers_ceiling_enforced_before_claim(tmp_path):
    app, _ = _launcher(tmp_path)
    app.resume("acme/repo#1", runtime="hermes-free", worker_role="builder",
               workflow="work-launcher/v1", max_runtime_seconds=5400, prompt="bounded",
               max_cost_usd=8.0, max_parallel_workers=2, delegation_depth=1,
               artifact_policy="policy", request_id="sha256:abc")
    # A second resume with the same ceiling finds one active run already at 1,
    # so a 1-worker ceiling is reached and the claim is rejected up front.
    with pytest.raises(ExecutionGateError) as exc:
        app.resume("acme/repo#2", runtime="hermes-free", worker_role="builder",
                   workflow="work-launcher/v1", max_runtime_seconds=5400, prompt="bounded",
                   max_cost_usd=8.0, max_parallel_workers=1, delegation_depth=1,
                   artifact_policy="policy", request_id="sha256:def")
    assert exc.value.code == "max_parallel_workers_reached"


def test_adapter_start_failure_maps_to_stable_launcher_dispatch_error(tmp_path):
    def unavailable(dispatcher, run, prompt, worktree=None):
        raise UnknownRuntimeError(f"no adapter registered for runtime={run.runtime!r}")

    app, _ = _launcher(tmp_path, dispatch=unavailable)
    with pytest.raises(LauncherDispatchError) as exc:
        app.resume("acme/repo#1", runtime="no-such-engine", worker_role="builder",
                   workflow="work-launcher/v1", max_runtime_seconds=5400, prompt="bounded",
                   max_cost_usd=8.0, max_parallel_workers=2, delegation_depth=1,
                   artifact_policy="policy", request_id="sha256:abc")
    assert exc.value.code == "adapter_not_registered"
    assert exc.value.recovery
