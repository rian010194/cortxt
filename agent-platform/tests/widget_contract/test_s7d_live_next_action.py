"""#498: the typed ``next_action`` must come from the live projections.

The S7d split between preview-navigation authority and mutation authority was
only ever implemented on the fixture side, so on a live host
``build_workstream_detail_v1`` and ``build_workstream_projection`` emitted no
``next_action`` at all and ``launchAvailable()``/``recoveryAvailable()`` in
``work-console.js`` could never be true. An approved, eligible Workstream
rendered "No next action pending" and offered no control.

These tests drive the **production builders**, never the fixtures, and assert
the derivation is bound to the same authorities the mutation gates use.
"""
import pytest

from widget_contract.detail import build_workstream_detail_v1
from widget_contract.next_action import has_active_run, resolve_next_action
from widget_contract.registry import TYPES
from widget_contract.validation import validate
from widget_contract.workstreams import build_workstream_projection

REPO = "rian010194/cortxt"
WS497 = REPO + "#497"

APPROVED_BODY = (
    "## Scope\n\nAdd one cross-reference paragraph.\n\n"
    "## Acceptance criteria\n\n- The paragraph exists.\n\n"
    "## Approval status\n\nOperator approved this exact scope on 2026-09-02.\n\n"
    "## Evidence\n\nRecorded.\n"
)


def _issue(number=497, workflow="workflow:ready", body=APPROVED_BODY, title="Dogfood"):
    return {"number": number, "title": title, "body": body, "state": "open",
            "labels": [{"name": workflow}], "url": "https://example.invalid/i",
            "milestone": None}


def _detail(issue, runs=(), **kwargs):
    return build_workstream_detail_v1(issue, list(runs), repo=REPO, **kwargs)


def _listed(issues, authority=None):
    projection = build_workstream_projection(REPO, issues, authority=authority)
    return {w["issue_id"]: w for w in projection["workstreams"]}


# --- the defect itself ----------------------------------------------------

def test_live_detail_emits_launch_for_an_eligible_ready_workstream():
    """The exact WS-497 case from the defect report: authoritatively ready,
    approved and eligible, and the projection now says so."""
    detail = _detail(_issue(), launch_eligible=True)
    assert detail["next_action"] == {"kind": "launch",
                                     "label": "Start the approved Run"}
    assert detail["view_capabilities"] == ["view:launch"]


def test_live_list_projection_emits_launch_because_work_reads_the_list():
    """work-console.js derives its primary affordance from
    state.model.workstreams -- the list, not the detail -- so the list must
    carry the field or the control still never appears."""
    listed = _listed([_issue()], authority={WS497: {"launch_eligible": True}})
    assert listed[WS497]["next_action"]["kind"] == "launch"
    assert listed[WS497]["view_capabilities"] == ["view:launch"]


def test_detail_and_list_agree_for_the_same_issue_and_authority():
    """The two projections must never disagree about what may be done next."""
    issue = _issue()
    detail = _detail(issue, launch_eligible=True)
    listed = _listed([issue], authority={WS497: {"launch_eligible": True}})
    assert detail["next_action"] == listed[WS497]["next_action"]
    assert detail["view_capabilities"] == listed[WS497]["view_capabilities"]


# --- fail closed ----------------------------------------------------------

def test_an_ineligible_ready_workstream_is_never_offered_launch():
    """The read projection must fail closed exactly as dispatch_request does:
    ready is not enough, the dispatch gate has to agree."""
    detail = _detail(_issue(), launch_eligible=False)
    assert detail["next_action"] is None
    assert detail["view_capabilities"] == []


def test_absent_authority_is_not_permission():
    """A caller that could not compute eligibility (a failed read, a routing
    error) must yield no next action rather than a default."""
    detail = _detail(_issue())
    assert detail["next_action"] is None
    listed = _listed([_issue()])
    assert listed[WS497]["next_action"] is None


@pytest.mark.parametrize("workflow", ["workflow:inbox", "workflow:blocked", "workflow:done"])
def test_no_other_workflow_state_yields_a_launch(workflow):
    detail = _detail(_issue(workflow=workflow), launch_eligible=True)
    assert (detail["next_action"] or {}).get("kind") != "launch"


def test_an_unknown_workflow_state_yields_nothing():
    """Two workflow labels is `unknown` (ADR-018 one-label discipline)."""
    issue = _issue()
    issue["labels"] = [{"name": "workflow:ready"}, {"name": "workflow:in-progress"}]
    detail = _detail(issue, launch_eligible=True, run_active=False)
    assert detail["next_action"] is None


# --- recovery: the label alone is not authority ---------------------------

def test_stranded_in_progress_workstream_is_offered_recovery():
    detail = _detail(_issue(workflow="workflow:in-progress"), run_active=False)
    assert detail["next_action"]["kind"] == "recover"
    assert detail["view_capabilities"] == ["view:recovery"]


def test_in_progress_with_a_live_run_is_not_offered_recovery():
    """Recovery re-opens the dispatch gate. Offering it under a running claim
    would undercut a worker that still holds the Issue."""
    detail = _detail(_issue(workflow="workflow:in-progress"), run_active=True)
    assert detail["next_action"] is None
    assert detail["view_capabilities"] == []


def test_in_progress_without_a_run_answer_is_not_offered_recovery():
    """workflow:in-progress alone is not sufficient authority."""
    detail = _detail(_issue(workflow="workflow:in-progress"))
    assert detail["next_action"] is None


def test_has_active_run_treats_a_stranded_claim_as_not_holding_the_issue():
    """A claim past the stranded bound is exactly what recovery exists to
    rescue, so it must not block its own remedy."""
    runs = [{"status": "in_progress"}]
    assert has_active_run(runs, "fresh") is True
    assert has_active_run(runs, "stale") is True
    assert has_active_run(runs, "stranded_running") is False
    assert has_active_run([], "fresh") is False
    assert has_active_run([{"status": "succeeded"}], "terminal") is False


# --- decision -------------------------------------------------------------

def test_review_with_evidence_yields_a_decision_and_never_a_launch():
    detail = _detail(_issue(workflow="workflow:review"))
    assert detail["next_action"]["kind"] == "decision"
    assert detail["view_capabilities"] == ["view:decision"]
    assert "view:launch" not in detail["view_capabilities"]


def test_review_without_evidence_yields_no_decision():
    body = APPROVED_BODY.replace("## Evidence\n\nRecorded.\n", "")
    detail = _detail(_issue(workflow="workflow:review", body=body))
    assert detail["next_action"] is None


# --- the mutation boundary is untouched -----------------------------------

def test_view_capabilities_can_never_express_a_mutation_grant():
    for workflow, kwargs in (("workflow:ready", {"launch_eligible": True}),
                             ("workflow:in-progress", {"run_active": False}),
                             ("workflow:review", {})):
        detail = _detail(_issue(workflow=workflow), **kwargs)
        for capability in detail["view_capabilities"]:
            assert capability.startswith("view:")
            assert not capability.startswith("act:")


def test_resolve_next_action_emits_no_capability_outside_the_view_namespace():
    for state in ("ready", "in-progress", "review", "inbox", "blocked", "done", "", None):
        result = resolve_next_action(state, launch_eligible=True, run_active=False,
                                     has_evidence=True)
        assert all(c.startswith("view:") for c in result["view_capabilities"])


# --- schema ---------------------------------------------------------------

def test_the_detail_projection_still_validates_against_its_versioned_schema():
    for workflow, kwargs in (("workflow:ready", {"launch_eligible": True}),
                             ("workflow:in-progress", {"run_active": False}),
                             ("workflow:review", {}),
                             ("workflow:inbox", {})):
        validate(_detail(_issue(workflow=workflow), **kwargs),
                 TYPES["workstream.detail.v1"].schema)


def test_the_schema_rejects_an_unknown_next_action_kind():
    detail = _detail(_issue(), launch_eligible=True)
    detail["next_action"] = {"kind": "merge", "label": "Merge it"}
    with pytest.raises(Exception):
        validate(detail, TYPES["workstream.detail.v1"].schema)


def test_the_schema_rejects_a_mutation_capability():
    detail = _detail(_issue(), launch_eligible=True)
    detail["view_capabilities"] = ["act:claim-run"]
    with pytest.raises(Exception):
        validate(detail, TYPES["workstream.detail.v1"].schema)
