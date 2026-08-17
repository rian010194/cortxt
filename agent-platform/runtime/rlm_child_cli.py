"""Process entrypoint for one RLM tree node (design spec beslut 1/2).

Spawned by Coordinator.run_node (supervisor/coordinator.py, Task 6) exactly
like Fas 4's coding_loop_cli.py is spawned by run_m1/run_m2 — but this
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


class InferencePort(Protocol):
    def invoke(self, content: Any) -> Any: ...


DecomposeFn = Callable[[ContextReference, Any], list[ContextReference]]


def decide_child_refs(context_ref: ContextReference, config: Any, depth: int,
                       decompose_fn: DecomposeFn) -> list[ContextReference]:
    """Pure leaf-vs-decompose decision — no inference dependency at all.

    Returns [] for a leaf decision, or the list of child ContextReferences to
    spawn for a decompose decision. Used by Coordinator.run_node (Task 6) to
    decide how many child processes to spawn WITHOUT needing an inference
    port — Coordinator itself never calls a model directly (Fas 3 §32.1: the
    Supervisor never does domain work itself). run_node_body (below) is the
    combined decide+execute function used only inside a spawned process's own
    main(), which always has a real inference port available.
    """
    can_decompose = depth < config.max_depth and config.max_total_children > 0
    return decompose_fn(context_ref, config) if can_decompose else []


def run_node_body(context_ref: ContextReference, config: Any, depth: int,
                   inference: InferencePort, decompose_fn: DecomposeFn) -> dict:
    """Pure decision+execute body: leaf (one model call) vs decompose (caller
    spawns children). Only called from within a process that already has a
    real inference port (rlm_child_cli.main(), Task 6) — never from
    Coordinator.run_node itself, which uses decide_child_refs above instead
    to avoid needing any inference port at the spawning level.
    """
    child_refs = decide_child_refs(context_ref, config, depth, decompose_fn)

    if not child_refs:
        value = inference.invoke(context_ref)
        return {"is_leaf": True, "value": value, "model_invocations": 1, "context_reads": 1}

    return {"is_leaf": False, "child_refs": child_refs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--context-ref-json", required=True)
    parser.add_argument("--depth", type=int, required=True)
    args = parser.parse_args(argv)

    config_data = json.loads(Path(args.config_json).read_text(encoding="utf-8"))
    ref_data = json.loads(Path(args.context_ref_json).read_text(encoding="utf-8"))
    context_ref = ContextReference(**ref_data)

    # Real wiring (RLMConfig, real InferencePort, real decompose_fn using
    # context_store.slicer, and — on a decompose result — a real Coordinator
    # instance calling run_node for each child_ref) is completed in Task 6,
    # which is the task that also builds Coordinator.run_node and therefore
    # knows both sides of this boundary. This module's contract (run_node_body)
    # is stable from this task forward; Task 6 only adds the process-spawning
    # glue around it.
    raise NotImplementedError("wired in Task 6 (Coordinator.run_node)")


if __name__ == "__main__":
    sys.exit(main())
