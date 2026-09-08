#!/usr/bin/env python3
"""Network-free checks for execution-map launcher integration (#262)."""
from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

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


class FakeDispatcher:
    def __init__(self, events):
        self.events = events
        self.registry = SimpleNamespace(_runs={})

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
