"""Neutralt SkillManifest — formatoberoende, användarägd skill-representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillManifest:
    """En formatneutral, versionerad skill.

    Innehåller INGA Hermes-specifika fält — kontraktet ägs av Cortxt och kan
    konsumeras av vilken runtime som helst (Hermes är en adapter bakom denna port).
    """

    name: str
    version: str
    category: str
    content_md: str
    linked_files_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillManifest":
        try:
            name = str(data["name"])
            version = str(data["version"])
            category = str(data["category"])
            content_md = str(data["content_md"])
        except (KeyError, TypeError) as exc:
            raise ValueError(f"invalid manifest: missing/typed field: {exc}") from exc
        return cls(
            name=name,
            version=version,
            category=category,
            content_md=content_md,
            linked_files_refs=[str(r) for r in data.get("linked_files_refs", [])],
            metadata=dict(data.get("metadata", {})),
        )
