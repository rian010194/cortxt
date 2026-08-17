"""Controlled learning loop — Fas 8. See docs/superpowers/specs/2026-08-18-fas8-controlled-learning-loop-v01-design.md."""
from __future__ import annotations

from .candidate import Candidate
from .registry import CandidateRegistry

__all__ = ["Candidate", "CandidateRegistry"]
