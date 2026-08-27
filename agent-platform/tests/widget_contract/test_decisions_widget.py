"""Decisions view as a contract widget (Phase 5 app-shell slice)."""
import json
from argparse import Namespace
from pathlib import Path

import pytest

from cli.unified_cli import _run_widget
from widget_contract.adapters.github_ports import TransitionDenied, record_decision_transition
from widget_contract.adapters.store_reads import ReadAdapterError, read_decision_pending_v1
from widget_contract.loader import load_widget_file
from widget_contract.registry import ACTIONS, READ_OPERATIONS, TYPES
from widget_contract.renderer import render
from widget_contract.validation import ValidationError, validate

SPEC = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "decisions-0.1.yaml"


def pending():
    return {
        "issue_id": "owner/repo#402",
        "workflow": "review",
        "summary": "Approve the reviewed evidence package for the gap analysis",
        "actionable": True,
    }


def test_decision_pending_type_and_read_are_registered_and_strict():
    validate(pending(), TYPES["decision.pending.v1"].schema)
    operation = READ_OPERATIONS["decision.pending.v1"]
    assert (operation.source, operation.output_type, operation.capability) == (
        "store", "decision.pending.v1", "read:decision-pending")
    malformed = {**pending(), "actionable": "yes"}
    with pytest.raises(ValidationError):
        validate(malformed, TYPES["decision.pending.v1"].schema)


def test_record_decision_action_is_registered():
    action = ACTIONS["workflow.record-decision.v1"]
    assert action.port == "github-transition"
    assert action.authorization_modes == frozenset({"operator"})
    assert action.capability == "act:record-decision"
    assert action.retryable is True


def test_adapter_validates_projection_and_rejects_malformed():
    result = read_decision_pending_v1(pending())
    assert result["actionable"] is True
    with pytest.raises(ReadAdapterError):
        read_decision_pending_v1({"issue_id": "owner/repo#402"})


def test_record_decision_transition_requires_exactly_review_label():
    def reader(issue_id):
        return {"issue_id": issue_id, "labels": [{"name": "workflow:review"}]}

    def writer(operation, request):
        return {"issue_id": request["issue_id"], "status": "ok"}

    result = record_decision_transition("workflow.record-decision.v1", {"issue_id": "owner/repo#402"},
                                        issue_reader=reader, transition=writer)
    assert result == {"issue_id": "owner/repo#402", "status": "ok"}


def test_record_decision_transition_refuses_non_review_state():
    def reader(issue_id):
        return {"issue_id": issue_id, "labels": [{"name": "workflow:ready"}]}

    def writer(operation, request):
        raise AssertionError("must not write when not workflow:review")

    with pytest.raises(TransitionDenied):
        record_decision_transition("workflow.record-decision.v1", {"issue_id": "owner/repo#402"},
                                   issue_reader=reader, transition=writer)


def test_spec_loads_and_declares_decision_pending_read_and_action():
    widget = load_widget_file(SPEC)
    assert widget.id == "decisions" and widget.version == "0.1"
    (read,) = widget.reads
    assert (read.id, read.source, read.operation, read.output_type) == (
        "pending", "store", "decision.pending.v1", "decision.pending.v1")
    (action,) = widget.actions
    assert (action.id, action.port, action.operation) == (
        "record-decision", "github-transition", "workflow.record-decision.v1")
    assert set(widget.capabilities) == {"read:decision-pending", "act:record-decision"}


def test_render_shows_summary_and_actionable_flag():
    widget = load_widget_file(SPEC)
    tree = render(widget, {"pending": pending()}, {"pending": "fresh"})
    children = tree["render"]["children"]
    values = [c["props"].get("value") for c in children if c["primitive"] in ("text", "badge")]
    assert "Approve the reviewed evidence package for the gap analysis" in values
    assert True in values


def test_cli_decisions_view_artifact_path(tmp_path):
    target = tmp_path / "decisions.json"
    result = _run_widget(
        Namespace(widget_command=None, view="decisions", repo=None, snapshot=target),
        decision_reader=pending,
    )
    assert result.status == "succeeded"
    assert target.is_file()
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["widget"] == {"id": "decisions", "version": "0.1"}
    assert artifact["error"] is None


def test_cli_decisions_view_failing_reader_produces_error_state(tmp_path):
    def broken():
        raise OSError("failed to load decision")

    target = tmp_path / "decisions-err.json"
    result = _run_widget(
        Namespace(widget_command=None, view="decisions", repo=None, snapshot=target),
        decision_reader=broken,
    )
    assert result.status == "succeeded"
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["error"]["kind"] == "decision_pending_read"
    assert artifact["render"]["primitive"] == "error-state"
