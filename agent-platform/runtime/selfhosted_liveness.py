"""Liveness probes for a self-hosted vLLM endpoint (Phase 7, Decision 5).

Two layers:
- ``parse_liveness``: a pure function that normalizes vLLM ``/health`` and
  Prometheus ``/metrics`` responses into a typed ``LivenessSample``. 0 network
  I/O here -- everything is tested against static fixtures.
- ``_LivenessHttpProbe`` (Task 3): the single HTTP boundary that talks to
  ``/health`` and ``/metrics`` and delegates to ``parse_liveness``.

Same split discipline as ``embedding_port.py``'s local HTTP adapter, and the
same degrade-not-fabricate rule: when health is down or a metric is missing,
the corresponding field is ``None`` -- we never invent a value.
"""
from __future__ import annotations

import os
import re
import time
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class LivenessSample:
    alive: bool
    vram_pct: float | None
    queue_depth: int | None
    tokens_per_sec: float | None
    checked_at: float


# vLLM Prometheus metric lines, e.g. (verified against a live vLLM 0.27.1
# instance, 2026-08-17 -- the real metric is kv_cache_usage_perc, not
# gpu_cache_usage_perc as an earlier draft assumed):
#   vllm:kv_cache_usage_perc{engine="0",model_name="Qwen/Qwen3-8B-AWQ"} 0.42
_VRAM_RE = re.compile(r"^vllm:kv_cache_usage_perc\b.*\s([0-9.]+)$", re.MULTILINE)
_QUEUE_RE = re.compile(r"^vllm:num_requests_waiting\b.*\s([0-9.]+)$", re.MULTILINE)


def _extract_float(metric_text: str, pattern: re.Pattern[str]) -> float | None:
    m = pattern.search(metric_text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_liveness(
    health_ok: bool, metrics_text: str, now_fn: "callable[[], float]" = time.time
) -> LivenessSample:
    if not health_ok:
        # Down: degrade, never fabricate. checked_at still recorded.
        return LivenessSample(
            alive=False, vram_pct=None, queue_depth=None, tokens_per_sec=None,
            checked_at=now_fn(),
        )
    vram = _extract_float(metrics_text, _VRAM_RE)
    queue = _extract_float(metrics_text, _QUEUE_RE)
    return LivenessSample(
        alive=True,
        vram_pct=(vram * 100.0) if vram is not None else None,
        queue_depth=(int(queue) if queue is not None else None),
        tokens_per_sec=None,
        checked_at=now_fn(),
    )


class _LivenessHttpProbe:
    """The single HTTP boundary against vLLM's /health and /metrics.

    Same fail-closed classification discipline as embedding_port.py's
    _EmbeddingHttpAdapter: TimeoutError / URLError / OSError (or any non-200 on
    /health) -> alive=False; nothing escapes check() as an uncontrolled
    exception.
    """

    def __init__(self, base_url: str, timeout_ms: int = 1000,
                 api_key_env: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = max(0.001, timeout_ms / 1000.0)
        self._api_key_env = api_key_env

    def _get_text(self, path: str) -> str | None:
        headers = {}
        if self._api_key_env:
            api_key = os.environ.get(self._api_key_env)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(f"{self._base_url}{path}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (TimeoutError, urllib.error.URLError, OSError):
            return None

    def _fetch_health(self) -> bool:
        # vLLM /health returns 200 when ready; any non-200 / exception -> down.
        return self._get_text("/health") is not None

    def _fetch_metrics(self) -> str:
        text = self._get_text("/metrics")
        return text if text is not None else ""

    def check(self) -> LivenessSample:
        health_ok = self._fetch_health()
        metrics_text = self._fetch_metrics()
        return parse_liveness(health_ok=health_ok, metrics_text=metrics_text)
