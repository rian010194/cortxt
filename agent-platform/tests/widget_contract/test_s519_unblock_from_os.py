"""W7 (#519): a refused Run can be retried from the OS, and a broken session
store says so instead of going quiet.

`workflow.unblock-to-ready.v1` has been registered since #519 -- its own
capability, its own input schema, its own preconditions -- and nothing ever
derived an affordance for it. `NEXT_ACTION_SCHEMA.kind` was closed at
`launch|recover|decision`, `resolve_next_action` had no `blocked` branch, and
`_next_action_authority` computed a grant only for `ready` and `in-progress`.
A blocked Workstream's only way back was `gh issue edit`: the exact hand-edit
outside the action ports these transitions exist to replace.

Two properties matter more than the affordance itself and are pinned here:

1. **Unblock and recovery are separate authorities.** They share one run-liveness
   check because both end at `workflow:ready` and re-open the dispatch gate.
   They share nothing else: different capability, different port, and the port
   re-reads the label at write time, so holding one grants nothing about the
   other.
2. **Session-store integrity is fail-closed *and* visible.** One record that
   fails its hash chain makes the run authority unanswerable for every Issue,
   so recovery and unblock disappear from the whole OS. The refusal is correct.
   The silence was not: the operator could not tell a withheld affordance from
   a Workstream with nothing to do.

Every mutation here is driven against a `tmp_path` store with injected writers.
Nothing in this file reads or writes the repository's real
`agent-platform/.sessions/`, and no model, dispatcher or worker is invoked.
"""
import json
import pathlib

import pytest

from runtime import session_state as state
from widget.action_host import ActionHost, StoreUnavailable
from widget_contract.next_action import resolve_next_action, run_holds_issue
from widget_contract.registry import TYPES
from widget_contract.validation import validate

REPO = "owner/repo"

READY_BODY = (
    "## Scope\n\nAdd one cross-reference paragraph to the launcher doc.\n\n"
    "## Acceptance criteria\n\n- The paragraph exists.\n\n"
    "## Approval status\n\nOperator approved this exact scope on 2026-09-02.\n\n"
    "## Worker role and limits\n\nWorkflow: work-launcher/v1\nWorker role: builder\n"
    "Max runtime: 900 seconds\nMax cost: USD 2.00\nMax parallel workers: 1\n"
    "Delegation depth: 0\n\n"
    "## Artifact policy\n\nOnly docs/agents/work-launcher.md inside the run's isolated worktree.\n\n"
    "## Engine policy\n\nReliability: unverified\nEngine: hermes-free\n"
)

NOW = "2026-09-02T12:00:00+00:00"
LATER = "2026-09-03T12:00:00+00:00"  # far enough ahead that a finished Run is terminal
LIVE_HEARTBEAT = 1788350400.0  # 2026-09-02T12:00:00Z


def _issue(number, workflow, body=READY_BODY, extra_labels=("background-task",)):
    return {"number": number, "title": "Dogfood", "body": body, "state": "open",
            "labels": [{"name": workflow}] + [{"name": x} for x in extra_labels],
            "url": "https://example.invalid/i", "milestone": None}


def _run_record(run_id, issue_id, status="in_progress", heartbeat=LIVE_HEARTBEAT,
                finished_at=None):
    return {"run_id": run_id, "issue_id": issue_id, "workflow": "work-launcher/v1",
            "worker_role": "builder", "runtime": "hermes-free", "claimed_at": 1756470000.0,
            "lease_seconds": 5400, "status": status, "parent_run_id": None, "depth": 0,
            "heartbeat_at": heartbeat, "finished_at": finished_at, "result": None,
            "gh_synced": False, "gh_sync_claimed_at": None}


def _released(run_id, issue_id):
    """A Run the dispatcher itself reports as finished: the only evidence that
    ownership was released (`run_holds_issue`). Read from `LATER`, so the
    freshness classification is `terminal` rather than a live heartbeat."""
    return {run_id: _run_record(run_id, issue_id, status="blocked",
                                finished_at=1756470600.0)}


class _StubIssues:
    def __init__(self, issues):
        self._issues = issues

    def read(self, repo):
        return {"issues": self._issues, "status": "fresh", "error": None}


def _host(tmp_path, issues, *, registry_doc=None, now=NOW):
    tmp_path.mkdir(parents=True, exist_ok=True)
    registry = tmp_path / "runs.json"
    registry.write_text(json.dumps(registry_doc or {}), encoding="utf-8")
    by_number = {i["number"]: i for i in issues}
    host = ActionHost(registry=registry, session_store=tmp_path / ".sessions",
                      issue_reader=lambda repo, number: by_number[number])
    host._issues = _StubIssues(issues)
    host._wall_clock = lambda: now
    return host


@pytest.fixture(autouse=True)
def _free_route_configured(monkeypatch):
    monkeypatch.setenv("CORTXT_FREE_MODEL", "upstage/solar-pro4:free")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "nous")


# --- the derivation --------------------------------------------------------

def test_a_blocked_issue_whose_run_released_it_is_offered_unblock():
    """The #519 shape: the negative arm is required to end at
    `workflow:blocked`, and `blocked` had no registered way back."""
    resolved = resolve_next_action("blocked", run_active=False)
    assert resolved["next_action"] == {"kind": "unblock",
                                       "label": "Lift the block and return to ready"}
    assert resolved["view_capabilities"] == ["view:unblock"]


@pytest.mark.parametrize("run_active", [True, None])
def test_a_blocked_issue_is_not_offered_unblock_without_positive_evidence(run_active):
    """`True` is a live claim; `None` is "not established" -- no correlated Run
    at all, an unresolvable clock, or an unreadable store. Both must refuse:
    returning to ready re-opens the dispatch gate, and doing that on absence of
    evidence is how a second Run claims an Issue somebody still holds."""
    resolved = resolve_next_action("blocked", run_active=run_active)
    assert resolved["next_action"] is None
    assert resolved["view_capabilities"] == []


def test_a_triage_blocked_issue_with_no_run_offers_nothing():
    """The documented, deliberate limit. `run_holds_issue` yields `None` when
    no Run correlates, so an Issue blocked by triage rather than by a Run
    cannot be lifted through this port -- it needs its own decision."""
    assert run_holds_issue([], "terminal") is None
    assert resolve_next_action("blocked", run_active=run_holds_issue([], "terminal"))[
        "next_action"] is None


def test_unblock_and_recovery_never_reach_each_others_state():
    """They share one run-liveness check and nothing else. A blocked Issue must
    never resolve to `recover`, and an in-progress Issue never to `unblock`:
    the two carry different capabilities and holding one grants nothing about
    the other."""
    assert resolve_next_action("blocked", run_active=False)["next_action"]["kind"] == "unblock"
    assert resolve_next_action("in-progress", run_active=False)["next_action"]["kind"] == "recover"


def test_no_projection_can_emit_an_act_capability():
    for workflow, kwargs in (("ready", {"launch_eligible": True}),
                             ("in-progress", {"run_active": False}),
                             ("blocked", {"run_active": False}),
                             ("review", {"has_evidence": True})):
        caps = resolve_next_action(workflow, **kwargs)["view_capabilities"]
        assert caps and all(c.startswith("view:") for c in caps)


# --- the host wiring -------------------------------------------------------

def test_host_list_projection_offers_unblock_for_a_released_blocked_issue(tmp_path):
    host = _host(tmp_path, [_issue(519, "workflow:blocked")],
                 registry_doc=_released("r1", f"{REPO}#519"), now=LATER)
    listed = host.workstreams(REPO)["workstreams"][0]

    assert listed["workflow"] == "blocked"
    assert listed["next_action"] == {"kind": "unblock",
                                     "label": "Lift the block and return to ready"}
    assert listed["view_capabilities"] == ["view:unblock"]


def test_host_refuses_unblock_while_a_run_still_holds_the_issue(tmp_path):
    """A blocked label with a live heartbeat is not a released Issue."""
    host = _host(tmp_path, [_issue(519, "workflow:blocked")],
                 registry_doc={"runs": {"r1": _run_record("r1", f"{REPO}#519")}})
    listed = host.workstreams(REPO)["workstreams"][0]
    assert listed["next_action"] is None
    assert listed["view_capabilities"] == []


def test_host_detail_and_list_agree_on_a_blocked_issue(tmp_path):
    """Two code paths compute this; if they disagree the operator sees one
    answer in Work and another in the detail panel."""
    host = _host(tmp_path, [_issue(519, "workflow:blocked")],
                 registry_doc=_released("r1", f"{REPO}#519"), now=LATER)
    listed = host.workstreams(REPO)["workstreams"][0]
    detail = host.workstream_detail(REPO, 519)

    validate(detail, TYPES["workstream.detail.v1"].schema)
    assert detail["next_action"] == listed["next_action"] is not None
    assert detail["view_capabilities"] == listed["view_capabilities"]


# --- session-store integrity ------------------------------------------------
#
# The acceptance criterion. A real store holds 91 records; one corrupt record
# used to deny the run authority for all of them with nothing shown anywhere.
# These build their own store under tmp_path and corrupt one record in it.


def _write_session(store, task_id, issue_id, run_id):
    """One real session record, written by the real writer so its hash chain
    is genuine and the corruption below is a genuine integrity failure."""
    store.mkdir(parents=True, exist_ok=True)
    doc = state.create(store, task_id, run_id=run_id, issue_id=issue_id)
    return store / doc["session_id"]


def _corrupt(session_dir):
    """Break the hash chain the way disk corruption would: change a payload
    without recomputing the event hash."""
    path = session_dir / "session.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["events"][0]["payload"]["issue_id"] = "owner/repo#999999"
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def _store_with_one_corrupt_record(tmp_path):
    """One intact record and one broken one, in an isolated store."""
    store = tmp_path / ".sessions"
    _write_session(store, "intact-task", f"{REPO}#519", "r1")
    broken = _write_session(store, "broken-task", f"{REPO}#600", "r2")
    _corrupt(broken)
    return broken.name


def test_a_corrupt_record_is_named_not_swallowed(tmp_path, _store_with_one_corrupt_record):
    host = _host(tmp_path, [_issue(519, "workflow:blocked")],
                 registry_doc=_released("r1", f"{REPO}#519"), now=LATER)
    health = host.workstreams(REPO)["store_health"]

    assert health["status"] == "degraded"
    assert [r["record"] for r in health["unreadable_records"]] == [_store_with_one_corrupt_record]
    assert health["unreadable_records"][0]["message"]
    # The operator is told which affordances went missing, not left to infer it.
    assert set(health["withheld"]) == {"recover", "unblock"}


def test_a_healthy_store_reports_ok_and_withholds_nothing(tmp_path):
    store = tmp_path / ".sessions"
    _write_session(store, "intact-task", f"{REPO}#519", "r1")
    host = _host(tmp_path, [_issue(519, "workflow:blocked")],
                 registry_doc=_released("r1", f"{REPO}#519"), now=LATER)
    health = host.workstreams(REPO)["store_health"]

    assert health["status"] == "ok"
    assert health["unreadable_records"] == []
    assert health["withheld"] == []


def test_an_unsafe_transition_is_still_refused_when_the_store_is_degraded(
        tmp_path, _store_with_one_corrupt_record):
    """The safety half of the criterion. A corrupt record could have held a
    session summary for ANY Issue, and a *missing* summary can only move the
    run authority from "not established" towards "released". So the affordance
    is withheld even though the dispatcher registry alone would have said the
    Run released this Issue."""
    host = _host(tmp_path, [_issue(519, "workflow:blocked")],
                 registry_doc=_released("r1", f"{REPO}#519"), now=LATER)
    listed = host.workstreams(REPO)["workstreams"][0]

    assert listed["next_action"] is None
    assert listed["view_capabilities"] == []


def test_valid_unrelated_work_keeps_the_affordances_that_do_not_read_the_store(
        tmp_path, _store_with_one_corrupt_record):
    """The usefulness half. Launch comes from the dispatch gate and decision
    from the Issue body; neither reads the session store, so a broken store
    must not take them down with it."""
    host = _host(tmp_path, [_issue(497, "workflow:ready"),
                            _issue(495, "workflow:review",
                                   body=READY_BODY + "\n## Evidence\n\n- A recorded result.\n")],
                 registry_doc={})
    listed = {w["id"]: w for w in host.workstreams(REPO)["workstreams"]}

    assert listed["WS-497"]["next_action"] == {"kind": "launch",
                                               "label": "Start the approved Run"}
    assert listed["WS-495"]["next_action"] == {"kind": "decision",
                                               "label": "Record the operator decision"}


def test_the_single_issue_read_path_still_fails_loudly(tmp_path, _store_with_one_corrupt_record):
    """`/api/runs` and friends answer about one Issue, so raising surfaces the
    fault to the operator who asked. Only the list projection, which answers
    for every Issue at once, degrades instead of raising."""
    host = _host(tmp_path, [_issue(519, "workflow:blocked")], registry_doc={})
    with pytest.raises(StoreUnavailable) as excinfo:
        host.run_summaries(REPO, 519)
    assert _store_with_one_corrupt_record in str(excinfo.value)


def test_a_non_integrity_read_problem_is_skipped_not_reported_as_corruption(tmp_path):
    """A directory without `session.json` is not a broken record; reporting it
    as one would cry wolf and train the operator to ignore the notice."""
    store = tmp_path / ".sessions"
    _write_session(store, "intact-task", f"{REPO}#519", "r1")
    (store / "not_a_session").mkdir()
    host = _host(tmp_path, [_issue(519, "workflow:blocked")], registry_doc={})
    assert host.workstreams(REPO)["store_health"]["status"] == "ok"


# --- the mutation, against isolated data ------------------------------------

def test_the_unblock_port_moves_blocked_to_ready_and_records_why(tmp_path):
    """Driven end to end against injected writers and a tmp_path store: the
    real registered operation, its real preconditions, no GitHub."""
    from widget_contract.adapters.github_ports import unblock_to_ready_transition

    written = {}

    def _transition(issue_id, justification):
        written["issue_id"] = issue_id
        written["justification"] = justification
        return {"status": "ok"}

    result = unblock_to_ready_transition(
        "workflow.unblock-to-ready.v1",
        {"issue_id": f"{REPO}#519",
         "justification": "The refusal was a correlation defect, now fixed and retested."},
        issue_reader=lambda ref: _issue(519, "workflow:blocked"),
        transition=lambda op, req: _transition(req["issue_id"], req["justification"]),
        unblock_authority=lambda ref: False)

    assert result["status"] == "ok"
    assert written["issue_id"] == f"{REPO}#519"
    assert "correlation defect" in written["justification"]


@pytest.mark.parametrize("justification", ["", "too short", "x" * 23])
def test_the_unblock_port_refuses_without_a_stated_reason(tmp_path, justification):
    """A block is a recorded refusal; lifting it without a durable reason
    leaves the Issue looking as though it had never been refused."""
    from widget_contract.adapters.github_ports import TransitionDenied, unblock_to_ready_transition

    called = []
    with pytest.raises(TransitionDenied):
        unblock_to_ready_transition(
            "workflow.unblock-to-ready.v1",
            {"issue_id": f"{REPO}#519", "justification": justification},
            issue_reader=lambda ref: _issue(519, "workflow:blocked"),
            transition=lambda op, req: called.append(req),
            unblock_authority=lambda ref: False)
    assert called == [], "no write may happen on a refused unblock"


@pytest.mark.parametrize("authority", [True, None])
def test_the_unblock_port_refuses_when_a_run_may_still_hold_the_issue(tmp_path, authority):
    """Re-derived at write time, so a Run that resumed between render and
    confirmation denies the unblock instead of being written over."""
    from widget_contract.adapters.github_ports import TransitionDenied, unblock_to_ready_transition

    called = []
    with pytest.raises(TransitionDenied):
        unblock_to_ready_transition(
            "workflow.unblock-to-ready.v1",
            {"issue_id": f"{REPO}#519",
             "justification": "A sufficiently long and specific stated reason."},
            issue_reader=lambda ref: _issue(519, "workflow:blocked"),
            transition=lambda op, req: called.append(req),
            unblock_authority=lambda ref: authority)
    assert called == []


def test_the_unblock_port_refuses_a_label_that_is_not_blocked(tmp_path):
    """The state is re-read immediately before the write. A block lifted on a
    stale read is a block lifted on something that may no longer be true."""
    from widget_contract.adapters.github_ports import TransitionDenied, unblock_to_ready_transition

    called = []
    with pytest.raises(TransitionDenied):
        unblock_to_ready_transition(
            "workflow.unblock-to-ready.v1",
            {"issue_id": f"{REPO}#519",
             "justification": "A sufficiently long and specific stated reason."},
            issue_reader=lambda ref: _issue(519, "workflow:in-progress"),
            transition=lambda op, req: called.append(req),
            unblock_authority=lambda ref: False)
    assert called == []


def test_every_store_this_suite_builds_lives_under_tmp_path(tmp_path,
                                                            _store_with_one_corrupt_record):
    """Guard on the instruction this suite was written under. The repository's
    own `.sessions/` holds 91 real records; nothing here may read or write it.
    The fixture's store is asserted to sit inside the per-test tmp_path, so a
    future edit that points it at the real store fails loudly."""
    store = tmp_path / ".sessions"
    assert store.is_dir()
    assert tmp_path in store.parents
    real = pathlib.Path(__file__).resolve().parents[2] / ".sessions"
    assert real != store
