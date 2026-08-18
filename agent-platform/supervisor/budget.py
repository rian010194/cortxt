"""Post-hoc budget rollover between sequential children (design spec decision
7). Only unused surplus from an already-terminal child rolls forward; there is
no mid-flight borrowing, since Fas 4 v0.1's M1/M2 scenarios never run two
children that both need to draw against the same pool concurrently.
"""
from __future__ import annotations


def reclaimable_surplus(child_allocated: int, child_spent: int) -> int:
    if child_spent >= child_allocated:
        return 0
    return child_allocated - child_spent


def next_child_budget(base_allocation: int, reclaimed_surplus: int) -> int:
    return base_allocation + reclaimed_surplus


def _split_int(total: int, n: int) -> list[int]:
    base, remainder = divmod(total, n)
    return [base + (1 if i < remainder else 0) for i in range(n)]


def _split_float(total: float, n: int) -> list[float]:
    share = total / n
    shares = [share] * n
    shares[0] += total - sum(shares)  # remainder to first child, avoids fp drift loss
    return shares


def split_rlm_config(config: RLMConfig, n: int) -> list[RLMConfig]:
    """Disjointly divide all eight §11.2 bounds across n children.

    depth is NOT touched here — the caller (Coordinator.run_node, Task 6)
    increments depth per level; this function only splits per-level budget.

    max_total_children is special: spawning n direct children consumes n
    slots of the parent's own pool, so only the REMAINDER
    (config.max_total_children - n, floored at 0) is available for those
    children's own further decomposition — matches the spec's combinatorial
    analysis (beslut 2). The other five bounds are consumable resources, not
    spawn-slot counts, so they divide the parent's full value n ways.
    """
    from reasoning.recursive.bounds import RLMConfig as _RLMConfig
    remaining_total_children = max(0, config.max_total_children - n)
    total_children = _split_int(remaining_total_children, n)
    model_invocations = _split_int(config.max_model_invocations, n)
    context_reads = _split_int(config.max_context_reads, n)
    runtime_seconds = _split_float(config.max_runtime_seconds, n)
    cost = _split_float(config.max_cost, n)
    output_size = _split_int(config.max_output_size, n)

    return [
        _RLMConfig(
            max_depth=config.max_depth,
            max_branches_per_node=config.max_branches_per_node,
            max_total_children=total_children[i],
            max_model_invocations=model_invocations[i],
            max_context_reads=context_reads[i],
            max_runtime_seconds=runtime_seconds[i],
            max_cost=cost[i],
            max_output_size=output_size[i],
            explicit_stop_policy=config.explicit_stop_policy,
        )
        for i in range(n)
    ]
