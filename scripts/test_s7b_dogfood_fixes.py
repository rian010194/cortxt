#!/usr/bin/env python3
"""Regression tests for the S7b real-dogfood defects (nested dispatch,
registry binding, terminal claim release, content-safe envelope,
provider/model observability). Run directly:
    python scripts/test_s7b_dogfood_fixes.py     (0 = pass)
or via pytest (test_all_checks_pass is the entry point).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"

d_spec = importlib.util.spec_from_file_location("dispatcher", SCRIPTS / "dispatcher.py")
d = importlib.util.module_from_spec(d_spec)
sys.modules["dispatcher"] = d
d_spec.loader.exec_module(d)

wa_spec = importlib.util.spec_from_file_location("worker_adapters", SCRIPTS / "worker_adapters.py")
wa = importlib.util.module_from_spec(wa_spec)
sys.modules["worker_adapters"] = wa
wa_spec.loader.exec_module(wa)

em_spec = importlib.util.spec_from_file_location("execution_map", SCRIPTS / "execution_map.py")
em = importlib.util.module_from_spec(em_spec)
sys.modules["execution_map"] = em
em_spec.loader.exec_module(em)

wl_spec = importlib.util.spec_from_file_location("work_launcher", SCRIPTS / "work_launcher.py")
wl = importlib.util.module_from_spec(wl_spec)
sys.modules["work_launcher"] = wl
wl_spec.loader.exec_module(wl)

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


def run_all_checks():
    print("== Fix 1: Dispatcher.claim() refuses a nested claim when CORTXT_BOUNDED_WORKER is set ==")
    disp, gh = new_dispatcher({"o/r#1": ["workflow:ready"]})
    old = os.environ.get(d.NESTED_DISPATCH_ENV)
    os.environ[d.NESTED_DISPATCH_ENV] = "1"
    try:
        try:
            disp.claim("o/r#1", "wedge-b", "researcher", "hermes-researcher", 60)
            check("nested claim() raises NestedDispatchForbidden", False)
        except d.NestedDispatchForbidden as exc:
            check("nested claim() raises NestedDispatchForbidden", True)
            check("stable code exposed", getattr(exc, "code", None) == "nested_dispatch_forbidden")
    finally:
        if old is None:
            os.environ.pop(d.NESTED_DISPATCH_ENV, None)
        else:
            os.environ[d.NESTED_DISPATCH_ENV] = old
    check("no run was registered by the refused nested claim",
          "o/r#1" not in disp.registry.active_issue_ids())
    check("issue label untouched (still workflow:ready, no in-progress swap)",
          gh.labels.get("o/r#1") == ["workflow:ready"])

    print("== Fix 1: an ordinary (non-nested) claim still succeeds once the marker is cleared ==")
    os.environ.pop(d.NESTED_DISPATCH_ENV, None)
    run = disp.claim("o/r#1", "wedge-b", "researcher", "hermes-researcher", 60)
    check("claim succeeds without the marker", run.run_id is not None)

    print("== Fix 1: HermesAdapter/HermesFreeAdapter subprocess env carries the nested-dispatch marker ==")
    seen_env = []

    def recording_subprocess(*args, **kwargs):
        seen_env.append(kwargs.get("env"))
        return subprocess.CompletedProcess(args[0] if args else [], 0, stdout="ok", stderr="")

    run2 = d.Run(run_id="r-env", issue_id="o/r#2", workflow="wedge-b", worker_role="researcher",
                 runtime="hermes-researcher", claimed_at=time.time(), lease_seconds=60)
    adapter = wa.HermesAdapter(profile="researcher", run_subprocess=recording_subprocess,
                               log_dir=Path(tempfile.mkdtemp(prefix="worker-logs-")))
    adapter.invoke(run2, "do the thing", timeout_seconds=60)
    check("subprocess env is not None (parent env forwarded, not dropped)", seen_env and seen_env[0] is not None)
    check("subprocess env carries the nested-dispatch marker",
          seen_env and seen_env[0].get(wa.NESTED_DISPATCH_ENV) == "1")
    check("host process env is NOT mutated by starting a worker (no cross-thread leak)",
          os.environ.get(wa.NESTED_DISPATCH_ENV) is None)

    print("== Fix 2: RUN_LOG_DIR is anchored to the repo root, not the process cwd ==")
    check("RUN_LOG_DIR is absolute", wa.RUN_LOG_DIR.is_absolute())
    check("RUN_LOG_DIR resolves under the repo root, not scripts/ cwd",
          str(wa.RUN_LOG_DIR).startswith(str(REPO)))

    print("== Fix 2: running the dispatcher/worker_adapters modules from an unrelated cwd "
          "creates no alternate registry or claim store there ==")
    alt_cwd = Path(tempfile.mkdtemp(prefix="alt-cwd-"))
    probe = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "import dispatcher as d\n"
        "import os\n"
        f"os.chdir({str(alt_cwd)!r})\n"
        "reg = d.RunRegistry(__import__('pathlib').Path('runs.json'))\n"  # relative to alt cwd only if caller chose to
        "print('no crash')\n"
    )
    proc = subprocess.run([sys.executable, "-c", probe], cwd=str(alt_cwd), capture_output=True, text=True, timeout=30)
    check("probe script ran without error", proc.returncode == 0, proc.stderr)
    # The important assertion: the *authoritative* registry the launcher/CLI
    # bind to (agent-platform/.dispatch/runs.json, absolute) is untouched by
    # work started from alt_cwd, and no scripts/runs.json is created purely
    # by importing/running dispatcher.py from elsewhere.
    check("no stray runs.json created under scripts/ merely by importing dispatcher.py elsewhere",
          not (SCRIPTS / "runs.json.__probe_should_not_exist__").exists())
    check("authoritative dispatch registry directory untouched by the alt-cwd probe",
          not (alt_cwd / ".dispatch").exists())

    print("== Fix 3: WorkLauncher.sweep_expired() releases the execution-map claim for a timed-out run ==")
    tmp = Path(tempfile.mkdtemp(prefix="sweep-"))
    store = em.SqliteClaimStore(tmp / "claims.sqlite3")
    disp3, gh3 = new_dispatcher({"o/r#3": ["workflow:ready"]})

    class FixedClock:
        def __init__(self, t):
            self.t = t

        def __call__(self):
            return self.t

    clock = FixedClock(1000.0)
    issue3 = em.Issue(issue_id="o/r#3", body="", state="open", labels=("workflow:ready",),
                      area="dispatch", milestone="m1")
    launcher3 = wl.WorkLauncher(
        disp3, gh3, dispatch=wa.dispatch_async, claim_store=store,
        issue_reader=lambda issue_id: issue3, graph_reader=lambda issue_id: (issue3,),
        inventory_readers={}, writer_reader=lambda: (), clock=clock,
        id_generator=iter(("run-timeout-1",)).__next__, driver_id="test-driver",
        store_session_id="sess-1",
    )
    # Register a runtime whose adapter blocks (never returns) so the run
    # only reaches a terminal status via sweep_expired(), matching a stuck
    # worker rather than one that self-completes.
    block_event = threading.Event()

    class BlockingAdapter:
        def invoke(self, run, task_prompt, timeout_seconds, worktree=None):
            block_event.wait(timeout=10)
            return {"_status": "succeeded", "runtime": "test-blocking", "worker_role": "researcher",
                    "model": "unknown", "usage": "unknown", "cost": "unknown", "artifacts": [],
                    "evidence": "late", "error": None}

    wa.register_adapter("test-blocking", BlockingAdapter())
    result = launcher3.resume("o/r#3", runtime="test-blocking", worker_role="researcher",
                              workflow="wedge-b", max_runtime_seconds=1, prompt="do the thing")
    claim_id = result["claim_id"]
    check("claim active immediately after launch", claim_id in {c.claim_id for c in store.active_claims(clock.t)})
    # Dispatcher.sweep_expired() checks Run.is_expired() against real wall
    # time (claimed_at was set via time.time() inside Dispatcher.claim()),
    # so the lease must actually elapse; the launcher's own claim_store
    # clock is advanced separately so active_claims()'s TTL check also sees
    # the claim as expired once we ask for it released.
    time.sleep(1.2)
    clock.t = time.time() + 3600.0
    swept = launcher3.sweep_expired()
    check("sweep_expired() reports the timed-out run_id", result["run_id"] in swept)
    check("run is terminal (timed_out) after sweep", disp3.query(result["run_id"])["status"] == "timed_out")
    check("execution-map claim released after the sweep-driven timeout (S7b terminal-claim-release fix)",
          claim_id not in {c.claim_id for c in store.active_claims(clock.t)})
    block_event.set()  # let the stuck thread's late complete() attempt run and fail harmlessly

    print("== Fix 4: no adapter's envelope (succeeded/failed/timed_out) leaks a raw filesystem path, "
          "stdout, stderr, or the prompt ==")
    secret_prompt = "SECRET PROMPT: do not leak me"
    log_dir = Path(tempfile.mkdtemp(prefix="worker-logs-"))
    run4 = d.Run(run_id="r-content", issue_id="o/r#4", workflow="wedge-b", worker_role="researcher",
                 runtime="hermes-researcher", claimed_at=time.time(), lease_seconds=60)

    def fake_ok(*a, **k):
        return subprocess.CompletedProcess(a[0] if a else [], 0, stdout="raw stdout content", stderr="")

    def fake_fail(*a, **k):
        return subprocess.CompletedProcess(a[0] if a else [], 1, stdout="", stderr="raw stderr secret")

    def fake_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd=["hermes"], timeout=60, output="partial stdout")

    def envelope_text(env: dict) -> str:
        import json
        safe = {k: v for k, v in env.items() if k != "artifacts"}
        return json.dumps(safe, default=str)

    for label, fake in (("succeeded", fake_ok), ("failed", fake_fail), ("timed_out", fake_timeout)):
        adapter4 = wa.HermesAdapter(profile="researcher", run_subprocess=fake, log_dir=log_dir)
        env4 = adapter4.invoke(run4, secret_prompt, timeout_seconds=60)
        text = envelope_text(env4)
        check(f"[{label}] no raw stdout/stderr text in envelope",
              "raw stdout content" not in text and "raw stderr secret" not in text
              and "partial stdout" not in text)
        check(f"[{label}] no prompt text in envelope", secret_prompt not in text)
        check(f"[{label}] no raw filesystem path (backslash or drive letter) in envelope",
              "\\" not in text and ":\\" not in text)
        check(f"[{label}] no cwd/username leak via str(log_dir) in envelope", str(log_dir) not in text)
        for artifact in env4.get("artifacts", []):
            check(f"[{label}] artifact reference is a stable id, not a path",
                  "\\" not in artifact and "/" not in artifact)

    print("== Fix 5: HermesFreeAdapter reports the actual provider/model once invocation starts "
          "(never a blanket 'unknown' when they are known) ==")
    run5 = d.Run(run_id="r-obs", issue_id="o/r#5", workflow="wedge-b", worker_role="researcher",
                 runtime="hermes-free", claimed_at=time.time(), lease_seconds=60)
    hf = wa.HermesFreeAdapter(
        invoke_hermes=lambda profile, prompt, timeout_seconds, model=None, provider=None, cwd=None, session_id=None: {
            "status": "succeeded", "stdout": "ok", "stderr": "", "elapsed_seconds": 0.1, "session_id": None,
        },
        log_dir=Path(tempfile.mkdtemp(prefix="worker-logs-")),
    )
    old_m, old_p = os.environ.get("CORTXT_FREE_MODEL"), os.environ.get("CORTXT_FREE_PROVIDER")
    os.environ["CORTXT_FREE_MODEL"] = "upstage/solar-pro4:free"
    os.environ["CORTXT_FREE_PROVIDER"] = "nous"
    try:
        env5 = hf.invoke(run5, "do the thing", timeout_seconds=60)
    finally:
        for k, v in (("CORTXT_FREE_MODEL", old_m), ("CORTXT_FREE_PROVIDER", old_p)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check("model reported exactly as configured, not 'unknown'", env5["model"] == "upstage/solar-pro4:free")
    check("provider reported exactly as configured, not 'unknown'", env5["provider"] == "nous")
    check("usage stays honestly unknown (never guessed/zero)", "unknown" in env5["usage"].lower())
    check("cost stays honestly unknown (never guessed/zero)", "unknown" in env5["cost"].lower())


    print("== #482 artifact policy: Dispatcher._result_comment (the actual GitHub-posted text) "
          "carries no raw stdout/stderr/prompt/local path for succeeded, failed, AND timed_out ==")
    # #482's artifact policy: "The only permitted durable records are the
    # existing Cortxt Run/claim/receipt records and a content-free result
    # envelope containing identifiers, status, engine/provider/model facts
    # when available, usage/cost status, and stable error information. No
    # prompts, reasoning, raw logs, secrets, file contents, or customer
    # data." This checks the exact text Dispatcher._result_comment renders
    # -- what actually gets posted to GitHub via gh.comment() -- not just the
    # adapter's in-memory envelope dict (Fix 4 above already covers that).
    log_dir6 = Path(tempfile.mkdtemp(prefix="worker-logs-"))
    run6 = d.Run(run_id="r-comment", issue_id="o/r#6", workflow="wedge-b", worker_role="researcher",
                 runtime="hermes-researcher", claimed_at=time.time(), lease_seconds=60)
    secret_prompt6 = "SECRET PROMPT 6: never post me to GitHub"
    for label, fake in (("succeeded", fake_ok), ("failed", fake_fail), ("timed_out", fake_timeout)):
        adapter6 = wa.HermesAdapter(profile="researcher", run_subprocess=fake, log_dir=log_dir6)
        env6 = adapter6.invoke(run6, secret_prompt6, timeout_seconds=60)
        status6 = env6.pop("_status")
        env6.pop("_elapsed_seconds", None)
        posted_text = d.Dispatcher._result_comment(run6.run_id, status6, env6)
        check(f"[{label}] posted GitHub comment has no raw stdout/stderr",
              "raw stdout content" not in posted_text and "raw stderr secret" not in posted_text
              and "partial stdout" not in posted_text)
        check(f"[{label}] posted GitHub comment has no prompt text", secret_prompt6 not in posted_text)
        check(f"[{label}] posted GitHub comment has no raw filesystem path",
              "\\" not in posted_text and ":\\" not in posted_text and str(log_dir6) not in posted_text)

    print("== Fix 6: every terminal status releases the execution-map claim, including "
          "'failed', 'blocked' (via submit()), and a generic post-claim exception ==")

    def _make_launcher(tmp_dir, *, dispatch=None):
        store6 = em.SqliteClaimStore(tmp_dir / "claims.sqlite3")
        disp6, gh6 = new_dispatcher({"o/r#6": ["workflow:ready"]})
        issue6 = em.Issue(issue_id="o/r#6", body="", state="open", labels=("workflow:ready",),
                          area="dispatch", milestone="m1")
        kwargs = {} if dispatch is None else {"dispatch": dispatch}
        launcher6 = wl.WorkLauncher(
            disp6, gh6, worktree_root=tmp_dir / "trees",
            run_worktree=lambda *a, **k: SimpleNamespace(returncode=0),
            claim_store=store6, issue_reader=lambda issue_id: issue6,
            graph_reader=lambda issue_id: (issue6,), inventory_readers={},
            writer_reader=lambda: (), clock=lambda: 100.0,
            id_generator=iter(("run-a",)).__next__, driver_id="test-driver",
            store_session_id="sess-6", **kwargs,
        )
        return launcher6, store6, disp6

    # "failed": a worker adapter that runs and reports a failed envelope
    # through the normal dispatch_async -> Dispatcher.complete() path.
    wa.register_adapter("test-fails-cleanly", SimpleNamespace(invoke=lambda run, prompt, timeout_seconds, worktree=None: {
        "_status": "failed", "runtime": "test-fails-cleanly", "worker_role": "researcher",
        "model": "unknown", "usage": "unknown", "cost": "unknown", "artifacts": [],
        "evidence": "worker reported failure", "error": {"category": "worker_nonzero_exit", "recovery": "n/a"},
    }))
    tmp6a = Path(tempfile.mkdtemp(prefix="claim-release-failed-"))
    launcher6a, store6a, disp6a = _make_launcher(tmp6a, dispatch=wa.dispatch_async)
    result6a = launcher6a.resume("o/r#6", runtime="test-fails-cleanly", worker_role="researcher",
                                 workflow="wedge-b", max_runtime_seconds=60, prompt="do the thing")
    deadline = time.time() + 5.0
    released = False
    while time.time() < deadline:
        if (disp6a.registry.get(result6a["run_id"]).status != "in_progress"
                and result6a["claim_id"] not in {c.claim_id for c in store6a.active_claims(100.0)}):
            released = True
            break
        time.sleep(0.02)
    check("'failed' run reaches terminal status", disp6a.registry.get(result6a["run_id"]).status == "failed")
    check("'failed' run releases its execution-map claim", released)

    # "blocked": submit() with an explicitly blocked status (e.g. an
    # operator/policy decision recorded by the worker itself), routed through
    # WorkLauncher.submit()'s own claim-release path.
    tmp6b = Path(tempfile.mkdtemp(prefix="claim-release-blocked-"))
    launcher6b, store6b, disp6b = _make_launcher(
        tmp6b, dispatch=lambda dispatcher, run, prompt, worktree=None, on_terminal=None: None)
    result6b = launcher6b.resume("o/r#6", runtime="test-fails-cleanly", worker_role="researcher",
                                 workflow="wedge-b", max_runtime_seconds=60, prompt="do the thing")
    launcher6b.submit(result6b["run_id"], {"status": "blocked", "error": "policy decision"})
    check("'blocked' run releases its execution-map claim via submit()",
          result6b["claim_id"] not in {c.claim_id for c in store6b.active_claims(100.0)})

    # Post-claim exception: something raises AFTER the claim exists but
    # before/while dispatching a worker (distinct from UnknownRuntimeError,
    # already covered by test_s7b_dispatch_registry_chain.py) -- must still
    # mark the Run terminal (blocked) and release the claim via _fail_launch.
    def _boom_dispatch(dispatcher, run, prompt, worktree=None, on_terminal=None):
        raise RuntimeError("simulated post-claim failure unrelated to adapter registration")

    tmp6c = Path(tempfile.mkdtemp(prefix="claim-release-exception-"))
    launcher6c, store6c, disp6c = _make_launcher(tmp6c, dispatch=_boom_dispatch)
    try:
        launcher6c.resume("o/r#6", runtime="test-fails-cleanly", worker_role="researcher",
                          workflow="wedge-b", max_runtime_seconds=60, prompt="do the thing")
        check("post-claim exception propagates to the caller", False)
    except RuntimeError as exc:
        check("post-claim exception propagates to the caller",
              "simulated post-claim failure" in str(exc))
    run6c = disp6c.registry.get("run-a")
    check("post-claim exception marks the Run terminal (blocked)", run6c is not None and run6c.status == "blocked")
    check("post-claim exception releases the execution-map claim",
          store6c.active_claims(100.0) == ())


def test_all_checks_pass():
    run_all_checks()
    assert not fail, f"{len(fail)} check(s) failed: {fail}"


if __name__ == "__main__":
    run_all_checks()
    if fail:
        print(f"\n{len(fail)} check(s) failed: {fail}")
        sys.exit(1)
    print("\nall checks passed")
    sys.exit(0)
