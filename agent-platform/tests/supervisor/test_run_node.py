# agent-platform/tests/supervisor/test_run_node.py
from pathlib import Path

from context_store.store import ContextReference
from reasoning.recursive.bounds import RLMConfig
from supervisor.coordinator import Coordinator


def test_run_node_single_leaf_when_config_forbids_decomposition(tmp_path, fake_spawner_leaf_only):
    coordinator = Coordinator(store=tmp_path, spawner=fake_spawner_leaf_only)
    ref = ContextReference(source="repo", locator="a.py", range=(0, 10), data_class="internal")
    result = coordinator.run_node(task_id="t1", context_ref=ref,
                                   config=RLMConfig(max_total_children=0))
    assert result["status"] == "succeeded"
    assert result["depth_reached"] == 0
    assert result["children"] == []


def test_run_node_decomposes_to_depth_2_within_total_children_budget(tmp_path, fake_spawner_decomposing):
    coordinator = Coordinator(store=tmp_path, spawner=fake_spawner_decomposing)
    ref = ContextReference(source="repo", locator="big.py", range=(0, 900), data_class="internal")
    result = coordinator.run_node(task_id="t2", context_ref=ref,
                                   config=RLMConfig(max_depth=2, max_branches_per_node=3,
                                                     max_total_children=6))
    assert result["status"] == "succeeded"
    assert result["depth_reached"] == 2
    # combinatorics from spec decision 2: 3 direct children consume 3 of 6; the
    # remaining pool (3) splits across those 3 children, so at most one
    # grandchild per child — exactly what the fixture (fake_spawner_decomposing)
    # is built to exercise.
    assert len(result["children"]) == 3
    assert sum(len(c["children"]) for c in result["children"]) <= 3
    # children genuinely carry their own nested results (review finding — the
    # original draft never tested that grandchildren project through)
    assert any(len(c["children"]) == 1 for c in result["children"])


def test_run_node_propagates_allowed_data_classes_to_spawned_children(tmp_path, fake_spawner_decomposing):
    """A non-default allowlist must survive the config JSON round-trip so
    grandchildren inherit the same policy, not revert to the default."""
    import json

    class PayloadInspectingSpawner:
        def __init__(self, inner):
            self._inner = inner
            self.seen_payloads = []

        def spawn(self, session_id: str, args: list[str]):
            config_path = Path(args[args.index("--config-json") + 1])
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.seen_payloads.append(payload)
            return self._inner.spawn(session_id, args)

        def is_alive(self, child):
            return self._inner.is_alive(child)

        def terminate_gracefully(self, child, timeout):
            self._inner.terminate_gracefully(child, timeout)

    inner = fake_spawner_decomposing
    spy = PayloadInspectingSpawner(inner)
    coordinator = Coordinator(store=tmp_path, spawner=spy)
    ref = ContextReference(source="repo", locator="big.py", range=(0, 900), data_class="foo")
    result = coordinator.run_node(
        task_id="t-allow", context_ref=ref,
        config=RLMConfig(max_depth=2, max_branches_per_node=3, max_total_children=6),
        allowed_data_classes=frozenset({"foo"}))
    assert result["status"] == "succeeded"
    assert spy.seen_payloads
    for payload in spy.seen_payloads:
        assert payload.get("allowed_data_classes") == ["foo"], payload


def test_run_node_result_carries_envelope_fields(tmp_path, fake_spawner_leaf_only):
    from context_store.store import ContextReference
    from reasoning.recursive.bounds import RLMConfig
    from supervisor.coordinator import Coordinator

    coordinator = Coordinator(store=tmp_path, spawner=fake_spawner_leaf_only)
    ref = ContextReference(source="repo", locator="a.py", range=(0, 10), data_class="internal")
    result = coordinator.run_node(task_id="t3", context_ref=ref,
                                   config=RLMConfig(max_total_children=0))
    for key in ("branches_explored", "model_invocations", "contradictions_found"):
        assert key in result


def test_run_node_root_data_class_blocked(tmp_path, fake_spawner_leaf_only):
    """An out-of-scope data class on the ROOT ref is denied before any flush —
    returns a controlled blocked result, does NOT crash (Kimi review fix)."""
    from context_store.store import ContextReference
    from reasoning.recursive.bounds import RLMConfig
    from supervisor.coordinator import Coordinator

    coordinator = Coordinator(store=tmp_path, spawner=fake_spawner_leaf_only)
    ref = ContextReference(source="repo", locator="secret.env", range=(0, 10),
                            data_class="restricted")
    result = coordinator.run_node(
        task_id="t-blocked", context_ref=ref,
        config=RLMConfig(max_total_children=0),
        allowed_data_classes=frozenset({"L0", "internal"}))
    assert result["status"] == "blocked"
    assert result["termination_reason"] == "admission_denied"
    assert result["children"] == []
    assert result["model_invocations"] == 0
