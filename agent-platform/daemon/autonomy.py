"""Earned unattended autonomy per (engine_id, task_shape) class (spec:
"Autonomy model - earned, not assumed"). Mirrors the N=3
consecutive-clean-runs rule target-architecture.md §23 already applies to
Fas 4+ exit criteria, applied here to the daemon's own track record instead
of a new invented threshold."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AutonomyTracker:
    unlock_threshold: int = 3
    _streaks: dict[tuple[str, str], int] = field(default_factory=dict)

    def record_pass(self, engine_id: str, task_shape: str, clean: bool) -> None:
        key = (engine_id, task_shape)
        self._streaks[key] = (self._streaks.get(key, 0) + 1) if clean else 0

    def is_unlocked(self, engine_id: str, task_shape: str) -> bool:
        return self._streaks.get((engine_id, task_shape), 0) >= self.unlock_threshold
