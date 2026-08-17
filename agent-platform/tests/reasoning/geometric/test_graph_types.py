"""Graph typing tests — ReasoningNode node_type+metadata (Task 1, Task 2)."""

from reasoning.geometric import ProblemSpace, ReasoningNode


# ---- Task 1: ReasoningNode node_type + metadata ----
def test_reasoning_node_has_type_and_metadata_defaults():
    n = ReasoningNode(id="a")
    assert n.node_type is None
    assert n.metadata is None


def test_reasoning_node_type_and_metadata_roundtrip():
    n = ReasoningNode(id="a", node_type="claim", metadata={"provenance": "p1", "data_class": "L0"})
    assert n.node_type == "claim"
    assert n.metadata["data_class"] == "L0"


# ---- Task 2: ProblemSpace typed relations + node_type index ----
def test_add_edge_with_rel_type_stores_type():
    s = ProblemSpace()
    s.add_edge("a", "b", rel_type="contradicts")
    assert s.edge_types("a", "b") == ["contradicts"]


def test_add_edge_default_opaque_keeps_behavior():
    s = ProblemSpace()
    s.add_edge("a", "b")  # otypad
    assert s.edge_types("a", "b") == []
    assert "b" in s.successors("a")  # orörd


def test_node_type_index_derives_from_nodes():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="c", node_type="claim"))
    assert s.node_type("c") == "claim"


def test_add_edge_without_rel_type_keeps_other_edges_intact():
    s = ProblemSpace()
    s.add_edge("a", "b", rel_type="supports")
    s.add_edge("a", "c")
    assert s.edge_types("a", "b") == ["supports"]
    assert "c" in s.successors("a")
