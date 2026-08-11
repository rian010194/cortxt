#!/usr/bin/env python3
"""
Profile CLI — Create, validate, list, export Hermes profiles
"""

import json
import sys
import yaml
import argparse
from pathlib import Path
from jsonschema import validate, ValidationError

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "profile-manifest.schema.json"
PROFILES_DIR = Path.home() / ".hermes" / "profiles"

def load_schema():
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_profile(profile_name):
    profile_dir = PROFILES_DIR / profile_name
    manifest_path = profile_dir / "manifest.yaml"
    if manifest_path.exists():
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    # Fallback to config.yaml
    config_path = profile_dir / "config.yaml"
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        # Convert legacy config to manifest format
        return {
            "name": profile_name,
            "version": "0.1.0",
            "model": config.get("model", "unknown"),
            "provider": config.get("provider", "unknown"),
            "skills": config.get("skills", []),
            "config": config,
            "delegation": config.get("delegation", {"max_concurrent_children": 2, "max_spawn_depth": 1}),
            "failure_domain": "orchestration",
            "cost_tier": "free",
            "latency_budget": "batch",
            "parallelism_class": "sequential",
            "auditability_level": "log-only"
        }
    return None

def validate_profile(manifest, schema):
    try:
        validate(instance=manifest, schema=schema)
        return True, "Valid"
    except ValidationError as e:
        return False, f"Validation error: {e.message} at {'.'.join(str(p) for p in e.path)}"

def create_profile(args):
    """Create new profile manifest"""
    manifest = {
        "name": args.name,
        "version": "0.1.0",
        "description": args.description or "",
        "model": args.model,
        "provider": args.provider,
        "skills": args.skills or [],
        "config": {
            "delegation": {
                "max_concurrent_children": args.max_children,
                "max_spawn_depth": args.max_depth
            },
            "tools": [],
            "model_params": {}
        },
        "delegation": {
            "max_concurrent_children": args.max_children,
            "max_spawn_depth": args.max_depth
        },
        "failure_domain": args.failure_domain,
        "cost_tier": args.cost_tier,
        "latency_budget": args.latency_budget,
        "parallelism_class": args.parallelism,
        "auditability_level": args.auditability,
        "auditor_pool": args.auditor_pool
    }
    
    schema = load_schema()
    valid, msg = validate_profile(manifest, schema)
    if not valid:
        print(f"❌ Invalid manifest: {msg}")
        return 1
    
    profile_dir = PROFILES_DIR / args.name
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    manifest_path = profile_dir / "manifest.yaml"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)
    
    print(f"✅ Created profile: {args.name}")
    print(f"   Manifest: {manifest_path}")
    print(f"   Profile dir: {profile_dir}")
    return 0

def validate_cmd(args):
    """Validate profile manifest"""
    schema = load_schema()
    
    if args.name:
        profiles = [args.name]
    else:
        profiles = [d.name for d in PROFILES_DIR.iterdir() if d.is_dir()]
    
    if not profiles:
        print("No profiles found")
        return 1
    
    all_valid = True
    for name in profiles:
        manifest = load_profile(name)
        if not manifest:
            print(f"❌ {name}: No manifest.yaml or config.yaml found")
            all_valid = False
            continue
        
        valid, msg = validate_profile(manifest, schema)
        status = "✅" if valid else "❌"
        print(f"{status} {name}: {msg}")
        if not valid:
            all_valid = False
    
    return 0 if all_valid else 1

def list_profiles(args):
    """List all profiles"""
    profiles = []
    for d in PROFILES_DIR.iterdir():
        if d.is_dir():
            manifest = load_profile(d.name)
            if manifest:
                profiles.append({
                    "name": d.name,
                    "version": manifest.get("version", "unknown"),
                    "model": manifest.get("model", "unknown"),
                    "provider": manifest.get("provider", "unknown"),
                    "failure_domain": manifest.get("failure_domain", "unknown"),
                    "cost_tier": manifest.get("cost_tier", "unknown"),
                    "skills_count": len(manifest.get("skills", []))
                })
    
    if args.json:
        print(json.dumps(profiles, indent=2))
    else:
        print(f"{'NAME':<25} {'VERSION':<10} {'MODEL':<25} {'DOMAIN':<18} {'COST':<8} {'SKILLS'}")
        print("-" * 100)
        for p in profiles:
            print(f"{p['name']:<25} {p['version']:<10} {p['model']:<25} {p['failure_domain']:<18} {p['cost_tier']:<8} {p['skills_count']}")

def export_profile(args):
    """Export profile as JSON/YAML"""
    manifest = load_profile(args.name)
    if not manifest:
        print(f"Profile not found: {args.name}")
        return 1
    
    if args.format == "json":
        print(json.dumps(manifest, indent=2))
    else:
        print(yaml.dump(manifest, default_flow_style=False, sort_keys=False))

def main():
    parser = argparse.ArgumentParser(description="Profile CLI — manage Hermes profiles")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # create
    create_parser = subparsers.add_parser("create", help="Create new profile")
    create_parser.add_argument("name", help="Profile name (lowercase, hyphens)")
    create_parser.add_argument("--description", help="Profile description")
    create_parser.add_argument("--model", required=True, help="Model name (e.g., kimi-k2.6)")
    create_parser.add_argument("--provider", required=True, help="Provider (e.g., openrouter)")
    create_parser.add_argument("--skills", nargs="*", default=[], help="Skills to load")
    create_parser.add_argument("--max-children", type=int, default=2, help="Max concurrent children")
    create_parser.add_argument("--max-depth", type=int, default=1, help="Max spawn depth")
    create_parser.add_argument("--failure-domain", choices=["orchestration", "research", "execution", "review", "observability", "specialist", "receptionist-layer"], default="orchestration")
    create_parser.add_argument("--cost-tier", choices=["free", "low", "medium", "high", "premium"], default="free")
    create_parser.add_argument("--latency-budget", choices=["interactive", "batch", "async"], default="batch")
    create_parser.add_argument("--parallelism", choices=["sequential", "parallel-2", "parallel-N", "fan-out"], default="sequential")
    create_parser.add_argument("--auditability", choices=["none", "log-only", "full-trace", "signed-attestation"], default="log-only")
    create_parser.add_argument("--auditor-pool", action="store_true", help="Include in auditor pool")
    create_parser.set_defaults(func=create_profile)
    
    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate profile manifest(s)")
    validate_parser.add_argument("name", nargs="?", help="Profile name (default: all)")
    validate_parser.set_defaults(func=validate_cmd)
    
    # list
    list_parser = subparsers.add_parser("list", help="List all profiles")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")
    list_parser.set_defaults(func=list_profiles)
    
    # export
    export_parser = subparsers.add_parser("export", help="Export profile manifest")
    export_parser.add_argument("name", help="Profile name")
    export_parser.add_argument("--format", choices=["json", "yaml"], default="yaml")
    export_parser.set_defaults(func=export_profile)
    
    args = parser.parse_args()
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())