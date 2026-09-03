"""#506 -- the launcher/adapter supply the authoritative correlation to the gate.

Before #506 two producer paths fed `Dispatcher.complete()`:
`worker_adapters.dispatch_async` (hermes-free background adapter) and
`work_launcher.submit()` (coordinator-direct). Neither supplied the correlation
fields the Evidence Gate (#490) needs, so a worker that returned a bare
`{"status": "succeeded"}` envelope -- reporting nothing about which Run it
belonged to or what it landed -- was recorded as `run_correlation_mismatch`
rather than failing on the real defect (a missing commit). That worker prose
was trusted for correlation at all.

#506 closes this on the producer side, without touching the gate itself
(`scripts/commit_evidence.py` and `scripts/dispatcher.py` are out of artifact
scope):

- `worker_adapters.enrich_run_correlation(run, envelope, ...)` injects the
  authoritative `run_id` / `issue_id` / `request_id` from the durable Run
  record, so an envelope that echoes wrong values (or none) can never move the
  correlation check. Worker prose is not trusted for identity.
- `work_launcher.submit()` additionally derives the `commit` from the Run's own
  isolated branch (via `repo_dir` + `git`) when the worker reported none. The
  gate still verifies that commit (reachability, branch, strictly-after-claim
  timestamp, DCO, artifact policy) -- this enriches, it never weakens.
- `generate_worker_prompt` now states the result contract (DCO commit in the
  run's own worktree; report run/issue/request + commit SHA).

The negative arm stays fail-closed: a worker that lands nothing is still
`blocked`, now reported as `commit_missing` (correlation is established, but a
missing commit is not evidence of a landed commit).

These tests drive the REAL launcher, adapter, dispatcher and `make_commit_gate`
chain end to end against a throwaway git repo -- not fixtures. The assertions on
the gate's own failure codes (`commit_not_on_run_branch`, `dco_trailer_missing`,
`artifact_policy_violation`, `commit_predates_run`) are stability locks: #506
must not shift or weaken any of them.
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest

# `scripts/` is not on the interpreter path in CI; the other widget_contract
# chain tests bootstrap it the same way (see test_s7b_dispatch_registry_chain).
SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from commit_evidence import make_commit_gate  # noqa: E402
from dispatcher import Dispatcher, Run, RunRegistry  # noqa: E402
from work_launcher import WorkLauncher  # noqa: E402
from worker_adapters import enrich_run_correlation  # noqa: E402

POLICY = "Only `docs/agents/work-launcher.md` inside the run's isolated worktree."
SIGNOFF = "Signed-off-by: Operator <operator@example.com>"


def _git(repo: "Path", *args: str):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "operator@example.com")
    _git(root, "config", "user.name", "Operator")
    _git(root, "config", "commit.gpgsign", "false")
    for rel in ("docs/agents/work-launcher.md", "docs/agents-secret/x.md",
                "README.md", "LICENSE"):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "chore: base\n\n" + SIGNOFF)
    return root


def _commit(repo, branch, path, *, signoff=True):
    if _git(repo, "rev-parse", "--verify", "refs/heads/" + branch).returncode != 0:
        _git(repo, "checkout", "-b", branch)
    else:
        _git(repo, "checkout", branch)
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed at " + str(time.time()) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    message = "docs: land the artifact"
    _git(repo, "commit", "-m", (message + "\n\n" + SIGNOFF) if signoff else message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


class FakeGitHub:
    """Duck-typed GitHubOps so the real Dispatcher needs no network."""

    def __init__(self):
        self.labels = {}
        self.comments = []

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


def _launcher(repo, run_id, *, claimed_at=1000.0, tmp_path=None):
    registry = RunRegistry(tmp_path / ("reg-" + run_id + ".json"))
    dispatcher = Dispatcher(registry, gh=FakeGitHub(), commit_gate=make_commit_gate(repo))
    run = Run(
        run_id=run_id, issue_id="owner/repo#485", workflow="work-launcher/v1",
        worker_role="builder", runtime="hermes-free", claimed_at=claimed_at,
        lease_seconds=600, status="in_progress", mutating=True,
        isolation="worktree", branch="work/run-1", artifact_policy=POLICY,
        request_id="sha256:abc",
    )
    registry.add(run)
    app = WorkLauncher.__new__(WorkLauncher)
    app.dispatcher = dispatcher
    app.claim_store = None
    app._claims_by_run = {}
    app.clock = time.time
    app.repo_path = repo
    return app, dispatcher


# ==========================================================================
# The result-reported identity is the Run's, never the worker's prose.
# ==========================================================================

def test_enrich_run_correlation_uses_the_run_record_not_worker_prose():
    run = Run(
        run_id="run-1", issue_id="owner/repo#485", workflow="work-launcher/v1",
        worker_role="builder", runtime="hermes-free", claimed_at=1000.0,
        lease_seconds=600, status="in_progress", mutating=True,
        isolation="worktree", branch="work/run-1", artifact_policy=POLICY,
        request_id="sha256:abc",
    )
    # A worker that echoes a foreign run/issue must not be able to move the
    # correlation check.
    env = enrich_run_correlation(run, {"status": "succeeded",
                                       "run_id": "run-EVIL",
                                       "issue_id": "owner/repo#EVIL"})
    assert env["run_id"] == "run-1"
    assert env["issue_id"] == "owner/repo#485"
    assert env["request_id"] == "sha256:abc"
    # A Run without a request_id must not gain one out of nothing.
    run2 = Run(
        run_id="run-2", issue_id="owner/repo#485", workflow="w",
        worker_role="builder", runtime="hermes-free", claimed_at=1000.0,
        lease_seconds=600, status="in_progress", mutating=False,
        isolation="worktree", branch="work/run-2", artifact_policy=None,
        request_id=None,
    )
    env2 = enrich_run_correlation(run2, {"status": "succeeded"})
    assert env2["run_id"] == "run-2"
    assert "request_id" not in env2


# ==========================================================================
# Positive arm -- the full launcher -> dispatcher -> gate chain, not fixtures.
# ==========================================================================

def test_commit_evidence_positive_arm_via_real_launcher(repo, tmp_path):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md", signoff=True)
    app, dispatcher = _launcher(repo, "run-pos", tmp_path=tmp_path)
    app.submit("run-pos", {"status": "succeeded"})
    run = dispatcher.registry.get("run-pos")
    assert run.status == "succeeded"
    assert run.result["evidence_gate"] == "commit_correlated"
    # The commit was derived from the run's own branch by the launcher (#506).
    assert run.result["commit"] == sha
    assert run.result["run_id"] == "run-pos"
    assert run.commit_evidence is not None
    # complete() persists commit_evidence as a record dict (CommitEvidence.as_record()).
    assert run.commit_evidence["commit"] == sha


# ==========================================================================
# Negative arm -- correlation is established, but a missing commit is still
# a block. This is the #506 shift: `run_correlation_mismatch` -> `commit_missing`.
# ==========================================================================

def test_no_commit_fails_as_commit_missing_not_correlation_mismatch(repo, tmp_path):
    app, dispatcher = _launcher(repo, "run-neg", tmp_path=tmp_path)
    app.submit("run-neg", {"status": "succeeded"})
    run = dispatcher.registry.get("run-neg")
    assert run.status == "blocked"
    assert run.result["evidence_gate"] == "commit_correlation_failed"
    assert run.result["error"]["category"] == "commit_missing"
    # Correlation is still supplied from the Run record, not worker prose.
    assert run.result["run_id"] == "run-neg"
    assert run.commit_evidence is None


# ==========================================================================
# The gate's own fail-closed checks are unchanged -- #506 must not weaken any.
# ==========================================================================

def test_a_commit_on_the_wrong_branch_is_still_refused(repo, tmp_path):
    other = _commit(repo, "work/other", "docs/agents/work-launcher.md", signoff=True)
    app, dispatcher = _launcher(repo, "run-wb", tmp_path=tmp_path)
    app.submit("run-wb", {"status": "succeeded", "commit": other})
    run = dispatcher.registry.get("run-wb")
    assert run.status == "blocked"
    assert run.result["error"]["category"] == "commit_not_on_run_branch"


def test_a_commit_without_a_dco_signoff_is_still_refused(repo, tmp_path):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md", signoff=False)
    app, dispatcher = _launcher(repo, "run-dco", tmp_path=tmp_path)
    app.submit("run-dco", {"status": "succeeded", "commit": sha})
    run = dispatcher.registry.get("run-dco")
    assert run.status == "blocked"
    assert run.result["error"]["category"] == "dco_trailer_missing"


def test_a_commit_outside_the_artifact_policy_is_still_refused(repo, tmp_path):
    sha = _commit(repo, "work/run-1", "docs/agents-secret/x.md", signoff=True)
    app, dispatcher = _launcher(repo, "run-art", tmp_path=tmp_path)
    app.submit("run-art", {"status": "succeeded", "commit": sha})
    run = dispatcher.registry.get("run-art")
    assert run.status == "blocked"
    assert run.result["error"]["category"] == "artifact_policy_violation"


def test_a_pre_existing_commit_does_not_count_as_output(repo, tmp_path):
    # A commit already on the run branch at claim time is not this Run's work:
    # the claim is in the future relative to it, so the gate refuses it.
    pre = _commit(repo, "work/run-1", "docs/agents/work-launcher.md", signoff=True)
    app, dispatcher = _launcher(repo, "run-base", claimed_at=time.time() + 100000,
                                tmp_path=tmp_path)
    app.submit("run-base", {"status": "succeeded", "commit": pre})
    run = dispatcher.registry.get("run-base")
    assert run.status == "blocked"
    assert run.result["error"]["category"] == "commit_predates_run"


# ==========================================================================
# The live OS path: WorkLauncher._dispatch -> dispatch_async -> adapter ->
# Dispatcher.complete -> Evidence Gate.
#
# This is the path #497 and a real Cortxt OS launch take. `submit()` is the
# coordinator-direct path and passing it proves nothing about this one: no
# adapter emits a `commit` field, so before #506 every mutating Run on the
# live path stopped at `commit_missing` no matter what it landed.
# ==========================================================================

class _NoCommitAdapter:
    """Shaped like the hermes-free success envelope: no correlation, no commit."""

    def __init__(self, status="succeeded"):
        self.status = status

    def invoke(self, run, task_prompt, timeout_seconds, worktree=None):
        return {"_status": self.status, "runtime": run.runtime,
                "worker_role": run.worker_role, "provider": "nous",
                "model": "upstage/solar-pro4:free", "usage": "unknown",
                "cost": "unknown (not measured)", "artifacts": [],
                "evidence": "worker reported status=" + self.status, "error": None}


def _run_worktree(repo, branch, tmp_path, name):
    """A real linked git worktree for `branch`, as the launcher creates."""
    _git(repo, "checkout", "main")
    path = tmp_path / name
    _git(repo, "worktree", "add", str(path), branch)
    return path


def _dispatch_live(repo, tmp_path, run_id, branch, worktree, *, claimed_at,
                   status="succeeded"):
    from worker_adapters import dispatch_async, register_adapter

    registry = RunRegistry(tmp_path / ("reg-live-" + run_id + ".json"))
    dispatcher = Dispatcher(registry, gh=FakeGitHub(),
                            commit_gate=make_commit_gate(repo))
    run = Run(run_id=run_id, issue_id="owner/repo#485",
              workflow="work-launcher/v1", worker_role="builder",
              runtime="test-nocommit", claimed_at=claimed_at, lease_seconds=600,
              status="in_progress", mutating=True, isolation="worktree",
              branch=branch, artifact_policy=POLICY, request_id="sha256:abc")
    registry.add(run)
    register_adapter("test-nocommit", _NoCommitAdapter(status))
    dispatch_async(dispatcher, run, "[test] see issue body",
                   worktree=worktree).join(timeout=30)
    return registry.get(run_id)


def test_live_dispatch_path_positive_arm_reaches_commit_correlated(repo, tmp_path):
    claimed_at = time.time()
    time.sleep(1.1)  # the gate refuses a commit inside the claim's own second
    _commit(repo, "work/run-live", "docs/agents/work-launcher.md", signoff=True)
    wt = _run_worktree(repo, "work/run-live", tmp_path, "wt-live")

    done = _dispatch_live(repo, tmp_path, "run-live", "work/run-live", wt,
                          claimed_at=claimed_at)

    assert done.status == "succeeded"
    assert done.result["evidence_gate"] == "commit_correlated"
    assert done.result["commit_evidence"]["branch"] == "work/run-live"
    # Correlation came from the Run record; the adapter emitted none of it.
    assert done.result["run_id"] == "run-live"
    assert done.result["request_id"] == "sha256:abc"


def test_live_dispatch_path_negative_arm_stays_blocked(repo, tmp_path):
    # The branch exists but sits on the baseline: the Run landed nothing. The
    # derived tip predates the claim, so the gate refuses it as output.
    _git(repo, "branch", "work/run-live-neg", "main")
    claimed_at = time.time()
    wt = _run_worktree(repo, "work/run-live-neg", tmp_path, "wt-live-neg")

    done = _dispatch_live(repo, tmp_path, "run-live-neg", "work/run-live-neg", wt,
                          claimed_at=claimed_at)

    assert done.status == "blocked"
    assert done.result["evidence_gate"] == "commit_correlation_failed"
    assert done.result["error"]["category"] == "commit_predates_run"


def test_live_dispatch_path_does_not_attach_a_commit_to_a_failed_run(repo, tmp_path):
    claimed_at = time.time()
    time.sleep(1.1)
    _commit(repo, "work/run-live-fail", "docs/agents/work-launcher.md", signoff=True)
    wt = _run_worktree(repo, "work/run-live-fail", tmp_path, "wt-live-fail")

    done = _dispatch_live(repo, tmp_path, "run-live-fail", "work/run-live-fail", wt,
                          claimed_at=claimed_at, status="failed")

    assert done.status == "failed"
    # A failed run must not carry a field that reads as landed evidence.
    assert "commit" not in done.result


# ==========================================================================
# submit() must uphold the same two invariants as the live path.
#
# Both cases below were unlocked by independent review of this PR: the
# coordinator-direct path had neither the success guard nor a test for what a
# branch sitting on its baseline actually produces there.
# ==========================================================================

def test_submit_does_not_attach_a_commit_to_a_non_succeeded_run(repo, tmp_path):
    # A stray commit exists on the run's branch, but the worker reported
    # failure. `_gate_commit` never runs for a non-success, so nothing would
    # verify a commit recorded here -- it must not be recorded at all.
    _commit(repo, "work/run-1", "docs/agents/work-launcher.md", signoff=True)
    app, dispatcher = _launcher(repo, "run-1", tmp_path=tmp_path)

    app.submit("run-1", {"status": "failed"})
    run = dispatcher.registry.get("run-1")

    assert run.status == "failed"
    assert "commit" not in run.result
    # Correlation identity is still supplied: it is never worker prose.
    assert run.result["run_id"] == "run-1"


def test_submit_on_a_baseline_branch_is_refused_as_predating_the_run(repo, tmp_path):
    # The Run's branch exists but nothing landed on it. Derivation resolves the
    # baseline tip, and the gate refuses it -- `commit_predates_run`, not
    # `commit_missing`, because a mutating Run always has a branch. This is the
    # production shape of the negative arm on this path too.
    _git(repo, "branch", "work/run-base2", "main")
    app, dispatcher = _launcher(repo, "run-base2", claimed_at=time.time(),
                                tmp_path=tmp_path)
    dispatcher.registry.get("run-base2").branch = "work/run-base2"

    app.submit("run-base2", {"status": "succeeded"})
    run = dispatcher.registry.get("run-base2")

    assert run.status == "blocked"
    assert run.result["evidence_gate"] == "commit_correlation_failed"
    assert run.result["error"]["category"] == "commit_predates_run"
