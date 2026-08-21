"""Neutral SkillManifest — format-independent, user-owned skill representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillManifest:
    """A format-neutral, versioned skill.

    Contains NO Hermes-specific fields — the contract is owned by Cortxt and can
    be consumed by any runtime (Hermes is an adapter behind this port).
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
            linked_files_refs=[str(r) for r in data.get("linked_files_refs") or []],
            metadata=dict(data.get("metadata") or {}),  # None-safe (CP1.1 P2)
        )
