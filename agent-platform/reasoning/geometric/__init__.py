"""Cortxt Geometric Reasoning Engine — DM3 vertical slice.

Reasoning as paths/transformations in a structured problem space (target
architecture §12): a directed graph of reasoning nodes, embeddings for semantic
proximity, metrics (normalized [0,1]), attractor detection + escape, and guided
exploration. Deterministic (0 model calls); embedding is a stubbed reproducible
function.
"""

from .attractor_detector import AttractorDetector
from .contradiction import Contradiction, ContradictionDetector, find_contradiction
from .escape_attractor import escape_attractor
from .explorer import Explorer, exploration_cost
from .graph_space import ReasoningNode, ProblemSpace
from .metrics import GraphMetrics
from .operators import PerspectiveResult, change_perspective, compare_paths
from .path_scoring import CandidatePathScore, score_path
from .trajectory import TrajectoryReport, apply_confidence_update

__all__ = [
    "ReasoningNode",
    "ProblemSpace",
    "GraphMetrics",
    "AttractorDetector",
    "escape_attractor",
    "Explorer",
    "exploration_cost",
    "Contradiction",
    "ContradictionDetector",
    "find_contradiction",
    "PerspectiveResult",
    "change_perspective",
    "compare_paths",
    "CandidatePathScore",
    "score_path",
    "TrajectoryReport",
    "apply_confidence_update",
]
