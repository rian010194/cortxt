"""#514: the worktree in `commit_evidence` is the launcher's, never the worker's.

The Evidence Gate used to read this field from the worker's own result
envelope. That both left it `null` for any adapter that did not report it --
which is what the #497 dogfood produced, making `run.diff.v1` refuse with
`no_registered_worktree` -- and let a worker-supplied string decide which
directory the operator's later review runs `git` in.

These tests exercise the real launcher against a real git repository, and the
real gate against a real Run record.
"""

import subprocess

import pytest


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
    (root / "docs").mkdir()
    (root / "docs" / "a.md").write_text("before\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


# --------------------------------------------------------------------------- #
# the launcher records it, and a mutating Run cannot proceed without it
# --------------------------------------------------------------------------- #
def _launcher_module():
    from pathlib import Path
    import sys

    scripts = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import work_launcher

    return work_launcher


class _Registry:
    def __init__(self):
        self.fields = {}

    def update(self, run_id, **fields):
        self.fields.setdefault(run_id, {}).update(fields)


class _Dispatcher:
    def __init__(self, registry):
        self.registry = registry


def _app(registry):
    work_launcher = _launcher_module()
    app = work_launcher.WorkLauncher.__new__(work_launcher.WorkLauncher)
    app.dispatcher = _Dispatcher(registry)
    return app, work_launcher


def test_the_launcher_records_the_worktree_it_created(tmp_path):
    registry = _Registry()
    app, _ = _app(registry)
    worktree = tmp_path / ".worktrees" / "run-1"
    app._record_isolation("run-1", True, required=True, base_commit="a" * 40,
                          worktree=worktree)
    recorded = registry.fields["run-1"]
    assert recorded["worktree"] == str(worktree)
    assert recorded["isolation"] == "worktree"
    assert recorded["branch"] == "work/run-1"


def test_a_mutating_run_whose_worktree_cannot_be_recorded_fails_closed(tmp_path):
    """Evidence nobody can open is not evidence. Same rule as `base_commit`."""
    app, work_launcher = _app(_Registry())
    with pytest.raises(work_launcher.ExecutionGateError) as exc:
        app._record_isolation("run-1", True, required=True, base_commit="a" * 40,
                              worktree=None)
    assert "worktree_not_recordable" in str(exc.value)


def test_a_shared_checkout_run_records_no_worktree(tmp_path):
    """A run that got no isolated directory must not claim one."""
    registry = _Registry()
    app, _ = _app(registry)
    app._record_isolation("run-1", False, required=False, worktree=tmp_path)
    assert registry.fields["run-1"]["worktree"] is None
    assert registry.fields["run-1"]["isolation"] == "shared-checkout"


# --------------------------------------------------------------------------- #
# the gate reads the Run, not the envelope
# --------------------------------------------------------------------------- #
class _Run:
    def __init__(self, worktree, **kw):
        self.run_id = kw.get("run_id", "run-1")
        self.issue_id = kw.get("issue_id", "owner/repo#514")
        self.worktree = worktree
        self.branch = "work/run-1"
        self.isolation = "worktree"
        self.base_commit = kw["base_commit"]
        self.claimed_at = kw["claimed_at"]
        self.request_id = "sha256:abc"
        self.artifact_policy = "Only `docs/a.md` inside the run's isolated worktree."
        self.artifact_paths = None
        self.mutating = True


def _contribute(repo, message="change\n\nSigned-off-by: T <t@example.com>\n"):
    _git(repo, "checkout", "-q", "-b", "work/run-1")
    (repo / "docs" / "a.md").write_text("before\nafter\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _envelope(run, sha, **extra):
    """A result envelope shaped the way a real adapter's is after enrichment."""
    body = {"run_id": run.run_id, "issue_id": run.issue_id,
            "request_id": run.request_id, "commit": sha, "branch": run.branch}
    body.update(extra)
    return body


def _verify(repo, run, envelope):
    from pathlib import Path
    import sys

    scripts = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from commit_evidence import verify_commit_correlation

    return verify_commit_correlation(run, envelope, repo_path=repo)


def test_the_gate_records_the_run_s_worktree_when_the_worker_reports_none(repo):
    """The #497 dogfood's exact shape: an adapter that never reports a worktree."""
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    sha = _contribute(repo)
    committed = int(_git(repo, "show", "-s", "--format=%ct", sha).stdout.strip())
    run = _Run(str(repo), base_commit=base, claimed_at=committed - 5)

    outcome = _verify(repo, run, _envelope(run, sha))  # no "worktree" key at all

    record = outcome.as_record()
    assert record["worktree"] == str(repo)


def test_a_worker_cannot_redirect_the_worktree_the_review_will_read(repo, tmp_path):
    """A worker naming another directory must not change the recorded one."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    sha = _contribute(repo)
    committed = int(_git(repo, "show", "-s", "--format=%ct", sha).stdout.strip())
    run = _Run(str(repo), base_commit=base, claimed_at=committed - 5)

    outcome = _verify(repo, run, _envelope(run, sha, worktree=str(elsewhere)))

    record = outcome.as_record()
    assert record["worktree"] == str(repo)
    assert str(elsewhere) not in str(record)


# --------------------------------------------------------------------------- #
# end to end: the operator can now read the change
# --------------------------------------------------------------------------- #
def test_run_diff_can_read_a_gate_passed_run_end_to_end(repo):
    """The regression #514 exists to close: `no_registered_worktree`."""
    from widget_contract.adapters.store_reads import read_run_diff_v1

    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    sha = _contribute(repo)
    committed = int(_git(repo, "show", "-s", "--format=%ct", sha).stdout.strip())
    run = _Run(str(repo), base_commit=base, claimed_at=committed - 5)
    outcome = _verify(repo, run, _envelope(run, sha))

    store = {"run-1": {"run_id": "run-1", "issue_id": "owner/repo#514",
                       "status": "succeeded",
                       "commit_evidence": outcome.as_record(),
                       "result": {"evidence_gate": "commit_correlated"}}}

    result = read_run_diff_v1("owner/repo#514", store, run_id="run-1")

    assert result["available"] is True, result.get("reason")
    permitted = [f for f in result["files"] if not f["withheld"]]
    assert [f["path"] for f in permitted] == ["docs/a.md"]
    assert "+after" in permitted[0]["patch"]
