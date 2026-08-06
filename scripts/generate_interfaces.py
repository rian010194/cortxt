#!/usr/bin/env python3
"""
Interface Generator — Generates TypeScript interfaces, OpenAPI 3.1, JSON Schemas, Python stubs from skill.yaml
"""

import json
import sys
import yaml
import argparse
from pathlib import Path
from string import Template

SKILLS_DIR = Path(__file__).parent.parent / "skills"

# TypeScript primitive mapping
JSON_TO_TS = {
    "string": "string",
    "number": "number",
    "integer": "number",
    "boolean": "boolean",
    "array": "unknown[]",
    "object": "Record<string, unknown>",
    "null": "null"
}

def load_skill_manifest(skill_dir):
    """Load skill.yaml from skill directory"""
    manifest_path = skill_dir / "skill.yaml"
    if manifest_path.exists():
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    # Fallback to SKILL.md frontmatter
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        with open(skill_md, 'r', encoding='utf-8') as f:
            content = f.read()
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 2:
                return yaml.safe_load(parts[1])
    return None

def json_schema_to_ts(name, schema, required=None, depth=0):
    """Convert JSON Schema to TypeScript interface"""
    indent = "  " * depth
    required = required or []
    
    if "allOf" in schema:
        # Combine allOf
        interfaces = []
        for sub in schema["allOf"]:
            interfaces.append(json_schema_to_ts(name, sub, required, depth))
        return " & ".join(interfaces)
    
    if "anyOf" in schema or "oneOf" in schema:
        key = "anyOf" if "anyOf" in schema else "oneOf"
        types = [json_schema_to_ts(f"{name}{i}", sub, [], depth) for i, sub in enumerate(schema[key])]
        return " | ".join(types)
    
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        if not props:
            return "Record<string, unknown>"
        
        lines = [f"{indent}{name}: {{"]
        for prop_name, prop_schema in props.items():
            optional = "" if prop_name in required else "?"
            prop_type = json_schema_to_ts(prop_name, prop_schema, [], depth + 1)
            desc = prop_schema.get("description", "")
            if desc:
                lines.append(f"{indent}  /** {desc} */")
            lines.append(f"{indent}  {prop_name}{optional}: {prop_type};")
        lines.append(f"{indent}}}")
        return "\n".join(lines)
    
    if schema.get("type") == "array":
        items = schema.get("items", {})
        item_type = json_schema_to_ts("Item", items, [], depth)
        return f"{item_type}[]"
    
    if "enum" in schema:
        vals = [json.dumps(v) for v in schema["enum"]]
        return " | ".join(vals)
    
    if "const" in schema:
        return json.dumps(schema["const"])
    
    ts_type = JSON_TO_TS.get(schema.get("type", "object"), "unknown")
    return ts_type

def generate_typescript(skill_name, manifest):
    """Generate TypeScript interfaces for skill"""
    input_schema_name = manifest["interface"]["input_schema"].replace(".input.schema.json", "")
    output_schema_name = manifest["interface"]["output_schema"].replace(".output.schema.json", "")
    error_codes_name = manifest["interface"]["error_codes"].replace(".errors.schema.json", "")
    
    # We'd need to load the actual JSON schemas to generate proper TS
    # For now, generate template based on manifest info
    ts = f"""/**
 * Auto-generated TypeScript interfaces for {skill_name}
 * Generated from skill.yaml — DO NOT EDIT MANUALLY
 * Run: python scripts/generate_interfaces.py
 */

// Input Request
export interface {skill_name.replace('-', '')}Request {{
  action: string;
  resource: string;
  params: Record<string, unknown>;
  context: {{
    run_id: string;
    agent_id: string;
    trace_id: string;
    priority: "normal" | "high" | "low";
    timeout_ms?: number;
  }};
}}

// Output Response
export interface {skill_name.replace('-', '')}Response<T = unknown> {{
  success: boolean;
  data: T | null;
  metadata: {{
    request_id: string;
    timestamp: string;
    duration_ms: number;
    rate_limit_remaining: number;
    rate_limit_reset: string;
    cache_hit: boolean;
    pagination?: {{
      page: number;
      page_size: number;
      total_pages: number;
      total_items: number;
    }};
  }};
  links?: Record<string, string>;
  errors?: {skill_name.replace('-', '')}Error[];
}}

// Error
export interface {skill_name.replace('-', '')}Error {{
  code: {skill_name.replace('-', '')}ErrorCode;
  message: string;
  details?: Record<string, unknown>;
  recovery_hint?: "refresh_token" | "backoff_retry" | "check_permissions" | "contact_admin";
}}

// Error Codes (from skill manifest)
export type {skill_name.replace('-', '')}ErrorCode = 
  | "AUTH_EXPIRED"
  | "RATE_LIMITED"
  | "NOT_FOUND"
  | "VALIDATION_ERROR"
  | "UPSTREAM_ERROR"
  | "TIMEOUT"
  | "PERMISSION_DENIED";
  // Add skill-specific codes here

// Skill Interface
export interface {skill_name.replace('-', '')}Skill {{
  call(request: {skill_name.replace('-', '')}Request): Promise<{skill_name.replace('-', '')}Response>;
}}
"""
    return ts

def generate_openapi(skill_name, manifest):
    """Generate OpenAPI 3.1 spec for skill"""
    openapi = {
        "openapi": "3.1.0",
        "info": {
            "title": f"{skill_name} API",
            "version": manifest["version"],
            "description": manifest["description"]
        },
        "servers": [{"url": "local://", "description": "Local skill invocation"}],
        "paths": {
            "/call": {
                "post": {
                    "summary": f"Invoke {skill_name} skill",
                    "operationId": "callSkill",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{skill_name.replace('-', '')}Request"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Successful response",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": f"#/components/schemas/{skill_name.replace('-', '')}Response"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                f"{skill_name.replace('-', '')}Request": {
                    "type": "object",
                    "required": ["action", "resource", "params", "context"],
                    "properties": {
                        "action": {"type": "string"},
                        "resource": {"type": "string"},
                        "params": {"type": "object"},
                        "context": {
                            "type": "object",
                            "required": ["run_id", "agent_id", "trace_id", "priority"],
                            "properties": {
                                "run_id": {"type": "string"},
                                "agent_id": {"type": "string"},
                                "trace_id": {"type": "string"},
                                "priority": {"type": "string", "enum": ["normal", "high", "low"]},
                                "timeout_ms": {"type": "integer"}
                            }
                        }
                    }
                },
                f"{skill_name.replace('-', '')}Response": {
                    "type": "object",
                    "required": ["success", "data", "metadata"],
                    "properties": {
                        "success": {"type": "boolean"},
                        "data": {"type": "object", "nullable": True},
                        "metadata": {
                            "type": "object",
                            "required": ["request_id", "timestamp", "duration_ms", "rate_limit_remaining", "rate_limit_reset", "cache_hit"],
                            "properties": {
                                "request_id": {"type": "string"},
                                "timestamp": {"type": "string", "format": "date-time"},
                                "duration_ms": {"type": "integer"},
                                "rate_limit_remaining": {"type": "integer"},
                                "rate_limit_reset": {"type": "string", "format": "date-time"},
                                "cache_hit": {"type": "boolean"},
                                "pagination": {
                                    "type": "object",
                                    "properties": {
                                        "page": {"type": "integer"},
                                        "page_size": {"type": "integer"},
                                        "total_pages": {"type": "integer"},
                                        "total_items": {"type": "integer"}
                                    }
                                }
                            }
                        },
                        "links": {"type": "object", "additionalProperties": {"type": "string"}},
                        "errors": {
                            "type": "array",
                            "items": {"$ref": f"#/components/schemas/{skill_name.replace('-', '')}Error"}
                        }
                    }
                },
                f"{skill_name.replace('-', '')}Error": {
                    "type": "object",
                    "required": ["code", "message"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "details": {"type": "object"},
                        "recovery_hint": {"type": "string", "enum": ["refresh_token", "backoff_retry", "check_permissions", "contact_admin"]}
                    }
                }
            }
        }
    }
    return yaml.dump(openapi, default_flow_style=False, sort_keys=False)

def generate_python_stubs(skill_name, manifest):
    """Generate Python stubs (.pyi) for skill"""
    stub = f'''"""
Auto-generated Python stubs for {skill_name}
Generated from skill.yaml — DO NOT EDIT MANUALLY
Run: python scripts/generate_interfaces.py
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

class {skill_name.replace('-', '').title()}Context(TypedDict):
    run_id: str
    agent_id: str
    trace_id: str
    priority: Literal["normal", "high", "low"]
    timeout_ms: Optional[int]

class {skill_name.replace('-', '').title()}Request(TypedDict):
    action: str
    resource: str
    params: Dict[str, Any]
    context: {skill_name.replace('-', '').title()}Context

class {skill_name.replace('-', '').title()}Metadata(TypedDict):
    request_id: str
    timestamp: str
    duration_ms: int
    rate_limit_remaining: int
    rate_limit_reset: str
    cache_hit: bool
    pagination: Optional[Dict[str, int]]

class {skill_name.replace('-', '').title()}Error(TypedDict):
    code: str
    message: str
    details: Optional[Dict[str, Any]]
    recovery_hint: Optional[Literal["refresh_token", "backoff_retry", "check_permissions", "contact_admin"]]

class {skill_name.replace('-', '').title()}Response(TypedDict):
    success: bool
    data: Optional[Any]
    metadata: {skill_name.replace('-', '').title()}Metadata
    links: Optional[Dict[str, str]]
    errors: Optional[List[{skill_name.replace('-', '').title()}Error]]

# Skill interface
class {skill_name.replace('-', '').title()}Skill:
    async def call(self, request: {skill_name.replace('-', '').title()}Request) -> {skill_name.replace('-', '').title()}Response: ...

# Error codes (from manifest)
{skill_name.replace('-', '').upper()}_ERROR_CODES = [
    "AUTH_EXPIRED",
    "RATE_LIMITED",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "UPSTREAM_ERROR",
    "TIMEOUT",
    "PERMISSION_DENIED",
    # Add skill-specific codes here
]
'''
    return stub

def generate_json_schemas(skill_name, manifest):
    """Generate JSON Schema files for input/output/errors"""
    # Input schema
    input_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{skill_name} Input",
        "type": "object",
        "required": ["action", "resource", "params", "context"],
        "properties": {
            "action": {"type": "string"},
            "resource": {"type": "string"},
            "params": {"type": "object"},
            "context": {
                "type": "object",
                "required": ["run_id", "agent_id", "trace_id", "priority"],
                "properties": {
                    "run_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "trace_id": {"type": "string"},
                    "priority": {"type": "string", "enum": ["normal", "high", "low"]},
                    "timeout_ms": {"type": "integer"}
                }
            }
        }
    }
    
    # Output schema
    output_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{skill_name} Output",
        "type": "object",
        "required": ["success", "data", "metadata"],
        "properties": {
            "success": {"type": "boolean"},
            "data": {"type": "object", "nullable": True},
            "metadata": {
                "type": "object",
                "required": ["request_id", "timestamp", "duration_ms", "rate_limit_remaining", "rate_limit_reset", "cache_hit"],
                "properties": {
                    "request_id": {"type": "string"},
                    "timestamp": {"type": "string", "format": "date-time"},
                    "duration_ms": {"type": "integer"},
                    "rate_limit_remaining": {"type": "integer"},
                    "rate_limit_reset": {"type": "string", "format": "date-time"},
                    "cache_hit": {"type": "boolean"},
                    "pagination": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "integer"},
                            "page_size": {"type": "integer"},
                            "total_pages": {"type": "integer"},
                            "total_items": {"type": "integer"}
                        }
                    }
                }
            },
            "links": {"type": "object", "additionalProperties": {"type": "string"}},
            "errors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["code", "message"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "details": {"type": "object"},
                        "recovery_hint": {"type": "string", "enum": ["refresh_token", "backoff_retry", "check_permissions", "contact_admin"]}
                    }
                }
            }
        }
    }
    
    # Error codes schema
    error_codes = manifest.get("error_taxonomy", {}).get("transient", []) + manifest.get("error_taxonomy", {}).get("permanent", [])
    error_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{skill_name} Error Codes",
        "type": "string",
        "enum": error_codes if error_codes else [
            "AUTH_EXPIRED", "RATE_LIMITED", "NOT_FOUND", "VALIDATION_ERROR",
            "UPSTREAM_ERROR", "TIMEOUT", "PERMISSION_DENIED"
        ]
    }
    
    return input_schema, output_schema, error_schema

def main():
    parser = argparse.ArgumentParser(description="Generate interfaces from skill manifests")
    parser.add_argument("--skills-dir", default="skills", help="Skills directory")
    parser.add_argument("--skill", help="Generate for specific skill only")
    parser.add_argument("--output-dir", default=".", help="Output base directory")
    args = parser.parse_args()
    
    skills_dir = Path(args.skills_dir)
    output_dir = Path(args.output_dir)
    
    if not skills_dir.exists():
        print(f"Skills directory not found: {skills_dir}")
        return 1
    
    skill_dirs = [skills_dir / args.skill] if args.skill else [d.parent for d in skills_dir.rglob("skill.yaml")]
    
    print(f"DEBUG: skills_dir={skills_dir}")
    print(f"DEBUG: skill_dirs={skill_dirs}")
    print(f"DEBUG: output_dir={output_dir}")

    for skill_dir in skill_dirs:
        if not skill_dir.exists():
            continue
        
        manifest = load_skill_manifest(skill_dir)
        if not manifest:
            print(f"⚠️  {skill_dir.name}: No manifest found, skipping")
            continue
        
        # Check if manifest has required interface field
        if "interface" not in manifest:
            print(f"⚠️  {skill_dir.name}: No 'interface' field in manifest, skipping")
            continue
        
        skill_name = skill_dir.name
        
        # Create output directories
        (output_dir / "skills" / skill_name / "interfaces").mkdir(parents=True, exist_ok=True)
        (output_dir / "skills" / skill_name / "openapi").mkdir(parents=True, exist_ok=True)
        (output_dir / "skills" / skill_name / "schemas").mkdir(parents=True, exist_ok=True)
        (output_dir / "skills" / skill_name / "stubs").mkdir(parents=True, exist_ok=True)
        
        # Generate TypeScript
        ts = generate_typescript(skill_name, manifest)
        (output_dir / "skills" / skill_name / "interfaces" / f"{skill_name}.ts").write_text(ts, encoding='utf-8')
        
        # Generate OpenAPI
        openapi = generate_openapi(skill_name, manifest)
        (output_dir / "skills" / skill_name / "openapi" / f"{skill_name}.yaml").write_text(openapi, encoding='utf-8')
        
        # Generate JSON Schemas
        input_schema, output_schema, error_schema = generate_json_schemas(skill_name, manifest)
        (output_dir / "skills" / skill_name / "schemas" / f"{skill_name}.input.schema.json").write_text(json.dumps(input_schema, indent=2), encoding='utf-8')
        (output_dir / "skills" / skill_name / "schemas" / f"{skill_name}.output.schema.json").write_text(json.dumps(output_schema, indent=2), encoding='utf-8')
        (output_dir / "skills" / skill_name / "schemas" / f"{skill_name}.errors.schema.json").write_text(json.dumps(error_schema, indent=2), encoding='utf-8')
        
        # Generate Python stubs
        stubs = generate_python_stubs(skill_name, manifest)
        (output_dir / "skills" / skill_name / "stubs" / f"{skill_name}.pyi").write_text(stubs, encoding='utf-8')
        
        print(f"✅ {skill_name}: Generated interfaces (TS, OpenAPI, JSON Schemas, Python stubs)")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())