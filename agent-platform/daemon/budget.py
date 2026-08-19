"""Daemon-level total budget ceiling (spec: dispatch-contract.md already
requires max_cost_usd/max_runtime_seconds per individual request; this adds
a whole-session ceiling that halts the loop independent of per-run limits).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SessionBudget:
    max_cost_usd: float
    max_wall_clock_seconds: float
    spent_usd: float = 0.0
    _started_at: float = field(default_factory=lambda: time.monotonic())

    def record_cost(self, cost_usd: float) -> None:
        if cost_usd < 0:
            raise ValueError(f"cost_usd must be >= 0, got {cost_usd}")
        self.spent_usd += cost_usd

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def exhausted(self) -> bool:
        return self.spent_usd >= self.max_cost_usd or self.elapsed_seconds() >= self.max_wall_clock_seconds
