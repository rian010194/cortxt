"""Portabilitet för skills — neutralt manifest + Hermes-adapter (ADR-012-komplement).

Cortxt äger ett formatneutralt skill-manifest. Hermes-formatet läses via en adapter
och normaliseras till det neutrala manifestet, så arbetsförmågans skills är portabla
och användarägda oberoende av Hermes-runtime (F0).
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
