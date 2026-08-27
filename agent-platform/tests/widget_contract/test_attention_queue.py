"""Attention queue read operation (Cortxt OS shell slice)."""
import pytest

from widget_contract.adapters.store_reads import ReadAdapterError, read_attention_queue_v1
from widget_contract.registry import READ_OPERATIONS, TYPES
from widget_contract.validation import ValidationError, validate


def queue():
    return {
        "items": [
            {"workstream_id": "ws-builder-339", "kind": "evidence",
             "summary": "Evidence package blocked, awaiting review", "issue_id": "owner/repo#402"},
            {"workstream_id": "ws-atlas-118", "kind": "decision",
             "summary": "Record decision on milestone rollover", "issue_id": "owner/repo#118"},
        ]
    }


def test_attention_queue_type_and_read_are_registered():
    validate(queue(), TYPES["attention.queue.v1"].schema)
    operation = READ_OPERATIONS["attention.queue.v1"]
    assert (operation.source, operation.output_type, operation.capability) == (
        "store", "attention.queue.v1", "read:attention-queue")


def test_attention_queue_rejects_unknown_kind():
    malformed = queue()
    malformed["items"][0]["kind"] = "not-a-kind"
    with pytest.raises(ValidationError):
        validate(malformed, TYPES["attention.queue.v1"].schema)


def test_adapter_validates_and_passes_through_items():
    result = read_attention_queue_v1(queue())
    assert len(result["items"]) == 2
    assert result["items"][0]["kind"] == "evidence"
    with pytest.raises(ReadAdapterError):
        read_attention_queue_v1({"items": [{"workstream_id": "x"}]})
    with pytest.raises(ReadAdapterError):
        read_attention_queue_v1("not-an-object")


def test_adapter_accepts_empty_queue():
    result = read_attention_queue_v1({"items": []})
    assert result == {"items": []}


from pathlib import Path

from widget_contract.loader import load_widget_file
from widget_contract.renderer import render

SPEC = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "attention-queue-0.1.yaml"


def test_spec_loads_and_declares_attention_queue_read():
    widget = load_widget_file(SPEC)
    assert widget.id == "attention-queue" and widget.version == "0.1"
    (read,) = widget.reads
    assert (read.id, read.source, read.operation, read.output_type) == (
        "queue", "store", "attention.queue.v1", "attention.queue.v1")
    assert set(widget.capabilities) == {"read:attention-queue"}


def test_render_shows_attention_queue_table():
    widget = load_widget_file(SPEC)
    tree = render(widget, {"queue": queue()}, {"queue": "fresh"})
    table = tree["render"]["children"][0]
    assert table["primitive"] == "table"
    assert len(table["props"]["rows"]) == 2


import json
from argparse import Namespace

from cli.unified_cli import _run_widget


def test_cli_attention_queue_view_artifact_path(tmp_path):
    target = tmp_path / "attention-queue.json"
    result = _run_widget(
        Namespace(widget_command=None, view="attention-queue", repo=None, snapshot=target),
        attention_queue_reader=queue,
    )
    assert result.status == "succeeded"
    assert target.is_file()
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["widget"] == {"id": "attention-queue", "version": "0.1"}
    assert artifact["error"] is None


def test_cli_attention_queue_view_failing_reader_produces_error_state(tmp_path):
    def broken():
        raise OSError("failed to load attention queue")

    target = tmp_path / "attention-queue-err.json"
    result = _run_widget(
        Namespace(widget_command=None, view="attention-queue", repo=None, snapshot=target),
        attention_queue_reader=broken,
    )
    assert result.status == "succeeded"
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["error"]["kind"] == "attention_queue_read"
    assert artifact["render"]["primitive"] == "error-state"


import json as jsonlib
from pathlib import Path as _Path

WIDGET_DIR = _Path(__file__).resolve().parents[2] / "widget"


def test_widgets_manifest_registers_attention_queue():
    manifest = jsonlib.loads((WIDGET_DIR / "widgets.json").read_text(encoding="utf-8"))
    entry = next((w for w in manifest["widgets"] if w["id"] == "attention-queue"), None)
    assert entry is not None
    assert entry["spec"] == "widget_contract/specs/attention-queue-0.1.yaml"
    assert entry["artifact"] == "fixtures/attention-queue.json"


def test_apps_manifest_has_icon_and_route_per_app():
    manifest = jsonlib.loads((WIDGET_DIR / "apps.json").read_text(encoding="utf-8"))
    for app in manifest["apps"]:
        if app["id"] == "all":
            continue
        assert "icon" in app and "route" in app
