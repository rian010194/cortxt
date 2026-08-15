#!/usr/bin/env python3
"""Deterministic regression tests for scripts/worker_adapters.py (#122).

No real hermes/subprocess/network calls: HermesAdapter is exercised with an
injected fake `run_subprocess`, matching the FakeGitHub pattern already used
in test_dispatcher.py. Run directly: python scripts/test_worker_adapters.py
(0 = pass)
"""
import importlib.util
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# dispatcher.py first, registered under its import name so worker_adapters.py's
# `from dispatcher import Dispatcher, Run` resolves via sys.modules.
d_spec = importlib.util.spec_from_file_location("dispatcher", REPO / "scripts" / "dispatcher.py")
d = importlib.util.module_from_spec(d_spec)
sys.modules["dispatcher"] = d
d_spec.loader.exec_module(d)

wa_spec = importlib.util.spec_from_file_location("worker_adapters", REPO / "scripts" / "worker_adapters.py")
wa = importlib.util.module_from_spec(wa_spec)
wa_spec.loader.exec_module(wa)

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


def fake_completed(returncode=0, stdout="ok", stderr=""):
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)
    return _run


def fake_timeout(cmd, timeout, stdout="partial"):
    def _run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output=stdout)
    return _run


print("== HermesAdapter.invoke: success -> succeeded envelope, no cost/usage guessed ==")
adapter = wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(0, stdout="did the thing"))
run = d.Run(run_id="r1", issue_id="o/r#1", workflow="wedge-b", worker_role="researcher",
            runtime="hermes-researcher", claimed_at=time.time(), lease_seconds=60)
env = adapter.invoke(run, "do the thing", timeout_seconds=60)
check("status succeeded", env["_status"] == "succeeded")
check("evidence carries stdout", "did the thing" in env["evidence"])
check("cost reported unknown, not zero", "unknown" in env["cost"].lower())
check("usage reported unknown, not guessed", "unknown" in env["usage"].lower())
check("error is None on success", env["error"] is None)

print("== HermesAdapter.invoke: nonzero exit -> failed envelope with stderr in recovery ==")
adapter2 = wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(1, stdout="", stderr="boom: bad prompt"))
env2 = adapter2.invoke(run, "do the thing", timeout_seconds=60)
check("status failed", env2["_status"] == "failed")
check("error category set", env2["error"]["category"] == "worker_nonzero_exit")
check("stderr surfaced in recovery", "boom" in env2["error"]["recovery"])

print("== HermesAdapter.invoke: subprocess timeout -> timed_out envelope, not an exception ==")
adapter3 = wa.HermesAdapter(profile="researcher", run_subprocess=fake_timeout(["hermes"], 60))
env3 = adapter3.invoke(run, "do the thing", timeout_seconds=60)
check("status timed_out", env3["_status"] == "timed_out")
check("error category timeout", env3["error"]["category"] == "timeout")

print("== HermesAdapter.invoke: hermes not on PATH -> failed envelope, not an exception ==")
def _missing(*a, **k):
    raise FileNotFoundError("hermes")
adapter4 = wa.HermesAdapter(profile="researcher", run_subprocess=_missing)
env4 = adapter4.invoke(run, "do the thing", timeout_seconds=60)
check("status failed", env4["_status"] == "failed")
check("error category runtime_unavailable", env4["error"]["category"] == "runtime_unavailable")

print("== ADAPTER_REGISTRY: hermes-researcher registered by default ==")
check("hermes-researcher present", "hermes-researcher" in wa.ADAPTER_REGISTRY)
check("default adapter is a HermesAdapter for profile researcher",
      isinstance(wa.ADAPTER_REGISTRY["hermes-researcher"], wa.HermesAdapter)
      and wa.ADAPTER_REGISTRY["hermes-researcher"].profile == "researcher")

print("== register_adapter: dynamic selection, no hardcoded runtime ==")
wa.register_adapter("fake-runtime", wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(0)))
check("new runtime resolvable after registration", "fake-runtime" in wa.ADAPTER_REGISTRY)

print("== dispatch_async: unknown runtime raises before touching the dispatcher ==")
disp, gh = new_dispatcher({"o/r#2": ["workflow:ready"]})
run_unknown = disp.claim("o/r#2", "wedge-b", "researcher", "no-such-runtime", 60)
try:
    wa.dispatch_async(disp, run_unknown, "do the thing")
    check("raises UnknownRuntimeError", False)
except wa.UnknownRuntimeError:
    check("raises UnknownRuntimeError", True)
check("no complete() side effect on unknown runtime", disp.query(run_unknown.run_id)["status"] == "in_progress")

print("== dispatch_async: end-to-end succeeded run reaches dispatcher.complete() via background thread ==")
disp2, gh2 = new_dispatcher({"o/r#3": ["workflow:ready"]})
wa.register_adapter("test-hermes-ok", wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(0, stdout="worked")))
run2 = disp2.claim("o/r#3", "wedge-b", "researcher", "test-hermes-ok", 60)
thread = wa.dispatch_async(disp2, run2, "do the thing")
thread.join(timeout=5)
check("thread finished", not thread.is_alive())
q = disp2.query(run2.run_id)
check("run completed via complete()", q["status"] == "succeeded")
check("label moved to workflow:review (top-level run)", gh2.labels["o/r#3"] == ["workflow:review"])
check("result envelope has no leaked internal keys", "_status" not in q["result"] and "_elapsed_seconds" not in q["result"])

print("== dispatch_async: end-to-end failed run moves label to workflow:blocked ==")
disp3, gh3 = new_dispatcher({"o/r#4": ["workflow:ready"]})
wa.register_adapter("test-hermes-fail", wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(1, stderr="bad")))
run3 = disp3.claim("o/r#4", "wedge-b", "researcher", "test-hermes-fail", 60)
thread3 = wa.dispatch_async(disp3, run3, "do the thing")
thread3.join(timeout=5)
check("label moved to workflow:blocked", gh3.labels["o/r#4"] == ["workflow:blocked"])

if fail:
    print(f"\n{len(fail)} check(s) failed: {fail}")
    sys.exit(1)
print("\nall checks passed")
sys.exit(0)
