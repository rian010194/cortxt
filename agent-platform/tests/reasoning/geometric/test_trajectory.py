"""TrajectoryReport tests (Fas 6, Task 7). Determinism + serialization contract."""

import json

from reasoning.geometric import ProblemSpace, ReasoningNode, TrajectoryReport


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
    assert r1 == r2  # samma space+path+scoring -> identisk serialisering


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
