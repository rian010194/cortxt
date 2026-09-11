#!/usr/bin/env python3
"""Network-free checks for execution-map launcher integration (#262)."""
from __future__ import annotations

import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import dispatcher
import worker_adapters as wa
from execution_map import SqliteClaimStore
from work_launcher import ExecutionGateError, WorkLauncher


@dataclass
class FakeRun:
    run_id: str
    issue_id: str
    workflow: str
    worker_role: str
    runtime: str
    claimed_at: float = 100.0
    heartbeat_at: float = 100.0
    status: str = "in_progress"
    lease_seconds: int = 60
    finished_at: Optional[float] = None
    result: Optional[dict] = None


class FakeDispatcher:
    class Registry:
        def __init__(self):
            self._runs = {}

        def get(self, run_id):
            return self._runs.get(run_id)

        def update(self, run_id, **fields):
            run = self._runs.get(run_id)
            if run:
                for k, v in fields.items():
                    setattr(run, k, v)

    def __init__(self, events):
        self.events = events
        self.registry = self.Registry()

    def claim(self, issue_id, workflow, worker_role, runtime, lease_seconds, *, run_id):
        self.events.append(("dispatcher.claim", run_id))
        run = FakeRun(run_id, issue_id, workflow, worker_role, runtime)
        self.registry._runs[run_id] = run
        return run

    def complete(self, run_id, status, result):
        self.events.append(("dispatcher.complete", run_id))
        run = self.registry._runs[run_id]
        run.status = status
        return run


class FakeGitHub:
    def __init__(self, issues, events):
        self.issues, self.events, self.next_number = issues, events, 90

    def get_issue(self, issue_id):
        self.events.append(("issue.read", issue_id))
        return dict(self.issues[issue_id])

    def get_labels(self, repo, issue_num):
        self.events.append(("issue.get_labels", repo, issue_num))
        # Build issue_id from repo and issue_num (e.g., "acme/repo#90")
        issue_id = f"{repo}#{issue_num}"
        issue = self.issues.get(issue_id)
        if issue:
            return list(issue.get("labels", ()))
        return []

    def swap_label(self, repo, issue_num, remove, add):
        self.events.append(("issue.swap_label", repo, issue_num, remove, add))
        # Extract issue_id from repo and issue_num
        issue_id = f"{repo}#{issue_num}"
        if issue_id in self.issues:
            labels = list(self.issues[issue_id].get("labels", ()))
            if remove in labels:
                labels.remove(remove)
            if add not in labels:
                labels.append(add)
            self.issues[issue_id]["labels"] = tuple(labels)

    def comment(self, repo, issue_num, body):
        self.events.append(("issue.comment", repo, issue_num, body))

    def create_issue(self, repo, title, body):
        self.events.append(("issue.create", repo))
        self.next_number += 1
        issue_id = f"{repo}#{self.next_number}"
        self.issues[issue_id] = issue(issue_id, ("workflow:inbox",))
        return issue_id

    def approve(self, issue_id):
        self.events.append(("issue.approve", issue_id))
        self.issues[issue_id]["labels"] = ("workflow:ready",)


def issue(issue_id, labels=("workflow:ready",), body=""):
    return {"issue_id": issue_id, "body": body, "state": "open", "labels": labels,
            "area": "dispatch", "milestone": "m1"}


OPEN_STORES = []


def fake_completed_hermes_adapter(stdout="worked", stderr="", returncode=0):
    """Factory for a mock adapter that returns a fixed completion envelope."""
    import time
    from pathlib import Path

    class MockAdapter:
        """Simple adapter that returns a fixed completion envelope without invoking hermes."""

        def __init__(self):
            self.profile = "mock"
            self.log_dir = Path(tempfile.gettempdir()) / "cortxt-test-logs"
            self.log_dir.mkdir(exist_ok=True)

        def invoke(self, run, task_prompt, timeout_seconds, worktree=None):
            started = time.time()
            print(f"DEBUG MockAdapter.invoke: run={run.run_id}, worktree={worktree}", file=sys.stderr)
            return {
                "_status": "succeeded",
                "runtime": run.runtime,
                "worker_role": run.worker_role,
                "model": "test-model",
                "usage": "measured",
                "cost": 0.001,
                "artifacts": [],
                "evidence": "fake hermes completed",
                "commit": "a" * 40,  # A dummy commit for mutating runs
                "issue_id": run.issue_id,
                "run_id": run.run_id,
                "request_id": getattr(run, "request_id", None),
                "_elapsed_seconds": time.time() - started,
            }

    return MockAdapter()


def launcher(root, issues, events, ids, *, store=None, issue_reader=None,
             engine="engine-session-1", session="store-session-1"):
    store = store or SqliteClaimStore(root / "claims.sqlite3")
    if store not in OPEN_STORES:
        OPEN_STORES.append(store)
    gh = FakeGitHub(issues, events)
    disp = FakeDispatcher(events)
    # `repo_path` is bound to the temporary root rather than left at its
    # `Path.cwd()` default. WorkLauncher.submit()'s success path passes
    # `repo_path` to `enrich_run_correlation`, which runs real (read-only) `git`
    # under it. Today that never fires here -- `_derive_branch_tip` returns None
    # before touching git when the Run has no `branch`
    # (`worker_adapters.py:835-837`), and `FakeRun` has no such field -- so this
    # is a guard, not a fix for observed behaviour: give `FakeRun` a `branch`
    # and the default would run git inside the real checkout.
    return WorkLauncher(disp, gh, dispatch=lambda d, r, p: events.append(("engine", r.run_id)),
        repo_path=root,
        worktree_root=root / "trees",
        run_worktree=lambda argv, **k: SimpleNamespace(
            returncode=0, stdout=("0" * 40 if argv[1] == "rev-parse" else "")),
        claim_store=store, issue_reader=issue_reader or gh.get_issue,
        inventory_readers={name: (lambda: ()) for name in WorkLauncher.INVENTORY_NAMES},
        clock=lambda: 100.0, id_generator=lambda: next(ids), store_session_id=session,
        engine_session_id=engine)


def expect_code(code, fn):
    try:
        fn()
    except ExecutionGateError as exc:
        assert exc.code == code, (exc.code, code)
    else:
        raise AssertionError(f"expected {code}")


def check_gate_order_stale_and_terminal_release(root):
    """AC: fresh receipt/claim ordering, immediate reread, stable fail closed, release."""
    events, issues = [], {"acme/repo#1": issue("acme/repo#1")}
    app = launcher(root, issues, events, iter(("run-1",)))
    result = app.resume("acme/repo#1", runtime="fake", worker_role="builder", workflow="wf/v1",
                        max_runtime_seconds=60, prompt="bounded")
    assert result["run_id"] == "run-1" and result["claim_id"]
    assert [x[0] for x in events[:3]] == ["issue.read", "issue.read", "dispatcher.claim"]
    assert app.claim_store.active_claims(100.0)
    app.submit("run-1", {"status": "succeeded", "evidence": ["ok"]})
    assert not app.claim_store.active_claims(100.0)

    reads = 0
    def changing(_):
        nonlocal reads
        reads += 1
        return issue("acme/repo#2", ("workflow:ready",) if reads == 1 else ("workflow:blocked",))
    stale = launcher(root, {"acme/repo#2": issue("acme/repo#2")}, [], iter(("run-2",)),
                     store=SqliteClaimStore(root / "stale.sqlite3"), issue_reader=changing)
    expect_code("stale_issue_generation", lambda: stale.resume(
        "acme/repo#2", runtime="fake", worker_role="builder", workflow="wf/v1",
        max_runtime_seconds=60, prompt="bounded"))
    assert not stale.dispatcher.events and not stale.claim_store.active_claims(100.0)


def check_approval_prerequisite_and_observer_boundaries(root):
    """AC: approval stays external; graph/frontier/widget projections grant no authority."""
    issues, events = {"acme/repo#3": issue("acme/repo#3")}, []
    app = launcher(root, issues, events, iter(("run-3",)))
    expect_code("issue_not_ready", lambda: (
        issues["acme/repo#3"].update(labels=("workflow:inbox",)),
        app.resume("acme/repo#3", runtime="fake", worker_role="builder", workflow="wf/v1",
                   max_runtime_seconds=60, prompt="bounded"))[1])
    assert not any(x[0] == "dispatcher.claim" for x in events)
    assert not hasattr(app, "approve") and not hasattr(app, "mark_done")
    # The only projection entry point is content-free and has no executable callback.
    assert app.combined_status() == []


def check_disjoint_parallel_and_overlap(root):
    """AC: disjoint runs launch in parallel; every exclusive overlap rejects once."""
    store_path = root / "parallel.sqlite3"
    stores = [SqliteClaimStore(store_path), SqliteClaimStore(store_path)]
    issues = {"acme/repo#4": issue("acme/repo#4"), "acme/repo#5": issue("acme/repo#5")}
    apps = [launcher(root, issues, [], iter((f"run-{n}",)), store=stores[n - 4],
                     session=f"store-session-{n}", engine=f"engine-session-{n}") for n in (4, 5)]
    barrier, outcomes = threading.Barrier(2), []
    def launch_one(index):
        barrier.wait()
        outcomes.append(apps[index].resume(f"acme/repo#{index + 4}", runtime="fake",
            worker_role="builder", workflow="wf/v1", max_runtime_seconds=60, prompt="bounded"))
    threads = [threading.Thread(target=launch_one, args=(x,)) for x in range(2)]
    [x.start() for x in threads]; [x.join() for x in threads]
    assert sorted(x["run_id"] for x in outcomes) == ["run-4", "run-5"]

    overlap_path = root / "overlap.sqlite3"
    same = {"acme/repo#6": issue("acme/repo#6")}
    a = launcher(root, same, [], iter(("run-6a",)), store=SqliteClaimStore(overlap_path))
    b = launcher(root, same, [], iter(("run-6b",)), store=SqliteClaimStore(overlap_path))
    a.resume("acme/repo#6", runtime="fake", worker_role="builder", workflow="wf/v1",
             max_runtime_seconds=60, prompt="bounded")
    expect_code("resource_collision", lambda: b.resume("acme/repo#6", runtime="fake",
        worker_role="builder", workflow="wf/v1", max_runtime_seconds=60, prompt="bounded"))
    assert len(a.dispatcher.registry._runs) == 1 and not b.dispatcher.registry._runs


def check_identity_retry_status_and_no_payload(root):
    """AC: identity separation, immutable retry history, exact engine identity, no payloads."""
    store = SqliteClaimStore(root / "identity.sqlite3")
    issues, events = {"acme/repo#7": issue("acme/repo#7")}, []
    app = launcher(root, issues, events, iter(("run-7a", "run-7b")), store=store)
    first = app.resume("acme/repo#7", runtime="fake", worker_role="builder", workflow="wf/v1",
                       max_runtime_seconds=60, prompt="SECRET CONTENT")
    row = app.list_active()[0]
    assert (row["run_id"], row["store_session_id"], row["engine_session_id"]) == (
        "run-7a", "store-session-1", "engine-session-1")
    assert "prompt" not in row and "result" not in row and "SECRET" not in repr(row)
    app.submit("run-7a", {"status": "failed", "private": "not projected"})
    second = app.resume("acme/repo#7", runtime="fake", worker_role="builder", workflow="wf/v1",
                        max_runtime_seconds=60, prompt="bounded")
    assert second["run_id"] != first["run_id"]
    history = store.history(first["claim_id"])
    assert [x["event"] for x in history] == ["acquired", "released"]
    assert store.history(first["claim_id"]) == history


def check_no_forbidden_transitions(root):
    """AC: github-transition handoff is gated; no review/done/cleanup/recovery action exists."""
    events, issues = [], {"acme/repo#8": issue("acme/repo#8")}
    app = launcher(root, issues, events, iter(("github-transition-8",)))
    app.resume("acme/repo#8", runtime="github-transition", worker_role="builder",
               workflow="wf/v1", max_runtime_seconds=60, prompt="bounded")
    names = {name for name, *_ in events}
    assert "dispatcher.claim" in names and "engine" in names
    assert not names.intersection({"approve", "merge", "close", "deploy", "publish", "cleanup",
                                   "recover", "review_sync", "mark_done"})


def check_dispatcher_completion_loop_closes(root):
    """AC4: Dispatcher/WWorkLauncher join path closes to terminal succeeded.

    When a worker adapter returns quickly with a landed commit, the run must
    reach terminal succeeded with commit_evidence. The fix joins the worker
    thread in WorkLauncher._dispatch so a daemon thread isn't killed by
    process exit before Dispatcher.complete() fires.

    This is the integration gap the previous suites missed: the adapter tests
    call dispatch_async and join() themselves; the launcher tests use a fake
    dispatch that doesn't return a thread. This check uses a real adapter to
    exercise the actual join path.
    """
    # Register a real adapter that returns quickly with a commit
    mock_adapter = fake_completed_hermes_adapter()
    print(f"DEBUG: mock_adapter={mock_adapter}, profile={mock_adapter.profile}", file=sys.stderr)
    wa.register_adapter("test-quick-complete", mock_adapter)
    print(f"DEBUG: registry={wa.ADAPTER_REGISTRY.get('test-quick-complete')}", file=sys.stderr)

    # Create a mock commit_gate that always succeeds for this test
    def mock_commit_gate(run, result_envelope):
        """Mock commit_gate that accepts the commit without actual git verification."""
        from commit_evidence import CommitEvidence
        commit = result_envelope.get("commit")
        branch = "work/" + run.run_id
        return CommitEvidence(
            run_id=run.run_id,
            issue_id=run.issue_id,
            commit=commit,
            branch=branch,
            committed_at=int(100.0),
            files=(),
            verified_at=100.0,
            worktree=str(root / "trees" / run.run_id),
        )

    store = SqliteClaimStore(root / "completion-loop.sqlite3")
    if store not in OPEN_STORES:
        OPEN_STORES.append(store)

    issues = {"acme/repo#9": issue("acme/repo#9", ("workflow:ready",))}
    events = []
    gh = FakeGitHub(issues, events)
    disp = FakeDispatcher(events)

    # Create a Dispatcher with the mock commit_gate
    from dispatcher import RunRegistry
    registry_path = root / "registry.json"
    registry = RunRegistry(registry_path)
    disp_with_gate = dispatcher.Dispatcher(
        registry,
        gh,
        commit_gate=mock_commit_gate,
    )

    # Use a launcher with the real dispatch_async to exercise the join path
    # The run_worktree mock must also create the actual worktree directory
    # so that worktree.is_dir() returns True in _create_worktree
    def _mock_run_worktree(argv, **kwargs):
        cwd = kwargs.get("cwd", str(root))
        if len(argv) >= 3 and argv[1] == "worktree" and argv[2] == "add":
            # Create the worktree directory to satisfy the is_dir() check
            worktree_path = Path(argv[argv.index("HEAD") - 1])
            worktree_path.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            returncode=0,
            stdout=("0" * 40 if len(argv) >= 2 and argv[1] == "rev-parse" else ""),
        )

    launcher = WorkLauncher(
        disp_with_gate, gh,
        dispatch=wa.dispatch_async,
        worktree_root=root / "trees",
        run_worktree=_mock_run_worktree,
        repo_path=root,
        claim_store=store,
        issue_reader=gh.get_issue,
        inventory_readers={name: (lambda: ()) for name in WorkLauncher.INVENTORY_NAMES},
        clock=lambda: 100.0,
        id_generator=lambda: next(iter(("run-9",))),
        store_session_id="store-session-1",
        engine_session_id="engine-session-1",
    )

    # First, create and dispatch a mutating run (it needs a worktree + commit)
    # The adapter returns a commit, so the run should reach succeeded
    result = launcher.resume(
        "acme/repo#9",
        runtime="test-quick-complete",
        worker_role="builder",
        workflow="wf/v1",
        max_runtime_seconds=60,
        prompt="bounded",
        isolate=True,  # mutating run needs isolation
        mutating=True,
    )

    assert result["run_id"] == "run-9"

    # The critical check: after resume() returns, the run must be terminal
    # (not in_progress), because the worker thread was joined.
    run = disp_with_gate.registry.get("run-9")
    print(f"DEBUG: run.status={run.status}, run.result={run.result}", file=sys.stderr)
    assert run.status == "succeeded", f"expected succeeded, got {run.status}"
    assert run.finished_at is not None, "finished_at must be set on terminal run"

    # For a mutating run that succeeded, commit_evidence should be present
    # (the adapter returned a commit: "a" * 40)
    assert run.result is not None
    assert "commit_evidence" in run.result, "mutating succeeded run must have commit_evidence"
    ce = run.result["commit_evidence"]
    assert ce["commit"] == "a" * 40, "commit_evidence must carry the commit"

    # Claim should be released (not active)
    assert not store.active_claims(100.0), "claim must be released after terminal run"

    # Clean up adapter registration
    wa.ADAPTER_REGISTRY.pop("test-quick-complete", None)


def main():
    # These checks dispatch through an injected fake `dispatch` callable, not
    # the real ADAPTER_REGISTRY -- but since the S7b #482 follow-on
    # `WorkLauncher._launch` consults `runtime_launch_config_ok` (registry
    # membership plus a carrier preflight) *before* any claim, so the
    # synthetic runtimes used below must be registered for these fixtures to reach
    # the behaviour they exist to check. Without it every check here dies on
    # `ExecutionGateError: runtime_not_configured` at the first resume().
    # scripts/test_work_launcher.py has carried the same registration since
    # #482; this file was never run in CI, so it never caught up.
    _synthetic = ("fake", "github-transition")
    _prior = {name: wa.ADAPTER_REGISTRY.get(name) for name in _synthetic}
    for _runtime in _synthetic:
        wa.register_adapter(_runtime, SimpleNamespace(invoke=lambda *a, **k: {}))

    temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(temp.name)
        check_gate_order_stale_and_terminal_release(root)
        check_approval_prerequisite_and_observer_boundaries(root)
        check_disjoint_parallel_and_overlap(root)
        check_identity_retry_status_and_no_payload(root)
        check_no_forbidden_transitions(root)
        check_dispatcher_completion_loop_closes(root)
    finally:
        for store in OPEN_STORES:
            store.close()
        OPEN_STORES.clear()
        temp.cleanup()
        # Leave ADAPTER_REGISTRY as it was found. It is process-global, and the
        # pytest entry point below makes this module collectible alongside
        # others -- a synthetic runtime left registered would be visible to
        # every later test in the same interpreter.
        for name, prior in _prior.items():
            if prior is None:
                wa.ADAPTER_REGISTRY.pop(name, None)
            else:
                wa.ADAPTER_REGISTRY[name] = prior
    print("launcher integration checks passed")


def test_all_checks_pass():
    """Pytest entry point: run the same checks as the standalone script.

    Without this, `pytest scripts/` collects zero tests from this file and
    reports green while running none of the checks below. Every check here
    raises AssertionError on failure, so simply calling main() is the whole
    contract.
    """
    main()


if __name__ == "__main__":
    main()
