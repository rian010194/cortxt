"""S7b (#482): post-claim launch-failure safety in WorkLauncher._launch.

The dogfood defect: a durable Dispatcher claim and execution-map claim were
created, then the worker start failed, and the generic except block skipped
claim release because the run was already in ``_claims_by_run`` -- leaving the
Run ``in_progress`` with no live worker and the claim held.

These tests prove every post-claim failure path makes the Run terminal
(``blocked`` with stable ``adapter_start_failed`` evidence), releases the
execution-map claim with an attributable terminal reason, never leaves
``in_progress`` without a worker, preserves original Run history, and that a
retry always requires a fresh ``run_id`` and fresh receipt.
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from dispatcher import Dispatcher, RunRegistry  # noqa: E402
from execution_map import ClaimConflict, SqliteClaimStore  # noqa: E402
from work_launcher import ExecutionGateError, LauncherDispatchError, WorkLauncher  # noqa: E402
from worker_adapters import UnknownRuntimeError  # noqa: E402


class FakeGitHub:
    def __init__(self, labels=None):
        self.labels = dict(labels or {})
        self.comments = []
        self.next_number = 99

    def get_labels(self, repo, num):
        return self.labels.get(f"{repo}#{num}", [])

    def swap_label(self, repo, num, remove, add):
        key = f"{repo}#{num}"
        cur = self.labels.setdefault(key, [])
        if remove in cur:
            cur.remove(remove)
        cur.append(add)

    def comment(self, repo, num, body):
        self.comments.append((f"{repo}#{num}", body))

    def create_issue(self, repo, title, body):
        self.next_number += 1
        issue_id = f"{repo}#{self.next_number}"
        self.labels[issue_id] = ["workflow:inbox"]
        return issue_id

    def approve(self, issue_id):
        self.labels[issue_id] = ["workflow:ready"]


def _issue(issue_id="acme/repo#1"):
    return {"issue_id": issue_id, "body": "", "state": "open",
            "labels": ("workflow:ready",), "area": "dispatch", "milestone": "m1"}


def _launcher(tmp_path, *, dispatch=None, labels=None, ids=("run-1", "run-2", "run-3"),
              store=None, github=None):
    store = store or SqliteClaimStore(tmp_path / "claims.sqlite3")
    gh = github or FakeGitHub(labels or {"acme/repo#1": ["workflow:ready"]})
    registry = RunRegistry(tmp_path / "runs.json")
    dispatcher = Dispatcher(registry, gh)
    events = []

    def _dispatch(dispatcher, run, prompt, worktree=None):
        events.append(("engine", run.run_id))

    app = WorkLauncher(
        dispatcher, gh,
        dispatch=dispatch or _dispatch,
        worktree_root=tmp_path / "trees",
        run_worktree=lambda argv, **k: SimpleNamespace(
            returncode=0, stdout=("0" * 40 if argv[1] == "rev-parse" else "")),
        claim_store=store,
        issue_reader=lambda issue_id: _issue(issue_id),
        inventory_readers={name: (lambda: ()) for name in WorkLauncher.INVENTORY_NAMES},
        clock=lambda: 100.0,
        id_generator=iter(ids).__next__,
        store_session_id="store-session-1", engine_session_id="engine-session-1",
    )
    return app, store, dispatcher, gh, events


def _resume(app, issue_id="acme/repo#1", runtime="hermes-free"):
    return app.resume(
        issue_id, runtime=runtime, worker_role="builder",
        workflow="work-launcher/v1", max_runtime_seconds=60, prompt="bounded",
        max_cost_usd=1.0, max_parallel_workers=1, delegation_depth=0,
        artifact_policy="policy", request_id="sha256:abc")


def _boom_unknown(dispatcher, run, prompt, worktree=None):
    raise UnknownRuntimeError(f"no adapter registered for runtime={run.runtime!r}")


def test_post_claim_adapter_start_failure_is_terminal_and_releases_claim(tmp_path):
    """The exact dogfood shape: durable claim created, then worker start fails
    with an unregistered adapter. The Run must go terminal (blocked) with
    stable adapter_start_failed evidence and the claim must be released."""
    app, store, dispatcher, gh, _ = _launcher(tmp_path, dispatch=_boom_unknown)
    with pytest.raises(LauncherDispatchError) as exc:
        _resume(app)
    assert exc.value.code == "adapter_not_registered"

    run = dispatcher.registry.get("run-1")
    assert run.status == "blocked"  # never in_progress without a live worker
    assert run.result["error"]["category"] == "adapter_start_failed"
    assert run.result["error"]["code"] == "adapter_not_registered"
    assert "worker start failed" in run.result["evidence"]
    assert run.finished_at is not None
    # original Run history preserved: the record keeps its mandate fields.
    assert run.request_id == "sha256:abc" and run.max_cost_usd == 1.0
    # execution-map claim released with an attributable terminal reason.
    assert store.active_claims(100.0) == ()
    # GitHub label reflects the terminal state.
    assert gh.labels["acme/repo#1"] == ["workflow:blocked"]


def test_worktree_creation_failure_is_terminal_and_releases_claim(tmp_path):
    """A worktree-creation failure after the claim (create path, before the
    _claims_by_run insertion) is terminal blocked + claim released."""
    app, store, dispatcher, gh, _ = _launcher(tmp_path)
    # Force worktree creation failure via the create_worktree path.
    app.run_worktree = lambda *a, **k: SimpleNamespace(returncode=1)
    with pytest.raises(LauncherDispatchError) as exc:
        app.create("acme/repo", "Proof", "scope", ["AC one"], runtime="hermes-free",
                   worker_role="builder", workflow="work-launcher/v1",
                   max_runtime_seconds=60, max_cost_usd=1.0, approved=True,
                   artifact_paths=["docs/agents/work-launcher.md"])
    assert exc.value.code == "worktree_creation_failed"
    run = dispatcher.registry.get("run-1")
    assert run.status == "blocked"
    assert run.result["error"]["category"] == "adapter_start_failed"
    assert store.active_claims(100.0) == ()
    assert gh.labels["acme/repo#100"] == ["workflow:blocked"]


def test_pre_insertion_dispatcher_drift_is_safe(tmp_path):
    """A dispatcher that ignores the generated run_id fails before the
    _claims_by_run insertion; the claim must still be released and no Run may
    be left in_progress."""
    app, store, dispatcher, gh, _ = _launcher(tmp_path)
    orig_claim = dispatcher.claim

    def drifting(issue_id, workflow, worker_role, runtime, lease_seconds, *, run_id):
        return orig_claim(issue_id, workflow, worker_role, runtime, lease_seconds,
                          run_id="wrong-id")

    dispatcher.claim = drifting
    with pytest.raises(ExecutionGateError) as exc:
        _resume(app)
    assert exc.value.code == "dispatcher_run_id_mismatch"
    assert store.active_claims(100.0) == ()
    # The drifted Run (wrong-id) is still the dispatcher's record; nothing new
    # is left in_progress for the requested run_id.
    assert dispatcher.registry.get("run-1") is None


def test_unknown_runtime_and_generic_start_exception_are_terminal(tmp_path):
    """An unregistered/unconfigured runtime is rejected pre-claim (S7b #482
    follow-on: `runtime_launch_config_ok` is the single authoritative
    pre-claim gate, so this can never reach the post-claim adapter-start
    path at all); a generic adapter-start exception for a *registered*
    runtime still becomes terminal blocked with stable evidence and a
    released claim."""
    app, store, dispatcher, gh, _ = _launcher(tmp_path / "a", dispatch=_boom_unknown)
    with pytest.raises(ExecutionGateError) as exc:
        _resume(app, runtime="no-such-engine")
    assert exc.value.code == "runtime_not_configured"
    # No claim of any kind was ever created for the rejected runtime.
    assert dispatcher.registry.get("run-1") is None
    assert store.active_claims(100.0) == ()

    app2, store2, dispatcher2, gh2, _ = _launcher(
        tmp_path / "b", dispatch=lambda d, r, p, worktree=None: (_ for _ in ()).throw(RuntimeError("adapter constructor exploded")))
    with pytest.raises(RuntimeError, match="adapter constructor"):
        _resume(app2)
    run2 = dispatcher2.registry.get("run-1")
    assert run2.status == "blocked"
    assert run2.result["error"]["category"] == "adapter_start_failed"
    assert run2.result["error"]["code"] == "RuntimeError"
    assert store2.active_claims(100.0) == ()
    assert gh2.labels["acme/repo#1"] == ["workflow:blocked"]


def test_failure_recording_terminal_status_still_releases_claim(tmp_path):
    """If dispatcher.complete() itself fails while recording the terminal
    status, the claim release still runs (never stranded)."""
    app, store, dispatcher, gh, _ = _launcher(tmp_path, dispatch=_boom_unknown)

    def failing_complete(run_id, status, envelope):
        raise RuntimeError("registry write failed")

    dispatcher.complete = failing_complete
    with pytest.raises(LauncherDispatchError):
        _resume(app)
    assert store.active_claims(100.0) == ()


def test_failure_releasing_claim_leaves_run_terminal(tmp_path):
    """If the claim release fails (ClaimConflict), the Run is still terminal;
    the release failure is contained, not a crash."""

    class FailingReleaseStore(SqliteClaimStore):
        def release(self, claim_id, run_id, driver_id, generation, reason, now=None):
            raise ClaimConflict("already released")

    app, store, dispatcher, gh, _ = _launcher(
        tmp_path, dispatch=_boom_unknown,
        store=FailingReleaseStore(tmp_path / "claims.sqlite3"))
    with pytest.raises(LauncherDispatchError):
        _resume(app)
    run = dispatcher.registry.get("run-1")
    assert run.status == "blocked"
    assert run.result["error"]["category"] == "adapter_start_failed"


def test_retry_requires_fresh_run_id_and_fresh_receipt(tmp_path):
    """After a terminal adapter-start failure, a retry (issue back at ready)
    creates a NEW run_id and a NEW claim/receipt; the original Run history is
    preserved and never overwritten."""
    calls = {"n": 0}

    def flaky(dispatcher, run, prompt, worktree=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise UnknownRuntimeError("no adapter registered")

    app, store, dispatcher, gh, _ = _launcher(tmp_path, dispatch=flaky)
    with pytest.raises(LauncherDispatchError):
        _resume(app)
    first_claim_ids = {c.claim_id for c in store.active_claims(100.0)}
    assert not first_claim_ids  # released

    # Operator resets the issue to ready; the retry uses a fresh run.
    gh.labels["acme/repo#1"] = ["workflow:ready"]
    result = _resume(app)
    assert result["run_id"] == "run-2"
    assert result["claim_id"]
    # Old Run stays terminal with its history preserved.
    assert dispatcher.registry.get("run-1").status == "blocked"
    # New claim exists (fresh receipt), distinct from the released one.
    assert [c.claim_id for c in store.active_claims(100.0)] == [result["claim_id"]]
