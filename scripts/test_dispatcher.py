#!/usr/bin/env python3
"""Deterministic regression tests for scripts/dispatcher.py (#122).

Exercises the claim/run-identity requirements from
docs/architecture/dispatch-contract.md against a fake GitHubOps, so no real
gh/network calls happen. Run directly: python scripts/test_dispatcher.py
(0 = pass)
"""
import importlib.util
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "dispatcher.py"
spec = importlib.util.spec_from_file_location("dispatcher", MOD)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

fail = []


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fail.append(name)


class FakeGitHub:
    def __init__(self, labels=None):
        self.labels = dict(labels or {})
        self.comments = []

    def get_labels(self, repo, issue_num):
        return self.labels.get(f"{repo}#{issue_num}", [])

    def swap_label(self, repo, issue_num, remove, add):
        # Matches real `gh issue edit --remove-label --add-label` semantics:
        # both operations are idempotent (removing an absent label, or
        # adding an already-present one, is a no-op), so a retried
        # swap_label after a partial failure doesn't duplicate labels.
        key = f"{repo}#{issue_num}"
        cur = self.labels.setdefault(key, [])
        if remove in cur:
            cur.remove(remove)
        if add not in cur:
            cur.append(add)

    def comment(self, repo, issue_num, body):
        self.comments.append((f"{repo}#{issue_num}", body))


def new_dispatcher(labels=None):
    ws = tempfile.mkdtemp(prefix="dispatcher-")
    reg = d.RunRegistry(Path(ws) / "runs.json")
    gh = FakeGitHub(labels)
    return d.Dispatcher(reg, gh), gh

def run_all_checks():
    print("== claim: run_id generated, labels swapped, claim comment posted ==")
    disp, gh = new_dispatcher({"o/r#1": ["workflow:ready"]})
    run = disp.claim("o/r#1", workflow="wedge-b", worker_role="builder", runtime="hermes", lease_seconds=600)
    check("run_id looks generated (not empty, has uuid suffix)", bool(run.run_id) and "_" in run.run_id)
    check("label swapped ready -> in-progress", gh.labels["o/r#1"] == ["workflow:in-progress"])
    check("claim comment posted", len(gh.comments) == 1 and run.run_id in gh.comments[0][1])
    check("status starts in_progress", run.status == "in_progress")

    print("== claim: refuses issue not in workflow:ready ==")
    disp2, gh2 = new_dispatcher({"o/r#2": ["workflow:blocked"]})
    try:
        disp2.claim("o/r#2", "wedge-b", "builder", "hermes", 600)
        check("raises on non-ready issue", False)
    except RuntimeError:
        check("raises on non-ready issue", True)

    print("== claim: refuses a second claim on the same issue ==")
    disp3, gh3 = new_dispatcher({"o/r#3": ["workflow:ready"]})
    disp3.claim("o/r#3", "wedge-b", "builder", "hermes", 600)
    gh3.labels["o/r#3"].append("workflow:ready")  # simulate a stale re-check
    try:
        disp3.claim("o/r#3", "wedge-b", "builder", "hermes", 600)
        check("raises on duplicate claim", False)
    except RuntimeError:
        check("raises on duplicate claim", True)

    print("== claim: unbounded by default, no worker cap (#136) ==")
    disp4, gh4 = new_dispatcher({"o/r#4": ["workflow:ready"], "o/r#5": ["workflow:ready"], "o/r#6": ["workflow:ready"]})
    disp4.claim("o/r#4", "wedge-b", "builder", "hermes", 600)
    disp4.claim("o/r#5", "wedge-b", "builder", "hermes", 600)
    disp4.claim("o/r#6", "wedge-b", "builder", "hermes", 600)
    check("no cap: third concurrent claim succeeds", True)

    print("== claim: max_parallel_workers still enforced when explicitly configured ==")
    ws4b = tempfile.mkdtemp(prefix="dispatcher-")
    reg4b = d.RunRegistry(Path(ws4b) / "runs.json")
    gh4b = FakeGitHub({"o/r#4b": ["workflow:ready"], "o/r#5b": ["workflow:ready"], "o/r#6b": ["workflow:ready"]})
    disp4b = d.Dispatcher(reg4b, gh4b, max_parallel_workers=2)
    disp4b.claim("o/r#4b", "wedge-b", "builder", "hermes", 600)
    disp4b.claim("o/r#5b", "wedge-b", "builder", "hermes", 600)
    try:
        disp4b.claim("o/r#6b", "wedge-b", "builder", "hermes", 600)
        check("raises past configured worker cap", False)
    except RuntimeError:
        check("raises past configured worker cap", True)

    print("== query by run_id: status/timestamps/result reachable ==")
    disp5, gh5 = new_dispatcher({"o/r#7": ["workflow:ready"]})
    run5 = disp5.claim("o/r#7", "wedge-b", "builder", "hermes", 600)
    q = disp5.query(run5.run_id)
    check("query returns dict, not just an unsolicited message", isinstance(q, dict))
    check("query has status", q["status"] == "in_progress")
    check("query has elapsed_seconds", q["elapsed_seconds"] >= 0)
    check("query on unknown run_id returns None", disp5.query("nope") is None)

    print("== complete: terminal result recorded, label moves to review ==")
    disp5.complete(run5.run_id, "succeeded", {"evidence": "tests passed"})
    q2 = disp5.query(run5.run_id)
    check("status now succeeded", q2["status"] == "succeeded")
    check("result envelope stored", q2["result"] == {"evidence": "tests passed"})
    check("label moved to workflow:review", gh5.labels["o/r#7"] == ["workflow:review"])

    print("== complete: failing status moves label to workflow:blocked ==")
    disp6, gh6 = new_dispatcher({"o/r#8": ["workflow:ready"]})
    run6 = disp6.claim("o/r#8", "wedge-b", "builder", "hermes", 600)
    disp6.complete(run6.run_id, "failed", {"error": "boom"})
    check("label moved to workflow:blocked", gh6.labels["o/r#8"] == ["workflow:blocked"])

    print("== complete: cancelled moves label back to workflow:ready, not blocked ==")
    disp6b, gh6b = new_dispatcher({"o/r#8b": ["workflow:ready"]})
    run6b = disp6b.claim("o/r#8b", "wedge-b", "builder", "hermes", 600)
    disp6b.complete(run6b.run_id, "cancelled", {"error": "operator abort"})
    check("label moved to workflow:ready (retryable, not blocked)", gh6b.labels["o/r#8b"] == ["workflow:ready"])

    print("== spawn_child: unbounded depth by default, same issue_id, own child run_id (#136) ==")
    disp7, gh7 = new_dispatcher({"o/r#9": ["workflow:ready"]})
    parent = disp7.claim("o/r#9", "wedge-b", "builder", "hermes", 600)
    child = disp7.spawn_child(parent.run_id, 1)
    check("child issue_id matches parent", child.issue_id == parent.issue_id)
    check("child run_id derived from parent", child.run_id == f"{parent.run_id}.1")
    check("child records parent_run_id", child.parent_run_id == parent.run_id)
    check("child depth is parent depth + 1", child.depth == 1)
    grandchild = disp7.spawn_child(child.run_id, 1)
    check("no cap: grandchild (depth 2) succeeds", grandchild.depth == 2)

    print("== spawn_child: delegation_depth still enforced when explicitly configured ==")
    ws7b = tempfile.mkdtemp(prefix="dispatcher-")
    reg7b = d.RunRegistry(Path(ws7b) / "runs.json")
    gh7b = FakeGitHub({"o/r#9b": ["workflow:ready"]})
    disp7b = d.Dispatcher(reg7b, gh7b, delegation_depth=1)
    parent7b = disp7b.claim("o/r#9b", "wedge-b", "builder", "hermes", 600)
    child7b = disp7b.spawn_child(parent7b.run_id, 1)
    try:
        disp7b.spawn_child(child7b.run_id, 1)
        check("refuses depth > configured max", False)
    except RuntimeError:
        check("refuses depth > configured max", True)

    print("== sweep_expired: expired lease -> timed_out, label -> blocked ==")
    disp8, gh8 = new_dispatcher({"o/r#10": ["workflow:ready"]})
    run8 = disp8.claim("o/r#10", "wedge-b", "builder", "hermes", lease_seconds=1)
    disp8.registry.update(run8.run_id, claimed_at=time.time() - 10)  # force expiry
    swept = disp8.sweep_expired()
    check("run swept", swept == [run8.run_id])
    check("status timed_out", disp8.query(run8.run_id)["status"] == "timed_out")
    check("label moved to workflow:blocked", gh8.labels["o/r#10"] == ["workflow:blocked"])

    print("== sweep_expired: expired CHILD run is swept too, but parent's label is untouched ==")
    disp8b, gh8b = new_dispatcher({"o/r#10b": ["workflow:ready"]})
    parent8b = disp8b.claim("o/r#10b", "wedge-b", "builder", "hermes", lease_seconds=600)
    child8b = disp8b.spawn_child(parent8b.run_id, 1)
    disp8b.registry.update(child8b.run_id, claimed_at=time.time() - 10, lease_seconds=1)  # force child expiry only
    swept8b = disp8b.sweep_expired()
    check("child run swept", swept8b == [child8b.run_id])
    check("child status timed_out", disp8b.query(child8b.run_id)["status"] == "timed_out")
    check("parent still in_progress", disp8b.query(parent8b.run_id)["status"] == "in_progress")
    check("label untouched by child's expiry (parent still owns it)", gh8b.labels["o/r#10b"] == ["workflow:in-progress"])

    print("== registry persistence: reload from disk keeps state ==")
    ws = tempfile.mkdtemp(prefix="dispatcher-persist-")
    regpath = Path(ws) / "runs.json"
    reg1 = d.RunRegistry(regpath)
    gh9 = FakeGitHub({"o/r#11": ["workflow:ready"]})
    disp9 = d.Dispatcher(reg1, gh9)
    run9 = disp9.claim("o/r#11", "wedge-b", "builder", "hermes", 600)
    reg2 = d.RunRegistry(regpath)
    check("reloaded registry has the run", reg2.get(run9.run_id) is not None)
    check("reloaded run has same issue_id", reg2.get(run9.run_id).issue_id == "o/r#11")

    print("== complete: refuses a second complete() on an already-terminal run (guards the async-completion race) ==")
    disp10, gh10 = new_dispatcher({"o/r#12": ["workflow:ready"]})
    run10 = disp10.claim("o/r#12", "wedge-b", "builder", "hermes", 600)
    disp10.complete(run10.run_id, "succeeded", {"evidence": "first completion"})
    try:
        disp10.complete(run10.run_id, "failed", {"evidence": "racing second completion"})
        check("raises on double complete", False)
    except RuntimeError:
        check("raises on double complete", True)
    check("first result preserved, not overwritten", disp10.query(run10.run_id)["result"] == {"evidence": "first completion"})
    check("only one result comment posted, not two", len(gh10.comments) == 2)  # claim comment + one result comment

    print("== Dispatcher._lock is reentrant (RLock): sweep_expired() already calls complete() on the same thread ==")
    disp11, gh11 = new_dispatcher({"o/r#13": ["workflow:ready"]})
    run11 = disp11.claim("o/r#13", "wedge-b", "builder", "hermes", lease_seconds=1)
    disp11.registry.update(run11.run_id, claimed_at=time.time() - 10)  # force expiry
    check("_lock is reentrant (RLock, not plain Lock)", isinstance(disp11._lock, d.threading.RLock().__class__))
    swept11 = disp11.sweep_expired()  # holds self._lock, then calls self.complete() -> re-acquires it
    check("sweep_expired -> complete() succeeded without deadlocking", swept11 == [run11.run_id])

    print("== spawn_child: mutates the registry under self._lock (was the unguarded gap) ==")
    disp12, gh12 = new_dispatcher({"o/r#14": ["workflow:ready"]})
    parent12 = disp12.claim("o/r#14", "wedge-b", "builder", "hermes", 600)
    orig_add = disp12.registry.add


    def slow_add(run):
        time.sleep(0.2)
        return orig_add(run)


    disp12.registry.add = slow_add
    spawn_thread = threading.Thread(target=lambda: disp12.spawn_child(parent12.run_id, 1))
    spawn_thread.start()
    time.sleep(0.05)  # let spawn_child enter its (now slow) registry.add() call
    heartbeat_started = time.time()
    disp12.heartbeat(parent12.run_id)  # from a DIFFERENT thread; must block until spawn_child releases the lock
    heartbeat_elapsed = time.time() - heartbeat_started
    spawn_thread.join(timeout=2)
    disp12.registry.add = orig_add
    check(
        "heartbeat() from another thread waited for spawn_child's registry mutation to finish -> lock is real",
        heartbeat_elapsed >= 0.1,
    )

    print("== complete: GitHub label/comment step runs outside the lock (only the registry transition is locked) ==")
    class SlowGitHub(FakeGitHub):
        def comment(self, repo, issue_num, body):
            # If complete() still held self._lock here, a concurrent heartbeat()
            # on a DIFFERENT run would block until this returns. It must not.
            time.sleep(0.2)
            super().comment(repo, issue_num, body)


    disp13, gh13 = new_dispatcher({"o/r#15": ["workflow:ready"], "o/r#16": ["workflow:ready"]})
    disp13.gh = SlowGitHub(disp13.gh.labels)
    run13a = disp13.claim("o/r#15", "wedge-b", "builder", "hermes", 600)
    run13b = disp13.claim("o/r#16", "wedge-b", "builder", "hermes", 600)

    complete_thread = threading.Thread(target=lambda: disp13.complete(run13a.run_id, "succeeded", {"evidence": "ok"}))
    complete_thread.start()
    time.sleep(0.05)  # let complete() get past the locked registry transition, into the slow unlocked GH call
    heartbeat_started = time.time()
    disp13.heartbeat(run13b.run_id)  # must return quickly, not block on run13a's in-flight GitHub call
    heartbeat_elapsed = time.time() - heartbeat_started
    complete_thread.join(timeout=2)
    check("heartbeat() on a different run was not blocked by another run's slow GitHub call", heartbeat_elapsed < 0.15)
    check("the slow complete() still finished successfully", disp13.query(run13a.run_id)["status"] == "succeeded")

    print("== complete: Run.gh_synced tracks whether the GitHub step actually succeeded ==")
    disp14, gh14 = new_dispatcher({"o/r#17": ["workflow:ready"]})
    run14 = disp14.claim("o/r#17", "wedge-b", "builder", "hermes", 600)
    disp14.complete(run14.run_id, "succeeded", {"evidence": "ok"})
    check("gh_synced True after an ordinary successful complete()", disp14.query(run14.run_id)["gh_synced"] is True)

    print("== resync_pending: recovers a run whose GitHub step failed, without re-running the registry transition ==")
    class FlakyGitHub(FakeGitHub):
        def __init__(self, labels=None):
            super().__init__(labels)
            self.comment_attempts = 0

        def comment(self, repo, issue_num, body):
            self.comment_attempts += 1
            if self.comment_attempts == 2:  # 1st call is claim()'s own comment; let that succeed
                raise d.GitHubError("simulated network failure")
            super().comment(repo, issue_num, body)


    disp15, gh15 = new_dispatcher({"o/r#18": ["workflow:ready"]})
    disp15.gh = FlakyGitHub(disp15.gh.labels)
    run15 = disp15.claim("o/r#18", "wedge-b", "builder", "hermes", 600)
    try:
        disp15.complete(run15.run_id, "succeeded", {"evidence": "ok"})
        check("complete() propagates the GitHub failure to its caller", False)
    except d.GitHubError:
        check("complete() propagates the GitHub failure to its caller", True)
    check("registry already correctly terminal despite the GitHub step failing", disp15.query(run15.run_id)["status"] == "succeeded")
    check("gh_synced correctly False after the failed GitHub step", disp15.query(run15.run_id)["gh_synced"] is False)
    # swap_label already succeeded before the simulated comment() failure -- gh_synced=False
    # means "the GitHub step isn't fully done", not "nothing happened yet".
    check("label already moved (swap_label succeeded before comment() failed)", gh15.labels["o/r#18"] == ["workflow:review"])
    check("resync_pending skips a fresh claim (lease not yet stale)", disp15.resync_pending() == [])
    # Simulate the claim lease going stale, as a real deployment would after
    # GH_SYNC_CLAIM_LEASE_SECONDS -- otherwise a same-second retry would
    # correctly skip (see the check just above), by design.
    disp15.registry.update(run15.run_id, gh_sync_claimed_at=time.time() - d.GH_SYNC_CLAIM_LEASE_SECONDS - 1)
    synced15 = disp15.resync_pending()
    check("resync_pending retried and succeeded once the claim lease went stale", synced15 == [run15.run_id])
    check("gh_synced now True", disp15.query(run15.run_id)["gh_synced"] is True)
    check("label finally moved to workflow:review", gh15.labels["o/r#18"] == ["workflow:review"])

    print("== _sync_github: two concurrent callers racing the same run post exactly one comment, not two ==")
    class SlowCommentGitHub(FakeGitHub):
        def comment(self, repo, issue_num, body):
            time.sleep(0.15)  # widen the race window between the claim and the actual post
            super().comment(repo, issue_num, body)


    disp17, gh17 = new_dispatcher({"o/r#20": ["workflow:ready"]})
    disp17.gh = SlowCommentGitHub(disp17.gh.labels)
    run17 = disp17.claim("o/r#20", "wedge-b", "builder", "hermes", 600)  # 1 claim comment posted
    # Simulate the exact race window: registry already terminal (as complete()
    # leaves it right after its locked transition), gh_synced still False, no
    # claim taken yet -- the state in which complete() and resync_pending() (or
    # two resync_pending() calls) could previously both reach _sync_github().
    disp17.registry.update(run17.run_id, status="succeeded")

    results17 = []


    def race_sync():
        results17.append(disp17._sync_github(run17.run_id, run17.issue_id, "succeeded", {"evidence": "race"}))


    t17a = threading.Thread(target=race_sync)
    t17b = threading.Thread(target=race_sync)
    t17a.start()
    time.sleep(0.02)  # let the first caller take the claim before the second starts
    t17b.start()
    t17a.join(timeout=2)
    t17b.join(timeout=2)

    check("exactly one caller actually performed the sync", sorted(results17) == [False, True])
    check("gh_synced now True", disp17.query(run17.run_id)["gh_synced"] is True)
    # disp17.gh (not the gh17 returned by new_dispatcher) is the live object:
    # `disp17.gh = SlowCommentGitHub(...)` reassigned disp17.gh to a new
    # instance after new_dispatcher() constructed gh17, so gh17 is a stale
    # reference from here on.
    result_comments17 = [c for c in disp17.gh.comments if "Run result" in c[1]]
    check("exactly ONE result comment posted, not two", len(result_comments17) == 1)
    check("label moved exactly once (idempotent swap, no duplicate append)", disp17.gh.labels["o/r#20"] == ["workflow:review"])

    print("== resync_pending: ignores runs that are already synced or still in_progress ==")
    disp16, gh16 = new_dispatcher({"o/r#19": ["workflow:ready"]})
    run16 = disp16.claim("o/r#19", "wedge-b", "builder", "hermes", 600)  # still in_progress, never completed
    check("nothing to resync for an in-progress run", disp16.resync_pending() == [])

def test_all_checks_pass():
    """Pytest entry point: run the same checks as the standalone script."""
    run_all_checks()
    assert not fail, f"{len(fail)} check(s) failed: {fail}"


if __name__ == "__main__":
    run_all_checks()
    if fail:
        print(f"\n{len(fail)} check(s) failed: {fail}")
        sys.exit(1)
    print("\nall checks passed")
    sys.exit(0)
