"""Model-assisted strategy: additive extension, does not touch DM1's numeric solvers.

AC: inspect delegates to an injected callable (no arithmetic), verify delegates
to an injected validator (no fallback summation), and existing solve() behavior
for DIRECT/RECURSIVE/GEOMETRIC content is completely unaffected.
"""
from reasoning.kernel import Engine, Strategy
from reasoning.kernel.operators import inspect_with_model, verify_against_schema
from reasoning.kernel.problem_state import new_problem


def test_inspect_with_model_delegates_to_callable():
    state = new_problem({"case_id": "SYNTH-1"})
    result = inspect_with_model(state, invoke=lambda content: {"classification": "high_risk"})
    assert result.value == {"classification": "high_risk"}
    assert state._computed == {"classification": "high_risk"}
    assert "inspect_with_model" in state.transformation_log[-1]


def test_verify_against_schema_true():
    state = new_problem({"case_id": "SYNTH-1"})
    state._computed = {"classification": "high_risk"}
    result = verify_against_schema(state, validate=lambda v: v["classification"] == "high_risk")
    assert result.value == {"classification": "high_risk"}
    assert state.confidence == 1.0


def test_verify_against_schema_false_does_not_fall_back_to_arithmetic():
    state = new_problem({"case_id": "SYNTH-1"})
    state._computed = {"classification": "wrong"}
    result = verify_against_schema(state, validate=lambda v: v["classification"] == "high_risk")
    assert state.confidence == 0.0
    assert result.value == {"classification": "wrong"}  # unchanged, no summation attempted


def test_engine_solve_model_assisted_end_to_end():
    engine = Engine()
    result = engine.solve_model_assisted(
        content={"case_id": "SYNTH-1"},
        invoke=lambda content: {"classification": "high_risk"},
        validate=lambda v: v.get("classification") == "high_risk",
    )
    assert result["strategy"] == "model_assisted"
    assert result["value"] == {"classification": "high_risk"}
    assert result["confidence"] == 1.0
    assert len(result["steps"]) == 2  # inspect_with_model, verify_against_schema


def test_existing_direct_strategy_unaffected():
    # Regression guard: DM1's numeric solve() must still work exactly as before.
    engine = Engine()
    result = engine.solve([1, 2, 3])
    assert result["strategy"] == "direct"
    assert result["value"] == 6
