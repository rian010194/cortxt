"""EmbeddingPort — real embedding-model invocation for RLM geometric reasoning (Phase 6, §27#10).

Drop-in for reasoning/geometric/embeddings.py's EmbeddingFn surface
(``Callable[[str], list[float]]``): an EmbeddingPort instance is itself callable, so it can be
passed directly as ``CandidatePathScore.embedder`` or ``GraphMetrics.semantic_closeness``'s
``embedder=`` in place of the deterministic ``hash_embedding`` stub.

Mirrors runtime/text_inference_port.py's fail-closed shape (the same BudgetGate +
inference/provider_policy.py gates, both checked before any network call) but targets an
OpenAI-compatible ``/embeddings`` route instead of ``/chat/completions``.
cortxt_resilient_inference's ``OpenAICompatibleAdapter`` is hardcoded to ``/chat/completions``
and a chat-message response shape (see http_adapter.py's ``_endpoint``/``_worker``), so it cannot
be reused unmodified for embeddings; ``_EmbeddingHttpAdapter`` below implements the same
``Adapter`` protocol (``(route, timeout_ms) -> Mapping``) that ``runner.execute`` expects, kept
local to this module rather than changing the external package.

Scope note: unlike ``OpenAICompatibleAdapter``, this first version enforces its timeout
in-process (``urllib`` socket timeout) rather than via a terminable child process. Process-level
isolation can be added later if embeddings calls need the same hard-kill guarantee as chat calls;
nothing here depends on that being deferred.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

try:
    from cortxt_resilient_inference import execute as _resilient_execute

    _RI_AVAILABLE = True
except Exception:  # pragma: no cover - only when the optional dep is absent
    _RI_AVAILABLE = False
    # Bound as a placeholder (never called for real -- _RI_AVAILABLE guards that) so tests
    # can monkeypatch this name even when the optional package isn't installed (default CI).
    _resilient_execute = None

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class EmbeddingError(RuntimeError):
    """Raised on provider-policy denial or an unavailable/failed backend (fail-closed)."""


def _embeddings_endpoint(base_url: str) -> str:
    parsed = urlsplit(base_url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("base_url must use HTTPS (HTTP is allowed only for localhost tests)")
    if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain credentials, query, or fragment")
    return base_url.rstrip("/") + "/embeddings"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so credentials never cross an unvalidated origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


def _classify_http_status(status: int) -> str:
    if status == 404:
        return "invalid_model_id"
    if status == 429:
        return "rate_limited"
    if 300 <= status < 400:
        return "invalid_configuration"
    return "provider_unavailable"


@dataclass(frozen=True)
class _EmbeddingHttpAdapter:
    """Invoke one OpenAI-compatible /embeddings route (Adapter protocol for runner.execute)."""

    text: str

    def __call__(self, route: Mapping[str, object], timeout_ms: int) -> Mapping[str, object]:
        if type(timeout_ms) is not int or timeout_ms <= 0:
            return {"outcome": "invalid_configuration", "latency_ms": 0, "cost_status": "unknown"}
        try:
            base_url = route["base_url"]
            model = route["model"]
            api_key_env = route["api_key_env"]
            if not all(isinstance(value, str) and value for value in (base_url, model, api_key_env)):
                raise ValueError
            endpoint = _embeddings_endpoint(base_url)
        except (KeyError, TypeError, ValueError):
            return {"outcome": "invalid_configuration", "latency_ms": 0, "cost_status": "unknown"}

        api_key = os.environ.get(api_key_env)
        if not api_key:
            return {"outcome": "missing_credentials", "latency_ms": 0, "cost_status": "unknown"}

        started = time.monotonic()
        try:
            body = json.dumps({"model": model, "input": [self.text]}).encode("utf-8")
            request = urllib.request.Request(
                endpoint, data=body, method="POST",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(request, timeout=timeout_ms / 1000) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            latency_ms = int((time.monotonic() - started) * 1000)
            if len(raw) > MAX_RESPONSE_BYTES:
                return {"outcome": "invalid_response", "effect_state": "unknown",
                        "latency_ms": latency_ms, "cost_status": "unknown"}
            payload = json.loads(raw.decode("utf-8"))
            embedding = payload["data"][0]["embedding"]
            if not isinstance(embedding, list) or not all(isinstance(x, (int, float)) for x in embedding):
                raise ValueError
            return {"outcome": "succeeded", "response": {"embedding": embedding},
                    "latency_ms": latency_ms, "cost_status": "unknown"}
        except urllib.error.HTTPError as exc:
            return {"outcome": _classify_http_status(exc.code), "effect_state": "unknown",
                    "latency_ms": int((time.monotonic() - started) * 1000), "cost_status": "unknown"}
        except (urllib.error.URLError, TimeoutError, OSError):
            return {"outcome": "provider_unavailable", "effect_state": "unknown",
                    "latency_ms": int((time.monotonic() - started) * 1000), "cost_status": "unknown"}
        except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            return {"outcome": "invalid_response", "effect_state": "unknown",
                    "latency_ms": int((time.monotonic() - started) * 1000), "cost_status": "unknown"}


class EmbeddingPort:
    """Fail-closed, budget+policy-gated embedding provider; itself an ``EmbeddingFn``.

    Call the instance directly (``port(text) -> list[float]``) to use it as
    ``CandidatePathScore.embedder`` or ``GraphMetrics.semantic_closeness``'s ``embedder=``.
    """

    def __init__(self, model: str, budget_gate, provider_evidence: dict,
                 data_class: str = "L0", base_url_env: str = "CORTXT_EMBEDDING_URL",
                 api_key_env: str = "CORTXT_EMBEDDING_API_KEY",
                 per_attempt_timeout_ms: int = 30000, max_attempts_total: int = 1,
                 expected_dim: int | None = None) -> None:
        self._model = model
        self._gate = budget_gate
        self._data_class = data_class
        self._provider_evidence = dict(provider_evidence)
        self._base_url_env = base_url_env
        self._api_key_env = api_key_env
        self._timeout_ms = per_attempt_timeout_ms
        self._max_attempts = max_attempts_total
        self._expected_dim = expected_dim

    def __call__(self, text: str) -> list[float]:
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
            raise EmbeddingError(f"provider evidence has an invalid schema: {error}") from error
        if decision.allowed is not True:
            raise EmbeddingError(f"provider policy denied this port: {decision.reasons}")

        return self._gate(self._call_backend, text)

    def _call_backend(self, text: str) -> list[float]:
        if not _RI_AVAILABLE:
            raise EmbeddingError(
                "cortxt_resilient_inference is unavailable in this environment; "
                f"install it and configure {self._base_url_env}/{self._api_key_env}"
            )
        base_url = os.environ.get(self._base_url_env)
        if not base_url or not os.environ.get(self._api_key_env):
            raise EmbeddingError(
                f"backend not configured: set {self._base_url_env}/{self._api_key_env}"
            )
        task_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
        request = {
            "task_id": task_id,
            "routes": [
                {
                    "route_id": "l0-embedding",
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
        adapter = _EmbeddingHttpAdapter(text=text)
        envelope: Any = _resilient_execute(request, adapters={"l0-embedding": adapter})
        if envelope.get("status") != "succeeded":
            raise EmbeddingError(
                f"embedding call did not succeed (task={task_id}, "
                f"reason={envelope.get('terminal_reason')}, attempts={envelope.get('attempts')})"
            )
        response = envelope.get("response") or {}
        embedding = response.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise EmbeddingError("backend response had no embedding vector")
        if self._expected_dim is not None and len(embedding) != self._expected_dim:
            raise EmbeddingError(
                f"backend returned dim={len(embedding)}, expected {self._expected_dim}"
            )
        return [float(x) for x in embedding]
