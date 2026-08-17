"""Liveness probes for a self-hosted vLLM endpoint (Fas 7, Beslut 5).

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

import re
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class LivenessSample:
    alive: bool
    vram_pct: float | None
    queue_depth: int | None
    tokens_per_sec: float | None
    checked_at: float


# vLLM Prometheus metric lines, e.g.:
#   vllm:gpu_cache_usage_perc{model_name="qwen3-8b-instruct"} 0.42
_VRAM_RE = re.compile(r"^vllm:gpu_cache_usage_perc\b.*\s([0-9.]+)$", re.MULTILINE)
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
