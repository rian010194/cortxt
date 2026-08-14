"""Strategy selection for the reasoning kernel.

A strategy is chosen from problem properties (structure of ``content``), NOT
from a single giant system prompt. This mirrors the target architecture §10.1
(strategy list) and §10's rule that the kernel must not reduce to one prompt.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class Strategy(str, Enum):
    DIRECT = "direct"
    RECURSIVE = "recursive"
    GEOMETRIC = "geometric"
    HUMAN_ESCALATION = "human_escalation"


def _is_nested(obj: Any, depth: int = 0, level: int = 0) -> bool:
    """True if obj contains a list-like nested at ``level`` >= 1."""
    if isinstance(obj, (list, tuple)):
        if level >= 1:
            return True
        return any(_is_nested(x, depth, level + 1) for x in obj)
    return False


def _has_constraint_dependencies(obj: Any) -> bool:
    """True if content is a mapping carrying an explicit 'constraints' key."""
    if isinstance(obj, dict):
        if "constraints" in obj:
            return True
        return any(_has_constraint_dependencies(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_has_constraint_dependencies(x) for x in obj)
    return False


def select_strategy(content: Any) -> Strategy:
    """Pick a strategy deterministically from problem structure.

    Order matters and is intentional:
      1. flat + no constraints  -> direct
      2. nested (list-in-list)  -> recursive
      3. explicit constraints   -> geometric
    """
    if _is_nested(content):
        return Strategy.RECURSIVE
    if _has_constraint_dependencies(content):
        return Strategy.GEOMETRIC
    return Strategy.DIRECT
