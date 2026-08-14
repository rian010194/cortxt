"""Operator isolation tests — each operator against a mock state (DM1 AC)."""

import pytest

from reasoning.kernel import ProblemState, new_problem
from reasoning.kernel.operators import OperatorResult, decompose, inspect, integrate, verify


class TestInspect:
    def test_inspect_returns_flat_scalars_and_logs(self):
        state = new_problem([1, [2, 3]])
        res = inspect(state)
        assert isinstance(res, OperatorResult)
        assert res.value == [1, 2, 3]
        assert state.applied_operator == "inspect"
        assert any("inspect" in s for s in state.transformation_log)


class TestDecompose:
    def test_decompose_creates_children_nested(self):
        state = new_problem([[1, 2], [3, 4]])
        decompose(state)
        assert len(state.children) == 2
        assert all(c.parent is state for c in state.children)
        assert any(s.startswith("decompose") for s in state.transformation_log)

    def test_decompose_uses_branches_key_when_present(self):
        state = new_problem({"branches": [[1], [2], [3]]})
        decompose(state)
        assert len(state.children) == 3


class TestIntegrate:
    def test_integrate_folds_child_computed_values(self):
        state = new_problem([[1, 2], [3, 4]])
        parent = state
        # simulate children already verified
        c1 = ProblemState(content=[1, 2]); c1._computed = 3  # noqa: SLF001
        c2 = ProblemState(content=[3, 4]); c2._computed = 7  # noqa: SLF001
        parent.add_child(c1); parent.add_child(c2)
        res = integrate(parent)
        assert res.value == 10
        assert parent._computed == 10  # noqa: SLF001  (fixed: was a vacuous assertion)


class TestVerify:
    def test_verify_sets_confidence_1_on_match(self):
        state = new_problem([1, 2, 3, 4, 5])
        res = verify(state, expected=15)
        assert res.value == 15
        assert state.confidence == 1.0

    def test_verify_sets_confidence_0_on_mismatch(self):
        state = new_problem([1, 2, 3])
        verify(state, expected=99)
        assert state.confidence == 0.0
