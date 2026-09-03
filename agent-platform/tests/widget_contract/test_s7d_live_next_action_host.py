"""#498: the action host itself must produce the typed next action.

`test_s7d_live_next_action.py` pins the pure derivation. These tests drive the
real `ActionHost` wiring -- the same `workstreams()` and `workstream_detail()`
methods `/api/workstreams` and `/api/workstream-detail` call -- so the chain
from the server's own authorities to the field the browser reads is covered end
to end, with no fixture involved.

The defect these close: `launchAvailable()` (`widget/work-console.js:855`) and
`recoveryAvailable()` (`:866`) both gate on `next_action.kind`, and Work reads
its Workstreams from the *list* projection. With the host emitting no such
field, both controls were unreachable on a live host regardless of how
authoritative the underlying mandate was.
"""
import json

import pytest

from widget.action_host import ActionHost
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


def _issue(number, workflow, body=READY_BODY, extra_labels=("background-task",)):
    """`background-task` is the routable task shape `hermes-free` declares in
    the engine manifest -- without a routable label nothing routes and the
    dispatch gate is ineligible for reasons unrelated to what is under test."""
    return {"number": number, "title": "Dogfood", "body": body, "state": "open",
            "labels": [{"name": workflow}] + [{"name": x} for x in extra_labels],
            "url": "https://example.invalid/i", "milestone": None}


@pytest.fixture(autouse=True)
def _free_route_configured(monkeypatch):
    """`runtime_launch_config_ok("hermes-free")` -- the same check the launcher
    consults -- requires these non-secret routing variables. They carry no
    credential; without them the engine is correctly reported unregistered."""
    monkeypatch.setenv("CORTXT_FREE_MODEL", "upstage/solar-pro4:free")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "nous")


LIVE_HEARTBEAT = 1788350400.0  # 2026-09-02T12:00:00Z


def _run_record(run_id, issue_id, status="in_progress", heartbeat=LIVE_HEARTBEAT,
                finished_at=None):
    return {"run_id": run_id, "issue_id": issue_id, "workflow": "work-launcher/v1",
            "worker_role": "builder", "runtime": "hermes-free", "claimed_at": 1756470000.0,
            "lease_seconds": 5400, "status": status, "parent_run_id": None, "depth": 0,
            "heartbeat_at": heartbeat, "finished_at": finished_at, "result": None,
            "gh_synced": False, "gh_sync_claimed_at": None}


def _host(tmp_path, issues, *, registry_doc=None, now="2026-09-02T12:00:00+00:00"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    registry = tmp_path / "runs.json"
    registry.write_text(json.dumps(registry_doc or {}), encoding="utf-8")
    by_number = {i["number"]: i for i in issues}
    host = ActionHost(registry=registry, session_store=tmp_path / ".sessions",
                      issue_reader=lambda repo, number: by_number[number])
    host._issues = _StubIssues(issues)
    host._wall_clock = lambda: now
    return host


class _StubIssues:
    """Stands in for `LastGoodIssues`, which shells out to `gh issue list`."""

    def __init__(self, issues):
        self._issues = issues

    def read(self, repo):
        return {"issues": self._issues, "status": "fresh", "error": None}


# --- launch ---------------------------------------------------------------

def test_host_list_projection_offers_launch_for_an_eligible_ready_issue(tmp_path):
    """The WS-497 shape: a complete, approved, routable mandate at
    workflow:ready. Before #498 this produced `next_action: null` and Work
    rendered "No next action pending"."""
    host = _host(tmp_path, [_issue(497, "workflow:ready")])
    listed = host.workstreams(REPO)["workstreams"][0]

    assert listed["workflow"] == "ready"
    assert listed["next_action"] == {"kind": "launch", "label": "Start the approved Run"}
    assert listed["view_capabilities"] == ["view:launch"]


def test_host_detail_and_list_agree_on_the_same_issue(tmp_path):
    host = _host(tmp_path, [_issue(497, "workflow:ready")])
    listed = host.workstreams(REPO)["workstreams"][0]
    detail = host.workstream_detail(REPO, 497)

    validate(detail, TYPES["workstream.detail.v1"].schema)
    assert detail["next_action"] == listed["next_action"]
    assert detail["view_capabilities"] == listed["view_capabilities"]


def test_host_derives_launch_from_the_dispatch_gate_not_from_the_label(tmp_path):
    """An incomplete mandate is `workflow:ready` and still not launchable: the
    projection must fail closed exactly where `build_dispatch_request_v1` does,
    so the browser can never offer what the claim gate would refuse."""
    incomplete = _issue(497, "workflow:ready", body="## Scope\n\nDo something vague.\n")
    host = _host(tmp_path, [incomplete])
    listed = host.workstreams(REPO)["workstreams"][0]

    assert listed["workflow"] == "ready"
    assert listed["next_action"] is None
    assert listed["view_capabilities"] == []
    # ... and the gate names why, so the projection and the gate agree.
    assert host.dispatch_request(REPO, 497)["eligible"] is False


# --- recovery -------------------------------------------------------------

def test_host_offers_recovery_only_when_the_dispatcher_released_the_claim(tmp_path):
    """An Issue whose Run the dispatcher recorded as finished is recoverable;
    the same Issue under a live claim is not. `workflow:in-progress` alone is
    never the authority, and neither is a heartbeat that stopped (#507)."""
    issue = _issue(473, "workflow:in-progress")
    released = {"r1": _run_record("r1", f"{REPO}#473", status="failed",
                                  finished_at=1756470600.0)}

    recoverable = _host(tmp_path / "a", [issue], registry_doc=released,
                        now="2026-09-03T12:00:00+00:00")
    assert recoverable.workstreams(REPO)["workstreams"][0]["next_action"]["kind"] == "recover"

    live = _host(tmp_path / "b", [issue],
                 registry_doc={"r1": _run_record("r1", f"{REPO}#473")},
                 now="2026-09-02T12:00:30+00:00")
    listed = live.workstreams(REPO)["workstreams"][0]
    assert listed["next_action"] is None
    assert listed["view_capabilities"] == []


def test_host_never_offers_recovery_for_an_issue_with_no_run_at_all(tmp_path):
    """The epic and manual-work shape, and the regression this test file
    previously encoded as intended behavior: an empty Run registry made every
    `workflow:in-progress` Issue look stranded. Recovery re-opens the dispatch
    gate, so on absence of evidence it must not be offered -- otherwise a
    worker can claim an Issue a human is actively working in."""
    host = _host(tmp_path, [_issue(473, "workflow:in-progress")])
    listed = host.workstreams(REPO)["workstreams"][0]

    assert listed["workflow"] == "in-progress"
    assert listed["next_action"] is None
    assert listed["view_capabilities"] == []
    assert host.workstream_detail(REPO, 473)["next_action"] is None


def test_host_does_not_offer_recovery_for_a_claim_the_dispatcher_still_holds(tmp_path):
    """A claim past the stranded bound is NOT a released claim (#507).

    The Run's heartbeat is 24h stale, well past the 900s stranded bound, but
    the dispatcher still records it `in_progress` and its 5400s lease is its
    own to expire. A stale heartbeat says only that nothing wrote a signal.
    Offering recovery here would re-open the dispatch gate under a claim the
    write side still considers valid, so the projection withholds it and waits
    for the dispatcher to release or time the claim out.
    """
    host = _host(tmp_path, [_issue(473, "workflow:in-progress")],
                 registry_doc={"r1": _run_record("r1", f"{REPO}#473")},
                 now="2026-09-03T12:00:00+00:00")
    listed = host.workstreams(REPO)["workstreams"][0]
    assert listed["next_action"] is None
    assert listed["view_capabilities"] == []


def test_host_never_offers_recovery_on_unresolved_provenance(tmp_path):
    """A status the projection cannot recognise is not evidence of anything
    (#507).

    `unknown` (and `conflict`, two stores disagreeing) used to sit in
    ACTIVE_RUN_STATUSES and so aged into `stranded_running`, which yielded
    recovery: the most uncertain state produced the most permissive answer.
    It is now `indeterminate`, and no recovery is derived from it.
    """
    host = _host(tmp_path, [_issue(473, "workflow:in-progress")],
                 registry_doc={"r1": _run_record("r1", f"{REPO}#473",
                                                 status="not-a-known-status")},
                 now="2026-09-03T12:00:00+00:00")
    listed = host.workstreams(REPO)["workstreams"][0]
    assert listed["next_action"] is None
    assert listed["view_capabilities"] == []


# --- the mutation boundary ------------------------------------------------

def test_host_never_emits_a_mutation_capability(tmp_path):
    host = _host(tmp_path, [_issue(497, "workflow:ready"),
                            _issue(473, "workflow:in-progress")])
    blob = json.dumps(host.workstreams(REPO))
    assert "act:" not in blob
    for ws in host.workstreams(REPO)["workstreams"]:
        for capability in ws["view_capabilities"]:
            assert capability.startswith("view:")


def test_an_unroutable_issue_loses_only_its_own_next_action(tmp_path):
    """Per-issue fail-closed: an Issue the gate cannot approve loses its own
    next action and nothing else in the list is affected."""
    unroutable = _issue(999, "workflow:ready", extra_labels=())
    host = _host(tmp_path, [_issue(497, "workflow:ready"), unroutable])
    listed = {w["number"]: w for w in host.workstreams(REPO)["workstreams"]}
    assert listed[497]["next_action"]["kind"] == "launch"
    assert listed[999]["next_action"] is None


def test_an_unreadable_run_registry_never_grants_recovery(tmp_path):
    """If the run stores cannot be read, the host has no authority to say the
    Issue is stranded -- absence of an answer is not permission."""
    registry = tmp_path / "runs.json"
    registry.write_text("{ not json", encoding="utf-8")
    by_number = {473: _issue(473, "workflow:in-progress")}
    host = ActionHost(registry=registry, session_store=tmp_path / ".sessions",
                      issue_reader=lambda repo, number: by_number[number])
    host._issues = _StubIssues(list(by_number.values()))

    listed = host.workstreams(REPO)["workstreams"][0]
    assert listed["next_action"] is None
    assert listed["view_capabilities"] == []
