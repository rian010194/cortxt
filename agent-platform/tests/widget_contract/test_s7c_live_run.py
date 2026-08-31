"""S7c (#472) deterministic tests: live Run status, safe activity/evidence
projection, immutable history, exact correlation, freshness/staleness,
terminal envelopes, and the sanctioned idempotent review path."""

import json
from pathlib import Path

import pytest

from runtime import session_state as state
from widget.action_host import ActionHandler, ActionHost
from widget_contract.adapters import review_ports
from widget_contract.adapters.store_reads import (
    RunNotCorrelated,
    read_run_activity_v1,
    read_run_review_v1,
    read_run_terminal_v1,
)
from widget_contract.registry import TYPES
from widget_contract.run_authority import (
    compute_run_freshness,
    correlate_run_summaries,
    run_activity_projection,
    run_terminal_projection,
    summaries_from_sessions,
)
from widget_contract.validation import validate

REPO = "owner/repo"
ISSUE_REF = f"{REPO}#472"
NOW = "2026-08-31T12:00:00+00:00"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _dispatcher_run(run_id="run_1", issue_id=ISSUE_REF, status="in_progress",
                    heartbeat_at=1756641600.0, claimed_at=1756641600.0, finished_at=None):
    return {
        "run_id": run_id, "issue_id": issue_id, "workflow": "work-launcher/v1",
        "worker_role": "builder", "runtime": "dsh", "claimed_at": claimed_at,
        "lease_seconds": 5400, "status": status, "parent_run_id": None, "depth": 0,
        "heartbeat_at": heartbeat_at, "finished_at": finished_at, "result": None,
        "gh_synced": False, "gh_sync_claimed_at": None,
    }


def _session_doc(run_id="run_1", issue_id=ISSUE_REF, *, turn=None, extra_events=()):
    events = [
        {"event_type": "session.created",
         "payload": {"task_id": "s7c", "run_id": run_id, "issue_id": issue_id,
                     "worker_role": "builder", "runtime": "dsh"},
         "timestamp": "2026-08-31T11:00:00Z", "sequence": 0},
        {"event_type": "run.created",
         "payload": {"run_id": run_id, "issue_ref": issue_id, "engine_id": "dsh",
                     "profile": "builder", "model": "m-1", "provider": "prov-1",
                     "scope_fingerprint": "abc"},
         "timestamp": "2026-08-31T11:00:01Z", "sequence": 1},
        {"event_type": "run.running",
         "payload": {"run_id": run_id, "started_at": "2026-08-31T11:00:02Z"},
         "timestamp": "2026-08-31T11:00:02Z", "sequence": 2},
    ]
    for i, ev in enumerate(extra_events, start=3):
        ev.setdefault("sequence", i)
        events.append(ev)
    if turn is not None:
        turn.setdefault("sequence", len(events))
        events.append(turn)
    return {"schema_version": 1, "session_id": f"session_{'0'*31}{run_id[-1]}", "events": events}


def _engine_turn(status="succeeded", *, cost=None, cost_status="unknown",
                 artifacts=None, evidence=None, error=None, ts="2026-08-31T11:30:00Z"):
    return {"event_type": "run.engine_turn", "timestamp": ts,
            "payload": {"run_id": "run_1", "engine_id": "dsh", "profile": "builder",
                        "status": status, "session_id": "eng-sess",
                        "model": "m-1", "provider": "prov-1",
                        "usage": {"tokens_in": 10, "tokens_out": 5},
                        "cost": cost if cost is not None else 0.0,
                        "cost_status": cost_status,
                        "artifacts": artifacts if artifacts is not None else [],
                        "evidence": evidence if evidence is not None else [],
                        "error": error, "finished_at": ts}}


# --------------------------------------------------------------------------- #
# AC3 — freshness / staleness / stranded / terminal / unavailable
# --------------------------------------------------------------------------- #
def _summaries(dispatcher, sessions=()):
    return correlate_run_summaries(ISSUE_REF, dispatcher,
                                   summaries_from_sessions(list(sessions), ISSUE_REF))


def test_freshness_no_runs_is_fresh_and_complete():
    fx = compute_run_freshness([], now_iso=NOW)
    assert fx == {"status": "fresh", "age_seconds": 0, "complete": True}


def test_freshness_running_with_recent_heartbeat_is_fresh():
    runs = _summaries({"run_1": _dispatcher_run(heartbeat_at=_epoch(NOW) - 5)})
    fx = compute_run_freshness(runs, now_iso=NOW)
    assert fx["status"] == "fresh" and fx["complete"] is False


def test_freshness_running_past_stale_bound_is_stale():
    runs = _summaries({"run_1": _dispatcher_run(heartbeat_at=_epoch(NOW) - 120)})
    assert compute_run_freshness(runs, now_iso=NOW)["status"] == "stale"


def test_freshness_running_with_no_signal_for_long_is_stranded():
    runs = _summaries({"run_1": _dispatcher_run(heartbeat_at=_epoch(NOW) - 5000,
                                                claimed_at=_epoch(NOW) - 5000)})
    assert compute_run_freshness(runs, now_iso=NOW)["status"] == "stranded_running"


def test_freshness_all_terminal_is_terminal_and_complete():
    runs = _summaries({"run_1": _dispatcher_run(status="succeeded",
                                                finished_at=_epoch(NOW) - 60)})
    fx = compute_run_freshness(runs, now_iso=NOW)
    assert fx["status"] == "terminal" and fx["complete"] is True and fx["age_seconds"] == 60


def test_freshness_unresolvable_now_fails_closed_unavailable():
    fx = compute_run_freshness([{"status": "in_progress"}], now_iso="not-a-time")
    assert fx["status"] == "unavailable" and fx["complete"] is False


def _epoch(iso):
    from widget_contract.run_authority import _epoch as e
    return e(iso)


# --------------------------------------------------------------------------- #
# AC4 — terminal envelope: honest cost, artifacts, evidence, conflicts
# --------------------------------------------------------------------------- #
def test_terminal_missing_cost_is_unknown_never_zero():
    doc = _session_doc(turn=_engine_turn("succeeded", cost=0.0, cost_status="unknown"))
    runs = _summaries({}, [doc])
    term = run_terminal_projection(ISSUE_REF, "run_1", runs, [doc])
    validate(term, TYPES["run.terminal.v1"].schema)
    assert term["cost"] is None
    assert term["cost_status"] == "unknown"
    assert term["incomplete"] is True


def test_terminal_reports_actual_cost_when_status_is_actual():
    doc = _session_doc(turn=_engine_turn(
        "succeeded", cost=1.25, cost_status="actual",
        artifacts=[{"ref": "artifact://a", "sha256": "deadbeef"}],
        evidence=[{"kind": "pytest", "ref": "junit://x"}]))
    runs = _summaries({}, [doc])
    term = run_terminal_projection(ISSUE_REF, "run_1", runs, [doc])
    assert term["cost"] == 1.25 and term["cost_status"] == "actual"
    assert term["artifacts"] == [{"ref": "artifact://a", "sha256": "deadbeef"}]
    assert term["incomplete"] is False
    assert term["provider"] == "prov-1" and term["model"] == "m-1"


def test_terminal_evidence_is_redacted_to_kind_and_ref_only():
    doc = _session_doc(turn=_engine_turn(
        "succeeded", cost=1.0, cost_status="actual",
        artifacts=[{"ref": "a", "sha256": None}],
        evidence=[{"kind": "log", "ref": "r", "sha256": "h",
                   "body": "api_key=deadbeef reasoning: first I will",
                   "raw_log": "line1\nline2 secret"}]))
    runs = _summaries({}, [doc])
    term = run_terminal_projection(ISSUE_REF, "run_1", runs, [doc])
    validate(term, TYPES["run.terminal.v1"].schema)
    assert term["evidence"] == [{"kind": "log", "ref": "r", "sha256": "h"}]
    blob = json.dumps(term)
    for marker in ("api_key", "reasoning:", "raw_log", "secret", "line1", "line2"):
        assert marker not in blob, marker


def test_terminal_drops_filesystem_paths_and_unstructured_error_text():
    doc = _session_doc(turn=_engine_turn(
        "failed", artifacts=[r"C:\\secret\\run.log", "/tmp/raw.log", "run-log:run_1"],
        evidence=[{"kind": "log", "path": r"C:\\secret\\evidence.log"},
                  {"kind": "secret free text", "ref": "evidence:opaque"}],
        error={"category": "failed", "code": "adapter_timeout",
               "message": "secret raw provider response"}))
    doc["events"][-1]["payload"]["usage"] = {
        "tokens_in": 10, "provider_note": "secret prompt", "nested": {"cached": 2}}
    term = run_terminal_projection(ISSUE_REF, "run_1", _summaries({}, [doc]), [doc])
    assert term["artifacts"] == [{"ref": "run-log:run_1", "sha256": None}]
    assert term["evidence"] == [{"kind": "log"}, {"ref": "evidence:opaque"}]
    assert term["error"] == {"category": "failed", "message": "adapter_timeout"}
    assert term["usage"] == {"tokens_in": 10, "nested": {"cached": 2}}
    assert "secret" not in json.dumps(term)


def test_terminal_conflict_is_flagged_not_resolved():
    doc = _session_doc(turn=_engine_turn("failed", ts="2026-08-31T14:00:00Z"))
    dispatcher = {"run_1": _dispatcher_run(status="in_progress")}
    runs = _summaries(dispatcher, [doc])
    term = run_terminal_projection(ISSUE_REF, "run_1", runs, [doc])
    assert term["status"] == "conflict"
    assert term["conflicting"] is True


def test_terminal_returns_none_when_issue_run_pair_not_correlated():
    doc = _session_doc(turn=_engine_turn("succeeded"))
    runs = _summaries({}, [doc])
    assert run_terminal_projection(ISSUE_REF, "run_MISSING", runs, [doc]) is None
    assert run_terminal_projection(f"{REPO}#999", "run_1", runs, [doc]) is None


def test_terminal_dispatcher_only_run_has_unknown_cost_and_is_incomplete():
    dispatcher = {"run_1": _dispatcher_run(status="failed", finished_at=1756641600.0)}
    dispatcher["run_1"]["result"] = {
        "runtime": "hermes-free", "provider": "nous", "model": "free-model",
        "usage": "unknown (not reported)", "cost": "unknown (not measured)",
        "artifacts": ["run-log:run_1", r"C:\\private\\raw.log"],
        "evidence": "free text must not be projected", "error": None,
    }
    runs = _summaries(dispatcher)
    term = run_terminal_projection(
        ISSUE_REF, "run_1", runs, [], dispatcher_store=dispatcher)
    validate(term, TYPES["run.terminal.v1"].schema)
    assert term["cost"] is None and term["cost_status"] == "unknown"
    assert term["provider"] == "nous" and term["model"] == "free-model"
    assert term["artifacts"] == [{"ref": "run-log:run_1", "sha256": None}]
    assert term["evidence"] == []
    assert term["incomplete"] is True


# --------------------------------------------------------------------------- #
# AC5 — safe activity projection
# --------------------------------------------------------------------------- #
def test_activity_timeline_is_content_free_and_whitelisted():
    turn = _engine_turn("succeeded", cost=1.0, cost_status="actual",
                        artifacts=[{"ref": "a", "sha256": None}],
                        evidence=[{"kind": "k", "ref": "r"}])
    review_ev = {"event_type": "run.review_submitted", "timestamp": "2026-08-31T12:00:00Z",
                 "payload": {"review_submission_id": "review_x", "review_kind": "independent",
                             "idempotency_key": "key-1", "result_status": "succeeded",
                             "payload_hash": "h"}}
    doc = _session_doc(turn=turn, extra_events=[
        {"event_type": "run.log", "payload": {"line": "secret prompt text"},
         "timestamp": "2026-08-31T11:15:00Z"},
    ])
    doc["events"].append(dict(review_ev, sequence=len(doc["events"])))
    runs = _summaries({}, [doc])
    act = run_activity_projection(ISSUE_REF, "run_1", [doc])
    validate(act, TYPES["run.activity.v1"].schema)
    kinds = [i["event_type"] for i in act["items"]]
    assert kinds == ["run.created", "run.running", "run.engine_turn", "run.review_submitted"]
    et = next(i for i in act["items"] if i["event_type"] == "run.engine_turn")
    assert et["detail"] == {"status": "succeeded", "cost_status": "actual",
                            "artifact_count": 1, "evidence_count": 1, "engine": "dsh"}
    rv = next(i for i in act["items"] if i["event_type"] == "run.review_submitted")
    assert rv["detail"] == {"review_kind": "independent", "result_status": "succeeded"}
    assert "secret prompt text" not in json.dumps(act)


def test_activity_read_adapter_fails_closed_on_mismatch():
    doc = _session_doc(turn=_engine_turn("succeeded"))
    with pytest.raises(RunNotCorrelated):
        read_run_activity_v1(ISSUE_REF, {}, [doc], run_id="run_NOPE")


def test_same_run_id_from_other_issue_cannot_supply_session_content():
    foreign = _session_doc(issue_id=f"{REPO}#999", turn=_engine_turn("succeeded"))
    local = _dispatcher_run(status="failed", finished_at=_epoch(NOW) - 10)
    term = read_run_terminal_v1(ISSUE_REF, {"run_1": local}, [foreign], run_id="run_1")
    assert term["provider"] is None and term["model"] is None
    assert term["artifacts"] == [] and term["evidence"] == []
    activity = read_run_activity_v1(ISSUE_REF, {"run_1": local}, [foreign], run_id="run_1")
    # S7d: with no correlated session doc the timeline is derived from THIS
    # issue's dispatcher record instead of rendering "nothing happened"
    # (#472 finding 5) -- but the foreign session's content still supplies
    # nothing, and every item names the store it came from.
    assert activity["run_id"] == "run_1"
    assert {item["source"] for item in activity["items"]} == {"dispatcher.runs"}
    assert "secret prompt text" not in json.dumps(activity)


# --------------------------------------------------------------------------- #
# AC6 — retry: new Run visible, prior Runs + accepted evidence preserved
# --------------------------------------------------------------------------- #
def test_retry_preserves_prior_runs_and_evidence_immutably():
    prior = _session_doc(run_id="run_1", turn=_engine_turn(
        "failed", cost=2.0, cost_status="actual",
        artifacts=[{"ref": "art://1", "sha256": "h1"}],
        evidence=[{"kind": "pytest", "ref": "junit://1"}]))
    retry = _session_doc(run_id="run_2")
    dispatcher = {"run_1": _dispatcher_run("run_1", status="failed"),
                  "run_2": _dispatcher_run("run_2", status="in_progress")}
    runs = _summaries(dispatcher, [prior, retry])
    by_id = {r["run_id"]: r for r in runs}
    assert set(by_id) == {"run_1", "run_2"}
    assert by_id["run_1"]["status"] == "failed"
    assert by_id["run_2"]["status"] in ("in_progress", "conflict")
    prior_term = run_terminal_projection(ISSUE_REF, "run_1", runs, [prior, retry])
    assert prior_term["artifacts"] == [{"ref": "art://1", "sha256": "h1"}]
    assert prior_term["evidence"] == [{"kind": "pytest", "ref": "junit://1"}]


# --------------------------------------------------------------------------- #
# AC7 / AC8 — the review path is the one sanctioned function, not a copy
# --------------------------------------------------------------------------- #
def test_review_port_is_the_canonical_sync_function_not_a_second_path():
    import daemon.review_sync as canonical
    assert review_ports.sync_run_review_submissions is canonical.sync_review_submissions


def test_review_projection_is_content_free_submission_facts():
    review_ev = {"event_type": "run.review_submitted", "timestamp": "2026-08-31T12:00:00Z",
                 "payload": {"review_submission_id": "review_x", "review_kind": "independent",
                             "idempotency_key": "key-1", "result_status": "succeeded",
                             "payload_hash": "h", "submitted_at": "2026-08-31T12:00:00Z"}}
    doc = _session_doc(turn=_engine_turn("succeeded"))
    doc["events"].append(dict(review_ev, sequence=len(doc["events"])))
    result = read_run_review_v1(ISSUE_REF, [doc])
    validate(result, TYPES["run.review.v1"].schema)
    sub = result["submissions"][0]
    assert sub["review_submission_id"] == "review_x"
    assert sub["idempotency_key_present"] is True
    assert "payload_hash" not in json.dumps(sub)
    assert "key-1" not in json.dumps(sub)


# --------------------------------------------------------------------------- #
# action host endpoints (AC1, AC2, AC9)
# --------------------------------------------------------------------------- #
def _issue(number=472):
    return {
        "number": number, "title": "Build: S7c", "state": "open",
        "body": "## Scope\n\nBuild it.\n\n## Approval status\n\nOK 2026-08-29.\n",
        "labels": [{"name": "workflow:in-progress"}],
        "url": f"https://github.com/{REPO}/issues/{number}", "milestone": None,
    }


def _host(tmp_path, *, dispatcher=None, sessions=None, now=NOW):
    registry = tmp_path / "runs.json"
    if dispatcher is not None:
        registry.write_text(json.dumps(dispatcher), encoding="utf-8")
    store = tmp_path / ".sessions"
    for run_id, status in (sessions or []):
        doc = state.create(store, task_id="s7c", run_id=run_id, issue_id=ISSUE_REF,
                           worker_role="builder", runtime="dsh")
        sid = doc["session_id"]
        state.append(store, sid, 0, "run.created",
                     {"run_id": run_id, "issue_ref": ISSUE_REF, "engine_id": "dsh",
                      "profile": "builder", "model": "m-1", "provider": "prov-1"})
        state.append(store, sid, 1, "run.running",
                     {"run_id": run_id, "started_at": "2026-08-31T11:00:02Z"})
        if status is not None:
            state.append(store, sid, 2, "run.engine_turn",
                         {"run_id": run_id, "engine_id": "dsh", "status": status,
                          "cost": 0.0, "cost_status": "unknown", "artifacts": [],
                          "evidence": [], "error": None})
    return ActionHost(registry=registry, session_store=store,
                      issue_reader=lambda repo, number: _issue(number),
                      wall_clock=lambda: now)


def test_detail_endpoint_reports_terminal_freshness_from_authority(tmp_path):
    host = _host(tmp_path, dispatcher={"run_1": _dispatcher_run(status="succeeded",
                                                               finished_at=_epoch(NOW) - 30)})
    detail = host.workstream_detail(REPO, 472)
    validate(detail, TYPES["workstream.detail.v1"].schema)
    assert detail["source"]["status"] == "terminal"
    assert detail["source"]["complete"] is True


def test_freshness_endpoint_tracks_store_changes_on_reload(tmp_path):
    host = _host(tmp_path, dispatcher={"run_1": _dispatcher_run(
        status="in_progress", heartbeat_at=_epoch(NOW) - 5)})
    assert host.run_freshness(REPO, 472)["status"] == "fresh"
    # A later read after the run reaches terminal reflects authority, not a cache.
    host._registry.write_text(json.dumps({"run_1": _dispatcher_run(
        status="succeeded", finished_at=_epoch(NOW) - 5)}), encoding="utf-8")
    assert host.run_freshness(REPO, 472)["status"] == "terminal"


def test_run_terminal_endpoint_404s_on_uncorrelated_run(tmp_path):
    host = _host(tmp_path, sessions=[("run_1", "succeeded")])
    with pytest.raises(RunNotCorrelated):
        host.run_terminal(REPO, 472, "run_other")
    term = host.run_terminal(REPO, 472, "run_1")
    validate(term, TYPES["run.terminal.v1"].schema)
    assert term["cost"] is None and term["cost_status"] == "unknown"


def test_run_activity_and_review_endpoints_are_schema_valid(tmp_path):
    host = _host(tmp_path, sessions=[("run_1", "succeeded")])
    validate(host.run_activity(REPO, 472, "run_1"), TYPES["run.activity.v1"].schema)
    validate(host.run_review(REPO, 472), TYPES["run.review.v1"].schema)


def test_read_endpoints_send_no_store_cache_header(tmp_path):
    host = _host(tmp_path, dispatcher={"run_1": _dispatcher_run()})
    captured = {}

    class _H(ActionHandler):
        def __init__(self):  # bypass socket wiring
            pass
        def send_response(self, code): captured["code"] = code
        def send_header(self, k, v): captured.setdefault("headers", {})[k] = v
        def wfile_write(self, *_): pass

    h = _H()
    h.wfile = type("W", (), {"write": lambda self, b: None})()
    h._headers_buffer = []
    h.request_version = "HTTP/1.1"
    h.host = host
    h.path = "/api/run-freshness?issue=" + ISSUE_REF
    h.do_GET()
    assert captured["headers"]["Cache-Control"] == "no-store"
    assert captured["code"] == 200


def test_live_renderer_asset_is_versioned_for_host_restart_cache_safety():
    root = Path(__file__).resolve().parents[2]
    host_html = (root / "widget" / "index.html").read_text(encoding="utf-8")
    site_html = (root.parent / "site" / "public" / "widgets" / "index.html").read_text(encoding="utf-8")
    marker = 'app-renderer-work-launch.js?v=20260831-s7c'
    assert marker in host_html and marker in site_html


def test_live_renderer_replaces_prior_panel_and_stops_prior_poller():
    root = Path(__file__).resolve().parents[2]
    source = (root / "widget" / "app-renderer-work-launch.js").read_text(encoding="utf-8")
    assert 'winEl._cortxtStopLiveRun()' in source
    assert 'winEl.querySelector("[data-run-live]")' in source
    assert 'winEl._cortxtStopLiveRun = stop' in source
