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
        key = f"{repo}#{issue_num}"
        cur = self.labels.setdefault(key, [])
        if remove in cur:
            cur.remove(remove)
        cur.append(add)

    def comment(self, repo, issue_num, body):
        self.comments.append((f"{repo}#{issue_num}", body))


def new_dispatcher(labels=None):
    ws = tempfile.mkdtemp(prefix="dispatcher-")
    reg = d.RunRegistry(Path(ws) / "runs.json")
    gh = FakeGitHub(labels)
    return d.Dispatcher(reg, gh), gh


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

print("== claim: enforces max_parallel_workers=2 ==")
disp4, gh4 = new_dispatcher({"o/r#4": ["workflow:ready"], "o/r#5": ["workflow:ready"], "o/r#6": ["workflow:ready"]})
disp4.claim("o/r#4", "wedge-b", "builder", "hermes", 600)
disp4.claim("o/r#5", "wedge-b", "builder", "hermes", 600)
try:
    disp4.claim("o/r#6", "wedge-b", "builder", "hermes", 600)
    check("raises past worker cap", False)
except RuntimeError:
    check("raises past worker cap", True)

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

print("== spawn_child: delegation_depth=1, same issue_id, own child run_id ==")
disp7, gh7 = new_dispatcher({"o/r#9": ["workflow:ready"]})
parent = disp7.claim("o/r#9", "wedge-b", "builder", "hermes", 600)
child = disp7.spawn_child(parent.run_id, 1)
check("child issue_id matches parent", child.issue_id == parent.issue_id)
check("child run_id derived from parent", child.run_id == f"{parent.run_id}.1")
check("child records parent_run_id", child.parent_run_id == parent.run_id)
try:
    disp7.spawn_child(child.run_id, 1)
    check("refuses depth > 1", False)
except RuntimeError:
    check("refuses depth > 1", True)

print("== sweep_expired: expired lease -> timed_out, label -> blocked ==")
disp8, gh8 = new_dispatcher({"o/r#10": ["workflow:ready"]})
run8 = disp8.claim("o/r#10", "wedge-b", "builder", "hermes", lease_seconds=1)
disp8.registry.update(run8.run_id, claimed_at=time.time() - 10)  # force expiry
swept = disp8.sweep_expired()
check("run swept", swept == [run8.run_id])
check("status timed_out", disp8.query(run8.run_id)["status"] == "timed_out")
check("label moved to workflow:blocked", gh8.labels["o/r#10"] == ["workflow:blocked"])

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

if fail:
    print(f"\n{len(fail)} check(s) failed: {fail}")
    sys.exit(1)
print("\nall checks passed")
sys.exit(0)
