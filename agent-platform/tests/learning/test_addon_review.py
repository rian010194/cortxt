from __future__ import annotations

from learning.addon_review import AddonReviewGate
from learning.promotion_gate import MANDATORY_OPERATOR_GATES, PromotionGate


def test_addon_is_a_mandatory_operator_gate_type():
    """Same structural guarantee tool candidates already have (§32.3
    no-self-grant): an addon can never be evaluated as auto-promotable."""
    assert "addon" in MANDATORY_OPERATOR_GATES


def test_addon_rejected_outright_when_codex_security_check_missing():
    gate = AddonReviewGate(PromotionGate())
    matrix = {"complete": True}  # no codex_security_passed key at all
    assert gate.submit(matrix, "addon@example-addon") == "REJECT"


def test_addon_rejected_outright_when_codex_security_check_failed():
    gate = AddonReviewGate(PromotionGate())
    matrix = {"complete": True, "codex_security_passed": False}
    assert gate.submit(matrix, "addon@example-addon") == "REJECT"


def test_addon_reaches_operator_queue_when_codex_security_check_passed():
    gate = AddonReviewGate(PromotionGate())
    matrix = {"complete": True, "codex_security_passed": True}
    assert gate.submit(matrix, "addon@example-addon") == "AWAIT_OPERATOR"


def test_addon_never_auto_promotes_even_with_a_perfect_eval_matrix():
    """The whole point: Codex passing security is necessary, never
    sufficient. Only the operator can promote."""
    gate = AddonReviewGate(PromotionGate())
    matrix = {
        "complete": True,
        "codex_security_passed": True,
        "quality_score": 100.0,
        "no_regression": True,
    }
    assert gate.submit(matrix, "addon@flawless-addon") == "AWAIT_OPERATOR"


def test_addon_rejected_when_matrix_incomplete_even_if_security_passed():
    gate = AddonReviewGate(PromotionGate())
    matrix = {"complete": False, "codex_security_passed": True}
    assert gate.submit(matrix, "addon@example-addon") == "REJECT"


def test_non_addon_candidate_types_are_unaffected():
    """AddonReviewGate only intercepts 'addon@...' candidates; anything
    else passes straight through to the wrapped PromotionGate unchanged."""
    gate = AddonReviewGate(PromotionGate())
    matrix = {"complete": True}
    assert gate.submit(matrix, "policy@some-policy") == PromotionGate().evaluate(matrix, "policy@some-policy")
