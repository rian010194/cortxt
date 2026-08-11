#!/usr/bin/env python3
"""
Breaking Changes Checker for Skills
Compares skill manifest against previous version to detect breaking changes
"""

import json
import sys
import yaml
import subprocess
from pathlib import Path

def get_git_prev_version(skill_name):
    """Get previous version from git history"""
    try:
        # Get the skill.yaml from previous commit
        result = subprocess.run(
            ["git", "show", "HEAD~1:skills/" + skill_name + "/skill.yaml"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent
        )
        if result.returncode == 0:
            return yaml.safe_load(result.stdout)
    except Exception:
        pass
    return None

def check_breaking_changes(current, previous):
    """Check for breaking changes between versions"""
    breaking = []
    
    if not previous:
        return breaking
    
    # Version must be incremented
    if current.get("version") == previous.get("version"):
        breaking.append("Version not incremented")
    
    # Maturity regression
    maturity_order = {"experimental": 0, "stable": 1, "deprecated": 2}
    if maturity_order.get(current.get("maturity", "experimental"), 0) < maturity_order.get(previous.get("maturity", "experimental"), 0):
        breaking.append(f"Maturity regression: {previous.get('maturity')} -> {current.get('maturity')}")
    
    # Interface changes
    curr_iface = current.get("interface", {})
    prev_iface = previous.get("interface", {})
    for key in ["input_schema", "output_schema", "error_codes", "openapi"]:
        if curr_iface.get(key) != prev_iface.get(key):
            breaking.append(f"Interface file changed: {key}")
    
    # Error taxonomy changes (removing codes is breaking)
    curr_errors = set(current.get("error_taxonomy", {}).get("transient", []) + 
                      current.get("error_taxonomy", {}).get("permanent", []))
    prev_errors = set(previous.get("error_taxonomy", {}).get("transient", []) + 
                      previous.get("error_taxonomy", {}).get("permanent", []))
    removed_errors = prev_errors - curr_errors
    if removed_errors:
        breaking.append(f"Error codes removed: {', '.join(removed_errors)}")
    
    # Dependency changes (removing required dep is breaking)
    curr_deps = {d["name"]: d for d in current.get("depends_on", [])}
    prev_deps = {d["name"]: d for d in previous.get("depends_on", [])}
    for name, dep in prev_deps.items():
        if dep.get("required") and name not in curr_deps:
            breaking.append(f"Required dependency removed: {name}")
        if name in curr_deps and curr_deps[name].get("required") != dep.get("required"):
            breaking.append(f"Dependency requirement changed: {name}")
    
    return breaking

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Check for breaking changes in skills")
    parser.add_argument("skills_dir", nargs="?", default="skills", help="Skills directory")
    parser.add_argument("--skill", help="Check specific skill only")
    args = parser.parse_args()
    
    skills_dir = Path(args.skills_dir)
    if not skills_dir.exists():
        print(f"Skills directory not found: {skills_dir}")
        return 1
    
    skill_dirs = [skills_dir / args.skill] if args.skill else [d for d in skills_dir.iterdir() if d.is_dir()]
    
    all_breaking = []
    for skill_dir in skill_dirs:
        if not skill_dir.exists():
            continue
        
        # Load current manifest
        manifest_path = skill_dir / "skill.yaml"
        if not manifest_path.exists():
            # Try SKILL.md frontmatter
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                with open(skill_md, 'r', encoding='utf-8') as f:
                    content = f.read()
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 2:
                        current = yaml.safe_load(parts[1])
                    else:
                        continue
                else:
                    continue
            else:
                continue
        else:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                current = yaml.safe_load(f)
        
        previous = get_git_prev_version(skill_dir.name)
        breaking = check_breaking_changes(current, previous)
        
        if breaking:
            print(f"❌ {skill_dir.name} v{current.get('version')}: BREAKING CHANGES")
            for b in breaking:
                print(f"   - {b}")
            all_breaking.extend([(skill_dir.name, b) for b in breaking])
        else:
            print(f"✅ {skill_dir.name} v{current.get('version')}: No breaking changes")
    
    if all_breaking:
        print(f"\n🚨 Total: {len(all_breaking)} breaking changes across {len(set(s for s, _ in all_breaking))} skills")
        return 1
    else:
        print(f"\n✅ No breaking changes detected")
        return 0

if __name__ == "__main__":
    sys.exit(main())