"""S7b (#482): end-to-end regression through action host -> dispatch request
-> WorkLauncher -> the actual adapter registry.

Proves the authoritative-dispatchability reconciliation:
- an eligible engine is actually dispatchable through the REAL
  scripts.worker_adapters.ADAPTER_REGISTRY (dispatch_async + the registered
  hermes-free adapter);
- a registry mismatch fails before any GitHub/Run claim where possible;
- any post-claim start failure becomes terminal and releases the claim;
- a second click/replay creates no duplicate Run.
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from dispatcher import Dispatcher, RunRegistry  # noqa: E402
from execution_map import SqliteClaimStore  # noqa: E402
from routing.engine_manifest import EngineManifest  # noqa: E402
from work_launcher import LauncherDispatchError, WorkLauncher  # noqa: E402
from worker_adapters import ADAPTER_REGISTRY, HermesFreeAdapter, UnknownRuntimeError  # noqa: E402
from widget_contract.adapters.cli_ports import DispatchNotEligible, gh_claim_run_resume  # noqa: E402

APPROVAL = (
    "Operator approved this exact scope, route, and limits on 2026-08-30. "
    "Implementation start is approved for the worker in the isolated worktree."
)

# A dispatch-eligible issue fixture shaped like the proof issue #482.
def _eligible_issue(number=482):
    return {
        "number": number,
        "title": "Proof: S7b local Review-and-start-Run through gated launcher",
        "body": (
            "## Scope\n\nProve the gated launcher end to end.\n\n"
            "## Deterministic acceptance criteria\n\n"
            "1. The dispatch request is eligible.\n"
            "2. Exactly one durable run and claim.\n\n"
            "## Approval status\n\n" + APPROVAL + "\n\n"
            "## Worker role and limits\n\n"
            "- Workflow: work-launcher/v1\n"
            "- Worker role: researcher.\n"
            "- Max runtime: 600 seconds.\n"
            "- Max cost: USD 0.20 hard ceiling.\n"
            "- Max parallel workers: 1.\n"
            "- Delegation depth: 0.\n\n"
            "## Artifact policy\n\nContent-free result envelope only.\n\n"
            "## Engine policy\n\nReliability: unverified\nEngine: hermes-free\n"
        ),
        "state": "open",
        "labels": [{"name": "workflow:ready"}, {"name": "background-task"}],
        "url": f"https://github.com/owner/repo/issues/{number}",
        "milestone": None,
    }


class FakeGitHub:
    def __init__(self, labels=None):
        self.labels = dict(labels or {})
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


def _issue(issue_id="owner/repo#482"):
    return {"issue_id": issue_id, "body": "", "state": "open",
            "labels": ("workflow:ready",), "area": "dispatch", "milestone": "m1"}


def _real_launcher(tmp_path, *, dispatch=None, issue_id="owner/repo#482"):
    """WorkLauncher with the REAL Dispatcher/RunRegistry/claim store; dispatch
    defaults to the REAL dispatch_async (adapter registry lookup at runtime)."""
    store = SqliteClaimStore(tmp_path / "claims.sqlite3")
    gh = FakeGitHub({issue_id: ["workflow:ready"]})
    registry = RunRegistry(tmp_path / "runs.json")
    dispatcher = Dispatcher(registry, gh)
    kwargs = {} if dispatch is None else {"dispatch": dispatch}

    def _run_worktree(argv, **_kwargs):
        # S7d: the UI launch path now isolates by default, and the launcher
        # verifies the directory exists before reporting that isolation, so a
        # stand-in for `git worktree add` has to create it like the real one.
        Path(argv[-2]).mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=0)

    app = WorkLauncher(
        dispatcher, gh,
        worktree_root=tmp_path / "trees",
        run_worktree=_run_worktree,
        claim_store=store,
        issue_reader=lambda issue_id: _issue(issue_id),
        inventory_readers={name: (lambda: ()) for name in WorkLauncher.INVENTORY_NAMES},
        clock=lambda: 100.0,
        id_generator=iter(("run-1", "run-2")).__next__,
        store_session_id="s1", engine_session_id="e1",
        **kwargs,
    )
    return app, store, dispatcher, gh


def _confirm_id(issue_reader, number=482):
    """Derive the request_id digest exactly as the confirmation view would."""
    from routing.engine_manifest import DEFAULT_FALLBACK_ENGINE, DEFAULT_MANIFESTS
    from widget_contract.adapters.store_reads import read_dispatch_request_v1
    from widget_contract.dispatch_request import route_for_issue

    issue = issue_reader("owner/repo", number)
    choice, tags = route_for_issue(issue, DEFAULT_MANIFESTS, fallback=DEFAULT_FALLBACK_ENGINE)
    request = read_dispatch_request_v1(issue, choice, repo="owner/repo",
                                       engine_registered=True, routable_tags=tags)
    assert request["eligible"] is True, request["missing"]
    return request["request_id"], request["approval_reference"]


def _wait_terminal(dispatcher, run_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = dispatcher.registry.get(run_id)
        if run is not None and run.status != "in_progress":
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach a terminal status")


def test_eligible_engine_is_actually_dispatchable_through_real_registry(tmp_path, monkeypatch):
    """The dogfood fix: eligibility (hermes-free dispatchable) and the real
    launcher dispatch agree, and a confirmed launch completes end-to-end
    through dispatch_async -> the registered hermes-free adapter."""
    # Inject the shared invoker result into the REAL registry entry.
    monkeypatch.setitem(ADAPTER_REGISTRY, "hermes-free", HermesFreeAdapter(
        invoke_hermes=lambda profile, prompt, timeout_seconds, model=None, provider=None, cwd=None, session_id=None: {
            "status": "succeeded", "stdout": "proof result", "stderr": "",
            "elapsed_seconds": 0.1, "session_id": None,
        },
        log_dir=tmp_path / "logs",
    ))
    app, store, dispatcher, gh = _real_launcher(tmp_path)

    def issue_reader(repo, number):
        # Stateful: reflects the real GitHub label movement (ready ->
        # in-progress -> review) as the dispatcher swaps labels, so a re-read
        # after launch sees the issue left workflow:ready.
        issue = _eligible_issue(number)
        gh_labels = gh.labels.get(f"{repo}#{number}", ["workflow:ready"])
        issue["labels"] = [{"name": x} for x in gh_labels] + [{"name": "background-task"}]
        return issue

    request_id, approval = _confirm_id(issue_reader)

    import os
    old_model, old_provider = os.environ.get("CORTXT_FREE_MODEL"), os.environ.get("CORTXT_FREE_PROVIDER")
    os.environ["CORTXT_FREE_MODEL"] = "test-free-model"
    os.environ["CORTXT_FREE_PROVIDER"] = "test-free-provider"
    try:
        result = gh_claim_run_resume(
            "owner/repo#482", registry=tmp_path / "unused.json", scripts_dir=SCRIPTS_DIR,
            issue_reader=issue_reader, launcher=app, approval_ref=approval,
            request_id=request_id)
    finally:
        if old_model is None:
            os.environ.pop("CORTXT_FREE_MODEL", None)
        else:
            os.environ["CORTXT_FREE_MODEL"] = old_model
        if old_provider is None:
            os.environ.pop("CORTXT_FREE_PROVIDER", None)
        else:
            os.environ["CORTXT_FREE_PROVIDER"] = old_provider
    run_id = result["run_id"]
    assert run_id == "run-1"
    run = _wait_terminal(dispatcher, run_id)
    # Routing still agrees end-to-end: the run reached the registered
    # hermes-free adapter and came back terminal through dispatch_async.
    # What it does NOT do any more is pass as success. This worker reports
    # "succeeded" with no commit -- exactly the #485 shape -- and the
    # Evidence Gate (#490) converts that claim into a structured block,
    # because the mandate carries an artifact policy and the run is therefore
    # mutating. Before #490 this assertion read `succeeded` on a run that had
    # landed nothing.
    assert run.status == "blocked"
    assert run.result["evidence_gate"] == "commit_correlation_failed"
    assert run.result["error"]["category"] == "commit_missing"
    assert run.commit_evidence is None
    # And the issue goes to blocked, not review: a failing terminal status is
    # still the dispatcher's to sync, while `workflow:review` is review-sync's
    # alone and needs a durable review submission this run never earned (#493).
    assert gh.labels["owner/repo#482"] == ["workflow:blocked"]
    assert run.review_submission_id is None
    # Terminal claim release (S7b dogfood fix): dispatch_async's background
    # thread completes the run directly through Dispatcher.complete(),
    # bypassing WorkLauncher.submit(); the launcher's on_terminal hook must
    # still release the execution-map claim once the run goes terminal, so
    # no claim is left held for a Run that already succeeded.
    assert result["claim_id"] not in {c.claim_id for c in store.active_claims(100.0)}

    # Second click / replay: the issue left workflow:ready, so the re-read at
    # confirmation rejects the same POST body without a second launch.
    with pytest.raises(DispatchNotEligible) as exc:
        gh_claim_run_resume(
            "owner/repo#482", registry=tmp_path / "unused.json", scripts_dir=SCRIPTS_DIR,
            issue_reader=issue_reader, launcher=app, approval_ref=approval,
            request_id=request_id)
    assert "workflow_ready" in exc.value.missing
    assert dispatcher.registry.get("run-2") is None  # no duplicate Run


def test_registry_mismatch_fails_before_claim(tmp_path):
    """A manifest-approved engine with NO launcher adapter (claude-direct, the
    #474 prerequisite) fails eligibility through the authoritative registry --
    before any GitHub label change or Run claim."""
    manifests = (EngineManifest(engine_id="claude-direct", task_shapes=("general",),
                                cost_class="metered", reliability_class="verified"),)
    issue = _eligible_issue()
    issue["labels"] = [{"name": "workflow:ready"}, {"name": "general"}]
    issue["body"] = issue["body"].replace(
        "## Engine policy\n\nReliability: unverified\nEngine: hermes-free\n",
        "## Engine policy\n\nReliability: verified\nEngine: claude-direct\n")

    calls = []
    fake_launcher = SimpleNamespace(resume=lambda issue_id, **kw: calls.append(issue_id) or {"run_id": "x"})
    with pytest.raises(DispatchNotEligible) as exc:
        gh_claim_run_resume(
            "owner/repo#482", registry=tmp_path / "unused.json", scripts_dir=SCRIPTS_DIR,
            issue_reader=lambda repo, number: issue, manifests=manifests,
            launcher=fake_launcher)
    assert "engine_registered" in exc.value.missing
    assert calls == []  # no claim attempted -- the mismatch failed before launch


def test_chain_post_claim_failure_is_terminal_and_releases_claim(tmp_path, monkeypatch):
    """Through the full chain (action host -> dispatch request -> launcher), a
    post-claim start failure marks the Run terminal and releases the claim --
    never leaving in_progress without a worker."""
    def boom(dispatcher, run, prompt, worktree=None):
        raise UnknownRuntimeError(f"no adapter registered for runtime={run.runtime!r}")

    # hermes-free must pass the same pre-claim runtime_launch_config_ok gate
    # eligibility now consults (S7b #482 follow-on) so this test still
    # exercises the *post-claim* failure path (boom raised by dispatch),
    # not the pre-claim config gate.
    monkeypatch.setenv("CORTXT_FREE_MODEL", "test-free-model")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "test-free-provider")

    app, store, dispatcher, gh = _real_launcher(tmp_path, dispatch=boom)
    issue_reader = lambda repo, number: _eligible_issue(number)
    request_id, approval = _confirm_id(issue_reader)

    with pytest.raises(LauncherDispatchError) as exc:
        gh_claim_run_resume(
            "owner/repo#482", registry=tmp_path / "unused.json", scripts_dir=SCRIPTS_DIR,
            issue_reader=issue_reader, launcher=app, approval_ref=approval,
            request_id=request_id)
    assert exc.value.code == "adapter_not_registered"
    run = dispatcher.registry.get("run-1")
    assert run.status == "blocked"
    assert run.result["error"]["category"] == "adapter_start_failed"
    assert store.active_claims(100.0) == ()
    assert gh.labels["owner/repo#482"] == ["workflow:blocked"]
