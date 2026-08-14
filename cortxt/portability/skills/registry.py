"""SkillRegistry — in-memory register + neutral export/import/validation."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict

from .manifest import SkillManifest


class SkillRegistry:
    """Register över neutrala SkillManifest; idempotent load + export/validate.

    Load av samma skill två gånger ger identiska manifest (hash-jämförbart) —
    registret är deterministiskt och nycklas på ``name@version``.
    """

    def __init__(self) -> None:
        self._skills: OrderedDict[str, SkillManifest] = OrderedDict()

    @staticmethod
    def _key(m: SkillManifest) -> str:
        return f"{m.name}@{m.version}"

    def add(self, manifest: SkillManifest) -> None:
        self._skills[self._key(manifest)] = manifest

    def get(self, name: str, version: str | None = None) -> SkillManifest | None:
        if version is not None:
            return self._skills.get(f"{name}@{version}")
        # senaste versionen av ett namn (sista inlagda)
        matches = [m for k, m in self._skills.items() if k.startswith(f"{name}@")]
        return matches[-1] if matches else None

    def all(self) -> list[SkillManifest]:
        return list(self._skills.values())

    def __len__(self) -> int:
        return len(self._skills)

    def to_neutral_export(self) -> dict:
        """Deterministisk neutral export (lista av manifest-dicts, fältordnat)."""
        return {"skills": [s.to_dict() for s in self.all()]}

    def export_json(self) -> str:
        payload = {"skills": [s.to_dict() for s in self.all()]}
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)

    def manifest_hashes(self) -> dict[str, str]:
        """Nyckel → sha256 för idempotens-jämförelse."""
        return {
            self._key(m): hashlib.sha256(
                json.dumps(m.to_dict(), sort_keys=True).encode("utf-8")
            ).hexdigest()
            for m in self.all()
        }

    @classmethod
    def from_export_json(cls, text: str) -> "SkillRegistry":
        data = json.loads(text)
        reg = cls()
        for item in data.get("skills", []):
            reg.add(SkillManifest.from_dict(item))
        return reg
