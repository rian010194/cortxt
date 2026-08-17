# agent-platform/tests/runtime/test_rlm_child_cli.py
from context_store.store import ContextReference
from reasoning.recursive.bounds import RLMConfig
from runtime.rlm_child_cli import run_node_body


class StubInference:
    def __init__(self, answer):
        self._answer = answer
    def invoke(self, content):
        return self._answer


def test_leaf_node_makes_one_model_invocation_and_returns_result():
    ref = ContextReference(source="repo", locator="tiny.py", range=(0, 10),
                            data_class="internal")
    config = RLMConfig(max_total_children=0)  # forces leaf: no budget to decompose
    result = run_node_body(context_ref=ref, config=config, depth=0,
                            inference=StubInference("answer-42"),
                            decompose_fn=lambda ref, cfg: [])  # decompose_fn returns no slices -> leaf
    assert result["is_leaf"] is True
    assert result["value"] == "answer-42"
    assert result["model_invocations"] == 1
    assert result["context_reads"] == 1


def test_depth_zero_budget_forces_leaf_even_if_decompose_fn_would_split():
    ref = ContextReference(source="repo", locator="x.py", range=(0, 300),
                            data_class="internal")
    config = RLMConfig(max_depth=0)
    result = run_node_body(context_ref=ref, config=config, depth=0,
                            inference=StubInference("x"),
                            decompose_fn=lambda ref, cfg: [ref, ref])
    assert result["is_leaf"] is True


def test_decide_child_refs_needs_no_inference_and_matches_run_node_body():
    from runtime.rlm_child_cli import decide_child_refs

    ref = ContextReference(source="repo", locator="x.py", range=(0, 300),
                            data_class="internal")
    config = RLMConfig(max_depth=2, max_total_children=6)
    refs = decide_child_refs(ref, config, depth=0, decompose_fn=lambda r, c: [r, r])
    assert refs == [ref, ref]  # decompose decision, no inference call needed


def test_decide_child_refs_returns_empty_list_for_a_leaf_decision():
    from runtime.rlm_child_cli import decide_child_refs

    ref = ContextReference(source="repo", locator="x.py", range=(0, 10),
                            data_class="internal")
    config = RLMConfig(max_total_children=0)
    refs = decide_child_refs(ref, config, depth=0, decompose_fn=lambda r, c: [r, r])
    assert refs == []


def test_decide_child_refs_rejects_out_of_scope_data_class():
    from runtime.rlm_child_cli import decide_child_refs
    import pytest
    from runtime.tools.gate import ToolAdmissionError

    ref = ContextReference(source="repo", locator="secret.env", range=(0, 10),
                            data_class="restricted")
    config = RLMConfig(max_total_children=0)

    def deny_restricted(data_class: str) -> bool:
        return data_class != "restricted"

    with pytest.raises(ToolAdmissionError):
        decide_child_refs(ref, config, depth=0, decompose_fn=lambda r, c: [],
                           data_class_check=deny_restricted)
