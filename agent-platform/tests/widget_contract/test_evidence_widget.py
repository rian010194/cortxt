"""Evidence comparison view as a contract widget (Phase 5 app-shell slice)."""
import json
from argparse import Namespace
from pathlib import Path

import pytest

from cli.unified_cli import _run_widget
from widget_contract.adapters.store_reads import ReadAdapterError, read_evidence_comparison_v1
from widget_contract.loader import load_widget_file
from widget_contract.registry import READ_OPERATIONS, TYPES
from widget_contract.renderer import render
from widget_contract.validation import ValidationError, validate

SPEC = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "evidence-0.1.yaml"


def comparison():
    return {
        "issue_id": "owner/repo#402",
        "runs": [
            {"run_id": "run-1", "engine": "hermes", "status": "blocked",
             "evidence": ["policy gate: data-class mismatch"], "artifacts": [],
             "artifacts_present": False, "artifacts_missing": ["changelog"],
             "independently_reviewed": False, "accepted": False},
            {"run_id": "run-2", "engine": "claude-direct", "status": "succeeded",
             "evidence": ["result envelope: task completed"], "artifacts": ["report.md"],
             "artifacts_present": True, "artifacts_missing": [],
             "independently_reviewed": True, "accepted": True},
        ],
    }


def test_adapter_includes_evidence_completeness_fields():
    result = read_evidence_comparison_v1(comparison())
    run0 = result["runs"][0]
    assert run0["artifacts_present"] is False
    assert run0["artifacts_missing"] == ["changelog"]
    assert run0["independently_reviewed"] is False
    assert run0["accepted"] is False


def test_adapter_rejects_run_missing_completeness_fields():
    incomplete = comparison()
    del incomplete["runs"][0]["accepted"]
    with pytest.raises(ReadAdapterError):
        read_evidence_comparison_v1(incomplete)


def test_evidence_comparison_type_and_read_are_registered_and_strict():
    validate(comparison(), TYPES["evidence.comparison.v1"].schema)
    operation = READ_OPERATIONS["evidence.comparison.v1"]
    assert (operation.source, operation.output_type, operation.capability) == (
        "store", "evidence.comparison.v1", "read:evidence-comparison")
    malformed = {**comparison(), "runs": "not-a-list"}
    with pytest.raises(ValidationError):
        validate(malformed, TYPES["evidence.comparison.v1"].schema)


def test_adapter_validates_projection_and_rejects_malformed():
    result = read_evidence_comparison_v1(comparison())
    assert result["runs"][0]["run_id"] == "run-1"
    assert result["runs"][1]["artifacts"] == ["report.md"]
    with pytest.raises(ReadAdapterError):
        read_evidence_comparison_v1({"issue_id": "owner/repo#402"})
    with pytest.raises(ReadAdapterError):
        read_evidence_comparison_v1({"issue_id": "owner/repo#402", "runs": [{"run_id": "x"}]})


def test_spec_loads_and_declares_evidence_comparison_read():
    widget = load_widget_file(SPEC)
    assert widget.id == "evidence" and widget.version == "0.1"
    (read,) = widget.reads
    assert (read.id, read.source, read.operation, read.output_type) == (
        "comparison", "store", "evidence.comparison.v1", "evidence.comparison.v1")
    assert set(widget.capabilities) == {"read:evidence-comparison"}


def test_render_produces_runs_table():
    widget = load_widget_file(SPEC)
    tree = render(widget, {"comparison": comparison()}, {"comparison": "fresh"})
    children = tree["render"]["children"]
    table = next(c for c in children if c["primitive"] == "table")
    assert table["props"]["rows"][0]["run_id"] == "run-1"
    assert table["props"]["rows"][1]["engine"] == "claude-direct"


def test_render_zero_state():
    widget = load_widget_file(SPEC)
    zero = {"issue_id": "owner/repo#0", "runs": []}
    tree = render(widget, {"comparison": zero}, {"comparison": "fresh"})
    table = next(c for c in tree["render"]["children"] if c["primitive"] == "table")
    assert table["props"]["rows"] == []


def test_cli_evidence_view_artifact_path(tmp_path):
    target = tmp_path / "evidence.json"
    result = _run_widget(
        Namespace(widget_command=None, view="evidence", repo=None, snapshot=target),
        evidence_reader=comparison,
    )
    assert result.status == "succeeded"
    assert target.is_file()
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["widget"] == {"id": "evidence", "version": "0.1"}
    assert artifact["error"] is None


def test_cli_evidence_view_failing_reader_produces_error_state(tmp_path):
    def broken():
        raise OSError("failed to load evidence")

    target = tmp_path / "evidence-err.json"
    result = _run_widget(
        Namespace(widget_command=None, view="evidence", repo=None, snapshot=target),
        evidence_reader=broken,
    )
    assert result.status == "succeeded"
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["error"]["kind"] == "evidence_comparison_read"
    assert artifact["render"]["primitive"] == "error-state"
