"""ProblemState — the central domain model for reasoning.

A ProblemState is a typed, immutable-ish node in the reasoning structure. It
carries the content under consideration, its position in the parent/child tree,
a confidence value, the operator that produced it, and an append-only
transformation log (a traceable reasoning step, per target architecture §9–§10).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


def _next_id(counter: itertools.count) -> str:
    return f"state-{next(counter):05d}"


# A single module-level counter keeps ids unique within a test process.
_ID_COUNTER = itertools.count()


@dataclass(eq=False)
class ProblemState:
    """A node in the reasoning structure.

    ``content`` is opaque from the kernel's perspective; operators interpret it
    based on the strategy. ``children`` are produced by ``decompose``;
    ``parent`` links back so an integrator can fold results upward.
    """

    content: Any
    id: str = field(default_factory=lambda: _next_id(_ID_COUNTER))
    parent: Optional["ProblemState"] = field(default=None, repr=False)
    children: list["ProblemState"] = field(default_factory=list)
    confidence: float = 0.0
    applied_operator: Optional[str] = None
    transformation_log: list[str] = field(default_factory=list)

    def record(self, operator: str, summary: str) -> None:
        """Append a structured, reviewable reasoning step."""
        self.applied_operator = operator
        self.transformation_log.append(f"{operator}: {summary}")

    def is_leaf(self) -> bool:
        return not self.children

    def depth(self) -> int:
        d = 0
        node: Optional[ProblemState] = self
        while node.parent is not None:
            d += 1
            node = node.parent
        return d

    def add_child(self, child: "ProblemState") -> None:
        child.parent = self
        self.children.append(child)

    def __repr__(self) -> str:  # keep logs readable
        return f"ProblemState({self.id}, op={self.applied_operator}, conf={self.confidence:.2f})"


def new_problem(content: Any) -> ProblemState:
    """Create a fresh root ProblemState with no operator applied yet."""
    return ProblemState(content=content)
