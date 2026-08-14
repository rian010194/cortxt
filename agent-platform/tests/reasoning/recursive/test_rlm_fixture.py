"""RLM fixture test — mocked inference producing a larger nested structure."""

from reasoning.recursive import RLMConfig, RLMEngine, StopReason

from .test_bounds import SumStub

# Larger nested arithmetic structure than DM1's: full sum = 60.
BIG = [[1, 2, 3], [4, [5, 6]], [[7, 8], [9, [10, 5]]]]


def test_rlm_solves_larger_fixture_with_all_bounds():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_depth=8, max_total_children=32, max_model_invocations=64))
    run = eng.run(BIG, expected=60)
    assert run.value == 60
    assert run.stop_reason in (StopReason.ALL_INTEGRATED, StopReason.ACCEPTED)
    # every leaf invoked through the stub (0 real model calls)
    assert stub.calls >= 1
    assert run.model_invocations >= 1


def test_rlm_logs_bounds_used():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig())
    run = eng.run(BIG, expected=60)
    assert run.model_invocations >= 1
    assert run.context_reads >= 1
    assert len(run.log) >= 1  # leaf/integrate events recorded


def test_contradiction_detected_via_challenger():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_depth=8, max_total_children=32, max_model_invocations=64))
    # expect 999 but actual is 60 -> challenger raises contradiction + stop
    run = eng.run(BIG, expected=999)
    assert run.value == 60
    assert run.stop_reason == StopReason.CONTRADICTION
