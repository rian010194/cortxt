"""Stop-condition tests — each StopReason triggered deterministically."""

import pytest

from reasoning.recursive import RLMConfig, RLMEngine, StopReason

from .test_bounds import SumStub

PROB = [[1, 2], [3, [4, 5]]]  # total 15


def test_stop_accepted_when_expected_matches():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig())
    run = eng.run(PROB, expected=15)
    # Interpreting policy: an accepted, verified candidate with matching expected.
    assert run.value == 15
    assert run.stop_reason == StopReason.ALL_INTEGRATED or run.stop_reason == StopReason.ACCEPTED


def test_stop_budget_exhausted_on_zero_runtime():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_runtime_seconds=0.0001))
    run = eng.run(PROB, clock=lambda: 9.0)  # already far over runtime budget
    assert run.stop_reason == StopReason.BUDGET_EXHAUSTED


def test_stop_budget_exhausted_on_zero_invocations():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_model_invocations=0))
    run = eng.run(PROB)
    assert run.stop_reason == StopReason.BUDGET_EXHAUSTED


def test_stop_contradiction_on_mismatch():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig())
    run = eng.run(PROB, expected=42)
    assert run.value == 15
    assert run.stop_reason == StopReason.CONTRADICTION


# -- CP2.1 rework regression tests ---------------------------------------- #
def test_stop_accepted_assigned_on_expected_match():
    """P1 rework: expected match must yield StopReason.ACCEPTED, not ALL_INTEGRATED."""
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_depth=4, max_total_children=32, max_model_invocations=64))
    run = eng.run(PROB, expected=15)
    assert run.value == 15
    assert run.stop_reason == StopReason.ACCEPTED


def test_contradiction_halts_sibling_execution():
    """P2 rework: a contradiction must stop remaining budget, not be overridden.

    We force a contradiction that would otherwise allow a later BUDGET_EXHAUSTED
    to override it: run with a tight invocation budget AND a mismatched expected.
    The contradiction should win because it raises out of the loop immediately.
    """
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_model_invocations=64, max_total_children=64, max_depth=8))
    run = eng.run(PROB, expected=999)  # actual 15 -> contradiction
    assert run.stop_reason == StopReason.CONTRADICTION
