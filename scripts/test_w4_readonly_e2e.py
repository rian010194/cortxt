#!/usr/bin/env python3
"""W-4 (#614) end-to-end: the read-only dispatch chain, launcher to settlement.

One new e2e file for the W-4 sprint, modelled on
`test_launcher_integration.check_dispatcher_completion_loop_closes`: a REAL
WorkLauncher with the REAL `dispatch_async` join path, a REAL Dispatcher (so
the W-4 read-only Evidence Gate and DISPATCH_OBSERVATIONS run exactly as in
production), a mock `git worktree` carrier, a SqliteClaimStore, and a REAL
`git init` repository as the launcher checkout -- a gitless checkout would
only ever produce `containment_scan_error`, so the containment pins below
would prove nothing.

The worker adapter is the real `HermesReadonlyAdapter` with an injected
invoker double (the established HermesAdapter test pattern), and the W-3
`PackagingOpsApi` is stubbed with a deterministic projection so the frozen
observation and its digest are byte-stable in any environment.

Pins required by the W-4 plan (supplement #4):

- `resume(..., isolate=True, mutating=False)` is passed EXPLICITLY on the
  read-only launch (signature: work_launcher.py:979);
- the `containment_snapshot_missing` arm is mutating-only
  (work_launcher.py:353-365 gates on `getattr(run, "mutating", False)`): a
  gate-time call with no snapshot flags a mutating top-level Run fail-closed
  and leaves a read-only Run unflagged.

Run directly: python scripts/test_w4_readonly_e2e.py (0 = pass). One pytest
entry point, per the colocated self-running check-script convention.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]

# dispatcher.py first, under its import name (worker_adapters resolves
# `from dispatcher import Dispatcher, Run` through sys.modules), then
# evidence_port (so adapter, gate and this file share ONE module object),
# then worker_adapters.
d_spec = importlib.util.spec_from_file_location("dispatcher", REPO / "scripts" / "dispatcher.py")
d = importlib.util.module_from_spec(d_spec)
sys.modules["dispatcher"] = d
d_spec.loader.exec_module(d)

ep_spec = importlib.util.spec_from_file_location("evidence_port", REPO / "scripts" / "evidence_port.py")
evidence_port = importlib.util.module_from_spec(ep_spec)
sys.modules["evidence_port"] = evidence_port
ep_spec.loader.exec_module(evidence_port)

wa_spec = importlib.util.spec_from_file_location("worker_adapters", REPO / "scripts" / "worker_adapters.py")
wa = importlib.util.module_from_spec(wa_spec)
sys.modules["worker_adapters"] = wa
wa_spec.loader.exec_module(wa)

from execution_map import SqliteClaimStore  # noqa: E402 - path set up above
from work_launcher import WorkLauncher  # noqa: E402

fail = []

OPEN_STORES = []

ISSUE = {"issue_id": None, "body": "", "state": "open", "labels": ("workflow:ready",),
         "area": "dispatch", "milestone": "m1"}


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fail.append(name)


class FakeGitHub:
    """Minimal label/comment surface for Dispatcher and WorkLauncher."""

    def __init__(self, issues):
        self.issues = issues
        self.comments = []

    def get_issue(self, issue_id):
        return dict(self.issues[issue_id])

    def get_labels(self, repo, issue_num):
        issue = self.issues.get(f"{repo}#{issue_num}")
        return list(issue.get("labels", ())) if issue else []

    def swap_label(self, repo, issue_num, remove, add):
        issue = self.issues.get(f"{repo}#{issue_num}")
        if not issue:
            return
        labels = list(issue.get("labels", ()))
        if remove in labels:
            labels.remove(remove)
        if add not in labels:
            labels.append(add)
        issue["labels"] = tuple(labels)

    def comment(self, repo, issue_num, body):
        self.comments.append((f"{repo}#{issue_num}", body))


def make_repo(root: Path) -> None:
    """A REAL git repository: containment scanning needs one to produce a
    real verdict (a gitless checkout can only yield containment_scan_error)."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    (root / ".gitignore").write_text("trees/\nruns.json\nclaims*.sqlite3\nlogs/\n",
                                     encoding="utf-8")
    (root / "README.md").write_text("w4 e2e\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True)


def _mock_run_worktree(argv, **kwargs):
    """The `git worktree` carrier double from the completion-loop model, with
    one upgrade for the containment pins: worktree/rev-parse calls run REAL
    git against the real fixture repository, so the post-run containment scan
    reads a genuinely clean isolated worktree instead of a stub directory.
    Only the subprocess boundary is stood in for; every argv is the real
    launcher-constructed command."""
    completed = subprocess.run(argv, cwd=kwargs.get("cwd"),
                               capture_output=True, text=True)
    if completed.returncode != 0 and len(argv) >= 3 and argv[1] == "worktree" and argv[2] == "add":
        # Never mask a real git failure silently: fall back to the model's
        # directory stub so the launch can proceed and the scan reports what
        # it actually finds.
        worktree_path = Path(argv[argv.index("HEAD") - 1])
        worktree_path.mkdir(parents=True, exist_ok=True)
    return completed


def make_launcher(root: Path, ids):
    """Real Dispatcher + real WorkLauncher over a real git checkout; the
    dispatch callable is the real `wa.dispatch_async`, so the worker thread is
    the production background thread and _dispatch's join closes the chain."""
    issues = {}
    gh = FakeGitHub(issues)
    registry = d.RunRegistry(root / "runs.json")
    disp = d.Dispatcher(registry, gh)
    store = SqliteClaimStore(root / "claims.sqlite3")
    if store not in OPEN_STORES:
        OPEN_STORES.append(store)
    app = WorkLauncher(
        disp, gh,
        dispatch=wa.dispatch_async,
        worktree_root=root / "trees",
        run_worktree=_mock_run_worktree,
        repo_path=root,
        claim_store=store,
        issue_reader=gh.get_issue,
        inventory_readers={name: (lambda: ()) for name in WorkLauncher.INVENTORY_NAMES},
        clock=lambda: 100.0,
        id_generator=lambda: next(ids),
        store_session_id="store-session-w4",
        engine_session_id="engine-session-w4",
    )
    return app, disp, gh, issues


def _readonly_invoker(observed_override=None):
    """An invoke_hermes double that honours its `--usage-file` channel: it
    embeds the task's observation in the report and ends stdout with the W-4
    attestation. `observed_override` lets an arm tamper with the payload."""
    def _invoke(profile, prompt, timeout_seconds, model=None, provider=None,
                cwd=None, usage_file=None, **_):
        idx = prompt.find("Observation (embed verbatim)")
        block = prompt[idx:] if idx >= 0 else "{}"
        start, end = block.find("{"), block.rfind("}")
        embedded = json.loads(block[start:end + 1]) if start >= 0 and end > start else {}
        observed = observed_override if observed_override is not None \
            else embedded.get("observed")
        if usage_file:
            Path(usage_file).write_text(json.dumps(
                {"completed": True, "failed": False, "report_version": 1,
                 "observed": observed}), encoding="utf-8")
        out = "readonly observation done\n" + wa.READONLY_ATTESTATION
        return {"status": "succeeded", "stdout": out, "stderr": "",
                "elapsed_seconds": 1.0, "session_id": None}
    return _invoke


@contextlib.contextmanager
def _packaging_stub(counts):
    """A deterministic stand-in for the W-3 ops API (the real package needs a
    Core store the e2e does not carry; the projection shape is what matters)."""
    class _Api:
        def __init__(self, *a, **k):
            pass

        def workstream(self):
            return dict(counts)
    mod = types.ModuleType("widget_contract.product_packaging.ops_api")
    mod.PackagingOpsApi = _Api
    pkg = types.ModuleType("widget_contract")
    pkg.product_packaging = mod
    saved = {name: sys.modules.pop(name, None) for name in (
        "widget_contract", "widget_contract.product_packaging",
        "widget_contract.product_packaging.ops_api")}
    sys.modules["widget_contract"] = pkg
    sys.modules["widget_contract.product_packaging"] = mod
    sys.modules["widget_contract.product_packaging.ops_api"] = mod
    try:
        yield
    finally:
        for name, prior in saved.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


@contextlib.contextmanager
def _free_route_env():
    """The free-route env vars `_call` demands before any invocation (#482)."""
    saved = {k: os.environ.get(k) for k in ("CORTXT_FREE_MODEL", "CORTXT_FREE_PROVIDER")}
    os.environ["CORTXT_FREE_MODEL"] = "test-free-model"
    os.environ["CORTXT_FREE_PROVIDER"] = "test-free-provider"
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main():
    registered = "test-w4-readonly"
    prior_adapter = wa.ADAPTER_REGISTRY.get(registered)
    temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        root = Path(temp.name)
        make_repo(root)

        # -- Arm 1: the read-only dispatch chain closes end-to-end ------------
        print("== W-4 #614 e2e: readonly chain closes to a gated succeeded ==")
        counts = {"packages": 3, "revisions": 7}
        digest = evidence_port.observed_digest(counts)
        check("observed_digest is stable 64-hex over the projection",
              isinstance(digest, str) and len(digest) == 64
              and evidence_port.observed_digest(dict(reversed(list(counts.items())))) == digest)
        wa.register_adapter(registered, wa.HermesReadonlyAdapter(
            invoke_hermes=_readonly_invoker(), log_dir=root / "logs"))
        app, disp, gh, issues = make_launcher(root, iter(("run-w4-1",)))
        issues["acme/repo#1"] = {**ISSUE, "issue_id": "acme/repo#1"}

        # The launch passes isolation and the mutating flag EXPLICITLY
        # (work_launcher.py:979): a read-only Run gets its own worktree and is
        # never left to whatever resume()'s defaults evolve into.
        with _packaging_stub(counts), _free_route_env():
            result = app.resume(
                "acme/repo#1", runtime=registered, worker_role="observer",
                workflow="wf/v1", max_runtime_seconds=60, prompt="observe the workstream",
                request_id="req-w4-1", isolate=True, mutating=False)
        check("resume returned the deterministic run_id", result["run_id"] == "run-w4-1")
        run = disp.registry.get("run-w4-1")
        check("run reached terminal succeeded (worker thread joined)",
              run is not None and run.status == "succeeded" and run.finished_at is not None)
        check("envelope carries the readonly evidence gate marker",
              (run.result or {}).get("evidence_gate") == evidence_port.EVIDENCE_GATE_READONLY)
        check("worker's carried observation survived the whole chain",
              (run.result or {}).get("report_payload", {}).get("observed") == counts)
        check("durable Run carries the verified readonly evidence",
              (run.readonly_report_evidence or {}).get("observed_digest") == digest)
        check("frozen observation digest == worker report digest (both sides of the equality)",
              (run.result or {}).get("observed_digest") == digest
              and evidence_port.observed_digest(run.result["report_payload"]["observed"]) == digest)
        check("settlement observation recorded after the gate passed",
              d.DISPATCH_OBSERVATIONS.get("run-w4-1", {}).get("disposition")
              == "readonly_report_verified"
              and d.DISPATCH_OBSERVATIONS["run-w4-1"]["observed_digest"] == digest)
        check("containment verdict recorded from the real scan",
              (run.containment or "") in ("containment_clean", "containment_scan_error"),
              f"containment={run.containment!r}")
        check("claim released after the terminal run",
              not app.claim_store.active_claims(100.0))
        check("label stays in-progress; review transition withheld (#493)",
              gh.issues["acme/repo#1"]["labels"] == ("workflow:in-progress",))
        check("result comment posted for the top-level run",
              any("run-w4-1" in body for _, body in gh.comments))

        # -- Arm 2: a tampered report is blocked through the FULL chain ------
        print("== W-4 #614: tampered observation -> blocked through the real chain ==")
        app2, disp2, gh2, issues2 = make_launcher(root, iter(("run-w4-2",)))
        issues2["acme/repo#2"] = {**ISSUE, "issue_id": "acme/repo#2"}
        wa.register_adapter("test-w4-tampered", wa.HermesReadonlyAdapter(
            invoke_hermes=_readonly_invoker(observed_override={"packages": 999, "revisions": 7}),
            log_dir=root / "logs"))
        with _packaging_stub(counts), _free_route_env():
            result2 = app2.resume(
                "acme/repo#2", runtime="test-w4-tampered", worker_role="observer",
                workflow="wf/v1", max_runtime_seconds=60, prompt="observe",
                request_id="req-w4-2", isolate=True, mutating=False)
        run2 = disp2.registry.get("run-w4-2")
        check("tampered report -> blocked, never succeeded", run2.status == "blocked")
        check("blocked shape carries the readonly gate failure marker",
              (run2.result or {}).get("evidence_gate") == evidence_port.READONLY_GATE_FAILED
              and (run2.result or {}).get("error", {}).get("category")
              == "readonly_report_unverifiable")
        check("no settlement observation for a refused run",
              "run-w4-2" not in d.DISPATCH_OBSERVATIONS)
        check("failing status moved the label to workflow:blocked",
              gh2.issues["acme/repo#2"]["labels"] == ("workflow:blocked",))
        check("claim released even on the blocked settlement",
              not app2.claim_store.active_claims(100.0))

        # -- Arm 3: the containment_snapshot_missing arm is MUTATING-only ----
        print("== W-4 #614: containment_snapshot_missing is mutating-only (work_launcher.py:353-365) ==")
        run_m = d.Run(run_id="run-w4-snap-m", issue_id="acme/repo#1", workflow="wf/v1",
                      worker_role="builder", runtime="hermes-free", claimed_at=1.0,
                      lease_seconds=60, mutating=True)
        disp.registry.add(run_m)
        app._record_containment(run_m.run_id)  # no snapshot recorded: gate-time call
        check("mutating top-level run with no snapshot is flagged fail-closed",
              disp.registry.get(run_m.run_id).containment == "containment_snapshot_missing")
        run_ro = d.Run(run_id="run-w4-snap-ro", issue_id="acme/repo#1", workflow="wf/v1",
                       worker_role="observer", runtime="hermes-readonly", claimed_at=1.0,
                       lease_seconds=60, mutating=False)
        disp.registry.add(run_ro)
        app._record_containment(run_ro.run_id)  # same missing snapshot, read-only run
        check("a read-only run is NEVER flagged for a missing snapshot",
              disp.registry.get(run_ro.run_id).containment is None)
    finally:
        for store in OPEN_STORES:
            store.close()
        OPEN_STORES.clear()
        temp.cleanup()
        wa.ADAPTER_REGISTRY.pop("test-w4-readonly", None)
        wa.ADAPTER_REGISTRY.pop("test-w4-tampered", None)
        if prior_adapter is not None:
            wa.ADAPTER_REGISTRY[registered] = prior_adapter

    if fail:
        print(f"\n{len(fail)} check(s) failed: {fail}")
        return 1
    print("\nall W-4 e2e checks passed")
    return 0


def test_all_checks_pass():
    """Pytest entry point: run the same checks as the standalone script."""
    rc = main()
    assert rc == 0, f"{len(fail)} check(s) failed: {fail}"


if __name__ == "__main__":
    sys.exit(main())
