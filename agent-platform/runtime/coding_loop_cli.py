"""Child-process entry point for a Fas 4 Supervisor-spawned coding run.

Fas 3's CodingLoop is used completely unmodified. This module supplies the two
things CodingLoop was never designed to need on its own: (1) a heartbeat signal
a Supervisor process can observe from outside, and (2) a way for that heartbeat
to share CodingLoop's own session log without racing on
session_state.append()'s optimistic concurrency (design spec decision 9's
"Implementation refinement"). Both are achieved by monkeypatching
runtime.session_state's module-level functions, scoped to this process only,
for the duration of the run. CodingLoop's source is never modified.

Supervisor pre-creates the child's session (session_state.create()) before
spawning this process and passes the resulting session_id via --session-id, so
the patched state.create() below returns that existing session rather than
creating a second one.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from runtime import session_state as state
from runtime.session_writer import SessionWriter

HEARTBEAT_INTERVAL_SECONDS = 5.0


def _start_heartbeat(writer: SessionWriter, interval: float) -> threading.Event:
    stop = threading.Event()

    def _tick() -> None:
        while not stop.wait(interval):
            try:
                writer.append("heartbeat.ping", {})
            except Exception:
                # A failed heartbeat write is itself the signal: Supervisor will
                # see a stale heartbeat and treat the child as stuck.
                return

    thread = threading.Thread(target=_tick, daemon=True)
    thread.start()
    return stop


@contextmanager
def _session_writer_scope(writer: SessionWriter):
    original = {
        "create": state.create,
        "load": state.load,
        "latest_sequence": state.latest_sequence,
        "append": state.append,
    }
    store_path = writer._store
    session_id = writer._session_id

    def _patched_create(store, task_id):  # noqa: ARG001 - session pre-created by Supervisor
        return original["load"](store_path, session_id)

    def _patched_load(store, sid):  # noqa: ARG001
        return original["load"](store_path, session_id)

    def _patched_latest_sequence(session_doc):  # noqa: ARG001
        return original["latest_sequence"](original["load"](store_path, session_id))

    def _patched_append(store, sid, expected_sequence, event_type, payload):  # noqa: ARG001
        doc = original["load"](store_path, session_id)
        current = original["latest_sequence"](doc)
        return original["append"](store_path, session_id, current, event_type, payload)

    state.create = _patched_create
    state.load = _patched_load
    state.latest_sequence = _patched_latest_sequence
    state.append = _patched_append
    try:
        yield
    finally:
        state.create = original["create"]
        state.load = original["load"]
        state.latest_sequence = original["latest_sequence"]
        state.append = original["append"]


def run_child(store: Path, session_id: str, task_id: str, fixture_dir: Path,
              port, patch_schema: dict, system_prompt: str,
              sandbox_factory=None, profile: dict | None = None,
              heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS) -> dict:
    writer = SessionWriter(store, session_id)
    stop_heartbeat = _start_heartbeat(writer, heartbeat_interval)
    try:
        with _session_writer_scope(writer):
            from runtime.coding.coding_loop import CodingLoop

            loop = CodingLoop(store=store, port=port, patch_schema=patch_schema,
                               system_prompt=system_prompt, sandbox_factory=sandbox_factory,
                               profile=profile)
            envelope = loop.run(task_id=task_id, fixture_dir=fixture_dir)
        if envelope["status"] == "succeeded" and "file_contents" in envelope.get("result", {}):
            writer.append("result.available", {"file_contents": envelope["result"]["file_contents"],
                                                 "cost": envelope.get("cost", {})})
        return envelope
    finally:
        stop_heartbeat.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fas 4 child-process coding run")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--config-json", required=True, type=Path)
    args = parser.parse_args(argv)

    config = json.loads(args.config_json.read_text(encoding="utf-8"))

    from adapters.inference.budget_gate import BudgetGate
    from runtime.coding.coding_profile import CODING_PROFILE
    from runtime.text_inference_port import TextInferencePort

    budget_gate = BudgetGate(max_calls=config.get("max_calls", 1),
                              db_path=args.store / args.session_id / "spend.db")
    port = TextInferencePort(
        model=config["model"], budget_gate=budget_gate,
        provider_evidence=config.get("provider_evidence", {"approved": True}),
        data_class=config.get("data_class", "L0"),
    )
    fixture_dir = Path(config["fixture_dir"])
    patch_schema = json.loads(Path(config["patch_schema_path"]).read_text(encoding="utf-8"))
    system_prompt = Path(config["system_prompt_path"]).read_text(encoding="utf-8")

    envelope = run_child(
        store=args.store, session_id=args.session_id, task_id=config["task_id"],
        fixture_dir=fixture_dir, port=port, patch_schema=patch_schema,
        system_prompt=system_prompt, profile=CODING_PROFILE,
    )
    print(json.dumps({"status": envelope["status"]}))
    return 0 if envelope["status"] == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
