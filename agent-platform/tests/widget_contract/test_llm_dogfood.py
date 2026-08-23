"""LLM-generated widget dogfood proof (issue #286): emit -> load -> render -> serve."""
import json
from pathlib import Path

import pytest

from widget_contract.llm_emitter import (
    emit_all_open_issues_spec, emit_session_pulse_spec, emit_unsafe_spec,
)
from widget_contract.loader import ContractError, load_widget
from widget_contract.renderer import render

WIDGET_DIR = Path(__file__).resolve().parents[2] / "widget"


def test_emitted_all_open_spec_loads_with_stable_canonical_identity():
    spec = emit_all_open_issues_spec("rian010194/cortxt")
    first = load_widget(spec)
    second = load_widget(spec)
    assert first.id == "all-open-issues" and first.version == "0.1"
    assert first.capabilities == ("read:issues",)
    assert first.document_hash == second.document_hash
    assert first.canonical_json == second.canonical_json


def test_emitted_pulse_spec_loads_and_uses_store_read():
    widget = load_widget(emit_session_pulse_spec())
    assert widget.id == "pulse"
    assert widget.capabilities == ("read:sessions",)
    (read,) = widget.reads
    assert (read.source, read.operation, read.output_type) == (
        "store", "sessions.snapshot.v2", "sessions.snapshot.v2")


def test_emitted_all_open_spec_renders_against_issues_data():
    widget = load_widget(emit_all_open_issues_spec("o/r"))
    data = {"issues": {"schema_version": 1, "complete": True, "issues": [
        {"number": 1, "title": "One", "workflow": "ready", "body": "",
         "labels": [], "state": "open", "milestone": None, "url": "u"},
        {"number": 2, "title": "Two", "workflow": "inbox", "body": "",
         "labels": [], "state": "open", "milestone": None, "url": "u"},
    ]}}
    tree = render(widget, data, {"issues": "fresh"})
    children = tree["render"]["children"]
    assert children[0]["primitive"] == "heading"
    assert children[0]["props"]["value"] == "All Open Issues"
    table = children[1]
    assert table["primitive"] == "table" and table["props"]["label"] == "Issues"
    assert [r["number"] for r in table["props"]["rows"]] == [1, 2]


def test_unsafe_emitted_spec_is_rejected_before_any_io():
    with pytest.raises(ContractError, match="forbidden value"):
        load_widget(emit_unsafe_spec())


def test_cli_load_writes_emitted_artifact_and_rejects_unsafe(monkeypatch, capsys, tmp_path):
    from argparse import Namespace
    from cli.unified_cli import _run_widget_load
    from widget_contract.adapters import github_ports

    monkeypatch.setattr(github_ports, "list_all_open_issues", lambda repo: {
        "schema_version": 1, "complete": True,
        "issues": [{"number": 1, "title": "One", "workflow": "ready", "body": "",
                    "labels": [], "state": "open", "milestone": None, "url": "u"}]})

    spec = tmp_path / "all-open.yaml"
    spec.write_text(emit_all_open_issues_spec("o/r"), encoding="utf-8")
    target = tmp_path / "loaded.json"
    result = _run_widget_load(Namespace(widget_command="load", spec=spec, view="loaded",
                                        repo="o/r", snapshot_input=None, snapshot=target))
    capsys.readouterr()
    assert result.status == "succeeded"
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["emitted"] is True
    assert artifact["document_hash"] == result.evidence[0]["document_hash"]
    assert artifact["widget"]["id"] == "all-open-issues"
    assert artifact["render"]["children"][1]["props"]["label"] == "Issues"

    unsafe = tmp_path / "unsafe.yaml"
    unsafe.write_text(emit_unsafe_spec(), encoding="utf-8")
    result2 = _run_widget_load(Namespace(widget_command="load", spec=unsafe, view="unsafe",
                                         repo=None, snapshot_input=None,
                                         snapshot=tmp_path / "unsafe.json"))
    capsys.readouterr()
    assert result2.status == "failed"
    assert result2.error["category"] == "contract_error"
    assert not (tmp_path / "unsafe.json").exists()


def test_widget_has_loaded_view_with_generic_renderer_and_no_post():
    widget_dir = WIDGET_DIR
    html = (widget_dir / "index.html").read_text(encoding="utf-8")
    manifest = json.loads((widget_dir / "widgets.json").read_text(encoding="utf-8"))
    assert any(w["id"] == "loaded" and w["artifact"] == "loaded.json" for w in manifest["widgets"])
    assert "renderGenericNode" in html
    assert "loadManifest" in html
    assert "do_POST" not in html
