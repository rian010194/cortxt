"""Skill portability — neutral manifest + Hermes adapter (ADR-012 complement).

Cortxt owns a format-neutral skill manifest. The Hermes format is read via an adapter
and normalized to the neutral manifest, so the capability's skills are portable
and user-owned, independent of the Hermes runtime (F0).
"""

from .adapter import HermesSkillAdapter, PortabilityValidationError
from .manifest import SkillManifest
from .registry import SkillRegistry

__all__ = [
    "SkillManifest",
    "SkillRegistry",
    "HermesSkillAdapter",
    "PortabilityValidationError",
]
