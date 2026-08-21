from __future__ import annotations

from supervisor.budget import next_child_budget, reclaimable_surplus


def test_reclaimable_surplus_is_the_unused_portion():
    assert reclaimable_surplus(child_allocated=10, child_spent=6) == 4


def test_reclaimable_surplus_is_zero_when_fully_spent_or_overspent():
    assert reclaimable_surplus(child_allocated=10, child_spent=10) == 0
    assert reclaimable_surplus(child_allocated=10, child_spent=11) == 0


def test_next_child_budget_adds_reclaimed_surplus_to_base():
    assert next_child_budget(base_allocation=5, reclaimed_surplus=4) == 9


# -- split_rlm_config (Phase 5) ------------------------------------------- #
from reasoning.recursive.bounds import RLMConfig
from supervisor.budget import split_rlm_config


def test_split_total_children_uses_the_REMAINING_pool_after_n_direct_spawns():
    # spec's combinatorics (decision 2): spawning n=3 direct children consumes
    # 3 of a max_total_children=6 pool; only the remainder (3) is available
    # for those children's OWN further decomposition. split_rlm_config must
    # divide (parent.max_total_children - n), not the full parent value —
    # dividing the full value would let each of 3 children spawn up to 2
    # grandchildren (6 more, 9 total), contradicting the spec's narrow-tree
    # analysis (at most ~1 grandchild per child).
    parent = RLMConfig(max_total_children=6, max_model_invocations=20,
                        max_context_reads=30, max_runtime_seconds=60.0,
                        max_cost=1.0, max_output_size=4096)
    children = split_rlm_config(parent, 3)
    assert len(children) == 3
    assert sum(c.max_total_children for c in children) == 3  # 6 - 3 spawned, not 6
    assert [c.max_total_children for c in children] == [1, 1, 1]
    # unchanged, non-splittable fields carry through unchanged
    for c in children:
        assert c.max_branches_per_node == parent.max_branches_per_node
        assert c.explicit_stop_policy == parent.explicit_stop_policy


def test_split_other_five_bounds_divide_the_full_parent_value():
    # max_model_invocations/max_context_reads/max_runtime_seconds/max_cost/
    # max_output_size are consumable resources, not a "spawn slot count" —
    # spawning a child does not itself consume one, so these five divide the
    # full parent value n ways (unlike max_total_children above).
    parent = RLMConfig(max_total_children=6, max_model_invocations=20,
                        max_context_reads=30, max_runtime_seconds=60.0,
                        max_cost=1.0, max_output_size=4096)
    children = split_rlm_config(parent, 3)
    assert sum(c.max_model_invocations for c in children) == 20
    assert sum(c.max_context_reads for c in children) == 30
    assert abs(sum(c.max_runtime_seconds for c in children) - 60.0) < 1e-9
    assert abs(sum(c.max_cost for c in children) - 1.0) < 1e-9
    assert sum(c.max_output_size for c in children) == 4096


def test_split_total_children_floors_at_zero_when_n_exceeds_the_pool():
    # spawning n=6 direct children from a max_total_children=6 pool leaves
    # nothing for any of them to further decompose with — they must be leaves.
    parent = RLMConfig(max_total_children=6)
    children = split_rlm_config(parent, 6)
    assert all(c.max_total_children == 0 for c in children)


def test_split_remainder_of_the_five_resource_bounds_goes_to_first_child():
    parent = RLMConfig(max_output_size=7)
    children = split_rlm_config(parent, 3)
    assert [c.max_output_size for c in children] == [3, 2, 2]
