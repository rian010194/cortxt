"""Work Console view as a contract widget (Phase 5 app-shell slice)."""
import json
from argparse import Namespace
from pathlib import Path

import pytest

from cli.unified_cli import _run_widget
from widget_contract.adapters.store_reads import ReadAdapterError, read_workstream_summary_v1
from widget_contract.registry import READ_OPERATIONS, TYPES
from widget_contract.validation import ValidationError, validate

SPEC = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "work-console-0.1.yaml"
HOST = Path(__file__).resolve().parents[2] / "widget" / "index.html"


def summary():
    return {
        "issue_id": "owner/repo#402",
        "title": "Municipal AI Act gap analysis",
        "outcome": "A reviewed evidence package for the gap analysis",
        "workflow": "review",
        "pending_decision": True,
        "mandate": {
            "mandate_id": "m-123",
            "granted_by": "operator",
            "allowed_tools": ["dispatch.claim", "dispatch.run"],
            "data_class_max": "operational",
            "budget_usd_max": 25.0,
            "max_runtime_seconds": 3600,
            "expires_at": "2026-09-01T00:00:00Z",
        },
        "gates": [
            {"domain": "human_decision", "status": "warn", "label": "pending",
             "detail": "Approval needed for the evidence package"},
            {"domain": "evidence", "status": "warn", "label": "gap",
             "detail": "Run 1 changelog artifact missing"},
            {"domain": "mandate", "status": "good", "label": "active", "detail": "expires 2026-09-01"},
            {"domain": "budget", "status": "warn", "label": "89% used", "detail": "$22.40 of $25.00"},
            {"domain": "execution", "status": "good", "label": "running", "detail": "Run 2 active"},
            {"domain": "provider_data", "status": "good", "label": "eligible", "detail": "data class: operational"},
        ],
        "run_continuity": {
            "authority": {"mandate_id": "m-123", "granted_by": "operator",
                          "replacement_policy": "rate-limit fallback policy p-17",
                          "dispatched_by": "cortxt-daemon"},
            "current_run": {"run_id": "run-2", "engine": "Hermes / DeepSeek V4 Flash"},
            "previous_run": {"run_id": "run-1", "engine": "Codex CLI", "status": "interrupted"},
        },
    }


def test_adapter_includes_gates_and_run_continuity_authority():
    result = read_workstream_summary_v1(summary())
    assert len(result["gates"]) == 6
    assert {g["domain"] for g in result["gates"]} == {
        "provider_data", "mandate", "evidence", "human_decision", "execution", "budget"}
    assert result["run_continuity"]["authority"]["dispatched_by"] == "cortxt-daemon"
    assert result["run_continuity"]["previous_run"]["status"] == "interrupted"


def test_adapter_rejects_summary_missing_gates():
    incomplete = summary()
    del incomplete["gates"]
    with pytest.raises(ReadAdapterError):
        read_workstream_summary_v1(incomplete)


def test_adapter_accepts_null_previous_run():
    solo = summary()
    solo["run_continuity"]["previous_run"] = None
    result = read_workstream_summary_v1(solo)
    assert result["run_continuity"]["previous_run"] is None


def test_workstream_summary_type_and_read_are_registered_and_strict():
    validate(summary(), TYPES["workstream.summary.v1"].schema)
    operation = READ_OPERATIONS["workstream.summary.v1"]
    assert (operation.source, operation.output_type, operation.capability) == (
        "store", "workstream.summary.v1", "read:workstream-summary")
    malformed = {**summary(), "pending_decision": "yes"}
    with pytest.raises(ValidationError):
        validate(malformed, TYPES["workstream.summary.v1"].schema)


def test_adapter_validates_projection_and_rejects_malformed():
    result = read_workstream_summary_v1(summary())
    assert result["issue_id"] == "owner/repo#402"
    assert result["mandate"]["budget_usd_max"] == 25.0
    with pytest.raises(ReadAdapterError):
        read_workstream_summary_v1({"issue_id": "owner/repo#402"})
    with pytest.raises(ReadAdapterError):
        read_workstream_summary_v1("not-an-object")


from widget_contract.loader import load_widget_file
from widget_contract.renderer import render


def test_spec_loads_and_declares_workstream_summary_read():
    widget = load_widget_file(SPEC)
    assert widget.id == "work-console" and widget.version == "0.1"
    (read,) = widget.reads
    assert (read.id, read.source, read.operation, read.output_type) == (
        "summary", "store", "workstream.summary.v1", "workstream.summary.v1")
    assert set(widget.capabilities) == {"read:workstream-summary"}


def test_render_shows_outcome_workflow_and_mandate_budget():
    widget = load_widget_file(SPEC)
    tree = render(widget, {"summary": summary()}, {"summary": "fresh"})
    children = tree["render"]["children"]
    values = [c["props"].get("value") for c in children if c["primitive"] in ("text", "metric")]
    assert "Municipal AI Act gap analysis" not in values  # title is a heading, not text/metric
    assert "review" in values
    assert 25.0 in values


def test_cli_work_console_view_artifact_path(tmp_path):
    target = tmp_path / "work-console.json"
    result = _run_widget(
        Namespace(widget_command=None, view="work-console", repo=None, snapshot=target),
        workstream_reader=summary,
    )
    assert result.status == "succeeded"
    assert target.is_file()
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["widget"] == {"id": "work-console", "version": "0.1"}
    assert artifact["error"] is None


def test_cli_work_console_view_failing_reader_produces_error_state(tmp_path):
    def broken():
        raise OSError("failed to load workstream")

    target = tmp_path / "work-console-err.json"
    result = _run_widget(
        Namespace(widget_command=None, view="work-console", repo=None, snapshot=target),
        workstream_reader=broken,
    )
    assert result.status == "succeeded"
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["error"]["kind"] == "workstream_summary_read"
    assert artifact["render"]["primitive"] == "error-state"


def test_work_console_default_hides_studio_until_studio_is_opened():
    host = HOST.read_text(encoding="utf-8")
    assert 'data-window="console"' in host
    assert 'data-window="studio" hidden' in host
    assert 'data-app="studio"' in host
