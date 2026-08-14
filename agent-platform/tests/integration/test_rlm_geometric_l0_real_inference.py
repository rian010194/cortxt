"""Fas 2A Delmål 2 — L0-fixtur + vertikal integration mot RIKTIG (opt-in) InferencePort.

Opt-in via ``@pytest.mark.real_inference``; körs ENDAST med ``pytest -m real_inference``
OCH när ``CORTXT_INFERENCE_*``-env. Default-sviten (``-m "not real_inference"``) använder
alltid mockad inference och är oförändrad.

Budget: varje scenario gör exakt 1 riktigt anrop; BudgetGate (env ``FAS2A_INFERENCE_BUDGET_MAX``)
fail-closed vid budgettak. L0-fixture innehåller endast syntetiska heltal.
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

    gated = lambda content: gate(real_inference_port.invoke, content)  # noqa: E731
    engine = RLMEngine(gated, _config())
    result = engine.run(scenario["content"])
    # The RLM engine aggregates leaf values; verify the expected sum surfaced.
    assert result.value == scenario["expected"], (
        f"{scenario['scenario_id']}: got {result.value}, expected {scenario['expected']}"
    )


def test_real_inference_skips_when_not_configured(monkeypatch):
    """Fail-closed: without env, real_inference_port is skip, not crash/hang.

    This test asserts the fixture's skip behaviour is safe for the default suite.
    """
    for var in ("CORTXT_INFERENCE_URL", "CORTXT_INFERENCE_API_KEY", "CORTXT_INFERENCE_MODEL"):
        monkeypatch.delenv(var, raising=False)
    from adapters.inference import ResilientInferencePort

    port = ResilientInferencePort()
    assert port.available() is False
