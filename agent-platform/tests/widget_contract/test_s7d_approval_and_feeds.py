"""S7d (#473): one approval authority, and run feeds that read every store.

Covers the remaining #472 dogfood findings that block an honest decision view:

- finding 3: two readers disagreed about recorded approval. The dispatch
  request read ``## Approval status`` (plus a later operator retry
  authorization comment) and reported eligible; the Workstream projection read
  only ``## Approval`` / ``## Human approval`` / ``## Operator approval`` and
  reported ``approval_recorded: false`` for the same issue. Approval had no
  single durable home.
- finding 5: ``run.activity.v1`` and ``run.review.v1`` returned empty for every
  real Run, because both read only the MCP/session-event store while the
  launcher path writes to the dispatcher registry. Run 2 of #485 committed
  code and still produced no activity item and no review submission.
"""
import pytest

from widget_contract.approval import resolve_approval
from widget_contract.detail import build_workstream_detail_v1
from widget_contract.dispatch_request import build_dispatch_request_v1
from widget_contract.run_authority import (run_activity_projection,
                                           run_review_projection)
from widget_contract.workstreams import build_workstream_projection

ISSUE_REF = "acme/repo#485"

APPROVED_BODY = (
    "## Scope\n\nDo the bounded thing.\n\n"
    "## Deterministic acceptance criteria\n\n- It works.\n\n"
    "## Approval status\n\nOperator approved implementation on 2026-08-31.\n"
)
NEGATED_BODY = (
    "## Scope\n\nDo the bounded thing.\n\n"
    "## Approval status\n\nImplementation is not approved yet.\n"
)
RETRY_COMMENT = [{"author": {"login": "rian010194"},
                  "createdAt": "2026-08-31T10:00:00Z", "id": "c1",
                  "body": "Operator retry authorization: rerun on hermes-free."}]


# --- finding 3: one approval authority --------------------------------------

def test_resolve_approval_reads_the_approval_status_section():
    result = resolve_approval(APPROVED_BODY)
    assert result["recorded"] is True
    assert result["source"] == "issue-body-approval-status"
    assert "Operator approved" in result["reference"]


def test_resolve_approval_treats_an_explicit_negation_as_no_approval():
    result = resolve_approval(NEGATED_BODY)
    assert result["recorded"] is False
    assert result["reference"] is None
    assert result["source"] is None


def test_resolve_approval_prefers_a_later_operator_retry_authorization():
    result = resolve_approval(NEGATED_BODY, RETRY_COMMENT)
    assert result["recorded"] is True
    assert result["source"] == "issue-comment-retry-authorization"


def test_workstream_projection_and_dispatch_request_agree_on_approval():
    """The exact #472 finding 3 shape: the dispatch gate said approved while the
    same issue's Workstream projection said approval_recorded: false."""
    issue = {"number": 485, "title": "Dogfood", "body": APPROVED_BODY,
             "labels": [{"name": "workflow:ready"}], "state": "open",
             "url": "https://example/485", "milestone": None}
    projection = build_workstream_projection("acme/repo", [issue])["workstreams"][0]
    request = build_dispatch_request_v1(issue, None, repo="acme/repo")

    assert projection["authority"]["approval_recorded"] is True
    assert request["approval_reference"] is not None
    assert projection["authority"]["approval_source"] == "issue-body-approval-status"


def test_workstream_projection_does_not_record_a_negated_approval():
    issue = {"number": 485, "title": "Dogfood", "body": NEGATED_BODY,
             "labels": [{"name": "workflow:inbox"}], "state": "open",
             "url": "https://example/485", "milestone": None}
    projection = build_workstream_projection("acme/repo", [issue])["workstreams"][0]
    request = build_dispatch_request_v1(issue, None, repo="acme/repo")

    assert projection["authority"]["approval_recorded"] is False
    assert projection["authority"]["approval_source"] is None
    assert request["approval_reference"] is None
    assert "approval_reference" in request["missing"]


def test_workstream_detail_records_the_same_approval_and_its_source():
    issue = {"number": 485, "title": "Dogfood", "body": APPROVED_BODY,
             "labels": [{"name": "workflow:ready"}], "state": "open",
             "url": "https://example/485", "milestone": None,
             "comments": RETRY_COMMENT}
    detail = build_workstream_detail_v1(issue, [], repo="acme/repo")
    assert detail["mandate"]["approval_source"] == "issue-comment-retry-authorization"
    assert "retry authorization" in detail["mandate"]["approval_reference"]


def test_workstream_detail_reports_no_approval_when_it_is_negated():
    issue = {"number": 485, "title": "Dogfood", "body": NEGATED_BODY,
             "labels": [{"name": "workflow:inbox"}], "state": "open",
             "url": "https://example/485", "milestone": None}
    detail = build_workstream_detail_v1(issue, [], repo="acme/repo")
    assert detail["mandate"]["approval_reference"] is None
    assert detail["mandate"]["approval_source"] is None


# --- finding 5: the feeds must read the store the launcher actually writes ---

def _dispatcher_store(status="succeeded", gh_synced=True):
    return {"run-6d9": {
        "run_id": "run-6d9", "issue_id": ISSUE_REF, "workflow": "work-launcher/v1",
        "worker_role": "builder", "runtime": "hermes-free", "claimed_at": 1756600000.0,
        "lease_seconds": 3600, "status": status, "heartbeat_at": 1756600100.0,
        "finished_at": 1756600200.0, "gh_synced": gh_synced,
        "result": {"status": status, "cost_status": "unknown",
                   "artifacts": ["run-log:run-6d9", "commit:d2dde76"],
                   "evidence": [{"kind": "git_commit_check", "ref": "commit:d2dde76"}]},
    }}


def test_activity_is_derived_from_the_dispatcher_registry_when_no_session_exists():
    """Run 2 of #485 modified a file, committed, and still produced an empty
    activity timeline: the projection only ever read the session-event store,
    which the launcher path never writes."""
    activity = run_activity_projection(ISSUE_REF, "run-6d9", [],
                                       dispatcher_store=_dispatcher_store())
    assert activity["run_id"] == "run-6d9"
    types = [item["event_type"] for item in activity["items"]]
    assert types == ["run.created", "run.engine_turn"]
    assert all(item["source"] == "dispatcher.runs" for item in activity["items"])
    turn = activity["items"][-1]
    assert turn["detail"]["status"] == "succeeded"
    assert turn["detail"]["artifact_count"] == 2
    assert turn["detail"]["evidence_count"] == 1


def test_activity_still_prefers_durable_session_events_when_they_exist():
    session = [{"events": [
        {"event_type": "session.created", "timestamp": "2026-08-31T10:00:00Z", "sequence": 0,
         "payload": {"run_id": "run-6d9", "issue_id": ISSUE_REF}},
        {"event_type": "run.engine_turn", "timestamp": "2026-08-31T10:05:00Z", "sequence": 1,
         "payload": {"status": "succeeded", "artifacts": [], "evidence": []}},
    ]}]
    activity = run_activity_projection(ISSUE_REF, "run-6d9", session,
                                       dispatcher_store=_dispatcher_store())
    assert [i["event_type"] for i in activity["items"]] == ["run.engine_turn"]
    assert activity["items"][0]["source"] == "session.events"


def test_activity_for_an_unrelated_issue_stays_empty():
    activity = run_activity_projection("acme/repo#999", "run-6d9", [],
                                       dispatcher_store=_dispatcher_store())
    assert activity == {"schema_version": 1, "issue_ref": "acme/repo#999",
                        "run_id": None, "items": []}


def test_review_submission_is_derived_from_the_dispatcher_label_sync():
    """The dispatcher moves a succeeded top-level run's issue to
    workflow:review and records gh_synced; that IS the submission for the
    launcher path, so an issue at workflow:review must not project zero
    submissions (#472 findings 4 and 5)."""
    review = run_review_projection(ISSUE_REF, [], dispatcher_store=_dispatcher_store())
    assert review["sources"] == ["dispatcher.runs", "session.events"]
    (submission,) = review["submissions"]
    assert submission["run_id"] == "run-6d9"
    assert submission["review_kind"] == "dispatcher-label-sync"
    assert submission["result_status"] == "succeeded"
    assert submission["source"] == "dispatcher.runs"


@pytest.mark.parametrize("status,gh_synced", [
    ("succeeded", False),   # the label swap never landed
    ("failed", True),       # a failing run goes to workflow:blocked, not review
    ("in_progress", False),  # nothing terminal yet
])
def test_review_submission_is_not_claimed_without_a_real_label_sync(status, gh_synced):
    review = run_review_projection(
        ISSUE_REF, [], dispatcher_store=_dispatcher_store(status, gh_synced))
    assert review["submissions"] == []


def test_review_projection_names_the_stores_it_consulted_when_empty():
    """An empty feed must read as 'no submission in these stores', never as
    'unavailable' -- the #472 report could not tell the two apart."""
    review = run_review_projection(ISSUE_REF, [])
    assert review["submissions"] == []
    assert review["sources"] == ["session.events"]
