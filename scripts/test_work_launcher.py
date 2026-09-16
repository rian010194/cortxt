#!/usr/bin/env python3
"""Offline fake-injection tests for the parallel work launcher."""
import contextlib
import tempfile
from pathlib import Path
from types import SimpleNamespace

import dispatcher as d
import work_launcher as w
import worker_adapters as wa

fail = []


def check(name, condition, detail=""):
    print(f"  {'ok' if condition else 'FAIL':4} {name}"
          + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        fail.append(name)


class FakeGitHub:
    def __init__(self):
        self.labels = {}

    def create_issue(self, repo, title, body):
        self.labels[f"{repo}#7"] = ["workflow:inbox"]
        return f"{repo}#7"

    def approve(self, issue_id):
        self.labels[issue_id] = ["workflow:ready"]

    def get_labels(self, repo, number):
        return self.labels[f"{repo}#{number}"]

    def swap_label(self, repo, number, remove, add):
        self.labels[f"{repo}#{number}"] = [add]

    def comment(self, repo, number, body):
        pass

def real_worktree_add(seen_cwd=None):
    """Acts like `git worktree add` (success) and actually creates the
    worktree directory so the launcher can bind the worker to it."""
    def _run(args, *a, **kwargs):
        if seen_cwd is not None:
            seen_cwd.append(kwargs.get("cwd"))
        if args[1] == "rev-parse":
            # #509: the launcher resolves the branch's base before creating it.
            return SimpleNamespace(returncode=0, stdout="0" * 40)
        # args: ["git", "worktree", "add", "-b", branch, <path>, "HEAD"]
        path = Path(args[5]) if len(args) > 5 else None
        if path:
            path.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=0)
    return _run


def fake_worktree_add(*args, **kwargs):
    """Stand-in for `git worktree add` that creates the directory like the real
    command does. S7d: the launcher verifies the worktree exists before it
    reports `isolation: "worktree"`, so a stand-in that creates nothing would
    (correctly) fail the launch closed."""
    argv = args[0] if args else kwargs.get("args")
    if argv[1] == "rev-parse":
        # #509: the launcher resolves the branch's base before creating it.
        return SimpleNamespace(returncode=0, stdout="0" * 40)
    Path(argv[-2]).mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(returncode=0)


_MISSING = object()


@contextlib.contextmanager
def _adapter_registered(name, adapter):
    """Register `name` in the process-global ADAPTER_REGISTRY and put the
    registry back exactly as it was found on the way out.

    The restore lives in a `finally`: a check that raises must not leak a
    synthetic runtime into every later test sharing this interpreter, and the
    cleanup must not replace that check's own exception either. `_MISSING` is a
    real sentinel rather than `None`, so "the key was absent" and "the key held
    None" restore differently.
    """
    prior = wa.ADAPTER_REGISTRY.get(name, _MISSING)
    wa.register_adapter(name, adapter)
    try:
        yield
    finally:
        if prior is _MISSING:
            wa.ADAPTER_REGISTRY.pop(name, None)
        else:
            wa.ADAPTER_REGISTRY[name] = prior


def main():
    # These offline tests dispatch through an injected fake `dispatch`
    # callable, not the real ADAPTER_REGISTRY -- but WorkLauncher._launch now
    # consults `runtime_launch_config_ok` (registry membership) before any
    # claim (S7b #482 follow-on), so the synthetic "fake" runtime must be
    # registered for these fixtures to reach that far.
    with _adapter_registered("fake", SimpleNamespace(invoke=lambda *a, **k: {})):
        _run_checks()

    print(f"\n{'PASS' if not fail else 'FAIL'}: {len(fail)} failure(s)")
    raise SystemExit(1 if fail else 0)


def _run_checks():
    root = Path(tempfile.mkdtemp(prefix="launcher-test-"))
    gh = FakeGitHub()
    disp = d.Dispatcher(d.RunRegistry(root / "runs.json"), gh)
    prompts = []
    launcher = w.WorkLauncher(
        disp, gh,
        dispatch=lambda dispatcher, run, prompt, worktree=None: prompts.append(prompt),
        worktree_root=root / "trees",
        run_worktree=fake_worktree_add,
    )
    result = launcher.create("o/r", "Task", "Build a safe launcher", ["Tests pass"],
                             runtime="fake", worker_role="builder", workflow="v1",
                             max_runtime_seconds=60, max_cost_usd=1.0, approved=True,
                             artifact_paths=["docs/agents/work-launcher.md"])
    check("new returns generated run id", bool(result["run_id"]))
    check("issue moved through claim to in-progress", gh.labels["o/r#7"] == ["workflow:in-progress"])
    check("worker prompt includes scope, AC, limits, and policy", all(x in prompts[0] for x in
          ("Build a safe launcher", "Tests pass", "max_runtime_seconds", "Artifact policy")))
    # W6 (plan 3.4): the versioned worker instruction -- not the legacy
    # `generate_worker_prompt` -- is what `work new` hands to the dispatch
    # boundary. It carries the contract version and the attestation grammar.
    check("work new prompt is the versioned worker instruction",
          "worker.result.v1" in prompts[0] and "CORTXT-OUTCOME: completed" in prompts[0])
    check("work new prompt carries the real request snapshot identity",
          "sha256:" in prompts[0])
    check("list returns active run metadata", launcher.list_active()[0]["worker"] == "builder")
    try:
        w.generate_worker_prompt("bad \u00e5", ["ok"], {})
        check("diacritics rejected", False)
    except ValueError:
        check("diacritics rejected", True)

    print("== #419 worktree binding: create() builds the worktree from repo_path and binds the worker to it ==")
    root2 = Path(tempfile.mkdtemp(prefix="launcher-wt-"))
    gh2 = FakeGitHub()
    disp2 = d.Dispatcher(d.RunRegistry(root2 / "runs.json"), gh2)
    repo2 = root2 / "repo"
    dispatched, seen_cwd = [], []
    launcher2 = w.WorkLauncher(
        disp2, gh2, dispatch=lambda dispatcher, run, prompt, worktree=None: dispatched.append(
            (run.run_id, worktree)),
        worktree_root=root2 / "trees",
        run_worktree=real_worktree_add(seen_cwd),
        repo_path=repo2,
    )
    res2 = launcher2.create("o/r", "Task", "Bound worker", ["Tests pass"],
                            runtime="fake", worker_role="builder", workflow="v1",
                            max_runtime_seconds=60, max_cost_usd=1.0, approved=True,
                            artifact_paths=["docs/agents/work-launcher.md"])
    check("worktree created from repo_path, not the process cwd",
          seen_cwd and seen_cwd[0] == str(repo2))
    bound = dispatched and dispatched[0]
    check("worker dispatched with the created worktree", bound and bound[1] == Path(res2["worktree"]))
    check("worktree path reported by create() exists", Path(res2["worktree"]).is_dir())

    print("== #608 worker instruction jail: isolated run's prompt carries the environment block ==")
    root2b = Path(tempfile.mkdtemp(prefix="launcher-jail-"))
    gh2b = FakeGitHub()
    # A real scratch git repository as the dispatching checkout: the launcher
    # snapshots its porcelain state pre-launch and scans it at worker terminal.
    repo2b = root2b / "repo"
    repo2b.mkdir()
    import subprocess as _sp
    _sp.run(["git", "init", "-q"], cwd=str(repo2b), capture_output=True)
    (repo2b / "seed.txt").write_text("seed\n")
    _sp.run(["git", "add", "."], cwd=str(repo2b), capture_output=True)
    _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.io", "commit", "-qm", "init"],
            cwd=str(repo2b), capture_output=True)
    disp2b = d.Dispatcher(d.RunRegistry(root2b / "runs.json"), gh2b)
    dispatched2b = []

    def fake_dispatch_with_terminal(dispatcher, run, prompt, worktree=None, on_terminal=None):
        dispatched2b.append((run.run_id, prompt, worktree, on_terminal))
        return None

    launcher2b = w.WorkLauncher(
        disp2b, gh2b, dispatch=fake_dispatch_with_terminal,
        worktree_root=repo2b / "trees",
        run_worktree=real_worktree_add(),
        repo_path=repo2b,
    )
    res2b = launcher2b.create("o/r", "Task", "Jailed worker", ["Tests pass"],
                              runtime="fake", worker_role="builder", workflow="v1",
                              max_runtime_seconds=60, max_cost_usd=1.0, approved=True,
                              artifact_paths=["docs/agents/work-launcher.md"])
    jail_prompt = dispatched2b and dispatched2b[0][1]
    check("isolated prompt contains the absolute worktree path",
          jail_prompt and str(Path(res2b["worktree"]).resolve()) in jail_prompt)
    check("isolated prompt contains the branch name",
          jail_prompt and f"work/{res2b['run_id']}" in jail_prompt)
    check("isolated prompt contains the do-not-leave line",
          jail_prompt and "All work happens in this directory; do not read or "
          "write outside it." in jail_prompt)
    check("the environment block is derived only from launcher state (appended last)",
          jail_prompt and jail_prompt.rstrip().endswith("write outside it."))

    print("== #608: a shared-checkout dispatch keeps today's prompt unchanged ==")
    root2c = Path(tempfile.mkdtemp(prefix="launcher-shared-"))
    gh2c = FakeGitHub()
    gh2c.labels["o/r#11"] = ["workflow:ready"]
    disp2c = d.Dispatcher(d.RunRegistry(root2c / "runs.json"), gh2c)
    prompts2c = []
    launcher2c = w.WorkLauncher(
        disp2c, gh2c, dispatch=lambda dispatcher, run, prompt, worktree=None: prompts2c.append(prompt),
        worktree_root=root2c / "trees",
        run_worktree=fake_worktree_add,
        repo_path=root2c,
    )
    launcher2c.resume("o/r#11", runtime="fake", worker_role="builder", workflow="v1",
                      max_runtime_seconds=60, prompt="shared work")
    check("shared-checkout prompt has no environment block",
          prompts2c and "Run environment" not in prompts2c[0])
    check("shared-checkout prompt has no do-not-leave line",
          prompts2c and "do not read or write outside it" not in prompts2c[0])

    print("== #608 post-run containment scan: misspelled sibling escape recorded on the Run ==")
    # Same real-repo fixture: escape into a misspelled SIBLING of the
    # registered worktree, then let the worker go terminal. The scan must
    # record `launcher_checkout_dirty` on the durable Run while the registered
    # worktree itself stays clean.
    jail_run_id = dispatched2b[0][0]
    (repo2b / "s5controlplane-typo").mkdir(exist_ok=True)
    (repo2b / "s5controlplane-typo" / "escape.txt").write_text("escaped\n")
    run_rec = disp2b.registry.get(jail_run_id)
    check("run registered its isolated worktree path",
          run_rec is not None and run_rec.worktree and Path(run_rec.worktree).is_dir())
    on_terminal = dispatched2b[0][3]
    on_terminal(jail_run_id, "succeeded")
    run_rec = disp2b.registry.get(jail_run_id)
    check("scan recorded launcher_checkout_dirty on the Run record",
          run_rec.containment == "launcher_checkout_dirty", str(run_rec.containment))
    code = _sp.run(["git", "status", "--porcelain"], cwd=str(repo2b),
                   capture_output=True, text=True).stdout
    check("the registered worktree is excluded from the checkout's own status",
          "trees/" not in code and run_rec.worktree not in code, repr(code))

    print("== #608: uncommitted work inside the registered worktree is its own code ==")
    root2d = Path(tempfile.mkdtemp(prefix="launcher-wtdirty-"))
    gh2d = FakeGitHub()
    repo2d = root2d / "repo"
    repo2d.mkdir()
    _sp.run(["git", "init", "-q"], cwd=str(repo2d), capture_output=True)
    (repo2d / "seed.txt").write_text("seed\n")
    _sp.run(["git", "add", "."], cwd=str(repo2d), capture_output=True)
    _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.io", "commit", "-qm", "init"],
            cwd=str(repo2d), capture_output=True)
    disp2d = d.Dispatcher(d.RunRegistry(root2d / "runs.json"), gh2d)
    launcher2d = w.WorkLauncher(
        disp2d, gh2d, dispatch=fake_dispatch_with_terminal,
        worktree_root=repo2d / "trees",
        run_worktree=real_worktree_add(),
        repo_path=repo2d,
    )
    res2d = launcher2d.create("o/r", "Task", "Worktree work", ["Tests pass"],
                              runtime="fake", worker_role="builder", workflow="v1",
                              max_runtime_seconds=60, max_cost_usd=1.0, approved=True,
                              artifact_paths=["docs/agents/work-launcher.md"])
    run2d = disp2d.registry.get(res2d["run_id"])
    (Path(res2d["worktree"]) / "wip.txt").write_text("work in progress\n")
    launcher2d._on_worker_terminal(res2d["run_id"], "succeeded")
    run2d = disp2d.registry.get(res2d["run_id"])
    check("in-worktree uncommitted work records worktree_dirty_uncommitted",
          run2d.containment == "worktree_dirty_uncommitted", str(run2d.containment))
    (Path(run2d.worktree) / "wip.txt").unlink()
    # `_record_containment` pops the snapshot by design: one scan per run, the
    # first terminal event's verdict. A second terminal event is a no-op, so
    # the Run's recorded code is the first scan's `worktree_dirty_uncommitted`
    # -- the check asserts exactly that stability.
    launcher2d._on_worker_terminal(res2d["run_id"], "failed")
    run2d = disp2d.registry.get(res2d["run_id"])
    check("a second terminal leaves the first scan's verdict (no rescan)",
          run2d.containment == "worktree_dirty_uncommitted", str(run2d.containment))

    print("== #608 settlement order: a violating mutating run settles blocked, snapshot consumed once ==")
    # The live OS/UI path: the async worker thread calls complete() (which
    # runs the Evidence Gate) BEFORE the on_terminal hook fires. The
    # settlement hook must put the scan verdict on the Run before the gate
    # reads it, so an escaping run settles blocked/refused here -- not
    # `succeeded` with the violation written only after the gate passed.
    root2e = Path(tempfile.mkdtemp(prefix="launcher-settle-order-"))
    gh2e = FakeGitHub()
    repo2e = root2e / "repo"
    repo2e.mkdir()
    _sp.run(["git", "init", "-q"], cwd=str(repo2e), capture_output=True)
    (repo2e / "seed.txt").write_text("seed\n")
    _sp.run(["git", "add", "."], cwd=str(repo2e), capture_output=True)
    _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.io", "commit", "-qm", "init"],
            cwd=str(repo2e), capture_output=True)
    disp2e = d.Dispatcher(d.RunRegistry(root2e / "runs.json"), gh2e)
    dispatched2e = []

    def settlement_order_dispatch(dispatcher, run, prompt, worktree=None, on_terminal=None):
        # dispatch_async's shape: the worker writes during the run, then the
        # background thread completes the Run before on_terminal ever fires.
        dispatched2e.append(run.run_id)
        (repo2e / "s5controlplane-typo").mkdir(exist_ok=True)
        (repo2e / "s5controlplane-typo" / "escape.txt").write_text("escaped\n")
        dispatcher.complete(run.run_id, "succeeded", {"evidence": "claimed success, escaped"})
        on_terminal(run.run_id, "succeeded")
        return None

    launcher2e = w.WorkLauncher(
        disp2e, gh2e, dispatch=settlement_order_dispatch,
        worktree_root=repo2e / "trees",
        run_worktree=real_worktree_add(),
        repo_path=repo2e,
    )
    res2e = launcher2e.create("o/r", "Task", "Escaping worker", ["Tests pass"],
                              runtime="fake", worker_role="builder", workflow="v1",
                              max_runtime_seconds=60, max_cost_usd=1.0, approved=True,
                              artifact_paths=["docs/agents/work-launcher.md"])
    q2e = disp2e.query(res2e["run_id"])
    check("a violating mutating run settles blocked, never succeeded",
          q2e["status"] == "blocked", str(q2e["status"]))
    check("the settlement-path refusal carries containment_violation",
          (q2e["result"] or {}).get("error", {}).get("category") == "containment_violation",
          str((q2e["result"] or {}).get("error")))
    check("the scan recorded the escape verdict before the gate ran",
          disp2e.registry.get(res2e["run_id"]).containment == "launcher_checkout_dirty",
          str(disp2e.registry.get(res2e["run_id"]).containment))
    check("the snapshot was consumed exactly once",
          launcher2e._containment_snapshots == {}, str(launcher2e._containment_snapshots))
    launcher2e._on_worker_terminal(res2e["run_id"], "failed")
    check("a second terminal is a no-op (the first verdict stands)",
          disp2e.registry.get(res2e["run_id"]).containment == "launcher_checkout_dirty",
          str(disp2e.registry.get(res2e["run_id"]).containment))

    print("== #608 fail-closed: a mutating run with no snapshot records containment_snapshot_missing ==")
    # Snapshots are memory-only: a launcher restart between dispatch and
    # settlement loses them. A launcher-owned mutating run that then reaches
    # the gate with neither snapshot nor verdict must be refused, never pass
    # unscanned -- the pre-gate hook records `containment_snapshot_missing`
    # and the gate turns it into the same containment_violation refusal.
    root2f = Path(tempfile.mkdtemp(prefix="launcher-snapshot-missing-"))
    gh2f = FakeGitHub()
    repo2f = root2f / "repo"
    repo2f.mkdir()
    _sp.run(["git", "init", "-q"], cwd=str(repo2f), capture_output=True)
    (repo2f / "seed.txt").write_text("seed\n")
    _sp.run(["git", "add", "."], cwd=str(repo2f), capture_output=True)
    _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.io", "commit", "-qm", "init"],
            cwd=str(repo2f), capture_output=True)
    disp2f = d.Dispatcher(d.RunRegistry(root2f / "runs.json"), gh2f)

    def restart_loss_dispatch(dispatcher, run, prompt, worktree=None, on_terminal=None):
        # dispatch_async's settlement shape, after the launcher process was
        # restarted mid-run: the in-memory snapshot is gone when complete()
        # runs its pre-gate containment settlement.
        launcher2f._containment_snapshots.clear()
        dispatcher.complete(run.run_id, "succeeded", {"evidence": "claimed"})
        on_terminal(run.run_id, "succeeded")
        return None

    launcher2f = w.WorkLauncher(
        disp2f, gh2f, dispatch=restart_loss_dispatch,
        worktree_root=repo2f / "trees",
        run_worktree=real_worktree_add(),
        repo_path=repo2f,
    )
    res2f = launcher2f.create("o/r", "Task", "Restarted launcher", ["Tests pass"],
                              runtime="fake", worker_role="builder", workflow="v1",
                              max_runtime_seconds=60, max_cost_usd=1.0, approved=True,
                              artifact_paths=["docs/agents/work-launcher.md"])
    check("a mutating run with no snapshot records containment_snapshot_missing",
          disp2f.registry.get(res2f["run_id"]).containment == "containment_snapshot_missing",
          str(disp2f.registry.get(res2f["run_id"]).containment))
    q2f = disp2f.query(res2f["run_id"])
    check("a snapshot-missing success settles blocked, never succeeded",
          q2f["status"] == "blocked", str(q2f["status"]))
    check("the snapshot-missing refusal carries containment_violation",
          (q2f["result"] or {}).get("error", {}).get("category") == "containment_violation",
          str((q2f["result"] or {}).get("error")))
    launcher2f._on_worker_terminal(res2f["run_id"], "failed")
    check("a second terminal after the fail-closed verdict is a no-op",
          disp2f.registry.get(res2f["run_id"]).containment == "containment_snapshot_missing",
          str(disp2f.registry.get(res2f["run_id"]).containment))

    print("== #608 scope: read-only runs and legacy hook-less settlements are unchanged ==")
    root2g = Path(tempfile.mkdtemp(prefix="launcher-readonly-"))
    gh2g = FakeGitHub()
    gh2g.labels["o/r#21"] = ["workflow:ready"]
    disp2g = d.Dispatcher(d.RunRegistry(root2g / "runs.json"), gh2g)
    seen2g = []

    def read_only_dispatch(dispatcher, run, prompt, worktree=None):
        # Shared-checkout shape: no worktree kwarg, no on_terminal contract.
        seen2g.append(run.run_id)
        return None

    launcher2g = w.WorkLauncher(
        disp2g, gh2g, dispatch=read_only_dispatch,
        worktree_root=root2g / "trees",
        run_worktree=fake_worktree_add,
        repo_path=root2g,
    )
    launcher2g.resume("o/r#21", runtime="fake", worker_role="builder", workflow="v1",
                      max_runtime_seconds=60, prompt="read-only shared work")
    launcher2g._on_worker_terminal(seen2g[0], "succeeded")
    check("a read-only run records no containment verdict at all",
          disp2g.registry.get(seen2g[0]).containment is None,
          str(disp2g.registry.get(seen2g[0]).containment))
    # Legacy settlement: a dispatcher with no launcher wiring (no
    # containment_recorder) behaves exactly as before -- the gate's
    # pre-existing correlation refusal, never a containment refusal.
    gh2h = FakeGitHub()
    gh2h.labels["o/r#22"] = ["workflow:ready"]
    disp2h = d.Dispatcher(d.RunRegistry(root2g / "runs-legacy.json"), gh2h)
    run2h = disp2h.claim("o/r#22", "wedge-b", "builder", "hermes", 600)
    disp2h.registry.update(run2h.run_id, mutating=True)
    disp2h.complete(run2h.run_id, "succeeded", {"evidence": "claimed"})
    q2h = disp2h.query(run2h.run_id)
    check("a legacy mutating settlement keeps the pre-existing gate verdict",
          q2h["status"] == "blocked"
          and (q2h["result"] or {}).get("error", {}).get("category") == "run_correlation_mismatch",
          str((q2h["result"] or {}).get("error")))

    print("== S7b #482 follow-on: unconfigured runtime is rejected BEFORE any claim ==")
    root3 = Path(tempfile.mkdtemp(prefix="launcher-cfg-"))
    gh3 = FakeGitHub()
    gh3.labels["o/r#9"] = ["workflow:ready"]
    disp3 = d.Dispatcher(d.RunRegistry(root3 / "runs.json"), gh3)
    dispatched3 = []
    launcher3 = w.WorkLauncher(
        disp3, gh3, dispatch=lambda dispatcher, run, prompt, worktree=None: dispatched3.append(run.run_id),
        worktree_root=root3 / "trees",
        run_worktree=fake_worktree_add,
    )
    try:
        launcher3.resume("o/r#9", runtime="no-such-runtime", worker_role="builder", workflow="v1",
                         max_runtime_seconds=60, prompt="do it")
        check("unregistered/unconfigured runtime raises ExecutionGateError", False)
    except w.ExecutionGateError as exc:
        check("unregistered/unconfigured runtime raises ExecutionGateError", exc.code == "runtime_not_configured")
    check("no Dispatcher claim was ever created for the rejected runtime",
          disp3.registry.active_issue_ids() == set() and not disp3.registry._runs)
    check("issue label untouched (still workflow:ready, never in-progress)",
          gh3.labels["o/r#9"] == ["workflow:ready"])
    check("no worker was ever dispatched", dispatched3 == [])

    # main()'s registry restore is only worth anything if it survives a check
    # that raises. Drive a controlled exception through the very same context
    # manager and assert both halves: the registry comes back, and the original
    # error is neither hidden nor replaced by the cleanup.
    boom = RuntimeError("controlled failure after registration")

    absent = "w1-registry-restore-probe"
    check("the probe runtime is absent before the block", absent not in wa.ADAPTER_REGISTRY)
    raised = None
    try:
        with _adapter_registered(absent, SimpleNamespace(invoke=lambda *a, **k: {})):
            check("the probe runtime is registered inside the block",
                  absent in wa.ADAPTER_REGISTRY)
            raise boom
    except RuntimeError as exc:
        raised = exc
    check("the original exception propagates unchanged, not swallowed", raised is boom)
    check("a previously absent runtime is removed again after an exception",
          absent not in wa.ADAPTER_REGISTRY)

    prior_fake = wa.ADAPTER_REGISTRY["fake"]
    replacement = SimpleNamespace(invoke=lambda *a, **k: {})
    raised = None
    try:
        with _adapter_registered("fake", replacement):
            check("the replacement adapter is in place inside the block",
                  wa.ADAPTER_REGISTRY["fake"] is replacement)
            raise boom
    except RuntimeError as exc:
        raised = exc
    check("the original exception propagates from the occupied-key path too", raised is boom)
    check("a previously present runtime is restored to its exact prior object",
          wa.ADAPTER_REGISTRY["fake"] is prior_fake)

    print("== #489: resume(isolate=True) pins isolation, branch and artifact policy ==")
    # The #489 fix already exists (resume(isolate=..., mutating=...) derives
    # mutating from isolation and refuses mutating-without-isolation). These
    # arms PIN the durable behavior: the Run record must carry the isolation
    # that actually happened, the branch derived from its own run_id, the
    # launcher-resolved base commit, and the approved artifact policy verbatim.
    root2i = Path(tempfile.mkdtemp(prefix="launcher-resume-pin-"))
    gh2i = FakeGitHub()
    gh2i.labels["o/r#31"] = ["workflow:ready"]
    disp2i = d.Dispatcher(d.RunRegistry(root2i / "runs.json"), gh2i)
    dispatched2i = []
    launcher2i = w.WorkLauncher(
        disp2i, gh2i,
        dispatch=lambda dispatcher, run, prompt, worktree=None: dispatched2i.append(run.run_id),
        worktree_root=root2i / "trees",
        run_worktree=real_worktree_add(),
        repo_path=root2i,
    )
    policy31 = ("Commit only English project artifacts on a feature branch. "
                "Do not push, merge, close issues, expose secrets, copy full "
                "prompts, or record model reasoning.")
    result2i = launcher2i.resume("o/r#31", runtime="fake", worker_role="builder", workflow="v1",
                                 max_runtime_seconds=60, prompt="isolated work",
                                 isolate=True, mutating=True, artifact_policy=policy31,
                                 artifact_paths=["scripts/work_launcher.py"])
    rec2i = disp2i.registry.get(result2i["run_id"])
    check("isolated resume reports isolation=worktree", result2i["isolation"] == "worktree")
    check("Run.isolation is durable as worktree", rec2i.isolation == "worktree",
          str(rec2i.isolation))
    check("Run.branch is work/<run_id>", rec2i.branch == f"work/{result2i['run_id']}",
          str(rec2i.branch))
    check("Run.base_commit was resolved by the launcher", rec2i.base_commit == "0" * 40,
          str(rec2i.base_commit))
    check("Run.worktree was recorded and exists",
          rec2i.worktree and Path(rec2i.worktree).is_dir(), str(rec2i.worktree))
    check("Run.mutating was recorded by the launcher", rec2i.mutating is True,
          str(rec2i.mutating))
    check("Run.artifact_policy carries the approved policy verbatim",
          rec2i.artifact_policy == policy31, repr(rec2i.artifact_policy))
    check("Run.artifact_paths carries the approved scope",
          rec2i.artifact_paths == ["scripts/work_launcher.py"], str(rec2i.artifact_paths))
    check("the worker was dispatched for the isolated run", len(dispatched2i) == 1)

    print("== #489: mutating derives from isolation on the resume path ==")
    gh2j = FakeGitHub()
    gh2j.labels["o/r#32"] = ["workflow:ready"]
    disp2j = d.Dispatcher(d.RunRegistry(root2i / "runs-32.json"), gh2j)
    launcher2j = w.WorkLauncher(
        disp2j, gh2j, dispatch=lambda dispatcher, run, prompt, worktree=None: None,
        worktree_root=root2i / "trees",
        run_worktree=real_worktree_add(),
        repo_path=root2i,
    )
    launcher2j.resume("o/r#32", runtime="fake", worker_role="builder", workflow="v1",
                      max_runtime_seconds=60, prompt="default derivation", isolate=True)
    rec2j = next(iter(disp2j.registry._runs.values()))
    check("resume(isolate=True) without mutating derives mutating=True",
          rec2j.mutating is True, str(rec2j.mutating))
    check("the derived-mutating run got its own worktree",
          rec2j.isolation == "worktree", str(rec2j.isolation))

    print("== #489: a non-mutating shared resume keeps today's shape ==")
    gh2k = FakeGitHub()
    gh2k.labels["o/r#33"] = ["workflow:ready"]
    disp2k = d.Dispatcher(d.RunRegistry(root2i / "runs-33.json"), gh2k)
    launcher2k = w.WorkLauncher(
        disp2k, gh2k, dispatch=lambda dispatcher, run, prompt, worktree=None: None,
        worktree_root=root2i / "trees",
        run_worktree=real_worktree_add(),
        repo_path=root2i,
    )
    launcher2k.resume("o/r#33", runtime="fake", worker_role="builder", workflow="v1",
                      max_runtime_seconds=60, prompt="read-only shared work", mutating=False)
    rec2k = next(iter(disp2k.registry._runs.values()))
    check("shared resume keeps isolation=shared-checkout and no branch",
          rec2k.isolation == "shared-checkout" and rec2k.branch is None,
          f"{rec2k.isolation!r}/{rec2k.branch!r}")
    check("the shared resume did not record mutating", rec2k.mutating is False,
          str(rec2k.mutating))

    print("== #489: resume(mutating=True, isolate=False) refused at both entry paths ==")
    gh2l = FakeGitHub()
    gh2l.labels["o/r#34"] = ["workflow:ready"]
    disp2l = d.Dispatcher(d.RunRegistry(root2i / "runs-34.json"), gh2l)
    dispatched2l = []
    launcher2l = w.WorkLauncher(
        disp2l, gh2l,
        dispatch=lambda dispatcher, run, prompt, worktree=None: dispatched2l.append(run.run_id),
        worktree_root=root2i / "trees",
        run_worktree=real_worktree_add(),
        repo_path=root2i,
    )
    try:
        launcher2l.resume("o/r#34", runtime="fake", worker_role="builder", workflow="v1",
                          max_runtime_seconds=60, prompt="unsafe combination",
                          mutating=True, isolate=False)
        check("resume(mutating=True, isolate=False) raises ExecutionGateError", False)
    except w.ExecutionGateError as exc:
        check("resume(mutating=True, isolate=False) raises ExecutionGateError",
              exc.code == "mutating_run_requires_isolation", exc.code)
    check("no Dispatcher claim was created for the refused combination",
          not disp2l.registry._runs and disp2l.registry.active_issue_ids() == set())
    check("no worker was dispatched for the refused combination", dispatched2l == [])
    check("issue label untouched (still workflow:ready)",
          gh2l.labels["o/r#34"] == ["workflow:ready"])
    # The second copy of the guard lives in _launch, so a direct launcher-level
    # caller cannot route around the resume()-side refusal. The binding is
    # present here so this arm keeps pinning the ISOLATION guard once the
    # approval guard (#617 criterion 15) lands ahead of it.
    try:
        launcher2l._launch("o/r#34", "unsafe", runtime="fake", worker_role="builder",
                           workflow="v1", max_runtime_seconds=60, create_worktree=False,
                           mutating=True, request_id="sha256:" + "a" * 64)
        check("the launcher-level guard independently refuses mutating without isolation",
              False)
    except w.ExecutionGateError as exc:
        check("the launcher-level guard independently refuses mutating without isolation",
              exc.code == "mutating_run_requires_isolation", exc.code)
    check("the launcher-level refusal also never created a claim",
          not disp2l.registry._runs and dispatched2l == [])


def test_all_checks_pass():
    """Pytest entry point: run the same checks as the standalone script.

    Without this, `pytest scripts/` collects zero tests from this file and
    reports green while running none of the checks below -- the exact "green
    signal over a path nobody walked" shape this suite exists to catch.
    """
    try:
        main()
    except SystemExit as exc:  # main() ends with raise SystemExit(0|1)
        assert exc.code == 0, f"{len(fail)} check(s) failed: {fail}"
    assert not fail, f"{len(fail)} check(s) failed: {fail}"


if __name__ == "__main__":
    main()
