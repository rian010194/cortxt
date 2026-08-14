"""Cortxt RLM Engine — bounded recursive decomposition over external context.

DM2 vertical slice: a deterministic engine that decomposes a ProblemState into
bounded sub-problems, allocates per-branch budgets, executes child runs through
a mockable inference interface, and integrates + challenges results — all under
hard resource limits (target architecture §11). No model is called by the
engine itself; inference is injected and stubbed in tests.
"""

from .bounds import RLMConfig
from .rlm_engine import RLMEngine, InferencePort
from .stop_conditions import StopCondition, StopReason

__all__ = ["RLMConfig", "RLMEngine", "InferencePort", "StopCondition", "StopReason"]
