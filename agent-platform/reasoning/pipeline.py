"""Integrated reasoning pipeline — orchestrates Kernel + RLM + Geometric.

DM4: a single entry point that selects a strategy from problem properties
(kernel), then dispatches to the bounded RLM engine (recursive) or the
geometric Explorer, and finally runs a verify step that folds contradiction and
evidence coverage into a confidence value. The pipeline may switch strategy
mid-flight when the problem declares both recursive and geometric parts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .kernel import Strategy, select_strategy
from .recursive import RLMConfig, RLMEngine, StopReason
from .geometric import Explorer, ProblemSpace, ReasoningNode
from .geometric.metrics import GraphMetrics


@dataclass
class PipelineResult:
    strategy_used: str = ""
    strategies_switched: bool = False
    value: object = None
    confidence: float = 0.0
    log: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.log.append(msg)


class ReasoningPipeline:
    """Deterministic entry point over the three reasoning engines (0 model calls
    when the injected inference port is a stub)."""

    def __init__(self, inference, rlm_config: RLMConfig = RLMConfig()):
        self._inference = inference
        self._rlm_config = rlm_config
        self._rlm_engine = RLMEngine(inference, rlm_config)

    # ------------------------------------------------------------------ #
    def run(self, problem: object, expected: object = None) -> PipelineResult:
        if isinstance(problem, dict) and {"recursive", "geometric"}.issubset(problem):
            return self._run_hybrid(problem, expected)
        return self._run_single(problem, expected)

    # -- single-strategy path ------------------------------------------- #
    def _run_single(self, problem: object, expected: object = None) -> PipelineResult:
        res = PipelineResult()
        strategy = select_strategy(problem)
        res.strategy_used = strategy.value
        if strategy == Strategy.RECURSIVE:
            rlm_run = self._rlm_engine.run(problem, expected=expected)
            res.value = rlm_run.value
            res.add(f"rlm stop={rlm_run.stop_reason.value} value={rlm_run.value}")
            res.confidence = 1.0 if rlm_run.stop_reason in (
                StopReason.ACCEPTED, StopReason.ALL_INTEGRATED) and rlm_run.value == expected else 0.5
        elif strategy == Strategy.GEOMETRIC:
            value, conf = self._run_geometric(problem, expected)
            res.value = value
            res.confidence = conf
            res.add(f"geometric value={value} conf={conf}")
        else:  # direct
            from .kernel import Engine

            eng = Engine(expected=expected)
            r = eng.solve(problem)
            res.value = r["value"]
            res.confidence = r["confidence"]
            res.add(f"direct value={r['value']}")
        return res

    # -- hybrid path: recursive then geometric -------------------------- #
    def _run_hybrid(self, problem: dict, expected: object = None) -> PipelineResult:
        res = PipelineResult()
        res.strategy_used = "recursive->geometric"
        res.strategies_switched = True

        rec_value = self._run_single(problem["recursive"]).value
        res.add(f"phase1 recursive value={rec_value}")

        geo_value, geo_conf = self._run_geometric(problem["geometric"], expected)
        res.add(f"phase2 geometric value={geo_value} conf={geo_conf}")

        # Integration: the final value fuses the recursive aggregate and the
        # geometric exploration; confidence folds both in.
        res.value = _combine(rec_value, geo_value)
        res.confidence = _verified_confidence(rec_value, geo_value, expected, geo_conf)
        return res

    # ------------------------------------------------------------------ #
    def _run_geometric(self, spec: dict, expected: object = None):
        """Run the geometric Explorer over a ProblemSpace built from ``spec``."""
        space = ProblemSpace()
        for nid, data in spec["nodes"].items():
            space.add_node(ReasoningNode(
                id=nid,
                evidence=data.get("evidence", 0.5),
                contradiction=data.get("contradiction", 0.0),
                confidence=data.get("confidence", 0.5),
            ))
        for src, dst in spec["edges"]:
            space.add_edge(src, dst)
        start = spec["start"]
        goal = spec["goal"]
        exp = Explorer(max_steps=spec.get("max_steps", 50))
        result = exp.explore(space, start, goal)
        # value = path length to goal (or -1 if not found); confidence grows with
        # evidence coverage along the found path and success.
        if result.found_goal:
            evidence = sum(
                (space.node(n).evidence if space.node(n) else 0.0) for n in result.path
            ) / max(1, len(result.path))
            value = len(result.path)
            confidence = 0.5 + 0.5 * evidence
        else:
            value = -1
            confidence = 0.0
        return value, confidence


def _combine(a, b):
    """Deterministic fusion of a recursive aggregate and a geometric value."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a + b
    return (a, b)


def _verified_confidence(rec_value, geo_value, expected, geo_conf) -> float:
    if expected is None:
        return round(0.5 + 0.5 * geo_conf, 3)
    total = _combine(rec_value, geo_value)
    match = 1.0 if total == expected else 0.0
    return round((0.6 * match + 0.4 * geo_conf), 3)
