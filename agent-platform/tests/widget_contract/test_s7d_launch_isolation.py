"""S7d (#473): the UI launch path must actually isolate, server-derived.

Commit 280ad71 stopped the launcher from *reporting* a branch it never made
and added `WorkLauncher.resume(isolate=True)` -- but every real caller stayed
on the default, so the Work UI launch path still created no worktree and a
mandate's "inside the run's isolated worktree" clause stayed unenforceable.

Isolation is now decided on the server, from the approved mandate's artifact
policy, inside `dispatch.request.v1`; it is part of the immutable request
snapshot (so it is covered by `request_id` and the browser supplies nothing
that can choose it), and `gh_claim_run_resume` carries it into the launcher.
It fails closed: anything that does not explicitly waive isolation gets an
isolated worktree.
"""
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from dispatcher import Dispatcher, RunRegistry  # noqa: E402
from execution_map import SqliteClaimStore  # noqa: E402
from work_launcher import WorkLauncher  # noqa: E402

from widget.action_host import ActionHost  # noqa: E402
from widget_contract.adapters.cli_ports import gh_claim_run_resume  # noqa: E402
from widget_contract.dispatch_request import (  # noqa: E402
    build_dispatch_request_v1, isolation_for_artifact_policy)

CLAIM_APPROVAL = "Operator approved this exact scope, route, and limits on 2026-08-31."
ISOLATED_POLICY = "Isolated worktree; approved source/tests/docs only."
SHARED_POLICY = "Work in the shared checkout on a feature branch."


def _ready_issue(number=473, *, artifact_policy=ISOLATED_POLICY):
    return {
        "number": number,
        "title": "Build: S7d",
        "body": (
            "## Scope\n\nComplete the operator journey.\n\n"
            "## Deterministic acceptance criteria\n\n1. It works.\n\n"
            "## Approval status\n\n" + CLAIM_APPROVAL + "\n\n"
            "## Worker role and limits\n\n"
            "- Workflow: work-launcher/v1\n"
            "- Worker role: builder.\n"
            "- Max runtime: 5400 seconds.\n"
            "- Max cost: USD 8.00 hard ceiling.\n"
            "- Max parallel workers: 2, one writer only.\n"
            "- Delegation depth: 1.\n\n"
            "## Artifact policy\n\n" + artifact_policy + "\n\n"
            "## Engine policy\n\nReliability: unverified\nEngine: hermes-free\n"
        ),
        "state": "open",
        "labels": [{"name": "workflow:ready"}, {"name": "background-task"}],
        "url": f"https://github.com/owner/repo/issues/{number}",
        "milestone": None,
    }


# --- the decision itself is server-derived and fails closed ------------------

@pytest.mark.parametrize("policy,expected", [
    (ISOLATED_POLICY, "worktree"),
    ("Commit only English project artifacts on a feature branch.", "worktree"),
    (SHARED_POLICY, "shared-checkout"),
    ("No isolated worktree is required for this documentation change.", "shared-checkout"),
    ("", "worktree"),
    (None, "worktree"),
])
def test_isolation_defaults_closed_for_every_policy_shape(policy, expected):
    assert isolation_for_artifact_policy(policy) == expected


def test_dispatch_request_declares_isolation_and_defaults_to_a_worktree():
    assert build_dispatch_request_v1(_ready_issue(), None, repo="owner/repo")["isolation"] == "worktree"


def test_an_artifact_policy_that_waives_isolation_is_explicit_and_honoured():
    request = build_dispatch_request_v1(
        _ready_issue(artifact_policy=SHARED_POLICY), None, repo="owner/repo")
    assert request["isolation"] == "shared-checkout"


def test_isolation_is_covered_by_the_request_digest():
    """The browser cannot choose isolation: it belongs to the immutable
    snapshot, so changing it changes request_id and a confirmation bound to the
    old snapshot fails closed."""
    isolated = build_dispatch_request_v1(_ready_issue(), None, repo="owner/repo")
    shared = build_dispatch_request_v1(
        _ready_issue(artifact_policy=SHARED_POLICY), None, repo="owner/repo")
    assert isolated["request_id"] != shared["request_id"]


# --- and it reaches the launcher through the real chain ----------------------

class _RecordingLauncher:
    def __init__(self):
        self.calls = []

    def resume(self, issue_id, **kwargs):
        self.calls.append({"issue_id": issue_id, **kwargs})
        return {"issue_id": issue_id, "run_id": "run-1", "claim_id": "claim-1",
                "receipt_id": "receipt-1", "store_session_id": "s1",
                "engine_session_id": "e1", "worktree": "trees/run-1",
                "branch": "work/run-1", "isolation": "worktree",
                "working_dir": "trees/run-1"}


def _chain(issue_reader, launcher):
    """Real host + real gh_claim_run_resume wiring; only the issue reader and
    the launcher are injected."""
    resume = partial(gh_claim_run_resume, registry=Path("unused-runs.json"),
                     scripts_dir=SCRIPTS_DIR, issue_reader=issue_reader, launcher=launcher)
    return ActionHost(issue_reader=issue_reader, resume=resume, token="test-token")


def _launch_through_host(host, number=473):
    request = host.dispatch_request("owner/repo", number)
    assert request["eligible"] is True, request["missing"]
    return host.execute(action_id="claim-run", issue_id=f"owner/repo#{number}",
                        approval_ref=request["approval_reference"],
                        request_id=request["request_id"],
                        confirm=True, token="test-token")


def test_ui_launch_chain_requests_isolation_from_the_launcher():
    launcher = _RecordingLauncher()
    result = _launch_through_host(_chain(lambda repo, number: _ready_issue(number), launcher))
    assert result["status"] == "ok"
    assert launcher.calls[0]["isolate"] is True


def test_ui_launch_chain_honours_an_explicit_shared_checkout_mandate():
    launcher = _RecordingLauncher()
    host = _chain(lambda repo, number: _ready_issue(number, artifact_policy=SHARED_POLICY),
                  launcher)
    _launch_through_host(host)
    assert launcher.calls[0]["isolate"] is False


class _FakeGitHub:
    def __init__(self):
        self.labels = {"owner/repo#473": ["workflow:ready"]}
        self.comments = []

    def get_labels(self, repo, num):
        return self.labels.get(f"{repo}#{num}", [])

    def swap_label(self, repo, num, remove, add):
        cur = self.labels.setdefault(f"{repo}#{num}", [])
        if remove in cur:
            cur.remove(remove)
        cur.append(add)

    def comment(self, repo, num, body):
        self.comments.append((f"{repo}#{num}", body))


def _real_launcher(tmp_path):
    """A real WorkLauncher with only the git and adapter boundaries recorded."""
    events = []
    gh = _FakeGitHub()
    dispatcher = Dispatcher(RunRegistry(tmp_path / "runs.json"), gh)

    def _dispatch(dispatcher, run, prompt, worktree=None):
        events.append(("dispatched", run.run_id, worktree))

    def _run_worktree(argv, **kwargs):
        events.append(("git", tuple(argv)))
        if not created_dirs["skip"]:
            Path(argv[-2]).mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=0)

    created_dirs = {"skip": False}

    app = WorkLauncher(
        dispatcher, gh,
        dispatch=_dispatch,
        worktree_root=tmp_path / "trees",
        run_worktree=_run_worktree,
        claim_store=SqliteClaimStore(tmp_path / "claims.sqlite3"),
        issue_reader=lambda issue_id: {
            "issue_id": issue_id, "body": "", "state": "open",
            "labels": ("workflow:ready",), "area": "dispatch", "milestone": "m1"},
        inventory_readers={name: (lambda: ()) for name in WorkLauncher.INVENTORY_NAMES},
        clock=lambda: 100.0,
        id_generator=iter(("run-1", "run-2")).__next__,
        store_session_id="s1", engine_session_id="e1",
        repo_path=tmp_path / "repo",
    )
    return app, dispatcher, events, created_dirs


def test_ui_launch_chain_reaches_a_real_isolated_worktree(tmp_path):
    """The full chain with a REAL WorkLauncher: a confirmed launch from the
    action host must actually invoke git to create the run's own worktree and
    branch, and report the isolation it really got."""
    app, dispatcher, events, _skip = _real_launcher(tmp_path)
    result = _launch_through_host(_chain(lambda repo, number: _ready_issue(number), app))

    assert result["status"] == "ok"
    git_calls = [event[1] for event in events if event[0] == "git"]
    assert git_calls, "the launch chain never asked git for an isolated worktree"
    assert git_calls[0][:5] == ("git", "worktree", "add", "-b", "work/run-1")

    launched = result["result"]
    assert launched["isolation"] == "worktree"
    assert launched["branch"] == "work/run-1"
    assert launched["worktree"] == str(tmp_path / "trees" / "run-1")
    assert dispatcher.registry.get("run-1").isolation == "worktree"
    # the worker was bound to that worktree, not to the launcher's checkout
    dispatched = [event for event in events if event[0] == "dispatched"]
    assert dispatched and dispatched[0][2] == tmp_path / "trees" / "run-1"


def test_a_shared_checkout_mandate_creates_no_worktree_through_the_real_chain(tmp_path):
    app, dispatcher, events, _skip = _real_launcher(tmp_path)
    host = _chain(lambda repo, number: _ready_issue(number, artifact_policy=SHARED_POLICY), app)
    result = _launch_through_host(host)

    assert not [event for event in events if event[0] == "git"]
    assert result["result"]["isolation"] == "shared-checkout"
    assert result["result"]["branch"] is None
    assert dispatcher.registry.get("run-1").isolation == "shared-checkout"


def test_isolation_that_produced_no_directory_fails_the_launch_closed(tmp_path):
    """A zero exit code is not proof: `_dispatch` binds the worker only to a
    worktree that really exists, so a launch that would report isolation it
    never got must fail instead of running in the shared checkout."""
    from widget.action_host import AdapterStartFailure

    app, dispatcher, _events, skip = _real_launcher(tmp_path)
    skip["skip"] = True
    host = _chain(lambda repo, number: _ready_issue(number), app)
    with pytest.raises(AdapterStartFailure) as exc:
        _launch_through_host(host)
    assert exc.value.code == "worktree_creation_failed"
    assert dispatcher.registry.get("run-1").status == "blocked"
