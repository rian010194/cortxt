"""CODING_ASSISTED: additive extension, injected callables only, zero new imports.

Same shape as Fas 2's test_model_assisted.py — the operators must delegate and
never do hidden work of their own, and every existing solver must be unaffected.
"""
from __future__ import annotations
from reasoning.kernel import Engine, Strategy
from reasoning.kernel.operators import (
    falsify_fix,
    inspect_diff_against_scope,
    propose_minimal_patch,
)
from reasoning.kernel.problem_state import new_problem

PROPOSAL = {
    "changes": [{"path": "ranges.py", "new_content": "def sum_to(n):\n    return n\n"}],
    "rationale": "off by one",
    "diff": "--- baseline/ranges.py\n+++ work/ranges.py\n",
    "files_changed": ["ranges.py"],
    "changed_lines": 2,
}


def test_strategy_member_exists_with_the_expected_value():
    assert Strategy.CODING_ASSISTED.value == "coding_assisted"


def test_propose_minimal_patch_delegates_to_the_callable():
    state = new_problem({"workspace_map": {"file_count": 1}})
    result = propose_minimal_patch(state, propose=lambda content: PROPOSAL)
    assert result.value == PROPOSAL
    assert state._computed == PROPOSAL
    assert "propose_minimal_patch" in state.transformation_log[-1]


def test_inspect_diff_against_scope_sets_confidence_one_when_in_scope():
    state = new_problem({})
    state._computed = PROPOSAL
    result = inspect_diff_against_scope(state, inspect_scope=lambda record: True)
    assert state.confidence == 1.0
    assert result.value == PROPOSAL


def test_inspect_diff_against_scope_records_scope_expansion_when_out_of_scope():
    state = new_problem({})
    state._computed = PROPOSAL
    inspect_diff_against_scope(state, inspect_scope=lambda record: False)
    assert state.confidence == 0.0
    assert "scope_expansion" in state.transformation_log[-1]


def test_falsify_fix_sets_confidence_one_only_when_the_verifier_says_so():
    state = new_problem({})
    state._computed = PROPOSAL
    falsify_fix(state, verify=lambda record: True)
    assert state.confidence == 1.0

    other = new_problem({})
    other._computed = PROPOSAL
    falsify_fix(other, verify=lambda record: False)
    assert other.confidence == 0.0


def test_operators_never_invent_a_value_of_their_own():
    """No hidden arithmetic, no fallback — same assertion Fas 2 made about
    inspect_with_model / verify_against_schema."""
    state = new_problem({"values": [1, 2, 3]})
    state._computed = PROPOSAL
    assert falsify_fix(state, verify=lambda record: False).value == PROPOSAL


def test_engine_solve_coding_assisted_end_to_end():
    engine = Engine()
    result = engine.solve_coding_assisted(
        content={"workspace_map": {"file_count": 1}},
        propose=lambda content: PROPOSAL,
        inspect_scope=lambda record: True,
        verify=lambda record: True,
    )
    assert result["strategy"] == "coding_assisted"
    assert result["value"] == PROPOSAL
    assert result["confidence"] == 1.0
    assert len(result["steps"]) == 3  # propose, inspect_diff_against_scope, falsify_fix


def test_engine_short_circuits_falsify_when_the_scope_check_fails():
    """An out-of-scope patch must never reach the sandbox."""
    verify_calls: list[object] = []
    engine = Engine()
    result = engine.solve_coding_assisted(
        content={},
        propose=lambda content: PROPOSAL,
        inspect_scope=lambda record: False,
        verify=lambda record: verify_calls.append(record) or True,
    )
    assert result["confidence"] == 0.0
    assert verify_calls == []
    assert len(result["steps"]) == 2  # falsify_fix never ran


def test_select_strategy_never_returns_coding_assisted():
    from reasoning.kernel.strategy import select_strategy

    for content in ([1, 2, 3], [[1], [2]], {"constraints": {"a": 1}}, {"changes": []}):
        assert select_strategy(content) is not Strategy.CODING_ASSISTED


def test_existing_solvers_are_unaffected():
    engine = Engine()
    assert engine.solve([1, 2, 3])["strategy"] == "direct"
    assert engine.solve([1, 2, 3])["value"] == 6
    model_assisted = engine.solve_model_assisted(
        content={"case_id": "SYNTH-1"},
        invoke=lambda content: {"classification": "high_risk"},
        validate=lambda value: value.get("classification") == "high_risk",
    )
    assert model_assisted["strategy"] == "model_assisted"
    assert model_assisted["confidence"] == 1.0
