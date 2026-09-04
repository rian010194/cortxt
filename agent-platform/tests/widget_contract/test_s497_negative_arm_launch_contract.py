"""#497's negative arm, driven through the REAL launch contract.

A gate that has never refused anything is not yet evidence. The #497 dogfood's
first Run committed, so it proved acceptance, not refusal.

What makes this the launch contract rather than a fixture: the Run, its branch,
its worktree, its `base_commit` and its `mutating` flag are all produced by the
real `WorkLauncher` -- `_create_worktree` and `_record_isolation` actually run.
The existing #506 tests build a `Run` directly and must hand it a `base_commit`
the launcher would have recorded; those are component-level by construction and
cannot show that the producer writes what the consumer requires.

Only the provider boundary is replaced: an adapter that reports `succeeded`
without committing. That is the one thing a deterministic test must stand in
for, and it is exactly the worker behaviour the arm exists to refuse.
"""

import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = str(Path(__file__).resolve().parents[3] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from dispatcher import Dispatcher, RunRegistry  # noqa: E402
from commit_evidence import make_commit_gate  # noqa: E402
from work_launcher import WorkLauncher  # noqa: E402
from execution_map import SqliteClaimStore  # noqa: E402
import worker_adapters  # noqa: E402

POLICY = "Only `docs/agents/work-launcher.md` inside the run's isolated worktree."
ISSUE = "owner/repo#497"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", check=True)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(tmp_path, "init", "-q", "-b", "main", str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "docs" / "agents").mkdir(parents=True)
    (root / "docs" / "agents" / "work-launcher.md").write_text("before\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


class _FakeGitHub:
    """Duck-typed GitHub port for both the Dispatcher and the launcher.

    Records label moves instead of calling `gh`; the arm is about the gate's
    verdict, not about GitHub.
    """

    def __init__(self):
        self.labels = {"owner/repo#497": ["workflow:ready"]}
        self.comments = []

    # Dispatcher side
    def get_labels(self, repo, num):
        return self.labels.get(f"{repo}#{num}", [])

    def swap_label(self, repo, num, remove, add):
        key = f"{repo}#{num}"
        cur = self.labels.setdefault(key, [])
        if remove in cur:
            cur.remove(remove)
        cur.append(add)

    def comment(self, repo, num, body):
        self.comments.append((f"{repo}#{num}", body))

    # Launcher side
    def get_issue(self, issue_id):
        return {"issue_id": issue_id, "number": 497, "title": "dogfood",
                "workflow": "ready", "labels": self.labels.get(issue_id, []),
                "body": ""}


class _NoCommitWorker:
    """A worker that reports success and lands nothing. The arm's whole point."""

    started = False

    def start(self, run, prompt, workdir=None, **kwargs):
        _NoCommitWorker.started = True
        return {"status": "succeeded",
                "evidence": "worker reports success",
                "artifacts": []}


@pytest.fixture()
def launcher(repo, tmp_path, monkeypatch):
    registry = RunRegistry(tmp_path / "runs.json")
    github = _FakeGitHub()
    dispatcher = Dispatcher(registry, gh=github,
                            commit_gate=make_commit_gate(repo))

    captured = {}

    def dispatch(dispatcher_, run, prompt, worktree=None, **kwargs):
        """Stand in for the provider only: run the worker, then complete."""
        captured["worktree"] = worktree
        envelope = _NoCommitWorker().start(run, prompt, workdir=worktree)
        envelope = worker_adapters.enrich_run_correlation(
            run, envelope, repo_dir=repo, git=lambda args: (
                subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                               text=True, encoding="utf-8").returncode,
                subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                               text=True, encoding="utf-8").stdout))
        dispatcher_.complete(run.run_id, envelope.get("status", "succeeded"), envelope)

    # A real claim store, because `_launch` takes a SHORTER branch without one
    # that never writes the approved limits (`request_id`, `artifact_policy`)
    # onto the Run. Production always has one; a test without it would exercise
    # a path the gate can only ever refuse for a reason unrelated to this arm.
    app = WorkLauncher(dispatcher, github, dispatch=dispatch,
                       worktree_root=repo / ".worktrees",
                       claim_store=SqliteClaimStore(tmp_path / "claims.sqlite3"),
                       issue_reader=github.get_issue,
                       clock=time.time, repo_path=repo)
    return app, dispatcher, registry, captured


# --------------------------------------------------------------------------- #
# the arm
# --------------------------------------------------------------------------- #
def test_a_run_that_reports_success_without_committing_is_refused(launcher, repo):
    app, dispatcher, registry, captured = launcher

    result = app.resume(ISSUE, runtime="hermes-free", worker_role="builder",
                        workflow="work-launcher/v1", max_runtime_seconds=900,
                        prompt="[negative arm] report success, commit nothing",
                        max_cost_usd=2.0, max_parallel_workers=1,
                        delegation_depth=0, artifact_policy=POLICY,
                        request_id="sha256:e0ef9e7e", isolate=True)

    run_id = result["run_id"]
    run = registry.get(run_id)

    # The launch itself was real: the launcher created the isolation, not a fixture.
    assert result["isolation"] == "worktree"
    assert run.isolation == "worktree"
    assert run.branch == f"work/{run_id}"
    assert run.mutating is True
    assert run.base_commit, "the launcher must have recorded the base it branched from"
    assert run.worktree, "#514: the launcher must record the worktree it created"
    assert captured["worktree"] is not None and _NoCommitWorker.started

    # The gate refused the claimed success.
    assert run.status == "blocked", "a Run that landed nothing must not be succeeded"
    envelope = run.result or {}
    assert envelope["evidence_gate"] == "commit_correlation_failed"
    assert envelope["error"]["category"] == "commit_predates_run"
    assert run.commit_evidence is None, "a refused Run must carry no correlated evidence"


def test_the_refusal_is_the_code_the_production_path_produces(launcher, repo):
    """`commit_predates_run`, not `commit_missing`.

    #497 records why: the branch of a Run that committed nothing still resolves
    -- to its own `base_commit` -- so a valid SHA reaches the gate and is
    refused on the strictly-after-claim check rather than on absence.
    `commit_missing` needs branch resolution to return `None`, which means
    deleting the Run branch before `complete()`. This asserts the reachable one.
    """
    app, dispatcher, registry, _ = launcher
    result = app.resume(ISSUE, runtime="hermes-free", worker_role="builder",
                        workflow="work-launcher/v1", max_runtime_seconds=900,
                        prompt="[negative arm]", max_cost_usd=2.0,
                        max_parallel_workers=1, delegation_depth=0,
                        artifact_policy=POLICY, request_id="sha256:e0ef9e7e",
                        isolate=True)
    run = registry.get(result["run_id"])
    envelope = run.result or {}

    assert envelope["error"]["category"] == "commit_predates_run"
    # The derived commit is the branch tip, which for this Run is its own base.
    assert envelope.get("commit") == run.base_commit


def test_the_refused_run_serves_no_readable_change(launcher):
    """The refusal must reach the operator's review surface, not just the log."""
    from widget_contract.adapters.store_reads import read_run_diff_v1

    app, dispatcher, registry, _ = launcher
    result = app.resume(ISSUE, runtime="hermes-free", worker_role="builder",
                        workflow="work-launcher/v1", max_runtime_seconds=900,
                        prompt="[negative arm]", max_cost_usd=2.0,
                        max_parallel_workers=1, delegation_depth=0,
                        artifact_policy=POLICY, request_id="sha256:e0ef9e7e",
                        isolate=True)
    run_id = result["run_id"]
    run = registry.get(run_id)
    store = {run_id: {"run_id": run_id, "issue_id": ISSUE, "status": run.status,
                      "commit_evidence": run.commit_evidence,
                      "result": run.result}}

    diff = read_run_diff_v1(ISSUE, store, run_id=run_id)

    assert diff["available"] is False
    assert diff["reason"] == "no_commit_evidence"
    assert diff["files"] == []
