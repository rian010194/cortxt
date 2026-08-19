# agent-platform/tests/daemon/test_evidence_gate.py
import pytest

from daemon.evidence_gate import GateOutcome, evaluate_gate


def _envelope(**overrides) -> dict:
    base = {"status": "succeeded", "evidence": [{"kind": "test_run", "detail": "5 passed"}],
            "artifacts": ["session:abc", "engine:hermes"]}
    base.update(overrides)
    return base


def test_non_succeeded_status_freezes():
    outcome = evaluate_gate(_envelope(status="failed"), checkpoint_required=False)
    assert outcome.decision == "freeze"
    assert "failed" in outcome.reason


def test_missing_evidence_freezes_even_if_status_succeeded():
    outcome = evaluate_gate(_envelope(evidence=[]), checkpoint_required=False)
    assert outcome.decision == "freeze"
    assert "evidence" in outcome.reason


def test_artifact_outside_allowed_prefix_freezes():
    outcome = evaluate_gate(
        _envelope(artifacts=["session:abc", "file:/etc/passwd"]),
        checkpoint_required=False,
        allowed_artifact_prefixes=("session:", "engine:"),
    )
    assert outcome.decision == "freeze"
    assert "file:/etc/passwd" in outcome.reason


def test_clean_pass_with_checkpoint_not_required_proceeds():
    outcome = evaluate_gate(_envelope(), checkpoint_required=False)
    assert outcome.decision == "proceed"


def test_clean_pass_with_checkpoint_required_pauses():
    outcome = evaluate_gate(_envelope(), checkpoint_required=True)
    assert outcome.decision == "pause"


def test_no_artifact_prefix_restriction_means_no_scope_check():
    outcome = evaluate_gate(_envelope(artifacts=["anything:goes"]), checkpoint_required=False)
    assert outcome.decision == "proceed"
