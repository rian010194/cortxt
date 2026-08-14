"""HermesSkillAdapter — läser Hermes-skillformat och normaliserar till SkillManifest.

Läser en Hermes skill-katalog (SKILL.md med YAML-frontmatter + linked_files under
references/ | templates/ | scripts/ | assets/) och producerar ett neutralt SkillManifest.
IMPORTERAR aldrig hermes_tools eller Hermes-runtime — fungerar på rena filer, så en
exporterad skill kan läsas utan att Hermes är installerat (portabilitets-invariant).
"""

from __future__ import annotations

import re
from pathlib import Path

try:  # PyYAML är ett implementeringsval; neutralt manifest är YAML/JSON-oberoende
    import yaml

    _HAS_YAML = True
except Exception:  # pragma: no cover
    _HAS_YAML = False

from .manifest import SkillManifest

# linked-file-kataloger vi behandlar som del av en skill (kända Hermes-skill-layout)
_LINKED_DIRS = ("references", "templates", "scripts", "assets")


def _json_safe(value):
    """Rekursivt normalisera YAML-utdata till JSON-serialiserbara typer (CP1.1 P2)."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)  # övriga (datetime, set, osv.) -> str


class PortabilityValidationError(ValueError):
    """Raised när en skill inte kan valideras till ett neutralt manifest."""


class HermesSkillAdapter:
    """Adapter från Hermes-skill-katalog (SKILL.md) → neutralt SkillManifest."""

    def read(self, skill_dir: str | Path) -> SkillManifest:
        root = Path(skill_dir)
        skill_md = root / "SKILL.md"
        if not skill_md.is_file():
            raise PortabilityValidationError(f"no SKILL.md in {root}")
        content = skill_md.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(content)
        meta = self._parse_frontmatter(frontmatter)
        name = meta.get("name")
        if not name:  # a skill manifest REQUIRES an explicit name (DM1 AC: saknad name -> error)
            raise PortabilityValidationError("manifest requires a non-empty 'name' in frontmatter")
        name = str(name)
        version = str(meta.get("version") or "0.0.0")
        category = meta.get("category") or meta.get("tags") or ""
        if isinstance(category, list):  # normalize lists BEFORE str() (CP1.1 P1)
            category = ",".join(str(t) for t in category)
        category = str(category)
        linked = self._collect_linked(refs=meta.get("linked_files", []), root=root)
        return SkillManifest(
            name=name,
            version=version,
            category=category,
            content_md=body.strip(),
            linked_files_refs=linked,
            # Sanitize frontmatter to JSON-safe types for export, and do NOT bake the
            # absolute path into hash-affected metadata (CP1.1 P2 — idempotensbrott).
            metadata={"frontmatter": _json_safe(meta)},
        )

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[str, str]:
        if not content.startswith("---"):
            return "", content
        # frontmatter mellan två ----rader
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            raise PortabilityValidationError("malformed YAML frontmatter")
        return match.group(1), content[match.end():]

    def _parse_frontmatter(self, block: str) -> dict:
        if not block.strip():
            return {}
        if not _HAS_YAML:
            # Minimal YAML-liknande fallback (key: value), endast för env utan PyYAML
            out: dict = {}
            for line in block.splitlines():
                if ":" in line and not line.lstrip().startswith("#"):
                    k, _, v = line.partition(":")
                    out[k.strip()] = v.strip().strip("'\"")
            return out
        try:
            data = yaml.safe_load(block) or {}
        except Exception as exc:
            raise PortabilityValidationError(f"invalid YAML frontmatter: {exc}") from exc
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _collect_linked(refs: object, root: Path) -> list[str]:
        explicit = [str(r) for r in refs] if isinstance(refs, list) else []
        # Plus alla filer under kända linked-dirs (deterministiskt, relativt till root)
        discovered: list[str] = []
        for d in _LINKED_DIRS:
            base = root / d
            if base.is_dir():
                for p in sorted(base.rglob("*")):
                    if p.is_file():
                        discovered.append(p.relative_to(root).as_posix())
        # sorterad, dedupad
        merged = sorted(set(explicit) | set(discovered))
        return merged
