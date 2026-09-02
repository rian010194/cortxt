"""S7 (#490, #493): a Run's success and its review transition must be earned.

The #485 forensics found two independent holes, and closing one does not close
the other:

- **#490** -- a mutating Run reached `succeeded` with no commit SHA, no branch
  and no worktree correlation. Nothing between the worker and the durable Run
  record required a landed artifact, so a self-reported status was accepted and
  relayed onward.
- **#493** -- `Dispatcher._sync_github()` mapped any non-failing terminal
  status straight to `workflow:review`, so a worker's own word moved the Issue,
  with no durable `run.review_submitted` and without review-sync ever running.

These tests drive both against real git repositories and a real session store,
covering the positive path, every negative correlation case, replay, and
idempotence.
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
PLATFORM_DIR = REPO_ROOT / "agent-platform"
for _path in (SCRIPTS_DIR, PLATFORM_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from commit_evidence import (  # noqa: E402
    CommitEvidence, CorrelationFailure, make_commit_gate, policy_paths,
    verify_commit_correlation)
from dispatcher import (  # noqa: E402
    LABEL_BLOCKED, LABEL_IN_PROGRESS, LABEL_READY, LABEL_REVIEW, Dispatcher,
    ReviewSubmissionError, Run, RunRegistry)
from work_launcher import ExecutionGateError, WorkLauncher  # noqa: E402

from daemon.review_submission import (  # noqa: E402
    REVIEW_EVENT, make_review_submitter, review_submission_id, submit_review)
from daemon.review_sync import sync_review_submissions  # noqa: E402
from runtime import session_state  # noqa: E402

SIGNOFF = "Signed-off-by: Operator <operator@example.com>"
POLICY = "Only `docs/agents/work-launcher.md` inside the run's isolated worktree."


# --------------------------------------------------------------------------
# git fixtures: a real repository, a real run branch, real commits.
# --------------------------------------------------------------------------

def _git(repo: Path, *args: str):
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
    (root / "docs").mkdir()
    (root / "docs" / "agents").mkdir()
    (root / "docs" / "agents" / "work-launcher.md").write_text("base\n", encoding="utf-8")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", f"chore: base\n\n{SIGNOFF}")
    return root


def _commit(repo: Path, branch: str, path: str, *, message: str = "docs: land the artifact",
            signoff: bool = True) -> str:
    if _git(repo, "rev-parse", "--verify", f"refs/heads/{branch}").returncode != 0:
        _git(repo, "checkout", "-b", branch)
    else:
        _git(repo, "checkout", branch)
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"changed at {time.time()}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    body = f"{message}\n\n{SIGNOFF}" if signoff else message
    _git(repo, "commit", "-m", body)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _run(**overrides) -> Run:
    fields = dict(
        run_id="run-1", issue_id="owner/repo#485", workflow="work-launcher/v1",
        worker_role="builder", runtime="hermes-free", claimed_at=1000.0,
        lease_seconds=600, status="in_progress", mutating=True,
        isolation="worktree", branch="work/run-1", artifact_policy=POLICY,
        request_id="sha256:abc",
    )
    fields.update(overrides)
    return Run(**fields)


# --------------------------------------------------------------------------
# #490 -- the commit-correlation Evidence Gate, in isolation.
# --------------------------------------------------------------------------

def test_gate_accepts_a_real_correlated_commit(repo):
    """The positive path: an existing, in-scope, signed-off commit on the run's
    own branch, made after the claim, is durable correlated evidence."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    outcome = verify_commit_correlation(_run(), {"status": "succeeded", "commit": sha},
                                        repo_path=repo)
    assert isinstance(outcome, CommitEvidence), getattr(outcome, "detail", outcome)
    record = outcome.as_record()
    assert record["commit"] == sha
    assert record["branch"] == "work/run-1"
    assert record["files"] == ["docs/agents/work-launcher.md"]
    assert record["run_id"] == "run-1"
    assert record["issue_id"] == "owner/repo#485"
    assert record["request_id"] == "sha256:abc"
    assert record["policy_paths"] == ["docs/agents/work-launcher.md"]


def test_gate_rejects_the_485_shape_exactly(repo):
    """#485's own result envelope: `succeeded`, a run-log artifact, and no
    commit anywhere. This is the case the gate exists for."""
    envelope = {"status": "succeeded",
                "artifacts": ["run-log:run-6d936b467f804939a4ce734ac5f45dd8"],
                "evidence": "hermes-free reported status=succeeded; see local run log"}
    outcome = verify_commit_correlation(_run(), envelope, repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "commit_missing"


@pytest.mark.parametrize("envelope_extra, code", [
    ({"run_id": "run-other"}, "run_correlation_mismatch"),
    ({"issue_id": "owner/repo#999"}, "issue_correlation_mismatch"),
    ({"request_id": "sha256:different"}, "request_correlation_mismatch"),
])
def test_gate_rejects_a_result_belonging_to_another_run(repo, envelope_extra, code):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    outcome = verify_commit_correlation(
        _run(), {"status": "succeeded", "commit": sha, **envelope_extra}, repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == code


@pytest.mark.parametrize("commit_value", [None, "", "not-a-sha", "abc123", 12345,
                                          "0" * 39, "g" * 40])
def test_gate_rejects_anything_that_is_not_a_full_sha(repo, commit_value):
    outcome = verify_commit_correlation(_run(), {"status": "succeeded",
                                                 "commit": commit_value}, repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "commit_missing"


def test_gate_rejects_a_commit_that_does_not_exist(repo):
    outcome = verify_commit_correlation(_run(), {"status": "succeeded", "commit": "a" * 40},
                                        repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "commit_not_found"


def test_gate_rejects_a_run_that_recorded_no_isolation(repo):
    """#489's shape: the mandate demanded an isolated worktree, the Run records
    `isolation: None` / `branch: None`. A commit cannot be correlated to a
    branch that was never registered, so the gate falls closed."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    outcome = verify_commit_correlation(
        _run(isolation=None, branch=None), {"status": "succeeded", "commit": sha},
        repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "isolation_not_recorded"


def test_gate_rejects_a_commit_on_a_different_branch(repo):
    """A real, signed-off, in-scope commit is still not this Run's evidence if
    it landed outside the Run's isolated worktree branch."""
    sha = _commit(repo, "work/somebody-else", "docs/agents/work-launcher.md")
    outcome = verify_commit_correlation(_run(), {"status": "succeeded", "commit": sha},
                                        repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "commit_not_on_run_branch"


def test_gate_rejects_a_commit_that_predates_the_run(repo):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    future = _run(claimed_at=time.time() + 86400)
    outcome = verify_commit_correlation(future, {"status": "succeeded", "commit": sha},
                                        repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "commit_predates_run"


def test_gate_rejects_a_commit_without_a_dco_trailer(repo):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md", signoff=False)
    outcome = verify_commit_correlation(_run(), {"status": "succeeded", "commit": sha},
                                        repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "dco_trailer_missing"


def test_gate_rejects_a_commit_outside_the_approved_artifact_policy(repo):
    """#485's policy named exactly one file. A commit touching anything else
    breaches the approved scope, however real it is."""
    sha = _commit(repo, "work/run-1", "README.md")
    outcome = verify_commit_correlation(_run(), {"status": "succeeded", "commit": sha},
                                        repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "artifact_policy_violation"
    assert "README.md" in outcome.detail


def test_gate_honors_an_explicit_artifact_path_set_over_prose(repo):
    sha = _commit(repo, "work/run-1", "README.md")
    outcome = verify_commit_correlation(
        _run(artifact_paths=["README.md"]), {"status": "succeeded", "commit": sha},
        repo_path=repo)
    assert isinstance(outcome, CommitEvidence)
    assert outcome.policy_paths == ("README.md",)


def test_gate_requires_a_real_change_under_an_unscoped_policy(repo):
    """An unscoped policy restricts nothing by path, so the gate falls back to
    the one thing every artifact policy implies: something actually landed."""
    unscoped = "Commit only English project artifacts on a feature branch."
    assert policy_paths(unscoped) == ()
    _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    empty = _git(repo, "commit", "--allow-empty", "-m", f"chore: nothing\n\n{SIGNOFF}")
    assert empty.returncode == 0
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    outcome = verify_commit_correlation(
        _run(artifact_policy=unscoped), {"status": "succeeded", "commit": sha}, repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "no_files_changed"


def test_policy_paths_reads_the_paths_an_operator_actually_writes():
    assert policy_paths(POLICY) == ("docs/agents/work-launcher.md",)
    assert policy_paths("Touch `docs/adr/` and `scripts/dispatcher.py` only.") == (
        "docs/adr/", "scripts/dispatcher.py")
    assert policy_paths(None) == ()
    assert policy_paths("No paths named here at all.") == ()


# --------------------------------------------------------------------------
# #490 -- the gate wired into the one choke point every launch path reaches.
# --------------------------------------------------------------------------

class FakeGh:
    def __init__(self, labels=None):
        self.labels = dict(labels or {"owner/repo#485": [LABEL_IN_PROGRESS]})
        self.comments = []
        self.swaps = []

    def get_labels(self, repo, num):
        return list(self.labels.get(f"{repo}#{num}", []))

    def swap_label(self, repo, num, remove, add):
        key = f"{repo}#{num}"
        self.swaps.append((key, remove, add))
        self.labels[key] = [x for x in self.labels.get(key, []) if x != remove] + [add]

    def comment(self, repo, num, body):
        self.comments.append((f"{repo}#{num}", body))


def _dispatcher(tmp_path, repo, *, submitter=None, gh=None):
    registry = RunRegistry(tmp_path / "runs.json")
    return Dispatcher(registry, gh=gh or FakeGh(),
                      commit_gate=make_commit_gate(repo), review_submitter=submitter)


def test_complete_blocks_a_mutating_run_with_no_commit(tmp_path, repo):
    """The exact #485 relay, now closed: a self-reported success without a
    landed commit becomes a structured block, never a success."""
    dispatcher = _dispatcher(tmp_path, repo)
    dispatcher.registry.add(_run())
    run = dispatcher.complete("run-1", "succeeded",
                              {"status": "succeeded", "evidence": "worker says so"})
    assert run.status == "blocked"
    assert run.result["evidence_gate"] == "commit_correlation_failed"
    assert run.result["error"]["category"] == "commit_missing"
    assert run.commit_evidence is None
    assert dispatcher.gh.labels["owner/repo#485"] == [LABEL_BLOCKED]


def test_complete_records_durable_correlated_evidence(tmp_path, repo):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    dispatcher = _dispatcher(tmp_path, repo)
    dispatcher.registry.add(_run())
    run = dispatcher.complete("run-1", "succeeded", {"status": "succeeded", "commit": sha})
    assert run.status == "succeeded"
    assert run.commit_evidence["commit"] == sha
    assert run.commit_evidence["branch"] == "work/run-1"
    assert run.result["evidence_gate"] == "commit_correlated"
    assert f"commit:{sha}" in run.result["artifacts"]
    # Durable, not in-memory: a fresh reader of the registry file sees it.
    reread = RunRegistry(tmp_path / "runs.json").get("run-1")
    assert reread.commit_evidence["commit"] == sha


def test_a_gate_that_raises_blocks_rather_than_passes(tmp_path, repo):
    """Fail closed in both directions: an unverifiable result is not a pass."""
    def exploding_gate(run, envelope):
        raise OSError("repository unreadable")

    registry = RunRegistry(tmp_path / "runs.json")
    dispatcher = Dispatcher(registry, gh=FakeGh(), commit_gate=exploding_gate)
    dispatcher.registry.add(_run())
    run = dispatcher.complete("run-1", "succeeded", {"status": "succeeded", "commit": "a" * 40})
    assert run.status == "blocked"
    assert run.result["error"]["category"] == "commit_gate_error"


def test_a_non_mutating_run_is_not_gated_on_a_commit(tmp_path, repo):
    """A research or diagnosis Run produces no commit and is not held to one."""
    dispatcher = _dispatcher(tmp_path, repo)
    dispatcher.registry.add(_run(mutating=False))
    run = dispatcher.complete("run-1", "succeeded", {"status": "succeeded",
                                                     "evidence": "report attached"})
    assert run.status == "succeeded"
    assert run.commit_evidence is None


def test_a_failing_status_is_not_re_gated(tmp_path, repo):
    dispatcher = _dispatcher(tmp_path, repo)
    dispatcher.registry.add(_run())
    run = dispatcher.complete("run-1", "failed", {"status": "failed", "error": {"category": "x"}})
    assert run.status == "failed"
    assert dispatcher.gh.labels["owner/repo#485"] == [LABEL_BLOCKED]


def test_launcher_fails_closed_when_the_mutating_flag_cannot_be_recorded():
    """A registry that cannot carry the flag would run a mutating worker under
    no Evidence Gate at all -- so the launch fails instead."""
    class NoUpdateRegistry:
        def active_issue_ids(self):
            return set()

    class Dispatcherish:
        registry = NoUpdateRegistry()

    launcher = WorkLauncher.__new__(WorkLauncher)
    launcher.dispatcher = Dispatcherish()
    with pytest.raises(ExecutionGateError) as exc:
        launcher._record_mutating("run-1")
    assert "mutating_run_not_recordable" in str(exc.value)


# --------------------------------------------------------------------------
# #493 -- who may move the Issue to workflow:review, and on what evidence.
# --------------------------------------------------------------------------

def test_terminal_success_alone_no_longer_moves_the_issue_to_review(tmp_path, repo):
    """The #485 transition, now refused: with no submitter configured there is
    no durable submission, so the Issue stays where it is."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    dispatcher = _dispatcher(tmp_path, repo)
    dispatcher.registry.add(_run())
    dispatcher.complete("run-1", "succeeded", {"status": "succeeded", "commit": sha})
    assert dispatcher.gh.labels["owner/repo#485"] == [LABEL_IN_PROGRESS]
    assert LABEL_REVIEW not in [add for _, _, add in dispatcher.gh.swaps]
    assert dispatcher.gh.comments  # the result is still reported, just not as a transition
    assert "does not move the issue" in dispatcher.gh.comments[-1][1]


def test_cancelled_and_failing_transitions_are_untouched(tmp_path, repo):
    """#493 removes only the forward move. A terminal status may still return
    the Issue to ready or take it out to blocked."""
    dispatcher = _dispatcher(tmp_path, repo)
    dispatcher.registry.add(_run(mutating=False))
    dispatcher.complete("run-1", "cancelled", {"status": "cancelled"})
    assert dispatcher.gh.labels["owner/repo#485"] == [LABEL_READY]


def test_the_sanctioned_order_end_to_end(tmp_path, repo):
    """Evidence Gate -> durable run.review_submitted -> review-sync moves the
    label. Each step happens, in that order, and only the last one edits the
    Issue."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    store = tmp_path / "sessions"
    dispatcher = _dispatcher(tmp_path, repo, submitter=make_review_submitter(store))
    dispatcher.registry.add(_run())

    run = dispatcher.complete("run-1", "succeeded", {"status": "succeeded", "commit": sha})
    # 1 + 2: gated, with correlated evidence.
    assert run.status == "succeeded"
    assert run.commit_evidence["commit"] == sha
    # 3: the durable submission exists and is recorded on the Run.
    assert run.review_submission_id == review_submission_id("run-1")
    # ...and the dispatcher did not move the label.
    assert dispatcher.gh.labels["owner/repo#485"] == [LABEL_IN_PROGRESS]

    # 4: review-sync, and only review-sync, performs in-progress -> review.
    calls = []

    def fake_gh(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["issue", "view"]:
            return _Proc(0, '{"state":"OPEN","labels":[{"name":"workflow:in-progress"}]}')
        return _Proc(0, "")

    report = sync_review_submissions(store, tmp_path / "state", run_subprocess=fake_gh)
    assert report["synced"] == [review_submission_id("run-1")]
    edit = next(a for a in calls if a[1:3] == ["issue", "edit"])
    assert "--add-label" in edit and LABEL_REVIEW in edit
    assert "--remove-label" in edit and LABEL_IN_PROGRESS in edit


class _Proc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_a_blocked_run_writes_no_review_submission(tmp_path, repo):
    """The gate's verdict governs the submission: no verified commit, no
    submission, and therefore no route to review at all."""
    store = tmp_path / "sessions"
    dispatcher = _dispatcher(tmp_path, repo, submitter=make_review_submitter(store))
    dispatcher.registry.add(_run())
    run = dispatcher.complete("run-1", "succeeded", {"status": "succeeded"})
    assert run.status == "blocked"
    assert run.review_submission_id is None
    assert not list(store.glob("session_*/session.json")) or not [
        event for path in store.glob("session_*/session.json")
        for event in session_state.load(store, path.parent.name)["events"]
        if event["event_type"] == REVIEW_EVENT]


def test_a_failing_submitter_is_surfaced_and_retried(tmp_path, repo):
    """A submission that cannot be written must not leave a Run that looks
    reviewable: the sync fails, stays unsynced, and resync_pending retries."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    attempts = []

    def flaky(run, envelope, evidence=None):
        attempts.append(run.run_id)
        if len(attempts) == 1:
            raise OSError("store unwritable")
        return review_submission_id(run.run_id)

    dispatcher = _dispatcher(tmp_path, repo, submitter=flaky)
    dispatcher.registry.add(_run())
    with pytest.raises(ReviewSubmissionError):
        dispatcher.complete("run-1", "succeeded", {"status": "succeeded", "commit": sha})
    assert dispatcher.registry.get("run-1").status == "succeeded"
    assert dispatcher.registry.get("run-1").gh_synced is False

    dispatcher.registry.update("run-1", gh_sync_claimed_at=None)
    assert dispatcher.resync_pending() == ["run-1"]
    assert dispatcher.registry.get("run-1").review_submission_id == review_submission_id("run-1")


# --------------------------------------------------------------------------
# #493 -- replay and idempotence.
# --------------------------------------------------------------------------

def test_the_submission_id_is_derived_from_the_run(tmp_path):
    assert review_submission_id("run-1") == review_submission_id("run-1")
    assert review_submission_id("run-1") != review_submission_id("run-2")


def test_a_replayed_submission_appends_nothing(tmp_path):
    """A resync, a restarted host and a duplicated completion all address the
    same submission; the second write is a no-op, not a second event."""
    store = tmp_path / "sessions"
    run = _run(status="succeeded")
    first = submit_review(store, run, {"status": "succeeded"},
                          commit_evidence={"commit": "a" * 40})
    second = submit_review(store, run, {"status": "succeeded"},
                           commit_evidence={"commit": "a" * 40})
    assert first == second == review_submission_id("run-1")
    sessions = list(store.glob("session_*/session.json"))
    assert len(sessions) == 1
    doc = session_state.load(store, sessions[0].parent.name)
    events = [e for e in doc["events"] if e["event_type"] == REVIEW_EVENT]
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["review_submission_id"] == payload["idempotency_key"] == first
    assert payload["run_id"] == "run-1"
    assert payload["issue_id"] == "owner/repo#485"
    assert payload["commit"] == "a" * 40
    assert payload["branch"] == "work/run-1"


def test_two_runs_on_one_issue_get_separate_submissions(tmp_path):
    """A second Run on the same Issue must not inherit the first Run's
    submission chain -- matching on run_id, not just issue_id."""
    store = tmp_path / "sessions"
    first = submit_review(store, _run(status="succeeded"), {"status": "succeeded"})
    second = submit_review(store, _run(run_id="run-2", status="succeeded"),
                           {"status": "succeeded"})
    assert first != second
    ids = {event["payload"]["review_submission_id"]
           for path in store.glob("session_*/session.json")
           for event in session_state.load(store, path.parent.name)["events"]
           if event["event_type"] == REVIEW_EVENT}
    assert ids == {first, second}


def test_a_submission_joins_an_existing_session_for_its_run(tmp_path):
    """When the launcher already opened a session for the Run, the submission
    is appended there rather than starting a rival chain."""
    store = tmp_path / "sessions"
    doc = session_state.create(store, "task", run_id="run-1", issue_id="owner/repo#485")
    submit_review(store, _run(status="succeeded"), {"status": "succeeded"})
    assert len(list(store.glob("session_*/session.json"))) == 1
    reread = session_state.load(store, doc["session_id"])
    assert [e["event_type"] for e in reread["events"]] == ["session.created", REVIEW_EVENT]


def test_review_sync_replays_a_submission_only_once(tmp_path, repo):
    """The GitHub side is idempotent too: a second sync pass on the same
    submission skips instead of editing the Issue again."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    store = tmp_path / "sessions"
    state = tmp_path / "state"
    dispatcher = _dispatcher(tmp_path, repo, submitter=make_review_submitter(store))
    dispatcher.registry.add(_run())
    dispatcher.complete("run-1", "succeeded", {"status": "succeeded", "commit": sha})

    edits = []

    def fake_gh(args, **kwargs):
        if args[1:3] == ["issue", "view"]:
            return _Proc(0, '{"state":"OPEN","labels":[{"name":"workflow:in-progress"}]}')
        edits.append(args)
        return _Proc(0, "")

    first = sync_review_submissions(store, state, run_subprocess=fake_gh)
    second = sync_review_submissions(store, state, run_subprocess=fake_gh)
    assert len(first["synced"]) == 1
    assert second["synced"] == []
    assert second["skipped"][0]["reason"] == "already_synced"
    assert len(edits) == 1


def test_the_default_launcher_is_wired_to_the_audited_session_store(tmp_path):
    """#493 fails closed without a submitter, so the sanctioned path must
    actually be wired -- otherwise no real run could ever reach review.

    The store resolves from the registry, the way `action_host.py` resolves the
    registry itself: a cwd-relative store is how #485's records ended up in a
    second, unaudited registry root.
    """
    from work_launcher import default_launcher, default_review_store

    registry = tmp_path / "agent-platform" / ".dispatch" / "runs.json"
    registry.parent.mkdir(parents=True)
    assert default_review_store(registry) == tmp_path / "agent-platform" / ".sessions"

    launcher = default_launcher(registry, repo_path=tmp_path)
    assert launcher.dispatcher.review_submitter is not None
    assert launcher.dispatcher.commit_gate is not None

    # And it writes where it says it does.
    launcher.dispatcher.registry.add(_run(status="succeeded"))
    submission = launcher.dispatcher.review_submitter(
        launcher.dispatcher.registry.get("run-1"), {"status": "succeeded"}, None)
    assert submission == review_submission_id("run-1")
    store = default_review_store(registry)
    assert [event["payload"]["review_submission_id"]
            for path in store.glob("session_*/session.json")
            for event in session_state.load(store, path.parent.name)["events"]
            if event["event_type"] == REVIEW_EVENT] == [submission]


def test_the_ci_dispatch_proof_worker_produces_gate_passing_evidence(tmp_path, repo):
    """The #207 live fixture must exercise the production gate, not a weaker
    path -- and it cannot be run from a test, so its offline-checkable parts
    are checked here: the branch it registers is the branch it creates, its
    commit carries a DCO trailer, its envelope reports the SHA, and the real
    `verify_commit_correlation` accepts the result.

    Before #490/#493 this fixture asserted `workflow:review` immediately after
    `Dispatcher.complete()`, which #493 makes false. Leaving it unchanged would
    have left a green PR with a broken live proof.
    """
    import ci_dispatch_proof as proof

    checkout, temp_root = repo, tmp_path / "temp"
    temp_root.mkdir()
    run = _run(run_id="run-ci-1", issue_id="owner/repo#207")

    branch = proof.proof_branch("207", run.run_id)
    worktree = proof.create_worktree(checkout, temp_root, "207", run.run_id)
    try:
        # The branch the proof registers on the Run is the branch it created.
        assert proof.run_cmd(["git", "-C", str(checkout), "rev-parse", "--verify",
                              f"refs/heads/{branch}"]).returncode == 0

        adapter = proof.DeterministicCommitAdapter(
            worktree, run.issue_id, tmp_path / "logs", "hermes-free")
        envelope = adapter.invoke(run, "[ci fixture]", timeout_seconds=60)
        assert envelope["_status"] == "succeeded", envelope.get("error")
        assert envelope["commit"] == envelope["evidence"][1]["head_after"]

        # And the production gate accepts it, against the run's real branch.
        gated = _run(run_id=run.run_id, issue_id=run.issue_id, branch=branch,
                     artifact_policy=None, request_id=None)
        outcome = verify_commit_correlation(gated, envelope, repo_path=checkout)
        assert isinstance(outcome, CommitEvidence), getattr(outcome, "detail", outcome)
        assert outcome.commit == envelope["commit"]
        assert outcome.branch == branch
    finally:
        proof.remove_worktree(checkout, worktree)
