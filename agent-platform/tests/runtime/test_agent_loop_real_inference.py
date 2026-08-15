"""Fas 2 exit-criterion proof: one real synthetic AI Act fixture, solved by
AgentLoop without Hermes, using a real model call. Excluded from default CI
(same convention as every other real_inference-marked test in this repo) --
run manually once CORTXT_INFERENCE_URL/CORTXT_INFERENCE_API_KEY are set and
cortxt_resilient_inference is installed. See
docs/superpowers/specs/2026-08-15-fas2-agent-runtime-v01-design.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from adapters.inference.budget_gate import BudgetGate
from runtime.agent_loop import AgentLoop
from runtime.text_inference_port import TextInferencePort
from runtime.tools import ToolGate

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-01-ai-act"
FIXTURE_YAML = VERTICAL / "evals" / "synthetic" / "positive-cases" / "001-high-risk-medical-diagnostic.yaml"
OUTPUT_SCHEMA = json.loads(
    (VERTICAL / "schemas" / "ai-act-assessment-output.schema.json").read_text(encoding="utf-8")
)
SYSTEM_PROMPT = (VERTICAL / "instructions" / "system-prompt-classify.md").read_text(encoding="utf-8")


@pytest.mark.real_inference
def test_ai_act_fixture_solved_without_hermes(tmp_path):
    fixture_case = yaml.safe_load(FIXTURE_YAML.read_text(encoding="utf-8"))["input"]
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    fixture_path = fixture_dir / "case.json"
    fixture_path.write_text(json.dumps(fixture_case), encoding="utf-8")

    gate = ToolGate(allowed_roots=[fixture_dir])
    budget_gate = BudgetGate(max_calls=1, db_path=tmp_path / "spend.db")
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=budget_gate,
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt=SYSTEM_PROMPT)

    envelope = loop.run(task_id="fas2-exit-criterion", fixture_path=str(fixture_path))

    assert envelope["status"] == "succeeded", envelope.get("reason")
    assert envelope["result"]["case_id"] == fixture_case["case_id"]
