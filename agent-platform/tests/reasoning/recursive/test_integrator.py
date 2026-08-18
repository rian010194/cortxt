"""Focused tests for integrator fallback + robustness (boost coverage on the
_content_sum path, which the RLM fixture rarely exercises)."""

from reasoning.kernel import ProblemState, new_problem
from reasoning.recursive.integrator import integrate_results, _content_sum


def test_integrate_uses_children_computed_when_present():
    parent = new_problem([[1, 2], [3, 4]])
    c1 = ProblemState(content=[1, 2]); c1._computed = 3  # noqa: SLF001
    c2 = ProblemState(content=[3, 4]); c2._computed = 7  # noqa: SLF001
    parent.add_child(c1); parent.add_child(c2)
    assert integrate_results(parent) == 10
    assert parent._computed == 10  # noqa: SLF001


def test_integrate_falls_back_to_content_sum_when_no_computed():
    """A child with no _computed must fall back to summing its content."""
    parent = new_problem([[1, 2], [3, 4]])
    c1 = ProblemState(content=[1, 2])          # no _computed
    c2 = ProblemState(content=[3, 4]); c2._computed = 7  # noqa: SLF001
    parent.add_child(c1); parent.add_child(c2)  # 1+2 + 7 = 10
    assert integrate_results(parent) == 10
    assert c1._computed == 3  # noqa: SLF001  (fallback stored)


def test_content_sum_handles_nested_and_dict():
    assert _content_sum([1, [2, 3]]) == 6
    assert _content_sum({"a": 1, "b": {"c": 2}}) == 3


def test_content_sum_ignores_non_numeric():
    assert _content_sum([1, "x", None, 2]) == 3


def test_content_sum_cyclic_list_terminates():
    a = []
    a.append(a)  # cyclic
    a.append(5)
    assert _content_sum(a) == 5


def test_integrate_excludes_lost_child_and_marks_incomplete():
    parent = ProblemState(content={"branches": []})
    ok_child = ProblemState(content=5)
    ok_child._computed = 5
    lost_child = ProblemState(content=99)  # no ._computed — simulates a lost child
    parent.add_child(ok_child)
    parent.add_child(lost_child)

    total = integrate_results(parent, lost_children={lost_child.id})

    assert total == 5  # lost_child excluded, not summed via _content_sum fallback
    assert parent._incomplete is True


def test_integrate_stays_complete_when_no_children_lost():
    parent = ProblemState(content={"branches": []})
    child = ProblemState(content=5)
    child._computed = 5
    parent.add_child(child)

    total = integrate_results(parent)

    assert total == 5
    assert parent._incomplete is False
