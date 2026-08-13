"""Reasoning package for the Cortxt agent platform.

DM1 status: kernel/ is implemented (ProblemState, strategy selector,
deterministic operators, engine). recursive/ (RLM) and geometric/ arrive in
later milestones per the checkpoint plan.
"""

from . import kernel

__all__ = ["kernel"]
