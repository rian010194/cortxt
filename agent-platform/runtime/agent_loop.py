"""Agent Runtime's orchestrating loop (Phase 2 v0.1, read-only research profile).

claim -> admit+run one tool -> reasoning kernel (MODEL_ASSISTED strategy) ->
schema-validate -> result envelope. Every step is logged to session_state so
a crash mid-run can resume from the last completed event (not implemented as
an explicit resume() call in v0.1 -- the log itself is the resumability proof,
per the design spec's error-handling section).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from adapters.inference.budget_gate import BudgetExhausted
from reasoning.kernel import Engine
from runtime import research_profile
from runtime import session_state as state
from runtime.text_inference_port import TextInferenceError
from runtime.tools import ToolAdmissionError, ToolExecutionError, ToolGate, read_fixture_file


class AgentLoop:
    def __init__(self, store: Path, tool_gate: ToolGate, port, output_schema: dict,
                 system_prompt: str, profile: dict | None = None) -> None:
        self._store = Path(store)
        self._gate = tool_gate
        self._port = port
        self._schema = output_schema
        self._prompt = system_prompt
        self._profile = profile if profile is not None else research_profile.RESEARCH_PROFILE

    def run(self, task_id: str, fixture_path: str) -> dict:
        session = state.create(self._store, task_id=task_id)
        session_id = session["session_id"]

        def _blocked(reason: str) -> dict:
            seq = state.latest_sequence(state.load(self._store, session_id))
            state.append(self._store, session_id, seq, "session.terminal",
                         {"status": "blocked", "reason": reason})
            return {"session_id": session_id, "status": "blocked", "result": None, "reason": reason}

        if "read_fixture_file" not in self._profile.get("allowed_tools", []):
            return _blocked("tool admission denied: read_fixture_file is not in the profile's allowed_tools")

        try:
            fixture = read_fixture_file(self._gate, fixture_path)
        except (ToolAdmissionError, ToolExecutionError) as error:
            return _blocked(f"tool admission denied: {error}")

        seq = state.latest_sequence(state.load(self._store, session_id))
        session = state.append(self._store, session_id, seq, "tool.admitted",
                                {"tool": "read_fixture_file", "path": fixture_path})
        seq = state.latest_sequence(session)
        session = state.append(self._store, session_id, seq, "tool.completed",
                                {"tool": "read_fixture_file"})
        seq = state.latest_sequence(session)

        def _invoke(content):
            current_seq = state.latest_sequence(state.load(self._store, session_id))
            state.append(self._store, session_id, current_seq, "inference.requested", {"content": content})
            full_prompt = f"{self._prompt}\n\nInput:\n{json.dumps(content)}"
            return self._port.invoke(full_prompt, self._schema)

        def _validate(response) -> bool:
            try:
                jsonschema.validate(instance=response, schema=self._schema)
                return True
            except jsonschema.ValidationError:
                return False

        engine = Engine()
        try:
            result = engine.solve_model_assisted(content=fixture, invoke=_invoke, validate=_validate)
        except BudgetExhausted as error:
            return _blocked(f"budget exhausted: {error}")
        except TextInferenceError as error:
            return _blocked(f"inference error: {error}")
        except jsonschema.SchemaError as error:
            return _blocked(f"invalid output schema: {error}")

        seq = state.latest_sequence(state.load(self._store, session_id))
        state.append(self._store, session_id, seq, "inference.completed",
                     {"confidence": result["confidence"]})
        seq = state.latest_sequence(state.load(self._store, session_id))

        if result["confidence"] < 1.0:
            return _blocked("response failed schema validation")

        state.append(self._store, session_id, seq, "session.terminal",
                     {"status": "succeeded"})
        return {"session_id": session_id, "status": "succeeded", "result": result["value"], "reason": None}
