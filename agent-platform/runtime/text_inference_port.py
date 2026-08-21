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

import hashlib
import json
import os
from typing import Any

try:
    from cortxt_resilient_inference import execute as _resilient_execute
    from cortxt_resilient_inference.http_adapter import OpenAICompatibleAdapter as _HttpAdapter

    _RI_AVAILABLE = True
except Exception:  # pragma: no cover - only when the optional dep is absent
    _RI_AVAILABLE = False
    # Bound as placeholders (never called for real -- _RI_AVAILABLE guards that)
    # so tests can monkeypatch.setattr these names even when the optional
    # package isn't installed, e.g. in default CI.
    _resilient_execute = None
    _HttpAdapter = None


class TextInferenceError(RuntimeError):
    """Raised on provider-policy denial or an unavailable/failed backend (fail-closed)."""


class TextInferencePort:
    def __init__(self, model: str, budget_gate, provider_evidence: dict,
                 data_class: str = "L0", base_url_env: str = "CORTXT_INFERENCE_URL",
                 api_key_env: str = "CORTXT_INFERENCE_API_KEY",
                 per_attempt_timeout_ms: int = 30000, max_attempts_total: int = 1,
                 route_id: str = "l0-default") -> None:
        self._model = model
        self._gate = budget_gate
        self._data_class = data_class
        self._provider_evidence = dict(provider_evidence)
        self._base_url_env = base_url_env
        self._api_key_env = api_key_env
        self._timeout_ms = per_attempt_timeout_ms
        self._max_attempts = max_attempts_total
        self._route_id = route_id

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
        
        # Phase 7 Decision 6: make spend rows route-isolated so GROUP BY route_id is
        # meaningful. Only when the gate exposes set_route_id (BudgetGate does);
        # a bare callable gate keeps its default route.
        set_route = getattr(self._gate, "set_route_id", None)
        if callable(set_route):
            set_route(self._route_id)
        return self._gate(self._call_backend, prompt, output_schema)

    def _call_backend(self, prompt: str, output_schema: dict) -> dict:
        if not _RI_AVAILABLE:
            raise TextInferenceError(
                "cortxt_resilient_inference is unavailable in this environment; "
                "install it and configure CORTXT_INFERENCE_URL/CORTXT_INFERENCE_API_KEY"
            )
        base_url = os.environ.get(self._base_url_env)
        if not base_url or not os.environ.get(self._api_key_env):
            raise TextInferenceError(
                f"backend not configured: set {self._base_url_env}/{self._api_key_env}"
            )
        task_id = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:24]
        request = {
            "task_id": task_id,
            "routes": [
                {
                    "route_id": self._route_id,
                    "policy_eligible": True,
                    "base_url": base_url,
                    "model": self._model,
                    "api_key_env": self._api_key_env,
                }
            ],
            "max_attempts_total": self._max_attempts,
            "per_attempt_timeout_ms": self._timeout_ms,
            "idempotency": "read_only",
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "Respond with a single JSON object only -- no prose, no markdown "
                    "code fences. The object MUST validate against this exact JSON "
                    "Schema (match field names, nesting, and required properties "
                    "precisely -- do not invent your own structure):\n\n"
                    + json.dumps(output_schema, indent=2)
                ),
            },
            {"role": "user", "content": prompt},
        ]
        adapter = _HttpAdapter(messages=messages)
        envelope: Any = _resilient_execute(request, adapters={self._route_id: adapter})
        if envelope.get("status") != "succeeded":
            raise TextInferenceError(
                f"inference did not succeed (task={task_id}, reason={envelope.get('terminal_reason')})"
            )
        response = envelope.get("response") or {}
        content = response.get("content")
        if not isinstance(content, str):
            raise TextInferenceError("backend response had no text content")
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            first_line, _, rest = content.partition("\n")
            if first_line.strip().isalpha():
                content = rest
            content = content.strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError as error:
            raise TextInferenceError(f"backend response was not valid JSON: {error}") from error
        if not isinstance(result, dict):
            raise TextInferenceError("backend returned a non-object response")
        return result
