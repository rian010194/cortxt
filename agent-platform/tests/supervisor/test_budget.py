from __future__ import annotations

from supervisor.budget import next_child_budget, reclaimable_surplus


def test_reclaimable_surplus_is_the_unused_portion():
    assert reclaimable_surplus(child_allocated=10, child_spent=6) == 4


def test_reclaimable_surplus_is_zero_when_fully_spent_or_overspent():
    assert reclaimable_surplus(child_allocated=10, child_spent=10) == 0
    assert reclaimable_surplus(child_allocated=10, child_spent=11) == 0


def test_next_child_budget_adds_reclaimed_surplus_to_base():
    assert next_child_budget(base_allocation=5, reclaimed_surplus=4) == 9
