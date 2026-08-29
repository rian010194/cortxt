"""S7a (#470) deterministic tests for the versioned Workstream detail projection."""

from widget_contract.adapters.store_reads import read_run_summaries_v1, read_workstream_detail_v1
from widget_contract.detail import build_synthetic_workstream_detail_v1, parse_dispatch_limits, parse_relations
from widget_contract.registry import TYPES
from widget_contract.run_authority import correlate_run_summaries, summaries_from_sessions
from widget_contract.validation import validate

REPO = "owner/repo"


def _issue(**overrides):
    issue = {
        "number": 470,
        "title": "Build: S7a — Real Workstream detail projection and Run authority",
        "body": (
            "## Scope\n\nBuild the versioned fail-closed read-model foundation.\n\n"
            "## Deterministic acceptance criteria\n\n"
            "- A real GitHub Issue fixture plus real-format local Run records produce a schema-valid detail projection.\n"
            "- Synthetic and local projections validate against the same versioned schema.\n\n"
            "## Approval status\n\nOperator approved issue creation on 2026-08-29.\n\n"
            "## Worker role and limits\n\n"
            "Worker role: builder\n"
            "Max runtime: 5400 seconds\n"
            "Max cost: USD 7.00 hard ceiling; target <= USD 4.00\n"
            "Max parallel workers: 2\n"
            "Delegation depth: 1\n\n"
            "Part of: #469\n"
        ),
        "state": "open",
        "labels": [{"name": "workflow:in-progress"}],
        "url": f"https://github.com/{REPO}/issues/470",
        "milestone": {"title": "S7"},
    }
    issue.update(overrides)
    return issue


def _dispatcher_run(run_id="20260829T120000Z_aaaaaaaa", issue_id=f"{REPO}#470",
                    status="in_progress", runtime="dsh", finished_at=None):
    return {
        "run_id": run_id,
        "issue_id": issue_id,
        "workflow": "work-launcher/v1",
        "worker_role": "builder",
        "runtime": runtime,
        "claimed_at": 1756470000.0,
        "lease_seconds": 5400,
        "status": status,
        "parent_run_id": None,
        "depth": 0,
        "heartbeat_at": 1756470000.0,
        "finished_at": finished_at,
        "result": None,
        "gh_synced": False,
        "gh_sync_claimed_at": None,
    }


def test_real_issue_and_runs_produce_schema_valid_detail_with_exact_ids_and_provenance():
    runs = correlate_run_summaries(f"{REPO}#470", {"run_1": _dispatcher_run(run_id="run_1")}, [])
    detail = read_workstream_detail_v1(_issue(), runs, repo=REPO)
    validate(detail, TYPES["workstream.detail.v1"].schema)
    assert detail["issue"]["issue_id"] == f"{REPO}#470"
    assert detail["issue"]["number"] == 470
    assert detail["issue"]["workflow"] == "in-progress"
    assert detail["runs"][0]["run_id"] == "run_1"
    assert detail["runs"][0]["issue_ref"] == f"{REPO}#470"
    assert detail["runs"][0]["sources"] == ["dispatcher.runs"]
    assert detail["relations"] == [{"relation": "part-of", "target": 469}]
    assert detail["mandate"]["dispatch_limits"]["max_cost_usd"] == 7.0
    assert detail["mandate"]["dispatch_limits"]["max_runtime_seconds"] == 5400


def test_synthetic_and_local_validate_against_the_same_schema():
    synthetic = build_synthetic_workstream_detail_v1(REPO, 470)
    local = read_workstream_detail_v1(_issue(), [], repo=REPO)
    validate(synthetic, TYPES["workstream.detail.v1"].schema)
    validate(local, TYPES["workstream.detail.v1"].schema)
    assert synthetic["synthetic"] is True and synthetic["mode"] == "synthetic"
    assert local["synthetic"] is False and local["mode"] == "local"
    assert synthetic["schema_version"] == local["schema_version"] == 1


def test_missing_authoritative_fields_stay_missing():
    issue = _issue(body="## Scope\n\nOnly scope, nothing else.", labels=[])
    detail = read_workstream_detail_v1(issue, [], repo=REPO)
    assert detail["issue"]["workflow"] == "unknown"
    assert detail["issue"]["workflow_labels"] == []
    assert detail["mandate"]["scope"] == "Only scope, nothing else."
    assert detail["mandate"]["outcome"] is None
    assert detail["mandate"]["acceptance_criteria"] == []
    assert detail["mandate"]["approval_reference"] is None
    assert detail["mandate"]["dispatch_limits"] == {}
    assert detail["relations"] == []


def test_multiple_workflow_labels_render_unknown_not_a_guess():
    issue = _issue(labels=[{"name": "workflow:review"}, {"name": "workflow:done"}])
    detail = read_workstream_detail_v1(issue, [], repo=REPO)
    assert detail["issue"]["workflow"] == "unknown"
    assert detail["issue"]["workflow_labels"] == ["workflow:review", "workflow:done"]


def test_run_mismatch_is_not_correlated_into_the_projection():
    runs = correlate_run_summaries(f"{REPO}#470", {"run_1": _dispatcher_run(run_id="run_1", issue_id=f"{REPO}#999")}, [])
    detail = read_workstream_detail_v1(_issue(), runs, repo=REPO)
    assert detail["runs"] == []


def test_conflicting_stores_render_conflict_not_silent_merge():
    dispatcher = {"run_1": _dispatcher_run(run_id="run_1", status="in_progress")}
    session = summaries_from_sessions([{
        "events": [
            {"event_type": "session.created",
             "payload": {"run_id": "run_1", "issue_id": f"{REPO}#470", "engine_id": "dsh"},
             "timestamp": "2026-08-29T12:00:00Z"},
            {"event_type": "session.terminal",
             "payload": {"status": "failed"},
             "timestamp": "2026-08-29T13:00:00Z"},
        ]
    }], f"{REPO}#470")
    runs = correlate_run_summaries(f"{REPO}#470", dispatcher, session)
    assert runs[0]["status"] == "conflict"
    assert runs[0]["conflict"] == {"field": "status", "values": ["in_progress", "failed"]}
    assert runs[0]["sources"] == ["dispatcher.runs", "session.events"]


def test_run_summaries_are_immutable_and_retry_history_is_preserved():
    dispatcher = {
        "run_1": _dispatcher_run(run_id="run_1", status="failed", finished_at=1756471000.0),
        "run_2": _dispatcher_run(run_id="run_2", status="in_progress"),
    }
    runs = correlate_run_summaries(f"{REPO}#470", dispatcher, [])
    ids = {run["run_id"] for run in runs}
    assert ids == {"run_1", "run_2"}
    by_id = {run["run_id"]: run for run in runs}
    assert by_id["run_1"]["status"] == "failed"
    assert by_id["run_1"]["finished_at"] is not None
    assert by_id["run_2"]["status"] == "in_progress"


def test_freshness_and_age_are_represented():
    detail = read_workstream_detail_v1(_issue(), [], repo=REPO, status="stale",
                                       age_seconds=120, error={"kind": "timeout", "message": "gh timed out"})
    assert detail["source"]["status"] == "stale"
    assert detail["source"]["age_seconds"] == 120
    assert detail["source"]["complete"] is False
    assert detail["source"]["error"]["kind"] == "timeout"


def test_redaction_no_prompt_reasoning_secret_or_artifact_content():
    issue = _issue(body=(
        "## Scope\n\nBuild it.\n\n"
        "## Evidence\n\napi_key=deadbeef password=hunter2 do not publish secret\n\n"
        "## Outcome\n\nReasoning: step one is to..."
    ))
    runs = correlate_run_summaries(f"{REPO}#470", {
        "run_1": _dispatcher_run(run_id="run_1"),
    }, [])
    detail = read_workstream_detail_v1(issue, runs, repo=REPO)
    assert "api_key" not in detail["mandate"]["scope"]
    # Evidence summary is explicit section text; secrets in evidence are not
    # promoted into mandate/issue fields, and no run summary carries them.
    for run in detail["runs"]:
        assert "api_key" not in str(run)
        assert "hunter2" not in str(run)
    assert "api_key" not in detail["issue"]["title"]


def test_parse_dispatch_limits_returns_only_explicit_fields():
    limits = parse_dispatch_limits("Worker role: builder\nMax runtime: 5400 seconds\nMax cost: USD 7.00\n")
    assert limits == {"worker_role": "builder", "max_runtime_seconds": 5400, "max_cost_usd": 7.0}


def test_parse_relations_reads_part_of_and_blocked_by():
    relations = parse_relations("Part of: #469\nBlocked by: #468\nDepends on: #467\n")
    assert relations == [
        {"relation": "part-of", "target": 469},
        {"relation": "blocked-by", "target": 468},
        {"relation": "blocked-by", "target": 467},
    ]


def test_run_summaries_v1_read_adapter_validates_and_correlates():
    result = read_run_summaries_v1(
        f"{REPO}#470",
        {"run_1": _dispatcher_run(run_id="run_1")},
        [],
    )
    validate(result, TYPES["run.summaries.v1"].schema)
    assert result["issue_ref"] == f"{REPO}#470"
    assert result["runs"][0]["run_id"] == "run_1"
