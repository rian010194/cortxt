import json
from pathlib import Path

import pytest

from widget_contract.adapters.store_reads import ReadAdapterError, read_snapshot_v2
from widget_contract.loader import load_widget_file
from widget_contract.registry import READ_OPERATIONS, TYPES
from widget_contract.renderer import render
from widget_contract.validation import ValidationError, validate

SPEC = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "session-pulse-0.1.yaml"


def snapshot(orchestrator=None, workstreams=None, activity=None):
    return {
        "schema_version": 2,
        "generated_at": "2026-01-01T00:00:00Z",
        "orchestrator": orchestrator or {"status": "idle", "active_agent_sessions": 0,
                                         "abandoned_agent_sessions": 0, "blocked_agent_sessions": 0,
                                         "failed_agent_sessions": 0, "attention_items": 0,
                                         "message": "idle"},
        "workstreams": workstreams or [],
        "sessions": [],
        "activity": activity or [],
    }


def test_session_pulse_spec_loads_and_declares_snapshot_read():
    widget = load_widget_file(SPEC)
    assert widget.id == "session-pulse" and widget.version == "0.1"
    assert widget.actions == ()
    (read,) = widget.reads
    assert (read.id, read.source, read.operation, read.output_type) == (
        "snapshot", "store", "sessions.snapshot.v2", "sessions.snapshot.v2")
    assert read.on_error == "stale"
    operation = READ_OPERATIONS["sessions.snapshot.v2"]
    assert (operation.source, operation.capability) == ("store", "read:sessions")
    assert set(widget.capabilities) == {"read:sessions"}


def test_session_pulse_render_produces_expected_tree():
    widget = load_widget_file(SPEC)
    data = snapshot(
        orchestrator={"status": "attention", "active_agent_sessions": 1,
                      "abandoned_agent_sessions": 0, "blocked_agent_sessions": 1,
                      "failed_agent_sessions": 0, "attention_items": 1, "message": "1 active"},
        workstreams=[{"workstream_id": "ws-1", "status": "running", "updated_at": "2026-01-01T00:00:01Z"}],
        activity=[{"timestamp": "2026-01-01T00:00:01Z", "event_type": "session.created",
                   "workstream_id": "ws-1", "actor": "agent"}],
    )
    tree = render(widget, {"snapshot": data}, {"snapshot": "fresh"})
    assert tree["render"]["primitive"] == "stack"
    children = tree["render"]["children"]
    assert children[0]["primitive"] == "key-value"
    assert children[0]["props"]["value"]["status"] == "attention"
    assert children[1]["primitive"] == "metric"
    assert children[1]["props"]["value"] == 1
    assert children[2]["props"]["label"] == "Workstreams"
    assert children[2]["props"]["rows"] == [{"workstream_id": "ws-1", "status": "running",
                                             "updated_at": "2026-01-01T00:00:01Z"}]
    assert children[3]["props"]["label"] == "Activity"
    assert children[3]["props"]["rows"][0]["event_type"] == "session.created"


def test_session_pulse_zero_state_and_schema_validation():
    widget = load_widget_file(SPEC)
    data = snapshot()
    tree = render(widget, {"snapshot": data}, {"snapshot": "fresh"})
    assert tree["render"]["children"][2]["props"]["rows"] == []
    assert tree["render"]["children"][3]["props"]["rows"] == []
    validate(data, TYPES["sessions.snapshot.v2"].schema)
    malformed = {**data, "workstreams": "wrong"}
    with pytest.raises(ValidationError):
        validate(malformed, TYPES["sessions.snapshot.v2"].schema)


def test_read_snapshot_v2_is_safe_projection_and_rejects_type_mismatch():
    source = {**snapshot(), "credentials": [{"value": "excluded"}], "profiles": []}
    projection = read_snapshot_v2(source)
    assert "credentials" not in projection and "profiles" not in projection
    assert sorted(projection) == ["activity", "generated_at", "orchestrator",
                                  "schema_version", "sessions", "workstreams"]
    with pytest.raises(ReadAdapterError):
        read_snapshot_v2({"workstreams": "wrong"})


def test_cli_session_pulse_writes_artifact_and_error_state(monkeypatch, capsys, tmp_path):
    from argparse import Namespace
    from cli.unified_cli import _run_widget

    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(snapshot(workstreams=[{"workstream_id": "ws-9", "status": "blocked",
                                                        "updated_at": "2026-01-01T00:00:00Z"}])), encoding="utf-8")
    target = tmp_path / "session-pulse.json"
    result = _run_widget(Namespace(widget_command=None, view="session-pulse", repo=None,
                                   snapshot=target, snapshot_input=source))
    capsys.readouterr()
    assert result.status == "succeeded"
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["widget"] == {"id": "session-pulse", "version": "0.1"}
    assert artifact["render"]["primitive"] == "stack"
    assert artifact["error"] is None
    tables = [c for c in artifact["render"]["children"] if c["primitive"] == "table"]
    assert tables[0]["props"]["label"] == "Workstreams"
    assert tables[0]["props"]["rows"][0]["workstream_id"] == "ws-9"

    missing = tmp_path / "missing.json"
    target2 = tmp_path / "session-pulse2.json"
    result2 = _run_widget(Namespace(widget_command=None, view="session-pulse", repo=None,
                                    snapshot=target2, snapshot_input=missing))
    capsys.readouterr()
    assert result2.status == "succeeded"
    artifact2 = json.loads(target2.read_text(encoding="utf-8"))
    assert artifact2["error"]["kind"] == "snapshot_read"
    assert artifact2["render"]["primitive"] == "error-state"
    assert artifact2["render"]["state"] == "error"


def test_widget_has_pulse_view_without_post():
    html = (Path(__file__).resolve().parents[2] / "widget" / "index.html").read_text(encoding="utf-8")
    assert "pulse-tab" in html
    assert "renderPulse" in html
    assert "pollPulse" in html
    assert "session-pulse.json" in html
    assert "do_POST" not in html
