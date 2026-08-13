"""Reasoning package for the Cortxt agent platform.

DM3 status: kernel/ (DM1), recursive/ (RLM, DM2), geometric/ (DM3) implemented.
The integrated pipeline (DM4) arrives last per the checkpoint plan.
"""

from . import geometric, kernel, recursive

__all__ = ["kernel", "recursive", "geometric"]
