#!/usr/bin/env python3
"""Offline fake-injection tests for the parallel work launcher."""
import tempfile
from pathlib import Path
from types import SimpleNamespace

import dispatcher as d
import work_launcher as w

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
        # args: ["git", "worktree", "add", "-b", branch, <path>, "HEAD"]
        path = Path(args[5]) if len(args) > 5 else None
        if path:
            path.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=0)
    return _run


def main():
    root = Path(tempfile.mkdtemp(prefix="launcher-test-"))
    gh = FakeGitHub()
    disp = d.Dispatcher(d.RunRegistry(root / "runs.json"), gh)
    prompts = []
    launcher = w.WorkLauncher(
        disp, gh, dispatch=lambda dispatcher, run, prompt: prompts.append(prompt),
        worktree_root=root / "trees",
        run_worktree=lambda *a, **k: SimpleNamespace(returncode=0),
    )
    result = launcher.create("o/r", "Task", "Build a safe launcher", ["Tests pass"],
                             runtime="fake", worker_role="builder", workflow="v1",
                             max_runtime_seconds=60, max_cost_usd=1.0, approved=True)
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
                            max_runtime_seconds=60, max_cost_usd=1.0, approved=True)
    check("worktree created from repo_path, not the process cwd",
          seen_cwd and seen_cwd[0] == str(repo2))
    bound = dispatched and dispatched[0]
    check("worker dispatched with the created worktree", bound and bound[1] == Path(res2["worktree"]))
    check("worktree path reported by create() exists", Path(res2["worktree"]).is_dir())

    print(f"\n{'PASS' if not fail else 'FAIL'}: {len(fail)} failure(s)")
    raise SystemExit(1 if fail else 0)


if __name__ == "__main__":
    main()
