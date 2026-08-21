"""Phase 8 Task 4 — PromotionGate: rule-driven executor, internal rule resolution, self-approval safe."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from learning.promotion_gate import (
    MANDATORY_OPERATOR_GATES,
    PromotionGate,
    PromotionRule,
)

# --- minimal helpers ----------------------------------------------------------

# policy is auto-promotable iff baseline_delta > 0 (strictly better, P1.7)
_POLICY_RULE = PromotionRule("policy", kind="eval", metric="baseline_delta",
                             threshold=0.0, comparator="gt")


def _matrix(delta, no_regression: bool = True, complete: bool = True) -> dict:
    m = {"baseline_delta": delta, "no_regression": no_regression, "complete": complete}
    return m


def _rules(*rules):
    """registry-style {type: [rules]} fed to the gate at construction (internal resolution)."""
    reg: dict[str, list] = {}
    for r in rules:
        reg.setdefault(r.candidate_type, []).append(r)
    return reg


# --- PromotionRule dataclass --------------------------------------------------

def test_promotion_rule_is_frozen_data():
    r = PromotionRule("policy", kind="eval", metric="baseline_delta", threshold=0.0, comparator="gt")
    assert r.metric == "baseline_delta"
    with pytest.raises((FrozenInstanceError, AttributeError)):
        r.metric = "x"


# --- gate: internal resolution (P0.2) -----------------------------------------

def test_gate_requires_callable_without_rules_param():
    """Kimi P0.2: evaluate() takes only (matrix, candidate_id) — no rules arg, bypass impossible."""
    gate = PromotionGate({})
    # passing a third positional would be a TypeError; calling normally works and is fail-closed
    assert gate.evaluate(_matrix(0.1), "policy@np@v1") in ("PROMOTE", "AWAIT_OPERATOR", "REJECT")


def test_unknown_candidate_type_no_rules_fail_closed():
    """No rules registered for a type -> no verified basis -> not PROMOTE (fail-closed)."""
    gate = PromotionGate({})
    assert gate.evaluate(_matrix(0.1), "policy@np@v1") != "PROMOTE"


def test_mandatory_operator_gates_always_applied():
    """MANDATORY_OPERATOR_GATES makes tool always AWAIT_OPERATOR even with a good eval (P0.2)."""
    assert "tool" in MANDATORY_OPERATOR_GATES
    gate = PromotionGate({})
    assert gate.evaluate(_matrix(0.9, no_regression=True), "tool@npm@v1") == "AWAIT_OPERATOR"


def test_promote_when_strictly_better_and_no_regression():
    gate = PromotionGate(_rules(_POLICY_RULE))
    assert gate.evaluate(_matrix(0.1, no_regression=True), "policy@np@v1") == "PROMOTE"


def test_reject_when_worse():
    gate = PromotionGate(_rules(_POLICY_RULE))
    assert gate.evaluate(_matrix(-0.1, no_regression=True), "policy@np@v1") == "REJECT"


def test_neutral_tie_not_promoted():
    """P1.7: exactly equal to baseline (delta 0.0) is a tie -> AWAIT_OPERATOR, not auto-promoted."""
    gate = PromotionGate(_rules(_POLICY_RULE))
    assert gate.evaluate(_matrix(0.0, no_regression=True), "policy@np@v1") == "AWAIT_OPERATOR"


def test_incomplete_matrix_fail_closed():
    """Plan-review P1.2: incomplete EvidenceMatrix is ALWAYS REJECT (never a weaker AWAIT either)."""
    gate = PromotionGate(_rules(_POLICY_RULE))
    assert gate.evaluate(_matrix(0.1, complete=False), "policy@np@v1") == "REJECT"


def test_default_comparator_is_strict_better():
    """Kimi Task4 P1: with the DEFAULT comparator (now 'gt'), a tie (delta=0) must NOT auto-promote."""
    default_rule = PromotionRule("policy", kind="eval", metric="baseline_delta", threshold=0.0)
    assert default_rule.comparator == "gt"  # default is strictly-better
    gate = PromotionGate(_rules(default_rule))
    assert gate.evaluate(_matrix(0.1), "policy@np@v1") == "PROMOTE"
    assert gate.evaluate(_matrix(0.0), "policy@np@v1") == "AWAIT_OPERATOR"  # tie not promoted


def test_mixed_case_type_prefix_normalized():
    """Kimi Task4 P2.1: 'Tool@...' / ' tool@...' must still hit MANDATORY_OPERATOR_GATES (no bypass)."""
    gate = PromotionGate({})
    assert gate.evaluate(_matrix(0.9), "Tool@script@v1") == "AWAIT_OPERATOR"
    assert gate.evaluate(_matrix(0.9), " tool@script@v1") == "AWAIT_OPERATOR"


def test_registered_operator_gate_rule_forces_await():
    """Kimi Task4 P2.2: a PromotionRule(kind='operator_gate') in the registry also forces AWAIT (not just tool)."""
    custom_gate = PromotionRule("sandbox-exec", kind="operator_gate", operator_scope="sandbox-exec")
    gate = PromotionGate(_rules(custom_gate))
    assert gate.evaluate(_matrix(0.9), "sandbox-exec@run@v1") == "AWAIT_OPERATOR"


def test_unknown_comparator_fails_closed():
    """Kimi Task4 P2.3: an unknown comparator in a rule -> REJECT (fail-closed), not an exception leak."""
    bad_rule = PromotionRule("policy", kind="eval", metric="baseline_delta", threshold=0.0, comparator="??")
    gate = PromotionGate(_rules(bad_rule))
    assert gate.evaluate(_matrix(0.1), "policy@np@v1") == "REJECT"


def test_unknown_rule_kind_fails_closed():
    """Kimi Task4 P3: an unknown rule.kind must NOT be silently fail-open — REJECT."""
    bad_rule = PromotionRule("policy", kind="evel", metric="baseline_delta", threshold=0.0)  # typo
    gate = PromotionGate(_rules(bad_rule))
    assert gate.evaluate(_matrix(0.1), "policy@np@v1") == "REJECT"

