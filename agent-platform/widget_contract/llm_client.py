"""Fixed-model text-completion wrapper for widget-spec generation.

Deliberately does NOT use the daemon's cost-based `routing.engine_manifest.
route()` -- issue #366 (no reliability signal on that router) is unresolved,
and wiring cost-routing into generation before it's fixed would repeat the
silent-failure pattern that already hit issue #362's daemon dispatch. The
model is a single pinned value from CORTXT_WIDGET_GEN_MODEL until #366 ships.

Credentials/base-url are read only from environment variables, matching
ResilientInferencePort's convention -- never hardcoded, never in the repo.
"""
from __future__ import annotations

import hashlib
import os

from cortxt_resilient_inference import execute as _execute
from cortxt_resilient_inference.http_adapter import OpenAICompatibleAdapter


class LLMCallError(RuntimeError):
    """Raised when the fixed-model completion call fails to produce text."""


def generate_text(
    prompt: str,
    *,
    system: str | None = None,
    model_env: str = "CORTXT_WIDGET_GEN_MODEL",
    base_url_env: str = "CORTXT_INFERENCE_URL",
    api_key_env: str = "CORTXT_INFERENCE_API_KEY",
    timeout_ms: int = 30000,
) -> str:
    model = os.environ.get(model_env)
    base_url = os.environ.get(base_url_env)
    api_key_present = bool(os.environ.get(api_key_env))
    if not (model and base_url and api_key_present):
        raise LLMCallError(
            f"LLM client not configured: set {base_url_env} / {api_key_env} / {model_env}"
        )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    task_id = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:24]
    request = {
        "task_id": task_id,
        "routes": [{
            "route_id": "l0-default",
            "policy_eligible": True,
            "base_url": base_url,
            "model": model,
            "api_key_env": api_key_env,
        }],
        "max_attempts_total": 1,
        "per_attempt_timeout_ms": timeout_ms,
        "idempotency": "read_only",
    }
    adapters = {"l0-default": OpenAICompatibleAdapter(messages=messages)}
    result = _execute(request, adapters)
    if result.get("status") != "succeeded":
        raise LLMCallError(f"LLM call did not succeed: {result.get('terminal_reason')}")
    response = result.get("response") or {}
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMCallError("LLM call succeeded but returned no text content")
    return content.strip()
