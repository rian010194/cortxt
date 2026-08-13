"""RLMEngine — bounded recursive decomposition loop (target architecture §11)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from ..kernel import ProblemState, new_problem
from .bounds import RLMConfig
from .challenger import ChallengeResult, challenge
from .decomposer import decompose_state
from .integrator import integrate_results
from .stop_conditions import StopReason


class InferencePort(Protocol):
    """A model-invocation surface the engine depends on (never called directly).

    For this DM2 slice every caller injects a stub; the engine never opens a real
    provider connection. Mirrors the boundary `cortxt-resilient-inference` exposes.
    """

    def invoke(self, content: Any) -> int:
        """Return a computed value for ``content`` (a stub must be pure)."""
        ...


# A clock returns elapsed seconds since engine start; injectable for tests.
Clock = Callable[[], float]


@dataclass
class RLMRun:
    """Result envelope of a single RLM run."""

    value: Optional[int] = None
    stop_reason: StopReason = StopReason.ALL_INTEGRATED
    model_invocations: int = 0
    context_reads: int = 0
    total_children: int = 0
    elapsed_seconds: float = 0.0
    cost: float = 0.0
    output_length: int = 0
    log: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.log.append(msg)


class BudgetExhausted(Exception):
    """Raised when any hard resource bound would be exceeded (fail-closed)."""


class MaxDepthError(BudgetExhausted):
    pass


class ContradictionError(BudgetExhausted):
    """Raised on a material contradiction so it halts sibling branches."""


class RLMEngine:
    """Deterministic bounded recursive solver.

    All hard limits from ``RLMConfig`` are enforced lazily and fail-closed: the
    moment any bound would be exceeded the run either prunes the branch or stops,
    and a resource-leak manifests as a raised error (so a determinististic test
    can prove the bound).
    """

    def __init__(self, inference: InferencePort, config: RLMConfig = RLMConfig()):
        config.validate()
        self._inference = inference
        self._config = config
        self._start = time.monotonic()
        self._clock: Clock = lambda: time.monotonic() - self._start

    # -- metering --------------------------------------------------------- #
    def _elapsed(self) -> float:
        return self._clock()

    # -- public entry ----------------------------------------------------- #
    def run(self, content: Any, expected=None, *, clock: Optional[Clock] = None,
            base_cost_per_call: float = 0.0) -> RLMRun:
        if clock is not None:
            self._clock = clock
        root = new_problem(content)
        run = RLMRun()
        try:
            self._solve(root, run, depth=0, expected=expected, base_cost=base_cost_per_call)
        except ContradictionError:
            run.stop_reason = StopReason.CONTRADICTION
        except BudgetExhausted:
            run.stop_reason = StopReason.BUDGET_EXHAUSTED
        run.value = getattr(root, "_computed", None)
        run.elapsed_seconds = self._elapsed()
        run.output_length = len(str(run.value or 0))
        return run

    # -- core loop -------------------------------------------------------- #
    def _solve(self, state: ProblemState, run: RLMRun, depth: int, expected, base_cost: float) -> None:
        if depth > self._config.max_depth:
            raise MaxDepthError(f"depth {depth} exceeds max_depth={self._config.max_depth}")

        if self._elapsed() >= self._config.max_runtime_seconds:
            raise BudgetExhausted("runtime budget")
        # model-invocation budget
        if run.model_invocations >= self._config.max_model_invocations:
            raise BudgetExhausted("model_invocations")
        if run.context_reads >= self._config.max_context_reads:
            raise BudgetExhausted("context_reads")
        if run.cost >= self._config.max_cost:
            raise BudgetExhausted("cost")
        if run.total_children >= self._config.max_total_children:
            raise BudgetExhausted("total_children")
        if run.output_length >= self._config.max_output_size:
            raise BudgetExhausted("output_size")

        remaining_children = max(0, self._config.max_total_children - run.total_children)
        children = decompose_state(state, self._config.max_branches_per_node,
                                   max_children=remaining_children)
        run.total_children += len(children)

        if not children:
            # leaf: invoke inference once (a "model invocation") and record usage
            run.model_invocations += 1
            run.context_reads += 1
            run.cost += base_cost
            state._computed = self._inference.invoke(state.content)  # type: ignore[attr-defined]
            run.output_length += len(str(state._computed))
            run.add(f"leaf {state.id} -> {state._computed}")
            return

        for child in children:
            self._solve(child, run, depth + 1, expected=None, base_cost=base_cost)
            run.context_reads += 1  # reading a child result counts as a context read

        value = integrate_results(state)
        run.output_length += len(str(value))
        run.add(f"integrate {state.id} -> {value}")

        # challenger (deterministic)
        res: ChallengeResult = challenge(state, expected)
        if res.contradiction and self._config.explicit_stop_policy:
            run.add(f"challenge contradiction on {state.id}: {res.message}")
            raise ContradictionError(res.message)
        if expected is not None and res.ok:
            run.stop_reason = StopReason.ACCEPTED
            run.add(f"accepted on {state.id} (expected {expected})")
