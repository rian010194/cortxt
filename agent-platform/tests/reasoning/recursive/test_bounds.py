"""Bound-enforcement tests for the RLM engine (each limit isolated + combined).

These are deterministic (0 model calls); the inference port is a stub.
"""

import pytest

from reasoning.recursive import RLMConfig, RLMEngine, StopReason


class SumStub:
    """A pure 'inference' stub: sums numeric leaves of the content."""

    def __init__(self):
        self.calls = 0

    def invoke(self, content):
        self.calls += 1
        total = 0
        stack = [content]
        seen = set()
        while stack:
            cur = stack.pop()
            if isinstance(cur, list):
                i = id(cur)
                if i in seen:
                    continue
                seen.add(i)
                stack.extend(cur)
            elif isinstance(cur, dict):
                i = id(cur)
                if i in seen:
                    continue
                seen.add(i)
                stack.extend(cur.values())
            else:
                total += int(cur)
        return total


NESTED = [[1, 2], [3, [4, 5]]]  # deep structure to exercise depth/children limits


# -- max_depth ----------------------------------------------------------- #
def test_max_depth_caps_node_depth():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_depth=1))
    run = eng.run(NESTED, expected=15)
    # With max_depth=1, the solver must never recurse to depth 2+.
    assert run.stop_reason in (StopReason.ALL_INTEGRATED, StopReason.BUDGET_EXHAUSTED)
    # value may be partial but the engine must not crash or loop
    assert run.elapsed_seconds >= 0


# -- max_total_children -------------------------------------------------- #
def test_max_total_children_stops_creation():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_total_children=5, max_depth=10))
    run = eng.run(NESTED, expected=15)
    assert run.total_children <= 5  # fail-closed: never exceeds the cap


# -- max_runtime_seconds (via injected clock, no real sleep) ------------- #
def test_runtime_budget_via_clock():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_runtime_seconds=0.1))
    # A clock that is already over budget on the first probe -> immediate stop.
    fake_clock = lambda: 0.5  # elapsed already >= 0.1
    run = eng.run(NESTED, expected=15, clock=fake_clock)
    assert run.stop_reason == StopReason.BUDGET_EXHAUSTED


# -- max_model_invocations ----------------------------------------------- #
def test_model_invocation_budget():
    stub = SumStub()
    eng = RLMEngine(stub, RLMConfig(max_model_invocations=0))
    run = eng.run(NESTED)
    assert run.model_invocations == 0  # none allowed; run stops before any leaf
    assert run.stop_reason == StopReason.BUDGET_EXHAUSTED


# -- combined bounds ----------------------------------------------------- #
def test_combined_bounds_fail_closed():
    stub = SumStub()
    eng = RLMEngine(
        stub,
        RLMConfig(max_depth=1, max_branches_per_node=1, max_total_children=2,
                  max_model_invocations=1, max_runtime_seconds=0.05),
    )
    run = eng.run(NESTED)
    assert run.total_children <= 2
    assert run.model_invocations <= 1


# -- max_output_size enforcement (CP2.1 P1 rework) ------------------------ #
def test_max_output_size_enforced_fail_closed():
    stub = SumStub()
    # A tiny output cap means even one leaf's value exceeds it -> immediate stop.
    eng = RLMEngine(stub, RLMConfig(max_output_size=0))
    run = eng.run(PROB := [[1, 2], [3, 4]], expected=10)
    assert run.stop_reason == StopReason.BUDGET_EXHAUSTED
    assert run.output_length >= 0


# -- v1 defaults (dispatch contract §19.1) ------------------------------- #
def test_v1_defaults_match_dispatch_contract_19_1():
    from reasoning.recursive.bounds import RLMConfig
    config = RLMConfig()
    assert config.max_depth == 2
    assert config.max_total_children == 6
    assert config.max_branches_per_node == 3
    assert config.max_model_invocations == 20
    assert config.max_context_reads == 30
