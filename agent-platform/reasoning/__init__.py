"""Reasoning package for the Cortxt agent platform.

DM2 status: kernel/ (DM1) and recursive/ (RLM engine, DM2) are implemented.
geometric/ (DM3) and the integrated pipeline (DM4) arrive in later milestones
per the checkpoint plan.
"""

from . import kernel, recursive

__all__ = ["kernel", "recursive"]
