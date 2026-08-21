"""TrajectoryReport tests (Phase 6, Task 7). Determinism + serialization contract."""

import json

import pytest

from reasoning.geometric import ProblemSpace, ReasoningNode, TrajectoryReport
from reasoning.geometric.trajectory import apply_confidence_update


def _report():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", evidence=0.9, contradiction=0.0, node_type="claim",
                            metadata={"provenance": "p1", "data_class": "L0"}))
    s.add_node(ReasoningNode(id="goal", evidence=0.9, contradiction=0.0, node_type="goal"))
    s.add_edge("a", "goal", rel_type="supports")
    return TrajectoryReport(
        space=s,
        path=["a", "goal"],
        goal="goal",
        path_score=0.75,
        policy_version="v1",
        attractor_nodes=[],
        contradictions=[],
    )


def test_to_json_is_deterministic():
    r1 = _report().to_json()
    r2 = _report().to_json()
    assert r1 == r2  # same space+path+scoring -> identical serialization


def test_to_json_contains_nodes_edges_and_metadata():
    data = json.loads(_report().to_json())
    assert data["version"] == "v1"
    ids = [n["id"] for n in data["nodes"]]
    assert "a" in ids and "goal" in ids
    # metadata + node_type included
    a = next(n for n in data["nodes"] if n["id"] == "a")
    assert a["node_type"] == "claim"
    assert a["metadata"]["data_class"] == "L0"
    # edges with types
    assert any((e["src"], e["dst"]) == ("a", "goal") for e in data["edges"])
    assert any("supports" in e["types"] for e in data["edges"] if (e["src"], e["dst"]) == ("a", "goal"))


def test_report_metadata_fields_present():
    data = json.loads(_report().to_json())
    assert data["goal"] == "goal"
    assert data["path_score"] == 0.75
    assert data["policy_version"] == "v1"
    assert data["path"] == ["a", "goal"]


def test_render_text_contains_path_and_score():
    text = _report().render_text()
    assert "a" in text and "goal" in text
    assert "0.75" in text


def test_apply_confidence_update_returns_measured_gain_and_mutates_node():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", confidence=0.4))
    gain = apply_confidence_update(s, "a", 0.9)
    assert gain == pytest.approx(0.5)  # real |after - before|, not a proxy
    assert s.node("a").confidence == 0.9  # mutated in place


def test_apply_confidence_update_unknown_node_is_noop_zero_gain():
    s = ProblemSpace()
    assert apply_confidence_update(s, "missing", 0.9) == 0.0


def test_trajectory_report_records_information_gains():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", confidence=0.4))
    s.add_node(ReasoningNode(id="goal", confidence=0.5))
    s.add_edge("a", "goal", rel_type="supports")
    report = TrajectoryReport(space=s, path=["a", "goal"], goal="goal")
    gain = apply_confidence_update(s, "a", 0.9)
    report.information_gains["a"] = gain

    data = json.loads(report.to_json())
    assert data["information_gains"] == {"a": pytest.approx(0.5)}
    assert "information_gains" in report.render_text()
