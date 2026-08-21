"""P3-DM1: neutral SkillManifest + Hermes adapter + registry — deterministic tests (0 model calls)."""

from __future__ import annotations

from pathlib import Path

import pytest

from portability.skills import (
    HermesSkillAdapter,
    PortabilityValidationError,
    SkillRegistry,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


def _loaded_skills():
    adapter = HermesSkillAdapter()
    reg = SkillRegistry()
    for skill_dir in sorted(FIXTURES.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
            reg.add(adapter.read(skill_dir))
    return reg


def test_hermes_roundtrip():
    """AC: adapter reads Hermes fixture → neutral manifest → export → import → fields equal."""
    adapter = HermesSkillAdapter()
    reg = SkillRegistry()
    for d in sorted(FIXTURES.iterdir()):
        if d.is_dir() and (d / "SKILL.md").is_file():
            reg.add(adapter.read(d))

    export = reg.export_json()
    restored = SkillRegistry.from_export_json(export)
    assert len(restored) == len(reg)
    # field-by-field
    assert restored.get("demo-receptionist", "0.1.0") is not None
    assert restored.get("demo-receptionist") == reg.get("demo-receptionist")
    assert restored.get("demo-researcher") == reg.get("demo-researcher")


def test_registry_idempotent_load():
    """AC: the same skill loaded twice → identical hash sums."""
    reg1 = _loaded_skills()
    reg2 = _loaded_skills()
    assert reg1.manifest_hashes() == reg2.manifest_hashes()
    assert len(reg1.manifest_hashes()) == len(reg1)


def test_linked_files_collected():
    """Adapter collects linked_files (references/ + templates/) deterministically."""
    reg = _loaded_skills()
    rec = reg.get("demo-receptionist")
    assert rec is not None
    assert "references/api.md" in rec.linked_files_refs
    res = reg.get("demo-researcher")
    assert res is not None
    assert "templates/brief.md" in res.linked_files_refs


def test_validation_rejects_missing_name(tmp_path):
    """AC: a missing name raises PortabilityValidationError."""
    skill = tmp_path / "broken"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nversion: 1.0\n---\nbody\n", encoding="utf-8")
    adapter = HermesSkillAdapter()
    with pytest.raises(PortabilityValidationError):
        adapter.read(skill)


def test_validation_rejects_no_skill_md(tmp_path):
    (tmp_path / "skill").mkdir()
    adapter = HermesSkillAdapter()
    with pytest.raises(PortabilityValidationError):
        adapter.read(tmp_path / "skill")


def test_manifest_requires_name():
    from portability.skills.manifest import SkillManifest

    with pytest.raises(ValueError):
        SkillManifest.from_dict({"version": "1.0", "category": "x", "content_md": "c"})


def test_category_list_normalized_before_str(tmp_path):
    """CP1.1 P1: category/tags as list must become 'a,b', not the list repr."""
    skill = tmp_path / "listcat"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: listcat\nversion: 1.0\ncategory:\n  - dev\n  - ops\n---\nbody\n",
        encoding="utf-8",
    )
    adapter = HermesSkillAdapter()
    m = adapter.read(skill)
    assert m.category == "dev,ops"
    assert m.category != "['dev', 'ops']"


def test_manifest_from_dict_none_metadata_safe():
    """CP1.1 P2: explicit null metadata/linked_files_refs breaks not."""
    from portability.skills.manifest import SkillManifest

    m = SkillManifest.from_dict(
        {"name": "x", "version": "1.0", "category": "c", "content_md": "b",
         "metadata": None, "linked_files_refs": None}
    )
    assert m.metadata == {}
    assert m.linked_files_refs == []
