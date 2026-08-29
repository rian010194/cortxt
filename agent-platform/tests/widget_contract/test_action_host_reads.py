"""S7a (#470): same-origin Workstream-detail and Runs read operations on the action host."""

import json

import pytest

from runtime import session_state as state
from widget.action_host import ActionHandler, ActionHost, StoreUnavailable
from widget_contract.registry import TYPES
from widget_contract.validation import validate

REPO = "owner/repo"
ISSUE_REF = f"{REPO}#470"


def _issue(number=470):
    return {
        "number": number,
        "title": "Build: S7a — Real Workstream detail projection and Run authority",
        "body": "## Scope\n\nBuild it.\n\n## Approval status\n\nOperator approved on 2026-08-29.\n\n"
                "## Worker role and limits\n\nWorker role: builder\nMax runtime: 5400 seconds\nMax cost: USD 7.00\n"
                "Max parallel workers: 2\nDelegation depth: 1\n\nPart of: #469\n",
        "state": "open",
        "labels": [{"name": "workflow:in-progress"}],
        "url": f"https://github.com/{REPO}/issues/{number}",
        "milestone": None,
    }


def _run_record(run_id="run_1", issue_id=ISSUE_REF, status="in_progress"):
    return {
        "run_id": run_id,
        "issue_id": issue_id,
        "workflow": "work-launcher/v1",
        "worker_role": "builder",
        "runtime": "dsh",
        "claimed_at": 1756470000.0,
        "lease_seconds": 5400,
        "status": status,
        "parent_run_id": None,
        "depth": 0,
        "heartbeat_at": 1756470000.0,
        "finished_at": None,
        "result": None,
        "gh_synced": False,
        "gh_sync_claimed_at": None,
    }


def _host(tmp_path, *, registry_doc=None, session_docs=None):
    registry = tmp_path / "runs.json"
    if registry_doc is not None:
        registry.write_text(json.dumps(registry_doc), encoding="utf-8")
    session_store = tmp_path / ".sessions"
    for i, doc in enumerate(session_docs or []):
        d = session_store / f"session_{i:032x}"
        d.mkdir(parents=True)
        (d / "session.json").write_text(json.dumps(doc), encoding="utf-8")
    return ActionHost(registry=registry, session_store=session_store, issue_reader=lambda repo, number: _issue(number))


def test_workstream_detail_endpoint_read_is_schema_valid_and_correlated(tmp_path):
    host = _host(tmp_path, registry_doc={"run_1": _run_record("run_1")})
    detail = host.workstream_detail("owner/repo", 470)
    validate(detail, TYPES["workstream.detail.v1"].schema)
    assert detail["issue"]["issue_id"] == ISSUE_REF
    assert detail["runs"][0]["run_id"] == "run_1"
    assert detail["runs"][0]["sources"] == ["dispatcher.runs"]


def _write_run_session(store, *, run_id="run_1", issue_id=ISSUE_REF, status="failed"):
    doc = state.create(store, task_id="s7a-test", run_id=run_id, issue_id=issue_id,
                       worker_role="builder", runtime="dsh")
    sid = doc["session_id"]
    state.append(store, sid, 0, "run.created",
                 {"run_id": run_id, "issue_ref": issue_id, "engine_id": "dsh", "profile": "builder"})
    state.append(store, sid, 1, "run.running",
                 {"run_id": run_id, "started_at": "2026-08-29T12:00:01Z"})
    state.append(store, sid, 2, "run.engine_turn", {"status": status, "engine_id": "dsh"})
    return store


def test_runs_endpoint_renders_conflict_across_stores(tmp_path):
    registry = tmp_path / "runs.json"
    registry.write_text(json.dumps({"run_1": _run_record("run_1", status="in_progress")}), encoding="utf-8")
    session_store = tmp_path / ".sessions"
    _write_run_session(session_store, run_id="run_1", issue_id=ISSUE_REF, status="failed")
    host = ActionHost(registry=registry, session_store=session_store,
                      issue_reader=lambda repo, number: _issue(number))
    result = host.run_summaries("owner/repo", 470)
    validate(result, TYPES["run.summaries.v1"].schema)
    assert result["issue_ref"] == ISSUE_REF
    assert result["runs"][0]["status"] == "conflict"
    assert result["runs"][0]["conflict"]["values"] == ["in_progress", "failed"]


def test_malformed_runs_registry_fails_closed(tmp_path):
    host = _host(tmp_path, registry_doc=None)
    host._registry.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(StoreUnavailable):
        host.run_summaries("owner/repo", 470)


def test_malformed_session_record_fails_closed(tmp_path):
    host = _host(tmp_path, registry_doc={}, session_docs=None)
    session_dir = tmp_path / ".sessions" / ("session_" + "0" * 32)
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text("{corrupt", encoding="utf-8")
    with pytest.raises(StoreUnavailable):
        host.run_summaries("owner/repo", 470)


def test_absent_store_is_empty_not_unavailable(tmp_path):
    host = _host(tmp_path, registry_doc=None, session_docs=None)
    result = host.run_summaries("owner/repo", 470)
    validate(result, TYPES["run.summaries.v1"].schema)
    assert result["runs"] == []


def test_issue_query_parser_accepts_owner_repo_number_only():
    handler = ActionHandler

    def parse(path):
        h = object.__new__(handler)
        h.path = path
        return h._issue_ref_from_query()

    assert parse("/api/runs?issue=owner/repo#470") == ("owner/repo", 470)
    assert parse("/api/runs?issue=owner/repo#notanumber") is None
    assert parse("/api/runs?issue=missing-number") is None
    assert parse("/api/runs") is None
