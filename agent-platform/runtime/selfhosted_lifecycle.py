"""Idle-stop + cold-start lifecycle for a self-hosted Vast.ai vLLM instance (Fas 7, Beslut 8).

Task 4: ``should_stop_for_idle`` -- the decision logic as a pure function (no I/O).
Task 5: ``_VastAiControlAdapter`` (Vast.ai REST boundary) + ``ensure_running()``
wrapper that makes a cold start transparent to the caller.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


def should_stop_for_idle(
    last_activity_ts: float, now_ts: float, idle_threshold_minutes: int
) -> bool:
    """True when idle longer than the threshold (pure arithmetic, fail-closed).

    Note the boundary: ``>=`` threshold means exactly-at-threshold stops too.
    Callers seed ``last_activity_ts`` with provisioning time so a brand-new
    instance is never treated as "idle forever".
    """
    return (now_ts - last_activity_ts) >= idle_threshold_minutes * 60
