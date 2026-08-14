"""Reasoning orchestrator — lifecycle around the pipeline.

init -> run -> verify -> finalize. Stops at a terminal state or
human_escalation. Deterministic; the pipeline handles strategy selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .kernel import Strategy, select_strategy
from .pipeline import ReasoningPipeline


@dataclass
class OrchestrationResult:
    terminal: bool = False
    human_escalated: bool = False
    strategy_used: str = ""
    final_value: object = None
    final_confidence: float = 0.0
    transcript: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.transcript.append(msg)


class ReasoningOrchestrator:
    """Bounded lifecycle for a single reasoning job."""

    def __init__(self, inference, rlm_config=None):  # rlm_config imported lazily
        from .recursive import RLMConfig

        self._pipeline = ReasoningPipeline(inference, rlm_config or RLMConfig())

    def run(self, problem: object, expected: object = None) -> OrchestrationResult:
        out = OrchestrationResult()
        is_hybrid = isinstance(problem, dict) and {"recursive", "geometric"}.issubset(problem)
        # CP4.1 fix (P2): log the true entry strategy ("hybrid") for hybrid problems.
        strat = select_strategy(problem) if not is_hybrid else Strategy.RECURSIVE
        out.add(f"init strategy={'hybrid' if is_hybrid else (strat.value or 'unknown')}")

        # human-escalation trigger: an explicit marker demands operator material decision
        if isinstance(problem, dict) and problem.get("escalate"):
            out.human_escalated = True
            out.terminal = True
            out.add("human_escalation requested")
            return out

        res = self._pipeline.run(problem, expected=expected)
        out.final_value = res.value
        out.final_confidence = res.confidence
        out.strategy_used = res.strategy_used
        out.add(f"run strategy_used={res.strategy_used} switched={res.strategies_switched}")

        # verify/finalize: a job is terminal when confidence is decisive OR
        # expected is provided and matched cleanly.
        if res.confidence >= 0.6 or (expected is not None and res.value == expected):
            out.terminal = True
            out.add(f"finalize terminal confidence={res.confidence}")
        else:
            out.add(f"finalize non-terminal confidence={res.confidence}")
        return out
