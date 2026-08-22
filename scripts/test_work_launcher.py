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

print(f"\n{'PASS' if not fail else 'FAIL'}: {len(fail)} failure(s)")
raise SystemExit(1 if fail else 0)
