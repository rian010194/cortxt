"""DM4 integration fixture — a problem needing both RLM decomposition and
geometric alternative-path exploration; the pipeline must switch strategy."""

from reasoning import ReasoningOrchestrator, ReasoningPipeline


class SumStub:
    def invoke(self, content):
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


def hybrid_problem():
    return {
        # recursive part: nested sum -> 6
        "recursive": [[1, 2], [3]],
        "geometric": {
            "start": "A",
            "goal": "Z",
            "nodes": {
                "A": {"evidence": 0.5}, "B": {"evidence": 0.1, "contradiction": 0.8},
                "C": {"evidence": 0.9}, "D": {"evidence": 0.9}, "Z": {"evidence": 0.9},
            },
            "edges": [("A", "B"), ("B", "Z"), ("A", "C"), ("C", "D"), ("D", "Z")],
            "max_steps": 10,
        },
    }


def test_pipeline_switches_strategy_at_least_once():
    pipe = ReasoningPipeline(SumStub())
    res = pipe.run(hybrid_problem())
    assert res.strategies_switched is True
    assert res.strategy_used == "recursive->geometric"
    # recursive sum (6) + geometric path length (A->C->D->Z = 4) = 10
    assert res.value == 10


def test_pipeline_confidence_above_threshold():
    pipe = ReasoningPipeline(SumStub())
    res = pipe.run(hybrid_problem())
    assert res.confidence > 0.5


def test_orchestrator_terminal_on_expected():
    orch = ReasoningOrchestrator(SumStub())
    out = orch.run(hybrid_problem(), expected=10)
    assert out.terminal is True
    assert out.final_value == 10
    assert any("finalize terminal" in m for m in out.transcript)


def test_orchestrator_human_escalation():
    orch = ReasoningOrchestrator(SumStub())
    out = orch.run({"escalate": True}, expected=None)
    assert out.human_escalated is True
    assert out.terminal is True


def test_orchestrator_non_terminal_on_ambiguous():
    orch = ReasoningOrchestrator(SumStub())
    out = orch.run([1, 2, 3], expected=999)  # direct, wrong expected -> low confidence
    assert out.terminal is False


def test_geometric_contradiction_lowers_pipeline_confidence():
    """CP4.1 P1 regression: a high-contradiction route must lower confidence vs a
    clean route with equal evidence (pipeline folds contradiction into geometric)."""
    pipe = ReasoningPipeline(SumStub())
    clean = pipe.run({
        "recursive": [[1], [1]],
        "geometric": {
            "start": "A", "goal": "Z",
            "nodes": {"A": {"evidence": 0.9}, "R": {"evidence": 0.9},
                      "Z": {"evidence": 0.9}},
            "edges": [("A", "R"), ("R", "Z")],
        },
    })
    contradict = pipe.run({
        "recursive": [[1], [1]],
        "geometric": {
            "start": "A", "goal": "Z",
            "nodes": {"A": {"evidence": 0.9},
                      "R": {"evidence": 0.9, "contradiction": 0.9},
                      "Z": {"evidence": 0.9}},
            "edges": [("A", "R"), ("R", "Z")],
        },
    })
    assert contradict.confidence < clean.confidence
