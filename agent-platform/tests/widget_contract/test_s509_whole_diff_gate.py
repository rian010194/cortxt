"""#509 -- the Evidence Gate verifies the change the Run contributed, not one commit.

Before #509 the artifact policy, the DCO trailer and the strictly-after-claim
ordering were checked against a single commit's file list. A Run could land
commit A outside its approved scope, then commit B inside it, present B, and
have the gate record `commit_correlated` while the branch that becomes a pull
request carried A. The approved scope was breached and the evidence said it was
not.

The fix is not "one commit per Run". Multiple commits are legitimate unless a
mandate says otherwise, and a single-commit rule would trade an evidence hole
for a workflow constraint no execution policy asked for. Instead the Run's base
is recorded durably at worktree creation, and every commit it contributed on
top of that base is held to the same rules.

These tests drive the real gate against a real git repository.
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
    CommitEvidence, CorrelationFailure, verify_commit_correlation)
from dispatcher import Run  # noqa: E402

SIGNOFF = "Signed-off-by: Operator <operator@example.com>"
POLICY = "Only `docs/agents/work-launcher.md` inside the run's isolated worktree."
BRANCH = "work/run-1"


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
    for rel in ("docs/agents/work-launcher.md", "scripts/commit_evidence.py",
                "README.md"):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "chore: repository\n\n" + SIGNOFF)
    # The baseline the run's branch is created at touches only an in-policy
    # path, so a test that presents the base itself is judged by the range
    # check rather than tripping the scope check on inherited history.
    (root / "docs" / "agents" / "work-launcher.md").write_text("baseline\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "docs: baseline\n\n" + SIGNOFF)
    _git(root, "checkout", "-b", BRANCH)
    return root


def _base(repo) -> str:
    return _git(repo, "rev-parse", "main").stdout.strip()


def _land(repo, path, *, signoff=True, message="docs: land the artifact") -> str:
    """Add one commit on the run's branch."""
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed at " + str(time.time()) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", (message + "\n\n" + SIGNOFF) if signoff else message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _run(repo, **overrides) -> Run:
    fields = dict(
        run_id="run-1", issue_id="owner/repo#485", workflow="work-launcher/v1",
        worker_role="builder", runtime="hermes-free", claimed_at=1000.0,
        lease_seconds=600, status="in_progress", mutating=True,
        isolation="worktree", branch=BRANCH, artifact_policy=POLICY,
        request_id="sha256:abc", base_commit=_base(repo),
    )
    fields.update(overrides)
    return Run(**fields)


def _envelope(**overrides) -> dict:
    envelope = {"status": "succeeded", "run_id": "run-1",
                "issue_id": "owner/repo#485", "request_id": "sha256:abc"}
    envelope.update(overrides)
    return envelope


def _verify(repo, run, commit):
    return verify_commit_correlation(run, _envelope(commit=commit), repo_path=repo)


# ==========================================================================
# The hole itself: a breaching commit cannot hide behind a conforming one.
# ==========================================================================

def test_an_out_of_policy_commit_is_not_hidden_by_a_conforming_tip(repo):
    """A: breaches the approved scope. B: conforms. The Run presents B.

    Before #509 this returned `commit_correlated` and wrote durable evidence,
    while the branch carried a change to a file the mandate never approved.
    """
    _land(repo, "scripts/commit_evidence.py", message="fix: out of scope")
    conforming = _land(repo, "docs/agents/work-launcher.md")

    outcome = _verify(repo, _run(repo), conforming)

    assert isinstance(outcome, CorrelationFailure), "the breaching commit was hidden"
    assert outcome.code == "contributed_artifact_policy_violation"
    assert "scripts/commit_evidence.py" in outcome.detail


def test_a_commit_without_a_dco_trailer_is_not_hidden_by_a_signed_tip(repo):
    _land(repo, "docs/agents/work-launcher.md", signoff=False)
    signed = _land(repo, "docs/agents/work-launcher.md")

    outcome = _verify(repo, _run(repo), signed)

    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "contributed_dco_trailer_missing"


def test_a_commit_at_or_before_the_claim_is_not_hidden_by_a_later_tip(repo):
    """Within the contributed range, not the inherited history: the baseline
    predates every claim and must not block anything."""
    early = _land(repo, "docs/agents/work-launcher.md")
    early_at = int(_git(repo, "show", "-s", "--format=%ct", early).stdout.strip())
    time.sleep(1.1)
    later = _land(repo, "docs/agents/work-launcher.md")

    # The claim lands in the same second as the first commit, so that commit
    # cannot be ordered after it -- the window the gate refuses.
    outcome = _verify(repo, _run(repo, claimed_at=float(early_at)), later)

    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "contributed_commit_predates_run"


# ==========================================================================
# Multiple commits are legitimate; the fix must not forbid them.
# ==========================================================================

def test_several_conforming_commits_still_pass(repo):
    first = _land(repo, "docs/agents/work-launcher.md")
    second = _land(repo, "docs/agents/work-launcher.md")
    third = _land(repo, "docs/agents/work-launcher.md")

    outcome = _verify(repo, _run(repo), third)

    assert isinstance(outcome, CommitEvidence), getattr(outcome, "detail", outcome)
    record = outcome.as_record()
    assert record["commit"] == third
    assert set(record["contributed_commits"]) == {first, second, third}
    assert record["base_commit"] == _base(repo)
    assert record["contributed_files"] == ["docs/agents/work-launcher.md"]


def test_the_evidence_record_describes_the_whole_contributed_change(repo):
    """A reviewer reads what the Run landed, not the one commit it presented."""
    _land(repo, "docs/agents/work-launcher.md")
    tip = _land(repo, "docs/agents/work-launcher.md")

    record = _verify(repo, _run(repo), tip).as_record()

    assert record["files"] == ["docs/agents/work-launcher.md"], "the presented commit"
    assert len(record["contributed_commits"]) == 2, "the whole contributed change"


# ==========================================================================
# The base is required, and fail-closed in every direction.
# ==========================================================================

def test_a_run_without_a_recorded_base_is_blocked(repo):
    """The gate cannot bound a change it has no starting point for. It refuses
    rather than falling back to verifying the tip alone."""
    tip = _land(repo, "docs/agents/work-launcher.md")

    outcome = _verify(repo, _run(repo, base_commit=None), tip)

    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "base_commit_not_recorded"


@pytest.mark.parametrize("bad", ["not-a-sha", "", "0" * 39, 12345])
def test_an_unusable_recorded_base_is_blocked(repo, bad):
    tip = _land(repo, "docs/agents/work-launcher.md")
    outcome = _verify(repo, _run(repo, base_commit=bad), tip)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "base_commit_not_recorded"


def test_a_base_that_does_not_exist_here_is_blocked(repo):
    tip = _land(repo, "docs/agents/work-launcher.md")
    outcome = _verify(repo, _run(repo, base_commit="a" * 40), tip)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "base_commit_not_found"


def test_a_branch_that_does_not_descend_from_its_base_is_blocked(repo):
    """A rewritten branch, or a base recorded for a different branch: a range
    computed from that base would not describe what the Run did."""
    tip = _land(repo, "docs/agents/work-launcher.md")
    _git(repo, "checkout", "main")
    unrelated = _land(repo, "README.md", message="chore: elsewhere")
    _git(repo, "checkout", BRANCH)

    outcome = _verify(repo, _run(repo, base_commit=unrelated), tip)

    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "branch_not_from_recorded_base"


def test_a_branch_sitting_on_its_base_contributed_nothing(repo):
    """The negative arm at range level: the branch exists but the Run added
    nothing to it."""
    base = _base(repo)
    outcome = verify_commit_correlation(_run(repo), _envelope(commit=base),
                                        repo_path=repo)
    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "no_contributed_commits"


def test_an_inherited_commit_presented_as_output_is_refused(repo):
    """Reachable from the branch, but not among what the Run added."""
    _land(repo, "docs/agents/work-launcher.md")
    base = _base(repo)

    # A base whose own commit is strictly after the claim, so the presented
    # commit clears the per-commit rules and only the range check can catch it.
    outcome = verify_commit_correlation(
        _run(repo, claimed_at=1.0), _envelope(commit=base), repo_path=repo)

    assert isinstance(outcome, CorrelationFailure)
    assert outcome.code == "commit_not_contributed_by_run"
