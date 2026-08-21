"""Process entrypoint for one RLM tree node (design spec decision 1/2).

Spawned by Coordinator.run_node (supervisor/coordinator.py, Task 6) exactly
like Phase 4's coding_loop_cli.py is spawned by run_m1/run_m2 — but this
entrypoint can itself decompose and spawn its own children, becoming a
Coordinator in its own right (see run_node_body's decompose branch).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Protocol

from context_store.store import ContextReference
from runtime.tools.gate import ToolAdmissionError


class InferencePort(Protocol):
    def invoke(self, content: Any) -> Any: ...


DecomposeFn = Callable[[ContextReference, Any], list[ContextReference]]


def decide_child_refs(context_ref: ContextReference, config: Any, depth: int,
                       decompose_fn: DecomposeFn,
                       data_class_check: Callable[[str], bool] = lambda dc: True,
                       ) -> list[ContextReference]:
    """Pure leaf-vs-decompose decision — no inference dependency at all.

    Returns [] for a leaf decision, or the list of child ContextReferences to
    spawn for a decompose decision. Used by Coordinator.run_node (Task 6) to
    decide how many child processes to spawn WITHOUT needing an inference
    port — Coordinator itself never calls a model directly (Phase 3 §32.1: the
    Supervisor never does domain work itself). run_node_body (below) is the
    combined decide+execute function used only inside a spawned process's own
    main(), which always has a real inference port available.

    ``data_class_check`` (optional, defaults to allow-all) applies the parent's
    admission policy to this node's own data class BEFORE any further
    decomposition is allowed — a ref whose data_class is not in the allowlist
    raises ToolAdmissionError (fail-closed at this boundary, §11.4 Tool Gateway
    admission) rather than returning [] and silently treating the ref as a leaf
    to be read anyway.
    """
    if not data_class_check(context_ref.data_class):
        raise ToolAdmissionError(
            f"rlm_context_read: data_class={context_ref.data_class!r} rejected for "
            f"locator={context_ref.locator!r}")
    can_decompose = depth < config.max_depth and config.max_total_children > 0
    return decompose_fn(context_ref, config) if can_decompose else []


def run_node_body(context_ref: ContextReference, config: Any, depth: int,
                   inference: InferencePort, decompose_fn: DecomposeFn,
                   data_class_check: Callable[[str], bool] = lambda dc: True) -> dict:
    """Pure decision+execute body: leaf (one model call) vs decompose (caller
    spawns children). Only called from within a process that already has a
    real inference port (rlm_child_cli.main(), Task 6) — never from
    Coordinator.run_node itself, which uses decide_child_refs above instead
    to avoid needing any inference port at the spawning level.
    """
    child_refs = decide_child_refs(context_ref, config, depth, decompose_fn, data_class_check)

    if not child_refs:
        value = inference.invoke(context_ref)
        return {"is_leaf": True, "value": value, "model_invocations": 1, "context_reads": 1}

    return {"is_leaf": False, "child_refs": child_refs}


import threading

HEARTBEAT_INTERVAL_SECONDS = 5.0


def _start_heartbeat(writer, interval: float) -> threading.Event:
    """Verbatim of coding_loop_cli.py's own helper (Phase 4 decision 9) —
    SessionWriter has no heartbeat methods itself; the caller owns the timer
    thread and the stop Event."""
    stop = threading.Event()

    def _tick() -> None:
        while not stop.wait(interval):
            try:
                writer.append("heartbeat.ping", {})
            except Exception:
                return

    thread = threading.Thread(target=_tick, daemon=True)
    thread.start()
    return stop


def _read_context_content(ref: ContextReference) -> str:
    """Reads the referenced slice directly from disk. Generic — works for
    both Coding-class repo files and research-class documents, both being
    plain files addressed by path+range. Task 14's read_fixture_file_sliced
    (research-profile tool wiring) reuses this same slicing logic rather than
    reimplementing it."""
    from pathlib import Path as _Path
    content = _Path(ref.locator).read_text(encoding="utf-8")
    start, end = ref.range
    return content[start:end]


class _TextPortAdapter:
    """Bridges TextInferencePort.invoke(prompt, output_schema) -> dict to
    run_node_body's expected InferencePort.invoke(context_ref) -> Any."""
    def __init__(self, port, output_schema: dict) -> None:
        self._port = port
        self._output_schema = output_schema

    def invoke(self, context_ref: ContextReference):
        content = _read_context_content(context_ref)
        prompt = f"Context ({context_ref.locator}, range {context_ref.range}):\n{content}"
        return self._port.invoke(prompt, self._output_schema)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--context-ref-json", required=True)
    parser.add_argument("--depth", type=int, required=True)
    args = parser.parse_args(argv)

    from pathlib import Path as _Path
    from adapters.inference.budget_gate import BudgetGate  # existing, Phase 3/4
    from reasoning.recursive.bounds import RLMConfig
    from runtime import session_state as state
    from runtime.session_writer import SessionWriter
    from runtime.text_inference_port import TextInferencePort  # existing, Phase 3

    # payload["rlm"] carries the RLMConfig fields; the sibling keys carry
    # inference wiring (model/provider/data-class) — see Task 6's
    # _spawn_rlm_node, which now writes this same combined shape instead of
    # a bare RLMConfig dict (fixed together with this read side).
    payload = json.loads(_Path(args.config_json).read_text(encoding="utf-8"))
    config = RLMConfig(**payload["rlm"])
    ref_data = json.loads(_Path(args.context_ref_json).read_text(encoding="utf-8"))
    context_ref = ContextReference(**ref_data)
    store = _Path(args.store)

    writer = SessionWriter(store, args.session_id)
    stop_heartbeat = _start_heartbeat(writer, HEARTBEAT_INTERVAL_SECONDS)
    try:
        from context_store.slicer import slice_for_children, SliceBudgetExhausted

        def _decompose_context(ref, cfg):
            n = min(cfg.max_branches_per_node, cfg.max_total_children)
            if n <= 0:
                return []
            try:
                return slice_for_children(ref, n)
            except (SliceBudgetExhausted, ValueError):
                return []

        # Inherit the parent's allowlist from the JSON payload; the same value
        # is passed back into Coordinator.run_node below so grandchildren keep
        # the policy.
        from runtime.tools.gate import DataClassGate
        allowed_data_classes = frozenset(payload.get("allowed_data_classes", ["L0", "internal"]))
        data_class_gate = DataClassGate(allowed_data_classes=allowed_data_classes)

        def _gate_check(data_class: str) -> bool:
            try:
                data_class_gate.admit("rlm_context_read", data_class)
                return True
            except ToolAdmissionError:
                return False

        budget_gate = BudgetGate(max_calls=payload.get("max_calls", 1),
                                  db_path=store / args.session_id / "spend.db")
        port = TextInferencePort(
            model=payload.get("model", "Qwen3-Coder-Next-FP8"),
            budget_gate=budget_gate,
            provider_evidence=payload.get("provider_evidence",
                                           {"approved": True, "provider_id": "inferx"}),
            data_class=payload.get("data_class", "L0"),
        )
        adapter = _TextPortAdapter(port, output_schema=payload.get(
            "output_schema", {"type": "object", "properties": {"answer": {"type": "string"}}}))

        decision = run_node_body(context_ref=context_ref, config=config, depth=args.depth,
                                  inference=adapter, decompose_fn=_decompose_context,
                                  data_class_check=_gate_check)

        if decision["is_leaf"]:
            # Placeholder unit cost: 0.01 per leaf invocation, matching Task 13/17's
            # fallback formula. Replace with port.cost_of(...) once TextInferencePort's
            # usage-reporting field is confirmed at execution time.
            cost = float(decision["model_invocations"]) * 0.01
            output_size = len(str(decision["value"]))
            writer.append("result.available", {"value": decision["value"],
                                                 "model_invocations": decision["model_invocations"],
                                                 "context_reads": decision["context_reads"],
                                                 "cost": cost,
                                                 "output_size": output_size})
            writer.append("session.terminal", {"status": "succeeded"})
            return 0

        # this process now becomes a spawner for its own children — the
        # concrete instance of "a node that decomposes further runs a full
        # Coordinator" (spec decision 2)
        from supervisor.coordinator import Coordinator
        coordinator = Coordinator(store=store)
        result = coordinator.run_node(task_id=args.session_id, context_ref=context_ref,
                                       config=config, depth=args.depth,
                                       allowed_data_classes=allowed_data_classes)
        writer.append("session.terminal", {"status": result["status"]})
        return 0 if result["status"] == "succeeded" else 1
    finally:
        stop_heartbeat.set()


if __name__ == "__main__":
    sys.exit(main())
