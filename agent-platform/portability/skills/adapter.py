"""HermesSkillAdapter — reads the Hermes skill format and normalizes to SkillManifest.

Reads a Hermes skill directory (SKILL.md with YAML frontmatter + linked_files under
references/ | templates/ | scripts/ | assets/) and produces a neutral SkillManifest.
Never IMPORTS hermes_tools or the Hermes runtime — works on plain files, so an
exported skill can be read without Hermes installed (portability invariant).
"""

from __future__ import annotations

import re
from pathlib import Path

try:  # PyYAML is an implementation choice; the neutral manifest is YAML/JSON-independent
    import yaml

    _HAS_YAML = True
except Exception:  # pragma: no cover
    _HAS_YAML = False

from .manifest import SkillManifest

# linked-file directories we treat as part of a skill (known Hermes skill layout)
_LINKED_DIRS = ("references", "templates", "scripts", "assets")


def _json_safe(value):
    """Recursively normalize YAML output to JSON-serializable types (CP1.1 P2)."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)  # other types (datetime, set, etc.) -> str


class PortabilityValidationError(ValueError):
    """Raised when a skill cannot be validated into a neutral manifest."""


class HermesSkillAdapter:
    """Adapter from a Hermes skill directory (SKILL.md) → neutral SkillManifest."""

    def read(self, skill_dir: str | Path) -> SkillManifest:
        root = Path(skill_dir)
        skill_md = root / "SKILL.md"
        if not skill_md.is_file():
            raise PortabilityValidationError(f"no SKILL.md in {root}")
        content = skill_md.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(content)
        meta = self._parse_frontmatter(frontmatter)
        name = meta.get("name")
        if not name:  # a skill manifest REQUIRES an explicit name (DM1 AC: missing name -> error)
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
            # absolute path into hash-affected metadata (CP1.1 P2 — idempotency violation).
            metadata={"frontmatter": _json_safe(meta)},
        )

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[str, str]:
        if not content.startswith("---"):
            return "", content
        # frontmatter between two ----lines
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            raise PortabilityValidationError("malformed YAML frontmatter")
        return match.group(1), content[match.end():]

    def _parse_frontmatter(self, block: str) -> dict:
        if not block.strip():
            return {}
        if not _HAS_YAML:
            # Minimal YAML-like fallback (key: value + simple '- item' lists
            # under a bare 'key:' line), only for environments without PyYAML.
            out: dict = {}
            last_key: str | None = None
            for line in block.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if stripped.startswith("- ") and last_key is not None:
                    item = stripped[2:].strip().strip("'\"")
                    existing = out.get(last_key)
                    if isinstance(existing, list):
                        existing.append(item)
                    else:
                        out[last_key] = [item]
                    continue
                if ":" in line:
                    k, _, v = line.partition(":")
                    key = k.strip()
                    value = v.strip().strip("'\"")
                    out[key] = value
                    last_key = key if value == "" else None
            return out
        try:
            data = yaml.safe_load(block) or {}
        except Exception as exc:
            raise PortabilityValidationError(f"invalid YAML frontmatter: {exc}") from exc
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _collect_linked(refs: object, root: Path) -> list[str]:
        explicit = [str(r) for r in refs] if isinstance(refs, list) else []
        # Plus all files under known linked dirs (deterministic, relative to root)
        discovered: list[str] = []
        for d in _LINKED_DIRS:
            base = root / d
            if base.is_dir():
                for p in sorted(base.rglob("*")):
                    if p.is_file():
                        discovered.append(p.relative_to(root).as_posix())
        # sorted, deduplicated
        merged = sorted(set(explicit) | set(discovered))
        return merged
