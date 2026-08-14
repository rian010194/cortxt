"""Stop conditions and stop reasons for the RLM loop (target architecture §11.3)."""

from __future__ import annotations

from enum import Enum


class StopReason(str, Enum):
    ACCEPTED = "accepted"                # acceptance criteria verified
    LOW_INFO_GAIN = "low_info_gain"      # expected info gain below threshold
    BUDGET_EXHAUSTED = "budget_exhausted"  # remaining budget insufficient
    ALL_INTEGRATED = "all_integrated"    # all relevant branches integrated
    CONTRADICTION = "contradiction"      # material contradiction requires operator/evidence
    POLICY_STOP = "policy_stop"          # policy/safety boundary


class StopCondition:
    """A single evaluable stop condition; deterministic."""
