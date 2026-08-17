# agent-platform/tests/supervisor/conftest.py
import json
from pathlib import Path

import pytest

from context_store.slicer import SliceBudgetExhausted, slice_for_children
from context_store.store import ContextReference
from reasoning.recursive.bounds import RLMConfig
from runtime import session_state as state
from runtime.rlm_child_cli import decide_child_refs
from supervisor.budget import split_rlm_config


class _FakeChildProcess:
    def __init__(self, pid): self.pid, self.pgid, self.session_id, self.start_time = pid, pid, "", 0.0


def _parse_arg(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def _fake_decompose(ref: ContextReference, cfg: RLMConfig) -> list[ContextReference]:
    """Same structural decompose_fn Coordinator.run_node uses internally
    (Task 6's _decompose_context) — duplicated here rather than imported
    because it is a private module-level function of coordinator.py; both
    copies must stay in sync if the slicing policy ever changes."""
    n = min(cfg.max_branches_per_node, cfg.max_total_children)
    if n <= 0:
        return []
    try:
        return slice_for_children(ref, n)
    except (SliceBudgetExhausted, ValueError):
        return []


def _fake_run_node_into(store: Path, session_id: str, context_ref: ContextReference,
                         config: RLMConfig, depth: int) -> None:
    """Executes one RLM node's leaf-or-decompose logic against an ALREADY
    pre-created session_id, recursing in-process for any further
    decomposition — the fake-spawner equivalent of what a real detached
    subprocess chain (rlm_child_cli.main() -> Coordinator.run_node -> ...)
    would produce, without needing real subprocesses, Docker, or a model."""
    child_refs = decide_child_refs(context_ref, config, depth, _fake_decompose)

    if not child_refs:
        seq = state.latest_sequence(state.load(store, session_id))
        state.append(store, session_id, seq, "session.terminal", {"status": "succeeded"})
        return

    child_configs = split_rlm_config(config, len(child_refs))
    statuses = []
    for ref, cfg in zip(child_refs, child_configs):
        child_session = state.create(store, task_id="fake")
        child_session_id = child_session["session_id"]
        seq = state.latest_sequence(state.load(store, session_id))
        state.append(store, session_id, seq, "child.spawned", {
            "session_id": child_session_id, "pid": 1, "pgid": 1, "start_time": 0.0,
            "allocated_budget": cfg.max_total_children})
        _fake_run_node_into(store, child_session_id, ref, cfg, depth + 1)
        child_doc = state.load(store, child_session_id)
        terminal = next(e for e in child_doc["events"] if e["event_type"] == "session.terminal")
        statuses.append(terminal["payload"]["status"])

    overall = "succeeded" if all(s == "succeeded" for s in statuses) else "blocked"
    seq = state.latest_sequence(state.load(store, session_id))
    state.append(store, session_id, seq, "session.terminal", {"status": overall})


class FakeSpawnerLeafOnly:
    """Every spawned node is an instant leaf — used where the top-level
    Coordinator.run_node call has already decided this is a leaf, so the fake
    only needs to close it out."""
    def __init__(self, store: Path):
        self._store = store

    def spawn(self, session_id: str, args: list[str]) -> _FakeChildProcess:
        seq = state.latest_sequence(state.load(self._store, session_id))
        state.append(self._store, session_id, seq, "session.terminal", {"status": "succeeded"})
        return _FakeChildProcess(pid=1)

    def is_alive(self, child: _FakeChildProcess) -> bool:
        return False

    def terminate_gracefully(self, child: _FakeChildProcess, timeout: float) -> None:
        pass


class FakeSpawnerDecomposing:
    """Parses the config/context-ref files _spawn_rlm_node wrote to disk
    (same files a real subprocess would read) and recurses in-process via
    _fake_run_node_into, so a test can exercise real depth-2 trees."""
    def __init__(self, store: Path):
        self._store = store

    def spawn(self, session_id: str, args: list[str]) -> _FakeChildProcess:
        payload = json.loads(Path(_parse_arg(args, "--config-json")).read_text(encoding="utf-8"))
        config = RLMConfig(**payload["rlm"])
        context_ref = ContextReference(**json.loads(
            Path(_parse_arg(args, "--context-ref-json")).read_text(encoding="utf-8")))
        depth = int(_parse_arg(args, "--depth"))
        _fake_run_node_into(self._store, session_id, context_ref, config, depth)
        return _FakeChildProcess(pid=1)

    def is_alive(self, child: _FakeChildProcess) -> bool:
        return False

    def terminate_gracefully(self, child: _FakeChildProcess, timeout: float) -> None:
        pass


@pytest.fixture
def fake_spawner_leaf_only(tmp_path):
    return FakeSpawnerLeafOnly(store=tmp_path)


@pytest.fixture
def fake_spawner_decomposing(tmp_path):
    return FakeSpawnerDecomposing(store=tmp_path)
