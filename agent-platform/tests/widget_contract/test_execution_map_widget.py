"""Execution-map view as a contract widget (issue #291)."""
import json
from pathlib import Path

import pytest

from widget_contract.adapters.store_reads import ReadAdapterError, read_execution_map_v1
from widget_contract.loader import load_widget_file
from widget_contract.registry import READ_OPERATIONS, TYPES
from widget_contract.renderer import render
from widget_contract.validation import ValidationError, validate

SPEC = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "execution-map-0.1.yaml"


def projection():
    return {
        "role": "observer",
        "issues": [
            {"id": "owner/repo#1", "wave": 0, "blockers": [], "drift_codes": [], "launchable": True},
            {"id": "owner/repo#2", "wave": 1, "blockers": ["owner/repo#1"],
             "drift_codes": ["missing_area_or_milestone"], "launchable": False},
        ],
        "waves": [["owner/repo#1"], ["owner/repo#2"]],
        "claims": [{"claim_id": "c1", "issue_id": "owner/repo#1", "run_id": "run-1",
                    "state": "active", "lease_expires_at": 200.0, "driver_id": "cortxt-work"}],
        "collision_codes": ["resource_collision"],
    }


def test_execution_map_type_and_read_are_registered_and_strict():
    validate(projection(), TYPES["execution-map.plan.v1"].schema)
    operation = READ_OPERATIONS["execution-map.plan.v1"]
    assert (operation.source, operation.output_type, operation.capability) == (
        "store", "execution-map.plan.v1", "read:execution-map")
    malformed = {**projection(), "role": 5}
    with pytest.raises(ValidationError):
        validate(malformed, TYPES["execution-map.plan.v1"].schema)


def test_spec_loads_and_declares_execution_map_read():
    widget = load_widget_file(SPEC)
    assert widget.id == "execution-map" and widget.version == "0.1"
    assert widget.actions == ()
    (read,) = widget.reads
    assert (read.id, read.source, read.operation, read.output_type) == (
        "plan", "store", "execution-map.plan.v1", "execution-map.plan.v1")
    assert read.on_error == "stale"
    assert set(widget.capabilities) == {"read:execution-map"}


def test_render_produces_expected_tree_with_waves_drift_and_claims():
    widget = load_widget_file(SPEC)
    tree = render(widget, {"plan": projection()}, {"plan": "fresh"})
    children = tree["render"]["children"]
    assert children[0]["primitive"] == "text" and children[0]["props"]["value"] == "observer"
    issues = children[1]
    assert issues["props"]["label"] == "Issues"
    assert issues["props"]["rows"][0] == {"id": "owner/repo#1", "wave": 0, "blockers": [],
                                          "drift_codes": [], "launchable": True}
    assert issues["props"]["rows"][1]["blockers"] == ["owner/repo#1"]
    assert issues["props"]["rows"][1]["drift_codes"] == ["missing_area_or_milestone"]
    assert issues["props"]["rows"][1]["launchable"] is False
    claims = children[2]
    assert claims["props"]["label"] == "Claims"
    assert claims["props"]["rows"][0]["claim_id"] == "c1"
    assert children[3]["props"]["items"] == [["owner/repo#1"], ["owner/repo#2"]]
    assert children[4]["props"]["items"] == ["resource_collision"]


def test_render_zero_state():
    widget = load_widget_file(SPEC)
    zero = {"role": "observer", "issues": [], "waves": [], "claims": [], "collision_codes": []}
    tree = render(widget, {"plan": zero}, {"plan": "fresh"})
    children = tree["render"]["children"]
    assert children[1]["props"]["rows"] == []
    assert children[2]["props"]["rows"] == []
    assert children[3]["props"]["items"] == []
    assert children[4]["props"]["items"] == []


def test_adapter_validates_projection_and_rejects_malformed():
    result = read_execution_map_v1(lambda store: projection(), {"issues": []})
    assert result["role"] == "observer"
    with pytest.raises(ReadAdapterError):
        read_execution_map_v1(lambda store: {"role": "observer"}, {})
    with pytest.raises(ReadAdapterError):
        read_execution_map_v1(lambda store: "not-an-object", {})


def test_adapter_with_real_plan_from_json(tmp_path, monkeypatch):
    import sys as _sys
    wt = Path(__file__).resolve().parents[3]
    scripts = wt / "scripts"
    if str(scripts) not in _sys.path:
        _sys.path.insert(0, str(scripts))
    from execution_map import plan_from_json
    store = {"issues": [
        {"issue_id": "owner/repo#1", "body": "", "state": "open", "labels": ["workflow:ready"]},
        {"issue_id": "owner/repo#2", "body": "Blocked by: #1\n", "state": "open", "labels": ["workflow:ready"]},
    ], "role": "observer"}
    result = read_execution_map_v1(plan_from_json, store)
    assert result["role"] == "observer"
    assert [i["id"] for i in result["issues"]] == ["owner/repo#1", "owner/repo#2"]
    assert result["issues"][1]["blockers"] == ["owner/repo#1"]
    assert result["waves"] == [["owner/repo#1"], ["owner/repo#2"]]


def test_cli_execution_map_writes_artifact_and_error_state(monkeypatch, capsys, tmp_path):
    from argparse import Namespace
    from cli.unified_cli import _run_widget

    plan_input = tmp_path / "plan.json"
    plan_input.write_text(json.dumps({"issues": [
        {"issue_id": "owner/repo#1", "body": "", "state": "open", "labels": ["workflow:ready"]},
    ], "role": "observer"}), encoding="utf-8")
    target = tmp_path / "execution-map.json"
    result = _run_widget(Namespace(widget_command=None, view="execution-map", repo=None,
                                   snapshot=target, snapshot_input=None, plan_input=plan_input))
    capsys.readouterr()
    assert result.status == "succeeded"
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["widget"] == {"id": "execution-map", "version": "0.1"}
    assert artifact["error"] is None
    tables = [c for c in artifact["render"]["children"] if c["primitive"] == "table"]
    assert tables[0]["props"]["label"] == "Issues"
    assert tables[0]["props"]["rows"][0]["id"] == "owner/repo#1"

    missing = tmp_path / "missing.json"
    target2 = tmp_path / "execution-map2.json"
    result2 = _run_widget(Namespace(widget_command=None, view="execution-map", repo=None,
                                    snapshot=target2, snapshot_input=None, plan_input=missing))
    capsys.readouterr()
    assert result2.status == "succeeded"
    artifact2 = json.loads(target2.read_text(encoding="utf-8"))
    assert artifact2["error"]["kind"] == "plan_read"
    assert artifact2["render"]["primitive"] == "error-state"


def test_widget_has_map_view_without_post():
    html = (Path(__file__).resolve().parents[2] / "widget" / "index.html").read_text(encoding="utf-8")
    assert "map-tab" in html
    assert "renderMap" in html
    assert "pollMap" in html
    assert "execution-map.json" in html
    assert "do_POST" not in html
