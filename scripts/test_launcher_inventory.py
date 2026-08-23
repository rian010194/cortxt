#!/usr/bin/env python3
"""Offline checks for the ADR-039 inventory readers and default-launcher wiring (#299).

Run: python scripts/test_launcher_inventory.py
Prints ok/FAIL lines and exits non-zero on any failure.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from execution_map import SqliteClaimStore
from launcher_inventory import (InventoryUnavailable, daemon_claims_reader,
                                dispatcher_registry_reader, git_resources_reader,
                                lifecycle_sessions_reader, make_graph_reader,
                                writer_domain_reader)
from work_launcher import ExecutionGateError, WorkLauncher

FAILS: list[str] = []
OPEN_STORES: list = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


class FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def fake_git(argv, **kwargs):
    if argv[1] == "worktree":
        return FakeProc(stdout="worktree C:/repo/main\nbranch main\nworktree C:/repo/trees/run-9\nbranch work/run-9\n")
    if argv[1] == "branch":
        return FakeProc(stdout="main\nwork/run-9\nfeat/other\n")
    return FakeProc(returncode=1, stderr="boom")


@dataclass
class FakeRun:
    run_id: str
    issue_id: str
    workflow: str
    worker_role: str
    runtime: str
    status: str = "in_progress"


class FakeDispatcher:
    def __init__(self):
        self.events = []
        self.registry = SimpleNamespace(_runs={})

    def claim(self, issue_id, workflow, worker_role, runtime, lease_seconds, *, run_id):
        run = FakeRun(run_id, issue_id, workflow, worker_role, runtime)
        self.registry._runs[run_id] = run
        return run

    def complete(self, run_id, status, result):
        self.registry._runs[run_id].status = status
        return self.registry._runs[run_id]


class FakeGitHub:
    def __init__(self, issues):
        self.issues = issues

    def get_issue(self, issue_id):
        return dict(self.issues[issue_id])


def issue(issue_id, labels=("workflow:ready",), body=""):
    return {"issue_id": issue_id, "body": body, "state": "open", "labels": labels,
            "area": "dispatch", "milestone": "m1"}


def launcher(root, issues, *, inventory=None, graph_reader=None, writer=None, ids=None):
    if ids is None:
        ids = iter(("run-1",))
    store = SqliteClaimStore(root / "claims.sqlite3")
    OPEN_STORES.append(store)
    gh = FakeGitHub(issues)
    disp = FakeDispatcher()
    return store, WorkLauncher(disp, gh, dispatch=lambda d, r, p: None,
        worktree_root=root / "trees", run_worktree=lambda *a, **k: SimpleNamespace(returncode=0),
        claim_store=store, issue_reader=gh.get_issue, graph_reader=graph_reader,
        inventory_readers=inventory or {n: (lambda: ()) for n in WorkLauncher.INVENTORY_NAMES},
        writer_reader=writer or (lambda: ()), clock=lambda: 100.0, id_generator=lambda: next(ids))


def expect_code(code, fn):
    try:
        fn()
    except ExecutionGateError as exc:
        check(f"gate code {code}", exc.code == code)
    else:
        check(f"gate code {code}", False)


def run(root):
    # 1. git reader inventory: worktrees + branches become collision resources.
    records = git_resources_reader(runner=fake_git)()
    resources = records[0]["resources"]
    check("git reader yields branch and worktree keys",
          "branch:work/run-9" in resources and any(x.startswith("worktree:") for x in resources))

    # 2. git reader fails closed on a failing runner.
    def failing(argv, **kwargs):
        return FakeProc(returncode=1, stderr="boom")
    check("git reader fail-closed on nonzero", raises(InventoryUnavailable, lambda: git_resources_reader(runner=failing)()))

    # 3. dispatcher registry reader yields in-progress runs.
    disp = FakeDispatcher()
    disp.claim("acme/repo#5", "wf/v1", "builder", "fake", 60, run_id="run-5")
    rows = dispatcher_registry_reader(disp.registry)()
    check("dispatcher reader yields run and branch", rows == [{"owner": "fake", "run_id": "run-5",
                                                              "issue_id": "acme/repo#5", "branch": "work/run-5"}])

    # 4. daemon reader: absent empty, present list, malformed fail-closed.
    check("daemon reader absent is empty", daemon_claims_reader(root / "nope")() == [])
    (root / "daemon").mkdir()
    (root / "daemon" / "claimed.json").write_text('["acme/repo#7"]')
    check("daemon reader yields issue keys",
          daemon_claims_reader(root / "daemon")() == [{"owner": "daemon", "issue_id": "acme/repo#7"}])
    (root / "daemon" / "claimed.json").write_text("{bad")
    check("daemon reader malformed fail-closed", raises(InventoryUnavailable, lambda: daemon_claims_reader(root / "daemon")()))

    # 5. lifecycle reader: absent empty, present sessions -> store_session keys.
    check("lifecycle reader absent is empty", lifecycle_sessions_reader(root / "nosess")() == [])
    (root / "sess" / "session_1").mkdir(parents=True)
    (root / "sess" / "session_1" / "session.json").write_text("{}")
    (root / "sess" / "session_2").mkdir(parents=True)
    (root / "sess" / "session_2" / "session.json").write_text("{}")
    got = lifecycle_sessions_reader(root / "sess")()
    check("lifecycle reader yields store_session keys",
          sorted(x["store_session_id"] for x in got) == ["session_1", "session_2"])

    # 6. writer domain: single owner ok, second driver -> shared_store_writer_conflict.
    check("writer domain single owner", writer_domain_reader()() == [{"domain": "state", "owner": "cortxt-work"}])

    # 7. graph reader: prerequisite edge parsed and target read.
    gh = FakeGitHub({"acme/repo#1": issue("acme/repo#1", body="Blocked by: #2"),
                     "acme/repo#2": issue("acme/repo#2")})
    graph = make_graph_reader(gh.get_issue)("acme/repo#1")
    check("graph reader includes prerequisite target", {x["issue_id"] for x in graph} == {"acme/repo#1", "acme/repo#2"})

    # 8. wiring: git collision rejects before dispatch.
    issues = {"acme/repo#9": issue("acme/repo#9")}
    store, app = launcher(root / "g1", issues, ids=iter(("run-9",)),
                          inventory={"git_resources": git_resources_reader(runner=fake_git)})
    expect_code("resource_collision", lambda: app.resume("acme/repo#9", runtime="fake", worker_role="builder",
                                                          workflow="wf/v1", max_runtime_seconds=60, prompt="bounded"))
    check("git collision has no dispatcher claim", not app.dispatcher.events)
    store.close()

    # 9. wiring: unavailable inventory fails closed with a stable code.
    def unavailable():
        raise InventoryUnavailable("down")
    store, app = launcher(root / "g2", issues, inventory={"git_resources": unavailable})
    expect_code("inventory_unavailable", lambda: app.resume("acme/repo#9", runtime="fake", worker_role="builder",
                                                            workflow="wf/v1", max_runtime_seconds=60, prompt="bounded"))
    store.close()

    # 10. wiring: unsatisfied prerequisite rejects before dispatch.
    issues2 = {"acme/repo#1": issue("acme/repo#1", body="Blocked by: #2"),
               "acme/repo#2": issue("acme/repo#2")}
    gh2 = FakeGitHub(issues2)
    store, app = launcher(root / "g3", issues2, graph_reader=make_graph_reader(gh2.get_issue))
    expect_code("unsatisfied_prerequisite", lambda: app.resume("acme/repo#1", runtime="fake", worker_role="builder",
                                                               workflow="wf/v1", max_runtime_seconds=60, prompt="bounded"))
    store.close()

    # 11. wiring: writer domain conflict rejects.
    store, app = launcher(root / "g4", {"acme/repo#4": issue("acme/repo#4")},
                          writer=lambda: ({"domain": "state", "owner": "other-driver"},))
    expect_code("shared_store_writer_conflict", lambda: app.resume("acme/repo#4", runtime="fake", worker_role="builder",
                                                                   workflow="wf/v1", max_runtime_seconds=60, prompt="bounded"))
    store.close()


def raises(exc_type, fn):
    try:
        fn()
    except exc_type:
        return True
    except Exception:
        return False
    return False


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="launcher-inventory-test-"))
    try:
        run(root)
    finally:
        for store in OPEN_STORES:
            try:
                store.close()
            except Exception:
                pass
    if FAILS:
        print(f"test_launcher_inventory: FAIL ({len(FAILS)}): {FAILS}")
        return 1
    print("test_launcher_inventory: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
