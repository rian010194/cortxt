"""S7 (#490, #493): regressions for the independent review of PR #494.

Eight findings, each of which was verified against the code before it was
fixed. The tests are grouped by finding and named for the property they
protect, not for the bug, so a future change that reintroduces one fails on a
sentence that says what is wrong.

The through-line of findings 2, 3 and 4 is one property: **worker-supplied data
must never be able to authorize its own evidence.** A worker chooses the
envelope; it does not choose which checks run, which paths are permitted, or
whether its commit can be ordered after the claim.
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

import yaml  # noqa: E402

from commit_evidence import (  # noqa: E402
    CommitEvidence, CorrelationFailure, make_commit_gate, normalize_repo_path,
    policy_paths, verify_commit_correlation)
from dispatcher import Dispatcher, Run, RunRegistry  # noqa: E402
from work_launcher import ExecutionGateError, WorkLauncher, parse_scope_file  # noqa: E402

from daemon.review_submission import (  # noqa: E402
    REVIEW_EVENT, review_submission_id, submit_review)
from runtime import session_state  # noqa: E402

SIGNOFF = "Signed-off-by: Operator <operator@example.com>"
POLICY = "Only `docs/agents/work-launcher.md` inside the run's isolated worktree."


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
    for rel in ("docs/agents/work-launcher.md", "docs/agents-secret/x.md",
                "README.md", "LICENSE"):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "chore: base\n\n" + SIGNOFF)
    return root


def _commit(repo: Path, branch: str, path: str, *, signoff: bool = True) -> str:
    if _git(repo, "rev-parse", "--verify", "refs/heads/" + branch).returncode != 0:
        _git(repo, "checkout", "-b", branch)
    else:
        _git(repo, "checkout", branch)
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed at " + str(time.time()) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    message = "docs: land the artifact"
    _git(repo, "commit", "-m", message + "\n\n" + SIGNOFF if signoff else message)
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


def _envelope(**overrides) -> dict:
    envelope = {"status": "succeeded", "run_id": "run-1",
                "issue_id": "owner/repo#485", "request_id": "sha256:abc"}
    envelope.update(overrides)
    return envelope


# ==========================================================================
# Finding 1 -- a review session belongs to exactly one Run.
# ==========================================================================

def test_a_second_run_on_one_issue_never_joins_the_first_runs_session(tmp_path):
    """A retry, or the attempt after a recovery, is a different Run.

    The `issue_id` fallback used to adopt any session for the Issue, so the
    second Run appended its submission to the first Run's chain. `review_sync`
    derives the Issue from `session.created`, so the second Run's evidence
    would have been filed under the first Run's identity -- correlating a Run
    to the wrong record is the exact class of defect #490/#493 exist to close.
    """
    store = tmp_path / "sessions"
    first = submit_review(store, _run(run_id="run-1", status="succeeded"),
                          {"status": "succeeded"})
    second = submit_review(store, _run(run_id="run-2", status="succeeded"),
                           {"status": "succeeded"})
    assert first != second
    sessions = sorted(p.parent.name for p in store.glob("session_*/session.json"))
    assert len(sessions) == 2, "the second Run must get its own session"
    for session_id in sessions:
        doc = session_state.load(store, session_id)
        created = doc["events"][0]["payload"]
        submissions = [e["payload"] for e in doc["events"]
                       if e["event_type"] == REVIEW_EVENT]
        assert len(submissions) == 1
        assert submissions[0]["run_id"] == created["run_id"]


def test_only_a_legacy_session_without_a_run_id_is_adopted(tmp_path):
    """The fallback exists for sessions written before `run_id` was recorded."""
    store = tmp_path / "sessions"
    legacy = session_state.create(store, "legacy", issue_id="owner/repo#485")
    assert "run_id" not in legacy["events"][0]["payload"]
    submit_review(store, _run(status="succeeded"), {"status": "succeeded"})
    assert len(list(store.glob("session_*/session.json"))) == 1, "legacy session reused"
    doc = session_state.load(store, legacy["session_id"])
    assert [e["event_type"] for e in doc["events"]] == ["session.created", REVIEW_EVENT]


def test_a_foreign_runs_session_is_not_adopted_even_as_a_last_resort(tmp_path):
    store = tmp_path / "sessions"
    foreign = session_state.create(store, "other", run_id="run-other",
                                   issue_id="owner/repo#485")
    submit_review(store, _run(run_id="run-1", status="succeeded"), {"status": "succeeded"})
    assert len(list(store.glob("session_*/session.json"))) == 2
    untouched = session_state.load(store, foreign["session_id"])
    assert [e["event_type"] for e in untouched["events"]] == ["session.created"]


def test_replay_is_still_idempotent_per_run(tmp_path):
    """Idempotence must survive the narrower session matching."""
    store = tmp_path / "sessions"
    run = _run(status="succeeded")
    ids = {submit_review(store, run, {"status": "succeeded"}) for _ in range(3)}
    assert ids == {review_submission_id("run-1")}
    events = [e for p in store.glob("session_*/session.json")
              for e in session_state.load(store, p.parent.name)["events"]
              if e["event_type"] == REVIEW_EVENT]
    assert len(events) == 1


# ==========================================================================
# Finding 2 -- single-segment paths, path safety, and no unrestricted fallback.
# ==========================================================================

@pytest.mark.parametrize("policy, expected", [
    ("Only `LICENSE`.", ("LICENSE",)),
    ("Only `Makefile` and `Dockerfile`.", ("Makefile", "Dockerfile")),
    ("Only `README`.", ("README",)),
    ("Only `docs/agents/work-launcher.md`.", ("docs/agents/work-launcher.md",)),
    ("Touch `docs/adr/` and `scripts/dispatcher.py` only.",
     ("docs/adr/", "scripts/dispatcher.py")),
])
def test_policy_parser_reads_single_segment_repository_paths(policy, expected):
    """`LICENSE` is a repository-relative path. The earlier pattern required a
    `/` or a `.ext`, so it dropped single-segment paths -- and a dropped path
    used to mean the policy restricted nothing at all."""
    assert policy_paths(policy) == expected


def test_a_single_segment_policy_is_actually_enforced(repo):
    """The consequence end to end: a `LICENSE`-scoped policy permits LICENSE
    and refuses everything else, rather than permitting everything."""
    sha = _commit(repo, "work/run-1", "README.md")
    run = _run(artifact_policy="Only `LICENSE` inside the run's isolated worktree.")
    outcome = verify_commit_correlation(run, _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "artifact_policy_violation"


def test_a_single_segment_policy_accepts_its_own_path(repo):
    sha = _commit(repo, "work/run-1", "LICENSE")
    run = _run(artifact_policy="Only `LICENSE` inside the run's isolated worktree.")
    outcome = verify_commit_correlation(run, _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CommitEvidence), getattr(outcome, "detail", outcome)
    assert outcome.policy_paths == ("LICENSE",)


def test_an_unparsable_policy_falls_closed_and_is_never_unrestricted(repo):
    """A non-empty policy naming no readable path blocks the run. Treating it
    as "no restriction" is the failure mode itself."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    run = _run(artifact_policy="Commit only English project artifacts on a feature branch.")
    outcome = verify_commit_correlation(run, _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "artifact_policy_unparsable"


def test_a_run_with_no_approved_scope_at_all_falls_closed(repo):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    outcome = verify_commit_correlation(_run(artifact_policy=None),
                                        _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "artifact_policy_missing"


@pytest.mark.parametrize("path", [
    "../outside.md", "/etc/passwd", "C:/Windows/system32.txt",
    "docs/../../escape.md", "..", "", "   ",
])
def test_unsafe_paths_never_normalize(path):
    assert normalize_repo_path(path) is None


@pytest.mark.parametrize("path, expected", [
    ("docs/agents/x.md", "docs/agents/x.md"),
    ("./docs/agents/x.md", "docs/agents/x.md"),
    ("docs\\agents\\x.md", "docs/agents/x.md"),
    ("docs//agents/x.md", "docs/agents/x.md"),
    ("LICENSE", "LICENSE"),
])
def test_repository_relative_paths_normalize_consistently(path, expected):
    assert normalize_repo_path(path) == expected


def test_a_traversing_permitted_entry_is_refused_not_ignored(repo):
    """An unsafe entry in the approved scope must fail loudly. Silently
    skipping it would shrink the permitted set and look like a policy
    violation somewhere else."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    outcome = verify_commit_correlation(
        _run(artifact_paths=["../elsewhere"]), _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "artifact_policy_unsafe_path"


def test_path_matching_is_not_a_string_prefix_match(repo):
    """`docs/agents` must not permit `docs/agents-secret/x.md`."""
    sha = _commit(repo, "work/run-1", "docs/agents-secret/x.md")
    outcome = verify_commit_correlation(
        _run(artifact_paths=["docs/agents"]), _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "artifact_policy_violation"


def test_explicit_paths_win_over_prose(repo):
    """Prose is what the parser can misread, so a recorded path set decides."""
    sha = _commit(repo, "work/run-1", "README.md")
    outcome = verify_commit_correlation(
        _run(artifact_paths=["README.md"], artifact_policy="Only `LICENSE`."),
        _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CommitEvidence), getattr(outcome, "detail", outcome)
    assert outcome.policy_paths == ("README.md",)


# ==========================================================================
# Finding 3 -- correlation is mandatory, not opportunistic.
# ==========================================================================

@pytest.mark.parametrize("omit", ["run_id", "issue_id", "request_id"])
def test_an_omitted_correlation_field_is_not_a_passed_check(repo, omit):
    """A worker must not skip its own correlation check by leaving the field
    out. Each check used to run only `if claimed is not None`."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    envelope = _envelope(commit=sha)
    del envelope[omit]
    outcome = verify_commit_correlation(_run(), envelope, repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code.endswith("_correlation_mismatch")


@pytest.mark.parametrize("field, wrong", [
    ("run_id", "run-other"),
    ("issue_id", "owner/repo#999"),
    ("request_id", "sha256:different"),
])
def test_a_mismatched_correlation_field_blocks(repo, field, wrong):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    outcome = verify_commit_correlation(
        _run(), {**_envelope(commit=sha), field: wrong}, repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code.endswith("_correlation_mismatch")


def test_a_run_record_without_a_request_id_cannot_be_correlated(repo):
    """There is nothing approved to match against, so the run fails closed."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    outcome = verify_commit_correlation(_run(request_id=None),
                                        _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "request_id_not_recorded"


def test_worker_supplied_data_alone_never_authorizes_evidence(repo):
    """The decisive facts come from the Run record and from git, never from the
    envelope. A worker stating a perfect-looking correlation -- and even a
    ready-made `commit_evidence` block -- for a commit on a branch it does not
    own is still refused."""
    foreign = _commit(repo, "work/somebody-else", "docs/agents/work-launcher.md")
    envelope = _envelope(commit=foreign, branch="work/run-1", worktree="/wherever",
                         evidence_gate="commit_correlated",
                         commit_evidence={"commit": foreign, "branch": "work/run-1"})
    outcome = verify_commit_correlation(_run(), envelope, repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "commit_not_on_run_branch"


def test_a_worker_cannot_widen_its_own_artifact_scope(repo):
    """`artifact_paths` is read from the Run record, never from the envelope."""
    sha = _commit(repo, "work/run-1", "README.md")
    envelope = _envelope(commit=sha, artifact_paths=["README.md"],
                         artifact_policy="Only `README.md`.")
    outcome = verify_commit_correlation(
        _run(artifact_paths=["docs/agents/work-launcher.md"]), envelope, repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "artifact_policy_violation"


# ==========================================================================
# Finding 4 -- same-second commits are not ordered after the claim.
# ==========================================================================

def test_a_same_second_commit_is_refused(repo):
    """Git timestamps have one-second resolution, so a commit inside the
    claim's own second cannot be ordered against it -- including one made just
    before the claim. That second is the whole window needed to present
    pre-existing work as this Run's output."""
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    committed_at = int(_git(repo, "show", "-s", "--format=%ct", sha).stdout.strip())
    outcome = verify_commit_correlation(
        _run(claimed_at=float(committed_at)), _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "commit_predates_run"


def test_a_commit_strictly_after_the_claim_is_accepted(repo):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    committed_at = int(_git(repo, "show", "-s", "--format=%ct", sha).stdout.strip())
    outcome = verify_commit_correlation(
        _run(claimed_at=float(committed_at - 1)), _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CommitEvidence), getattr(outcome, "detail", outcome)


def test_a_commit_before_the_claim_is_still_refused(repo):
    sha = _commit(repo, "work/run-1", "docs/agents/work-launcher.md")
    committed_at = int(_git(repo, "show", "-s", "--format=%ct", sha).stdout.strip())
    outcome = verify_commit_correlation(
        _run(claimed_at=float(committed_at + 60)), _envelope(commit=sha), repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "commit_predates_run"
