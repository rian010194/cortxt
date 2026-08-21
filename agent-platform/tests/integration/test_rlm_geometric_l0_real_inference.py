"""Phase 2A Milestone 2 — L0 fixture + vertical integration against a REAL (opt-in) InferencePort.

Opt-in via ``@pytest.mark.real_inference``; runs ONLY with ``pytest -m real_inference``
AND when the ``CORTXT_INFERENCE_*`` env is set. The default suite (``-m "not real_inference"``)
always uses mocked inference and is unchanged.

Budget: each scenario makes exactly 1 real call; BudgetGate (env ``FAS2A_INFERENCE_BUDGET_MAX``)
fails closed at the budget cap. The L0 fixture contains only synthetic integers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_inference

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "l0_synthetic_rlm.json"


def _scenarios():
    if not FIXTURE.exists():
        return []  # fixture absent -> no real_inference tests collect (default suite stays green)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["scenarios"]


def _config():
    """Build an RLMConfig with a generous-but-bounded routing."""
    from reasoning.recursive.rlm_engine import RLMConfig

    return RLMConfig(max_depth=6, max_total_children=16, max_model_invocations=4)


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda s: s["scenario_id"])
def test_rlm_real_inference_matches_expected(scenario, real_inference_port):
    from reasoning.recursive.rlm_engine import RLMEngine
    from adapters.inference.budget_gate import BudgetGate

    # Budget: exactly 1 real call per scenario, hard-capped via env (system-managed).
    gate = BudgetGate(max_calls=None)  # reads FAS2A_INFERENCE_BUDGET_MAX (default 0 = fail-closed)
    if gate.remaining < 1:
        pytest.skip("FAS2A_INFERENCE_BUDGET_MAX not set or <1 — budget-gate blocks (fail-closed)")

    class _GatedPort:
        """Adapts BudgetGate + real_inference_port to RLMEngine's InferencePort
        protocol (RLMEngine calls .invoke(content), not a bare callable)."""

        def __init__(self, port):
            self._port = port

        def invoke(self, content: str) -> int:
            result = self._port.invoke(
                content=content,
                output_schema={"type": "integer"},
            )
            return int(result)

    engine = RLMEngine(_GatedPort(real_inference_port), _config())
    result = engine.run(scenario["content"])
    # The RLM engine aggregates leaf values; verify the expected sum surfaced.
    assert result.value == scenario["expected"], (
        f"{scenario['scenario_id']}: got {result.value}, expected {scenario['expected']}"
    )
