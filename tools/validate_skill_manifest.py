#!/usr/bin/env python3
"""
Skill Manifest Validator
Validates skill.yaml against contracts/skill-manifest.schema.json
"""

import json
import sys
import yaml
from pathlib import Path
from jsonschema import validate, ValidationError

SCHEMA_PATH = Path(__file__).parent.parent / "contracts" / "skill-manifest.schema.json"

def load_schema():
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_skill_manifest(skill_dir):
    """Load skill.yaml from skill directory"""
    manifest_path = Path(skill_dir) / "skill.yaml"
    if manifest_path.exists():
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    # Fallback to SKILL.md frontmatter
    skill_md = Path(skill_dir) / "SKILL.md"
    if skill_md.exists():
        with open(skill_md, 'r', encoding='utf-8') as f:
            content = f.read()
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 2:
                return yaml.safe_load(parts[1])
    return None

def validate_skill(skill_dir, schema):
    manifest = load_skill_manifest(skill_dir)
    if not manifest:
        return False, f"No skill.yaml or valid SKILL.md frontmatter found in {skill_dir}"
    
    try:
        validate(instance=manifest, schema=schema)
        return True, "Valid"
    except ValidationError as e:
        return False, f"Validation error: {e.message} at {'.'.join(str(p) for p in e.path)}"

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Validate skill manifests")
    parser.add_argument("skills_dir", nargs="?", default="skills", help="Skills directory")
    parser.add_argument("--strict", action="store_true", help="Exit with error on any invalid skill")
    args = parser.parse_args()
    
    schema = load_schema()
    skills_dir = Path(args.skills_dir)
    
    if not skills_dir.exists():
        print(f"Skills directory not found: {skills_dir}")
        return 1
    
    skill_dirs = [d.parent for d in skills_dir.rglob("skill.yaml")]
    if not skill_dirs:
        print(f"No skill directories found in {skills_dir}")
        return 0
    
    results = []
    for skill_dir in skill_dirs:
        valid, msg = validate_skill(skill_dir, schema)
        status = "✅" if valid else "❌"
        print(f"{status} {skill_dir.name}: {msg}")
        results.append((skill_dir.name, valid, msg))
    
    invalid = [r for r in results if not r[1]]
    if invalid:
        print(f"\n{len(invalid)}/{len(results)} skills invalid")
        if args.strict:
            return 1
    else:
        print(f"\n✅ All {len(results)} skills valid")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
