"""ResilientInferencePort — concrete InferencePort backed by provider-neutral inference.

Implements the reasoning kernel's ``InferencePort`` protocol (``invoke(content) -> int``)
using ``cortxt-resilient-inference`` (policy-gated, provider-neutral fallback execution)
behind an OpenAI-compatible HTTP adapter.

Import direction is adapter → port, never port → adapter: this file depends on the
kernel's port protocol and on the provider-neutral runner, but the kernel never
imports this package (enforced by ``tests/reasoning/test_no_external_deps.py``).
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from reasoning.recursive.rlm_engine import InferencePort

# Provider-neutral reference implementation (separate repo, v0.2).
try:
    from cortxt_resilient_inference import execute as _resilient_execute
    from cortxt_resilient_inference.http_adapter import OpenAICompatibleAdapter as _HttpAdapter

    _RI_AVAILABLE = True
except Exception:  # pragma: no cover - only when the optional dep is absent
    _RI_AVAILABLE = False


class InferenceExecutionError(RuntimeError):
    """Raised when a provider-neutral inference call fails to produce an int (fail-closed)."""


class ResilientInferencePort:
    """Adapter implementing InferencePort.invoke(content) -> int via resilient inference.

    Credentials/base-url are read ONLY from environment variables; never hardcoded
    and never present in the repository. If the environment is not configured this
    adapter reports ``available() == False`` and ``invoke`` raises a clear error —
    it never silently fabricates a value.
    """

    def __init__(
        self,
        model: str | None = None,
        base_url_env: str = "CORTXT_INFERENCE_URL",
        api_key_env: str = "CORTXT_INFERENCE_API_KEY",
        per_attempt_timeout_ms: int = 30000,
        max_attempts_total: int = 1,
    ) -> None:
        if not _RI_AVAILABLE:
            raise RuntimeError("cortxt-resilient-inference is not installed")
        self._model = model or os.environ.get("CORTXT_INFERENCE_MODEL")
        self._base_url_env = base_url_env
        self._api_key_env = api_key_env
        self._timeout_ms = per_attempt_timeout_ms
        self._max_attempts = max_attempts_total

    def available(self) -> bool:
        """True only when credentials + endpoint + model are all configured."""
        return bool(
            self._model
            and os.environ.get(self._base_url_env)
            and os.environ.get(self._api_key_env)
        )

    def invoke(self, content: Any) -> int:
        if not self.available():
            raise InferenceExecutionError(
                "InferencePort not configured: set CORTXT_INFERENCE_URL / "
                "CORTXT_INFERENCE_API_KEY / CORTXT_INFERENCE_MODEL (L0 only)"
            )
        if self._model is None:
            raise InferenceExecutionError("model not configured")
        task_body = repr(content)
        task_id = hashlib.sha256(task_body.encode("utf-8")).hexdigest()[:24]

        request = {
            "task_id": task_id,
            "routes": [
                {
                    "route_id": "l0-default",
                    "policy_eligible": True,
                    "base_url": os.environ[self._base_url_env],
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
                    "Reply with a single integer only (nothing else, no explanation). "
                    "Calculate the sum of all integers in the input."
                ),
            },
            {"role": "user", "content": task_body},
        ]
        adapter = _HttpAdapter(messages=messages)
        envelope = _resilient_execute(request, adapters={"l0-default": adapter})
        return self._parse(envelope, task_id)

    def _parse(self, envelope: dict[str, Any], task_id: str) -> int:
        if envelope.get("status") != "succeeded":
            raise InferenceExecutionError(
                f"inference did not succeed (task={task_id}, reason={envelope.get('terminal_reason')})"
            )
        response = envelope.get("response")
        if not isinstance(response, dict):
            raise InferenceExecutionError(f"invalid response for task {task_id}")
        # The assistant message carries the integer as text; parse strictly.
        content = response.get("content")
        text = content if isinstance(content, str) else repr(content).strip()
        try:
            return int(text.strip())
        except (TypeError, ValueError) as exc:
            raise InferenceExecutionError(
                f"could not parse integer from model response (task={task_id}): {text!r}"
            ) from exc
