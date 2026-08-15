"""TextInferencePort — text/structured-JSON model invocation for Agent Runtime.

Distinct from reasoning/recursive/rlm_engine.py's InferencePort
(invoke(content) -> int), which is scoped to the DM1-DM4 abstract reasoning
proof. This port returns a real parsed dict response and is what
agent_loop.py (Task 5) wires into the kernel's new MODEL_ASSISTED strategy
(Task 2) via inspect_with_model's `invoke` callable.

Fail-closed on two independent gates, both checked before any network call:
budget (BudgetGate, adapters/inference/budget_gate.py) and provider policy
(inference/provider_policy.py, ADR-016). Never fabricates a response when the
optional backend package is unavailable.
"""
from __future__ import annotations

from typing import Any

try:
    from cortxt_resilient_inference import execute as _resilient_execute
    from cortxt_resilient_inference.http_adapter import OpenAICompatibleAdapter as _HttpAdapter

    _RI_AVAILABLE = True
except Exception:  # pragma: no cover - only when the optional dep is absent
    _RI_AVAILABLE = False


class TextInferenceError(RuntimeError):
    """Raised on provider-policy denial or an unavailable/failed backend (fail-closed)."""


class TextInferencePort:
    def __init__(self, model: str, budget_gate, provider_evidence: dict,
                 data_class: str = "L0") -> None:
        self._model = model
        self._gate = budget_gate
        self._data_class = data_class
        self._provider_evidence = dict(provider_evidence)

    def invoke(self, prompt: str, output_schema: dict) -> dict:
        from inference.provider_policy import AssuranceStatus, ProviderEvidence, evaluate_provider
        
        evidence = dict(self._provider_evidence)
        status = evidence.get("independent_assurance")
        if isinstance(status, str):
            try:
                evidence["independent_assurance"] = AssuranceStatus(status)
            except ValueError:
                pass
        try:
            decision = evaluate_provider(self._data_class, ProviderEvidence(**evidence))
        except (TypeError, ValueError) as error:
            raise TextInferenceError(f"provider evidence has an invalid schema: {error}") from error
        if decision.allowed is not True:
            raise TextInferenceError(f"provider policy denied this port: {decision.reasons}")
        
        return self._gate(self._call_backend, prompt, output_schema)

    def _call_backend(self, prompt: str, output_schema: dict) -> dict:
        if not _RI_AVAILABLE:
            raise TextInferenceError(
                "cortxt_resilient_inference is unavailable in this environment; "
                "install it and configure CORTXT_INFERENCE_URL/CORTXT_INFERENCE_API_KEY"
            )
        adapter = _HttpAdapter()
        result: Any = _resilient_execute(model=self._model, prompt=prompt,
                                          output_schema=output_schema, adapter=adapter)
        if not isinstance(result, dict):
            raise TextInferenceError("backend returned a non-object response")
        return result
