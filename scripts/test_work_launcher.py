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


def check(name, condition):
    print(f"  {'ok' if condition else 'FAIL':4} {name}")
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
