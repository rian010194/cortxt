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


def new_log_dir():
    return Path(tempfile.mkdtemp(prefix="worker-logs-"))


def fake_completed(returncode=0, stdout="ok", stderr=""):
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)
    return _run


def fake_timeout(cmd, timeout, stdout="partial"):
    def _run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output=stdout)
    return _run


def fake_raises(exc):
    def _run(*args, **kwargs):
        raise exc
    return _run


run = d.Run(run_id="r1", issue_id="o/r#1", workflow="wedge-b", worker_role="researcher",
            runtime="hermes-researcher", claimed_at=time.time(), lease_seconds=60)

print("== HermesAdapter.invoke: success -> succeeded envelope, no cost/usage guessed, no raw stdout in evidence ==")
log_dir = new_log_dir()
adapter = wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(0, stdout="did the thing"), log_dir=log_dir)
env = adapter.invoke(run, "do the thing", timeout_seconds=60)
check("status succeeded", env["_status"] == "succeeded")
check("evidence does NOT carry raw stdout (AGENTS.md: no model reasoning in GitHub)", "did the thing" not in env["evidence"])
check("evidence is a short bounded summary", len(env["evidence"]) < 200)
check("cost reported unknown, not zero", "unknown" in env["cost"].lower())
check("usage reported unknown, not guessed", "unknown" in env["usage"].lower())
check("error is None on success", env["error"] is None)
check("artifacts has exactly one local log reference", len(env["artifacts"]) == 1)
log_file = Path(env["artifacts"][0])
check("local log file actually written", log_file.exists())
check("raw stdout lives in the local log, not in the envelope", "did the thing" in log_file.read_text())
check("local log is under the injected log_dir (never the repo)", log_file.parent == log_dir)

print("== HermesAdapter.invoke: nonzero exit -> failed envelope, raw stderr in NEITHER evidence NOR error.recovery ==")
log_dir2 = new_log_dir()
adapter2 = wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(1, stdout="", stderr="boom: bad prompt"), log_dir=log_dir2)
env2 = adapter2.invoke(run, "do the thing", timeout_seconds=60)
check("status failed", env2["_status"] == "failed")
check("error category set", env2["error"]["category"] == "worker_nonzero_exit")
check("raw stderr NOT in error.recovery (AGENTS.md: no model reasoning in GitHub)", "boom" not in env2["error"]["recovery"])
check("recovery points at the local log instead", "run log" in env2["error"]["recovery"])
check("evidence has no raw content", "boom" not in env2["evidence"])
check("raw stderr still captured in the local log for debugging", "boom" in Path(env2["artifacts"][0]).read_text())

print("== HermesAdapter.invoke: local log write fails -> evidence/recovery don't falsely claim it succeeded ==")
blocked_log_dir = Path(tempfile.mkdtemp(prefix="worker-logs-")) / "blocked"
blocked_log_dir.write_text("a file, not a directory -- forces log_dir.mkdir() to fail")
adapter2b = wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(1, stdout="x", stderr="y"), log_dir=blocked_log_dir)
env2b = adapter2b.invoke(run, "do the thing", timeout_seconds=60)
check("status still failed (a logging failure must not become a worker error)", env2b["_status"] == "failed")
check("artifacts empty when the log write failed", env2b["artifacts"] == [])
check("evidence does NOT falsely claim the log was written", "could not be written" in env2b["evidence"])
check("evidence does not say 'logged locally' when it wasn't", "logged locally" not in env2b["evidence"])
check("error.recovery does NOT falsely point at a log that doesn't exist", "could not be written" in env2b["error"]["recovery"])

print("== HermesAdapter.invoke: subprocess timeout -> timed_out envelope, not an exception ==")
adapter3 = wa.HermesAdapter(profile="researcher", run_subprocess=fake_timeout(["hermes"], 60), log_dir=new_log_dir())
env3 = adapter3.invoke(run, "do the thing", timeout_seconds=60)
check("status timed_out", env3["_status"] == "timed_out")
check("error category timeout", env3["error"]["category"] == "timeout")

print("== HermesAdapter.invoke: hermes not on PATH -> failed envelope, not an exception ==")
adapter4 = wa.HermesAdapter(profile="researcher", run_subprocess=fake_raises(FileNotFoundError("hermes")), log_dir=new_log_dir())
env4 = adapter4.invoke(run, "do the thing", timeout_seconds=60)
check("status failed", env4["_status"] == "failed")
check("error category runtime_unavailable", env4["error"]["category"] == "runtime_unavailable")

print("== HermesAdapter.invoke: PermissionError -> failed envelope, not an exception ==")
adapter5 = wa.HermesAdapter(profile="researcher", run_subprocess=fake_raises(PermissionError("not executable")), log_dir=new_log_dir())
env5 = adapter5.invoke(run, "do the thing", timeout_seconds=60)
check("status failed (PermissionError caught, not raised)", env5["_status"] == "failed")
check("error category worker_invocation_error", env5["error"]["category"] == "worker_invocation_error")

print("== HermesAdapter.invoke: generic OSError -> failed envelope, not an exception ==")
adapter6 = wa.HermesAdapter(profile="researcher", run_subprocess=fake_raises(OSError("fork failed")), log_dir=new_log_dir())
env6 = adapter6.invoke(run, "do the thing", timeout_seconds=60)
check("status failed (OSError caught, not raised)", env6["_status"] == "failed")

print("== HermesAdapter.invoke: UnicodeDecodeError -> failed envelope, not an exception ==")
adapter7 = wa.HermesAdapter(
    profile="researcher",
    run_subprocess=fake_raises(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")),
    log_dir=new_log_dir(),
)
env7 = adapter7.invoke(run, "do the thing", timeout_seconds=60)
check("status failed (UnicodeDecodeError caught, not raised)", env7["_status"] == "failed")

print("== ADAPTER_REGISTRY: hermes-researcher registered by default ==")
check("hermes-researcher present", "hermes-researcher" in wa.ADAPTER_REGISTRY)
check("default adapter is a HermesAdapter for profile researcher",
      isinstance(wa.ADAPTER_REGISTRY["hermes-researcher"], wa.HermesAdapter)
      and wa.ADAPTER_REGISTRY["hermes-researcher"].profile == "researcher")

print("== ADAPTER_REGISTRY: hermes-coordinator registered by default ==")
check("hermes-coordinator present", "hermes-coordinator" in wa.ADAPTER_REGISTRY)
check("default adapter is a HermesAdapter for profile coordinator",
      isinstance(wa.ADAPTER_REGISTRY["hermes-coordinator"], wa.HermesAdapter)
      and wa.ADAPTER_REGISTRY["hermes-coordinator"].profile == "coordinator")

print("== register_adapter: dynamic selection, no hardcoded runtime ==")
wa.register_adapter("fake-runtime", wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(0), log_dir=new_log_dir()))
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
wa.register_adapter("test-hermes-ok", wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(0, stdout="worked"), log_dir=new_log_dir()))
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
wa.register_adapter("test-hermes-fail", wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(1, stderr="bad"), log_dir=new_log_dir()))
run3 = disp3.claim("o/r#4", "wedge-b", "researcher", "test-hermes-fail", 60)
thread3 = wa.dispatch_async(disp3, run3, "do the thing")
thread3.join(timeout=5)
check("label moved to workflow:blocked", gh3.labels["o/r#4"] == ["workflow:blocked"])

print("== dispatch_async: adapter that violates its contract and raises is still completed, not left stuck ==")
class RaisingAdapter:
    def invoke(self, run, task_prompt, timeout_seconds):
        raise RuntimeError("adapter bug: forgot to catch something")

disp4, gh4 = new_dispatcher({"o/r#5": ["workflow:ready"]})
wa.register_adapter("test-raising-adapter", RaisingAdapter())
run4 = disp4.claim("o/r#5", "wedge-b", "researcher", "test-raising-adapter", 60)
thread4 = wa.dispatch_async(disp4, run4, "do the thing")
thread4.join(timeout=5)
check("thread finished despite adapter raising", not thread4.is_alive())
q4 = disp4.query(run4.run_id)
check("run reached a terminal status instead of staying in_progress forever", q4["status"] == "failed")
check("error category records the contract violation", q4["result"]["error"]["category"] == "adapter_contract_violation")
check("label moved to workflow:blocked", gh4.labels["o/r#5"] == ["workflow:blocked"])

print("== dispatch_async: two runs completing concurrently do not corrupt the shared registry ==")
disp5, gh5 = new_dispatcher({"o/r#6": ["workflow:ready"], "o/r#7": ["workflow:ready"]})
wa.register_adapter("test-concurrent-a", wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(0, stdout="a"), log_dir=new_log_dir()))
wa.register_adapter("test-concurrent-b", wa.HermesAdapter(profile="researcher", run_subprocess=fake_completed(0, stdout="b"), log_dir=new_log_dir()))
run5a = disp5.claim("o/r#6", "wedge-b", "researcher", "test-concurrent-a", 60)
run5b = disp5.claim("o/r#7", "wedge-b", "researcher", "test-concurrent-b", 60)
t5a = wa.dispatch_async(disp5, run5a, "do a")
t5b = wa.dispatch_async(disp5, run5b, "do b")
t5a.join(timeout=5)
t5b.join(timeout=5)
check("both runs reached succeeded", disp5.query(run5a.run_id)["status"] == "succeeded" and disp5.query(run5b.run_id)["status"] == "succeeded")
check("both labels moved independently", gh5.labels["o/r#6"] == ["workflow:review"] and gh5.labels["o/r#7"] == ["workflow:review"])

print("== DshWorkerAdapter.invoke: succeeded envelope, no raw stdout in evidence, cost unknown ==")
dsh_log_dir = new_log_dir()
dsh_adapter = wa.DshWorkerAdapter(
    invoke_dsh=lambda prompt, timeout_seconds, cwd: {
        "status": "succeeded", "stdout": "the answer", "stderr": "",
        "session_id": "sess-1", "finish_reason": "completed", "elapsed_seconds": 1.2,
    },
    log_dir=dsh_log_dir,
)
dsh_env = dsh_adapter.invoke(run, "do the thing", timeout_seconds=60)
check("dsh status succeeded", dsh_env["_status"] == "succeeded")
check("dsh evidence does NOT carry raw stdout (AGENTS.md)", "the answer" not in dsh_env["evidence"])
check("dsh evidence is short and bounded", len(dsh_env["evidence"]) < 200)
check("dsh cost reported unknown, not zero", "unknown" in dsh_env["cost"].lower())
check("dsh error is None on success", dsh_env["error"] is None)
check("dsh artifacts has exactly one local log reference", len(dsh_env["artifacts"]) == 1)
check("dsh raw stdout lives in the local log, not the envelope", "the answer" in Path(dsh_env["artifacts"][0]).read_text())

print("== DshWorkerAdapter.invoke: failed status -> failed envelope, raw stderr stays local ==")
dsh_adapter2 = wa.DshWorkerAdapter(
    invoke_dsh=lambda prompt, timeout_seconds, cwd: {
        "status": "failed", "stdout": "", "stderr": "boom: bad prompt",
        "session_id": None, "finish_reason": None, "elapsed_seconds": 0.4,
    },
    log_dir=new_log_dir(),
)
dsh_env2 = dsh_adapter2.invoke(run, "do the thing", timeout_seconds=60)
check("dsh status failed", dsh_env2["_status"] == "failed")
check("dsh error category worker_nonzero_exit", dsh_env2["error"]["category"] == "worker_nonzero_exit")
check("dsh raw stderr NOT in error.recovery", "boom" not in dsh_env2["error"]["recovery"])
check("dsh recovery points at the local log", "run log" in dsh_env2["error"]["recovery"])
check("dsh raw stderr still captured in the local log", "boom" in Path(dsh_env2["artifacts"][0]).read_text())

print("== DshWorkerAdapter.invoke: DshInvocationError -> failed envelope, not an exception ==")
def _raising_invoke(prompt, timeout_seconds, cwd):
    raise RuntimeError("deepseek-harness-sdk is not installed")
dsh_adapter3 = wa.DshWorkerAdapter(invoke_dsh=_raising_invoke, log_dir=new_log_dir())
dsh_env3 = dsh_adapter3.invoke(run, "do the thing", timeout_seconds=60)
check("dsh status failed on raise", dsh_env3["_status"] == "failed")
check("dsh error category runtime_unavailable", dsh_env3["error"]["category"] == "runtime_unavailable")

print("== ADAPTER_REGISTRY: dsh registered by default ==")
check("dsh present in registry", "dsh" in wa.ADAPTER_REGISTRY)
check("default dsh adapter is a DshWorkerAdapter",
      isinstance(wa.ADAPTER_REGISTRY["dsh"], wa.DshWorkerAdapter))

print("== dispatch_async: end-to-end dsh run reaches dispatcher.complete() ==")
disp_dsh, gh_dsh = new_dispatcher({"o/r#8": ["workflow:ready"]})
wa.register_adapter("test-dsh-ok", wa.DshWorkerAdapter(
    invoke_dsh=lambda prompt, timeout_seconds, cwd: {
        "status": "succeeded", "stdout": "worked", "stderr": "",
        "session_id": "sess-x", "finish_reason": "completed", "elapsed_seconds": 1.0,
    },
    log_dir=new_log_dir(),
))
run_dsh = disp_dsh.claim("o/r#8", "wedge-b", "researcher", "test-dsh-ok", 60)
thread_dsh = wa.dispatch_async(disp_dsh, run_dsh, "do the thing")
thread_dsh.join(timeout=5)
check("dsh thread finished", not thread_dsh.is_alive())
q_dsh = disp_dsh.query(run_dsh.run_id)
check("dsh run completed via complete()", q_dsh["status"] == "succeeded")
check("dsh label moved to workflow:review (top-level run)", gh_dsh.labels["o/r#8"] == ["workflow:review"])
check("dsh result envelope has no leaked internal keys", "_status" not in q_dsh["result"] and "_elapsed_seconds" not in q_dsh["result"])

if fail:
    print(f"\n{len(fail)} check(s) failed: {fail}")
    sys.exit(1)
print("\nall checks passed")
sys.exit(0)
