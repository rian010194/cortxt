"""#499: the operator can read the actual change a Run contributed, from Cortxt OS.

These tests run against a REAL git repository and the real `run.diff.v1`
projection. Nothing is hand-constructed except the durable `commit_evidence`
record the Evidence Gate would have written -- the point of this read is what it
does with that record, and reproducing the gate here would test a copy of it.
"""

import subprocess
import sys

from widget_contract.run_authority import _diff_git as _real_git

import pytest

from widget_contract.adapters.store_reads import RunNotCorrelated, read_run_diff_v1
from widget_contract.registry import READ_OPERATIONS, TYPES
from widget_contract.validation import validate

REPO = "owner/repo"
ISSUE_REF = f"{REPO}#499"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", check=True)


@pytest.fixture()
def repo(tmp_path):
    """A repo with a base commit and one contributed commit on a Run branch."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(tmp_path, "init", "-q", "-b", "main", str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "docs" / "agents").mkdir(parents=True)
    (root / "secrets").mkdir()
    (root / "docs" / "agents" / "work-launcher.md").write_text("before\n", encoding="utf-8")
    (root / "secrets" / "keys.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD").stdout.strip()

    _git(root, "checkout", "-q", "-b", "work/run-1")
    (root / "docs" / "agents" / "work-launcher.md").write_text(
        "before\nTHE CONTRIBUTED LINE\n", encoding="utf-8")
    (root / "secrets" / "keys.txt").write_text("base\nleaked\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "contribution")
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    return {"root": root, "base": base, "head": head}


def _store(repo, *, run_id="run-1", issue_id=ISSUE_REF, gate="commit_correlated",
           envelope_evidence=None, durable=True, **overrides):
    """A dispatcher store shaped the way `Dispatcher.complete` writes one.

    `commit_evidence` sits on the durable Run record and `evidence_gate` on the
    result envelope, because that is where `_gate_commit` puts them -- and only
    when the gate passed.
    """
    record = {
        "run_id": run_id, "issue_id": issue_id, "commit": repo["head"],
        "branch": "work/run-1", "worktree": str(repo["root"]),
        "committed_at": 1756641601, "base_commit": repo["base"],
        "contributed_commits": [repo["head"]],
        "contributed_files": ["docs/agents/work-launcher.md", "secrets/keys.txt"],
        "files": ["docs/agents/work-launcher.md", "secrets/keys.txt"],
        "policy_paths": ["docs/agents/work-launcher.md"],
        "verified_at": 1756641602.0,
    }
    record.update(overrides)
    envelope = {"status": "succeeded", "evidence_gate": gate}
    if envelope_evidence is not None:
        envelope["commit_evidence"] = envelope_evidence
    return {run_id: {"run_id": run_id, "issue_id": issue_id, "status": "succeeded",
                     "commit_evidence": record if durable else None,
                     "result": envelope}}


def _diff(repo, **overrides):
    return read_run_diff_v1(ISSUE_REF, _store(repo, **overrides), run_id="run-1")


# --------------------------------------------------------------------------- #
# the acceptance criterion: readable content, not a hash
# --------------------------------------------------------------------------- #
def test_the_operator_can_read_the_actual_contributed_change(repo):
    result = _diff(repo)
    validate(result, TYPES["run.diff.v1"].schema)
    assert result["available"] is True
    permitted = [f for f in result["files"] if not f["withheld"]]
    assert [f["path"] for f in permitted] == ["docs/agents/work-launcher.md"]
    # Not a SHA, not a file list -- the change itself.
    assert "+THE CONTRIBUTED LINE" in permitted[0]["patch"]
    assert result["commit"] == repo["head"] and result["base_commit"] == repo["base"]


def test_a_file_outside_the_artifact_policy_is_withheld_with_its_reason(repo):
    withheld = {f["path"]: f for f in _diff(repo)["files"] if f["withheld"]}
    assert "secrets/keys.txt" in withheld
    assert withheld["secrets/keys.txt"]["reason"] == "outside_artifact_policy"
    assert withheld["secrets/keys.txt"]["patch"] is None


def test_an_unparsable_policy_withholds_everything_rather_than_opening_up(repo):
    """The gate treats a policy naming nothing as fail-closed; so does this."""
    result = _diff(repo, policy_paths=[])
    assert result["available"] is True
    assert all(f["withheld"] for f in result["files"])


def test_the_whole_contributed_range_is_diffed_not_only_the_tip(repo):
    """#509's lesson: the Run's change is base..tip, not the one presented commit."""
    root = repo["root"]
    (root / "docs" / "agents" / "work-launcher.md").write_text(
        "before\nTHE CONTRIBUTED LINE\nAND A SECOND ONE\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "second")
    tip = _git(root, "rev-parse", "HEAD").stdout.strip()
    result = _diff(repo, commit=tip, contributed_commits=[repo["head"], tip])
    patch = [f for f in result["files"] if not f["withheld"]][0]["patch"]
    assert "+THE CONTRIBUTED LINE" in patch and "+AND A SECOND ONE" in patch


# --------------------------------------------------------------------------- #
# fail-closed: every refusal states its reason and returns no content
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("overrides,reason", [
    ({"commit": None}, "no_correlated_commit"),
    ({"base_commit": None}, "no_correlated_commit"),
    ({"branch": None}, "no_registered_branch"),
    ({"worktree": None}, "no_registered_worktree"),
])
def test_a_broken_evidence_record_yields_a_reason_and_no_content(repo, overrides, reason):
    result = _diff(repo, **overrides)
    assert result["available"] is False and result["reason"] == reason
    assert result["files"] == []
    validate(result, TYPES["run.diff.v1"].schema)


def test_a_worker_authored_evidence_record_is_never_read(repo):
    """The gate, inverted: a refused Run's envelope is copied forward verbatim
    (`Dispatcher._gate_commit`), so a `commit_evidence` key the WORKER put there
    would otherwise choose the worktree this read runs git in. Only the durable
    record the gate itself wrote is ever read."""
    forged = {
        "commit": repo["head"], "branch": "work/run-1",
        "worktree": str(repo["root"]), "base_commit": repo["base"],
        "contributed_files": ["secrets/keys.txt"], "policy_paths": ["secrets"],
        "committed_at": 1756641601, "verified_at": 1756641602.0,
    }
    store = _store(repo, durable=False, gate="commit_correlation_failed",
                   envelope_evidence=forged)
    result = read_run_diff_v1(ISSUE_REF, store, run_id="run-1")
    assert result["available"] is False and result["reason"] == "no_commit_evidence"
    assert result["files"] == []


def test_a_run_the_gate_refused_serves_no_content(repo):
    """Even with a durable record present, a Run whose envelope does not carry
    the gate's pass is not readable."""
    store = _store(repo, gate="commit_correlation_failed")
    result = read_run_diff_v1(ISSUE_REF, store, run_id="run-1")
    assert result["available"] is False
    assert result["reason"] == "evidence_gate_did_not_pass"


@pytest.mark.parametrize("field,reason", [("run_id", "evidence_run_mismatch"),
                                          ("issue_id", "evidence_issue_mismatch")])
def test_an_evidence_record_that_names_nothing_is_refused(repo, field, reason):
    """A missing identifier must not compare equal to the one being asked for."""
    store = _store(repo)
    del store["run-1"]["commit_evidence"][field]
    result = read_run_diff_v1(ISSUE_REF, store, run_id="run-1")
    assert result["available"] is False and result["reason"] == reason


def test_an_evidence_record_belonging_to_another_issue_is_refused(repo):
    store = _store(repo)
    store["run-1"]["commit_evidence"]["issue_id"] = "owner/repo#1"
    result = read_run_diff_v1(ISSUE_REF, store, run_id="run-1")
    assert result["available"] is False and result["reason"] == "evidence_issue_mismatch"


def test_a_run_cannot_execute_code_through_a_diff_driver(repo, tmp_path):
    """A Run owns its worktree, so it owns `.gitattributes` and `.git/config`.

    Without `--no-ext-diff`, `git diff` would run a driver registered there --
    in the operator's process, at the moment they open the change to decide on
    it. The artifact policy cannot stop it: it governs what is displayed, while
    git reads attributes and config from the worktree regardless.
    """
    root = repo["root"]
    marker = tmp_path / "DRIVER_RAN"
    script = tmp_path / "driver.py"
    script.write_text(
        "import pathlib\npathlib.Path(r'{}').write_text('ran')\n".format(marker),
        encoding="utf-8")
    _git(root, "config", "diff.pwn.command",
         '"{}" "{}"'.format(sys.executable.replace("\\", "/"),
                            str(script).replace("\\", "/")))
    (root / ".gitattributes").write_text("*.md diff=pwn\n", encoding="utf-8")
    (root / "docs" / "agents" / "work-launcher.md").write_text(
        "before\nTHE CONTRIBUTED LINE\nthird\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "arm the driver")
    tip = _git(root, "rev-parse", "HEAD").stdout.strip()

    result = _diff(repo, commit=tip, contributed_commits=[tip])

    assert not marker.exists(), "an external diff driver was executed"
    permitted = [f for f in result["files"] if not f["withheld"]]
    # And the change is still rendered as ordinary text, not swallowed.
    assert permitted and "+third" in permitted[0]["patch"]


def test_the_diff_header_split_matches_what_git_actually_emits(repo):
    """`_split_diff` keys on git's own header; assert against real output."""
    from widget_contract.run_authority import _split_diff

    git = _real_git(str(repo["root"]))
    code, out = git(["diff", "--no-ext-diff", "--no-textconv",
                     repo["base"] + ".." + repo["head"], "--",
                     "docs/agents/work-launcher.md"])
    assert code == 0
    chunks = _split_diff(out, ["docs/agents/work-launcher.md"])
    assert list(chunks) == ["docs/agents/work-launcher.md"]
    assert chunks["docs/agents/work-launcher.md"].startswith("diff --git ")


def test_a_diff_header_line_inside_file_content_cannot_hide_a_file(repo):
    """Hunk bodies are prefixed, so content can never look like a header."""
    root = repo["root"]
    (root / "docs" / "agents" / "work-launcher.md").write_text(
        "before\nTHE CONTRIBUTED LINE\ndiff --git a/evil b/evil\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "smuggle a header")
    tip = _git(root, "rev-parse", "HEAD").stdout.strip()
    permitted = [f for f in _diff(repo, commit=tip)["files"] if not f["withheld"]]
    assert permitted and "+diff --git a/evil b/evil" in permitted[0]["patch"]


def test_the_whole_review_costs_one_git_diff(repo):
    """A single-threaded loopback host must not run one subprocess per file."""
    calls = []

    def factory(worktree):
        real = _real_git(worktree)

        def run(args):
            calls.append(list(args))
            return real(args)
        return run

    read_run_diff_v1(ISSUE_REF, _store(repo), run_id="run-1", git_factory=factory)
    assert sum(1 for c in calls if c[0] == "diff") == 1


def test_an_evidence_record_belonging_to_another_run_is_refused(repo):
    """A record that somehow reached this Run's slot is never read for it."""
    store = _store(repo)
    store["run-1"]["commit_evidence"]["run_id"] = "someone-elses-run"
    result = read_run_diff_v1(ISSUE_REF, store, run_id="run-1")
    assert result["available"] is False and result["reason"] == "evidence_run_mismatch"


def test_a_commit_that_left_the_registered_branch_is_refused(repo):
    """A commit not on the Run's own branch is not its reviewable work."""
    root = repo["root"]
    _git(root, "checkout", "-q", "-b", "elsewhere")
    (root / "docs" / "agents" / "work-launcher.md").write_text("elsewhere\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "off-branch")
    stray = _git(root, "rev-parse", "HEAD").stdout.strip()
    result = _diff(repo, commit=stray)
    assert result["available"] is False
    assert result["reason"] == "commit_not_on_registered_branch"


def test_a_vanished_worktree_is_a_reason_not_a_crash(repo):
    """A Run whose worktree was removed must fail closed, not raise into a 500."""
    result = _diff(repo, worktree=str(repo["root"] / "gone"))
    assert result["available"] is False
    assert result["reason"] == "worktree_unreadable"


def test_a_run_with_no_commit_evidence_says_so_rather_than_showing_nothing(repo):
    store = _store(repo)
    store["run-1"]["commit_evidence"] = None
    result = read_run_diff_v1(ISSUE_REF, store, run_id="run-1")
    assert result["available"] is False and result["reason"] == "no_commit_evidence"


def test_an_uncorrelated_issue_run_pair_fails_closed(repo):
    with pytest.raises(RunNotCorrelated):
        read_run_diff_v1(ISSUE_REF, _store(repo), run_id="run-2")
    with pytest.raises(RunNotCorrelated):
        read_run_diff_v1("owner/repo#1", _store(repo), run_id="run-1")


def test_the_browser_cannot_name_a_path():
    """The request schema is exactly issue_ref+run_id: no path can be asked for."""
    request = READ_OPERATIONS["run.diff.v1"].input_schema
    assert request["additionalProperties"] is False
    assert sorted(request["properties"]) == ["issue_ref", "run_id"]
    assert TYPES["run.diff.v1"].schema["additionalProperties"] is False


def test_an_unsafe_recorded_path_is_withheld_not_read(repo):
    result = _diff(repo, contributed_files=["../../etc/passwd", "C:/Windows/win.ini"],
                   files=["../../etc/passwd"])
    assert result["files"] and all(f["withheld"] for f in result["files"])
    assert {f["reason"] for f in result["files"]} <= {"unsafe_path", "outside_artifact_policy"}


def test_a_large_patch_is_truncated_and_says_so(repo, monkeypatch):
    from widget_contract import run_authority

    monkeypatch.setattr(run_authority, "_DIFF_FILE_MAX_CHARS", 40)
    permitted = [f for f in _diff(repo)["files"] if not f["withheld"]][0]
    assert permitted["truncated"] is True and len(permitted["patch"]) == 40


# --------------------------------------------------------------------------- #
# host endpoint
# --------------------------------------------------------------------------- #
def test_the_endpoint_is_wired_and_requires_a_run():
    from pathlib import Path

    import widget.action_host as module

    assert hasattr(module.ActionHost, "run_diff")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "/api/run-diff" in source
    assert '"run-activity", "run-terminal", "run-diff"' in source
