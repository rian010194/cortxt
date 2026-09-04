"""#515: Cortxt OS must not report a healthy Run as disputed or half empty.

Both cases are taken from the shape the #497 dogfood actually produced:
`run-14d3cb02c6314a3da6c7a36d2ecc66e1`, which succeeded, passed the Evidence
Gate and was submitted for review — and which the OS rendered as `conflict`
with no artifacts, provider or model.
"""

from widget_contract.registry import TYPES
from widget_contract.run_authority import (
    correlate_run_summaries,
    run_terminal_projection,
)
from widget_contract.validation import validate

ISSUE = "owner/repo#497"
RUN = "run-14d3cb02"


def _dispatcher(status="succeeded", **extra):
    run = {"run_id": RUN, "issue_id": ISSUE, "workflow": "work-launcher/v1",
           "worker_role": "builder", "runtime": "hermes-free",
           "claimed_at": 1756641600.0, "lease_seconds": 5400, "status": status,
           "parent_run_id": None, "depth": 0, "heartbeat_at": 1756641600.0,
           "finished_at": 1756641900.0, "gh_synced": True,
           "result": {"runtime": "hermes-free", "provider": "nous",
                      "model": "upstage/solar-pro4:free",
                      "artifacts": ["run-log:" + RUN, "commit:90ba45d"],
                      "evidence_gate": "commit_correlated",
                      "error": None}}
    run.update(extra)
    return {RUN: run}


def _session(status="review_submitted"):
    """The shape a Run launched from the OS produces: no `run.engine_turn`."""
    return [{"run_id": RUN, "issue_ref": ISSUE, "status": status,
             "engine": "hermes-free", "worker_role": "builder",
             "started_at": "2026-09-04T08:36:55+00:00",
             "finished_at": "2026-09-04T08:43:31+00:00"}]


# --------------------------------------------------------------------------- #
# a sequence is not a disagreement
# --------------------------------------------------------------------------- #
def test_succeeded_then_review_submitted_is_not_a_conflict():
    summaries = correlate_run_summaries(ISSUE, _dispatcher(), _session())

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["conflict"] is None, summary["conflict"]
    assert summary["status"] == "review_submitted", "the later state wins"
    assert sorted(summary["sources"]) == ["dispatcher.runs", "session.events"]


def test_the_terminal_projection_does_not_warn_about_a_healthy_run():
    summaries = correlate_run_summaries(ISSUE, _dispatcher(), _session())
    result = run_terminal_projection(ISSUE, RUN, summaries, [],
                                     dispatcher_store=_dispatcher())

    assert result["conflicting"] is False


def test_a_real_disagreement_is_still_reported():
    """Only the one ordered pair is a sequence; everything else still conflicts."""
    summaries = correlate_run_summaries(ISSUE, _dispatcher(status="blocked"),
                                        _session())
    assert summaries[0]["status"] == "conflict"
    assert summaries[0]["conflict"]["field"] == "status"
    assert sorted(summaries[0]["conflict"]["values"]) == ["blocked", "review_submitted"]


def test_two_competing_terminal_verdicts_still_conflict():
    summaries = correlate_run_summaries(ISSUE, _dispatcher(status="succeeded"),
                                        _session(status="failed"))
    assert summaries[0]["status"] == "conflict"


# --------------------------------------------------------------------------- #
# the projection must not drop fields one source recorded
# --------------------------------------------------------------------------- #
def test_the_terminal_projection_keeps_fields_the_dispatcher_recorded():
    """A session doc with no `run.engine_turn` must not blank the envelope.

    This is the exact #497 shape: the launcher writes the engine result to the
    dispatcher registry, and the session store holds only `session.created` and
    `run.review_submitted`.
    """
    doc = {"session_id": "s1", "events": [
        {"event_type": "session.created", "sequence": 0,
         "timestamp": "2026-09-04T08:36:55Z",
         "payload": {"run_id": RUN, "issue_id": ISSUE}},
        {"event_type": "run.review_submitted", "sequence": 1,
         "timestamp": "2026-09-04T08:43:31Z",
         "payload": {"run_id": RUN, "issue_ref": ISSUE,
                     "review_submission_id": "review-1"}},
    ]}
    summaries = correlate_run_summaries(ISSUE, _dispatcher(), _session())

    result = run_terminal_projection(ISSUE, RUN, summaries, [doc],
                                     dispatcher_store=_dispatcher())

    validate(result, TYPES["run.terminal.v1"].schema)
    assert [a["ref"] for a in result["artifacts"]] == ["run-log:" + RUN, "commit:90ba45d"]
    assert result["provider"] == "nous"
    assert result["model"] == "upstage/solar-pro4:free"
    assert result["evidence_gate"] == "commit_correlated"


def test_a_session_turn_still_wins_where_it_has_a_value():
    """The session store remains authoritative for what it actually recorded."""
    doc = {"session_id": "s1", "events": [
        {"event_type": "run.engine_turn", "sequence": 1,
         "timestamp": "2026-09-04T08:43:31Z",
         "payload": {"run_id": RUN, "issue_ref": ISSUE, "provider": "other-provider",
                     "model": "other-model"}},
    ]}
    summaries = correlate_run_summaries(ISSUE, _dispatcher(), _session())

    result = run_terminal_projection(ISSUE, RUN, summaries, [doc],
                                     dispatcher_store=_dispatcher())

    assert result["provider"] == "other-provider"
    assert result["model"] == "other-model"
    # and the dispatcher still supplies what the turn did not mention
    assert [a["ref"] for a in result["artifacts"]] == ["run-log:" + RUN, "commit:90ba45d"]


def test_missing_cost_is_still_unknown_never_zero():
    """The one rule this change must not relax."""
    summaries = correlate_run_summaries(ISSUE, _dispatcher(), _session())
    result = run_terminal_projection(ISSUE, RUN, summaries, [],
                                     dispatcher_store=_dispatcher())

    assert result["cost"] is None
    assert result["cost_status"] == "unknown"
