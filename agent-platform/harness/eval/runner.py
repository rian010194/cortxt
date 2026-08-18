from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class EvalRoundResult:
    success: bool
    cost: float
    budget_exhausted: bool = False

    @property
    def rlm_success_for_pass_purposes(self) -> bool:
        return self.success and not self.budget_exhausted


@dataclass
class EvalClassResult:
    rounds: list[EvalRoundResult] = field(default_factory=list)
    rlm_pass: bool = False


def run_eval_class(fixture_generator: Callable[[int], object], n_variants: int,
                    run_rlm_fn: Callable[[object], EvalRoundResult],
                    run_baseline_fn: Callable[[object], EvalRoundResult],
                    cost_multiplier: float = 5.0) -> EvalClassResult:
    rounds: list[EvalRoundResult] = []
    for seed in range(1, n_variants + 1):
        fixture = fixture_generator(seed)
        baseline_result = run_baseline_fn(fixture)
        rlm_result = run_rlm_fn(fixture)

        budget_exhausted = False
        if baseline_result.cost > 0 and rlm_result.cost > cost_multiplier * baseline_result.cost:
            budget_exhausted = True

        rounds.append(EvalRoundResult(success=rlm_result.success, cost=rlm_result.cost,
                                       budget_exhausted=budget_exhausted))

    passes = sum(1 for r in rounds if r.rlm_success_for_pass_purposes)
    return EvalClassResult(rounds=rounds, rlm_pass=passes >= 2)
