"""S7d (#473): honest launch reporting, sanctioned recovery, exact run lookup.

These cover the #472 dogfood findings that must be closed before an honest
S7d human-decision journey exists:

- finding 8/6: ``resume`` reported ``branch: work/<run_id>`` for a branch that
  was never created, because ``_launch(create_worktree=False)`` skips the
  worktree block but still constructs the branch name from the run_id. The
  launch result must describe what actually exists, and isolation must be
  requestable rather than silently absent.
- finding 2: no sanctioned actuator existed for ``in-progress -> ready``, so a
  failed Run stranded its Issue and recovery required a manual ``gh issue
  edit`` outside the action ports.
- Execution Inspector: ``renderExecution`` read ``ctx.workstream.runs``, which
  the workstreams projection never carries, so every Workstream rendered "No
  runs recorded" and a real ``conflict`` run stayed invisible.
- Work detail had no refresh path for authoritative workflow state.
- ``_KNOWN_AUDIT_EVIDENCE_PATHS`` exempted ``scripts/runs.json``; the dispatch
  registry actually lives under ``agent-platform/.dispatch/``.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from dispatcher import Dispatcher, RunRegistry  # noqa: E402
from execution_map import SqliteClaimStore  # noqa: E402
from work_launcher import LauncherDispatchError, WorkLauncher  # noqa: E402

from widget_contract.action_ports import github_transition_adapter  # noqa: E402
from widget_contract.adapters.github_ports import (  # noqa: E402
    TransitionDenied, return_to_ready_transition)

WIDGET = REPO_ROOT / "agent-platform" / "widget"


class FakeGitHub:
    def __init__(self, labels=None):
        self.labels = dict(labels or {})
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


def _issue(issue_id="acme/repo#1"):
    return {"issue_id": issue_id, "body": "", "state": "open",
            "labels": ("workflow:ready",), "area": "dispatch", "milestone": "m1"}


def _launcher(tmp_path, *, worktree_returncode=0, ids=("run-1", "run-2")):
    store = SqliteClaimStore(tmp_path / "claims.sqlite3")
    gh = FakeGitHub({"acme/repo#1": ["workflow:ready"]})
    dispatcher = Dispatcher(RunRegistry(tmp_path / "runs.json"), gh)
    created = []

    def _dispatch(dispatcher, run, prompt, worktree=None):
        created.append(("dispatched", run.run_id, worktree))

    def _run_worktree(argv, **kwargs):
        created.append(("git", tuple(argv)))
        if argv[1] == "rev-parse":
            # #509: the launcher resolves the branch's base before creating it.
            return SimpleNamespace(returncode=0, stdout="0" * 40)
        if not worktree_returncode:
            # a real `git worktree add` creates the directory; the launcher
            # verifies it before reporting isolation
            Path(argv[-2]).mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=worktree_returncode)

    app = WorkLauncher(
        dispatcher, gh,
        dispatch=_dispatch,
        worktree_root=tmp_path / "trees",
        run_worktree=_run_worktree,
        claim_store=store,
        issue_reader=lambda issue_id: _issue(issue_id),
        inventory_readers={name: (lambda: ()) for name in WorkLauncher.INVENTORY_NAMES},
        clock=lambda: 100.0,
        id_generator=iter(ids).__next__,
        store_session_id="s1", engine_session_id="e1",
        repo_path=tmp_path / "repo",
    )
    return app, dispatcher, created


def _resume(app, **kwargs):
    return app.resume(
        "acme/repo#1", runtime="hermes-free", worker_role="builder",
        workflow="work-launcher/v1", max_runtime_seconds=60, prompt="bounded",
        max_cost_usd=1.0, max_parallel_workers=1, delegation_depth=0,
        artifact_policy="policy", request_id="sha256:abc", **kwargs)


# --- finding 8: the launch result must not invent a branch -------------------

def test_resume_without_isolation_reports_no_branch_and_no_worktree(tmp_path):
    """The dogfood defect verbatim: resume() skipped worktree creation but still
    reported ``work/<run_id>``. A reviewer must be able to see that the change
    landed in the shared checkout, not in a branch that never existed."""
    app, _dispatcher, created = _launcher(tmp_path)
    result = _resume(app)

    assert result["branch"] is None
    assert result["worktree"] is None
    assert result["isolation"] == "shared-checkout"
    assert result["working_dir"] == str(tmp_path / "repo")
    assert not any(event[0] == "git" for event in created), "no worktree was created"


def test_resume_with_isolation_creates_and_reports_the_real_worktree(tmp_path):
    """Isolation is requestable through the same launch path; when it is asked
    for, the reported branch/worktree are the ones actually created."""
    app, _dispatcher, created = _launcher(tmp_path)
    result = _resume(app, isolate=True)

    assert result["isolation"] == "worktree"
    assert result["branch"] == "work/run-1"
    assert result["worktree"] == str(tmp_path / "trees" / "run-1")
    assert result["working_dir"] == result["worktree"]
    git_calls = [event[1] for event in created if event[0] == "git"]
    # #509: the base is resolved before the branch is created.
    assert git_calls and git_calls[0] == ("git", "rev-parse", "HEAD")
    assert git_calls[1][:4] == ("git", "worktree", "add", "-b")


def test_isolated_resume_failure_is_still_fail_closed(tmp_path):
    """A worktree that cannot be created must fail the launch, never silently
    downgrade to the shared checkout while the mandate demands isolation."""
    app, dispatcher, _created = _launcher(tmp_path, worktree_returncode=1)
    with pytest.raises(LauncherDispatchError) as exc:
        _resume(app, isolate=True)
    assert exc.value.code == "worktree_creation_failed"
    assert dispatcher.registry.get("run-1").status == "blocked"


def test_launch_isolation_is_recorded_on_the_durable_run(tmp_path):
    """The isolation mode belongs on the durable Run record, so the projection
    a reviewer reads is not reconstructed from the launch response."""
    app, dispatcher, _created = _launcher(tmp_path)
    _resume(app)
    assert dispatcher.registry.get("run-1").isolation == "shared-checkout"


# --- finding 2: sanctioned in-progress -> ready recovery ---------------------

def _reader(labels):
    return lambda issue_id: {"issue_id": issue_id,
                             "labels": [{"name": name} for name in labels]}


def test_return_to_ready_moves_a_stranded_in_progress_issue(tmp_path):
    calls = []

    def transition(operation, request):
        calls.append((operation, request["issue_id"]))
        return {"issue_id": request["issue_id"], "status": "ok"}

    result = return_to_ready_transition(
        "workflow.recover-to-ready.v1", {"issue_id": "acme/repo#1"},
        issue_reader=_reader(["workflow:in-progress"]), transition=transition)
    assert result["status"] == "ok"
    assert calls == [("workflow.recover-to-ready.v1", "acme/repo#1")]


@pytest.mark.parametrize("labels", [["workflow:ready"], ["workflow:review"],
                                    ["workflow:done"], [],
                                    ["workflow:in-progress", "workflow:review"]])
def test_return_to_ready_fails_closed_off_in_progress(labels):
    """Not a general label editor: only the exact in-progress state recovers."""
    def transition(operation, request):  # pragma: no cover - must never run
        raise AssertionError("transition must not be called")

    with pytest.raises(TransitionDenied):
        return_to_ready_transition(
            "workflow.recover-to-ready.v1", {"issue_id": "acme/repo#1"},
            issue_reader=_reader(labels), transition=transition)


def test_github_transition_adapter_routes_recovery_to_its_own_writer():
    """The recovery writer must never fall back to the inbox->ready writer."""
    seen = []
    adapter = github_transition_adapter(
        lambda issue_id: ["workflow:in-progress"],
        lambda issue_id: seen.append(("ready", issue_id)) or {"status": "ok"},
        review_transition_writer=lambda issue_id: seen.append(("done", issue_id)) or {"status": "ok"},
        recover_transition_writer=lambda issue_id: seen.append(("recover", issue_id)) or {"status": "ok"},
    )
    assert adapter("workflow.recover-to-ready.v1", {"issue_id": "acme/repo#1"})["status"] == "ok"
    assert seen == [("recover", "acme/repo#1")]


def test_github_transition_adapter_refuses_recovery_without_its_writer():
    adapter = github_transition_adapter(
        lambda issue_id: ["workflow:in-progress"],
        lambda issue_id: {"status": "ok"},
    )
    with pytest.raises(ValueError, match="recover_transition_writer"):
        adapter("workflow.recover-to-ready.v1", {"issue_id": "acme/repo#1"})


# --- action host wiring ------------------------------------------------------

def _host(**kwargs):
    from widget.action_host import ActionHost
    return ActionHost(**kwargs)


def test_action_host_exposes_the_recovery_action_as_a_capability():
    host = _host()
    ids = [action["id"] for action in host.capabilities()["actions"]]
    assert "recover-to-ready" in ids


def test_action_host_executes_recovery_through_the_authorized_port():
    seen = []
    host = _host(labels_reader=lambda issue_id: ["workflow:in-progress"],
                 recover_transition_writer=lambda issue_id: seen.append(issue_id) or {
                     "issue_id": issue_id, "status": "ok"})
    result = host.execute(action_id="recover-to-ready", issue_id="acme/repo#1",
                          approval_ref="operator-approval", confirm=True, token=host.token)
    assert result["operation"] == "workflow.recover-to-ready.v1"
    assert seen == ["acme/repo#1"]


def test_action_host_recovery_requires_explicit_confirmation():
    from widget.action_host import AuthorizationFailure
    host = _host(labels_reader=lambda issue_id: ["workflow:in-progress"],
                 recover_transition_writer=lambda issue_id: {"status": "ok"})
    with pytest.raises(AuthorizationFailure):
        host.execute(action_id="recover-to-ready", issue_id="acme/repo#1",
                     approval_ref="operator-approval", confirm=False, token=host.token)


# --- audit evidence allowlist points at the real registry --------------------

def test_audit_evidence_allowlist_matches_the_real_dispatch_registry():
    from widget.action_host import _KNOWN_AUDIT_EVIDENCE_PATHS
    assert "agent-platform/.dispatch/runs.json" in _KNOWN_AUDIT_EVIDENCE_PATHS
    assert "agent-platform/.dispatch/runs.claims.sqlite3" in _KNOWN_AUDIT_EVIDENCE_PATHS
    assert not any(path.startswith("scripts/runs") for path in _KNOWN_AUDIT_EVIDENCE_PATHS)


# --- Execution Inspector reads the authoritative run projection --------------

def _js(name):
    return (WIDGET / name).read_text(encoding="utf-8")


def test_execution_inspector_reads_api_runs_not_a_missing_workstream_field():
    js = _js("work-console.js")
    body = js[js.index("function runsEndpoint"):js.index("function renderAtlas")]
    assert "api/runs?issue=" in body, "Execution Inspector must read the run projection"
    assert "x.runs" not in body, "workstreams projection never carries a runs array"


def test_execution_inspector_renders_conflict_and_correlation_fields():
    js = _js("work-console.js")
    body = js[js.index("function runsEndpoint"):js.index("function renderAtlas")]
    for field in ("run_id", "sources", "conflict", "data-exec-run"):
        assert field in body, f"Execution Inspector must render {field}"


def test_work_surface_offers_an_authoritative_refresh():
    js = _js("work-console.js")
    assert "data-work-refresh" in js, "Work must offer a refresh of authoritative state"
    assert "function refreshAuthority" in js


def test_work_recovery_affordance_is_gated_on_the_registered_action():
    # S7d browser acceptance: the registered-action check now lives in
    # actAuthorized(), which requires a non-synthetic shell AND the registered
    # recover-to-ready capability before the executable affordance appears.
    # Synthetic mode reaches only the non-mutating recovery explanation via the
    # fixture's view:recovery grant (test_s7d_preview_navigation_authority.py).
    js = _js("work-console.js")
    assert 'actAuthorized(s, "recover-to-ready")' in js
    assert "function actAuthorized(s, actionId)" in js
    assert "!s.model.synthetic" in js
    assert 'a.id === actionId' in js
    assert 'x.workflow !== "in-progress"' in js
    assert 'nextActionKind(x) !== "recover"' in js
    assert "data-recover-ready" in js


def test_site_mirror_matches_the_widget_source():
    for name in ("work-console.js", "app-renderer-decisions-evidence.js",
                 "app-renderer-work-launch.js"):
        assert (REPO_ROOT / "site" / "public" / "widgets" / name).read_text(encoding="utf-8") \
            == _js(name), f"{name} mirror is out of date"
