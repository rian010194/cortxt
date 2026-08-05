#!/usr/bin/env python3
"""Deterministic eval runner for vertical-01-ai-act (AC5).

Validates every synthetic fixture against the input/output schemas and executes
the fixture's embedded `deterministic_assertions` (JSON Pointer + operator)
against its `expected_output`. Model-assisted rubrics and human-review flags are
reported but not executed here.

Usage:
    python harness/scripts/run-vertical-evals.py [--report <path>]

Exit code 0 = all fixtures pass; 1 = any failure.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import jsonschema
import referencing
import yaml

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "verticals" / "vertical-01-ai-act"
SCHEMAS = PKG / "schemas"
EVALS = PKG / "evals" / "synthetic"

BASE = "https://github.com/rian010194/ai-workspace-control-plane/schemas/"


def make_registry() -> referencing.Registry:
    """Map remote $ref URLs (github base) to the local schema files."""
    by_id = {doc.get("$id"): doc for doc in (load_json(p) for p in SCHEMAS.glob("*.json"))}
    reg = referencing.Registry()
    for uri, doc in by_id.items():
        if uri:
            reg = reg.with_resource(uri, referencing.Resource.from_contents(doc))
    return reg


def validate_with_refs(instance, schema):
    return jsonschema.Draft202012Validator(
        schema, registry=make_registry()
    ).validate(instance)


def load_json(p: Path) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def json_pointer_get(doc, pointer: str):
    """Resolve an RFC6901 JSON Pointer path without leading '/'."""
    if not pointer:
        return doc
    if pointer.startswith("/"):
        pointer = pointer[1:]
    cur = doc
    for part in pointer.split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(part)
            cur = cur[part]
        elif isinstance(cur, list):
            idx = int(part)
            cur = cur[idx]
        else:
            raise TypeError(f"cannot descend into {type(cur).__name__}")
    return cur


def check_assertion(actual, a: dict):
    path = a["path"]
    op = a["operator"]
    expected = a["expected_value"]
    try:
        val = json_pointer_get(actual, path)
    except (KeyError, TypeError, IndexError, ValueError) as e:
        return False, f"path {path} missing/not resolvable ({e})"
    if op == "equals":
        return val == expected, f"{path}: expected {expected!r}, got {val!r}"
    if op == "contains":
        return expected in val, f"{path}: expected to contain {expected!r}"
    if op == "exists":
        return True, f"{path}: exists"
    if op == "type_is":
        return isinstance(val, expected), f"{path}: expected type {expected}"
    return False, f"unknown operator {op}"


def run() -> int:
    input_schema = load_json(SCHEMAS / "ai-act-assessment-input.schema.json")
    output_schema = load_json(SCHEMAS / "ai-act-assessment-output.schema.json")
    fixture_schema = load_json(SCHEMAS / "eval-fixture.schema.json")

    fixture_files = sorted(EVALS.rglob("*.yaml"))
    fixture_files = [f for f in fixture_files if f.name != "manifest.yaml"]

    total_assertions = 0
    passed_assertions = 0
    failed = []
    results = {}

    for fp in fixture_files:
        fx = yaml.safe_load(fp.read_text(encoding="utf-8"))
        name = fp.relative_to(EVALS)
        row = {"file": str(name), "fixture_id": fx.get("fixture_id"),
               "type": fx.get("fixture_type"), "checks": []}

        # AC3-ish structural validation against fixture schema ($refs resolved manually)
        try:
            validate_with_refs(fx, fixture_schema)
            row["fixture_schema"] = "valid"
        except jsonschema.ValidationError as e:
            row["fixture_schema"] = f"INVALID: {e.message}"
            failed.append(name)

        # validate input and expected_output against their schemas
        for key, schema in (("input", input_schema), ("expected_output", output_schema)):
            try:
                jsonschema.validate(fx[key], schema)
                row[f"{key}_schema"] = "valid"
            except jsonschema.ValidationError as e:
                row[f"{key}_schema"] = f"INVALID: {e.message}"
                failed.append(name)

        # run deterministic assertions against expected_output
        for a in fx.get("deterministic_assertions", []):
            total_assertions += 1
            ok, msg = check_assertion(fx.get("expected_output", {}), a)
            passed_assertions += int(ok)
            row["checks"].append({"assertion": a["path"], "ok": ok})
            if not ok:
                failed.append(f"{name} :: {msg}")

        # report model-assisted + human gates (not executed)
        row["model_assisted"] = len(fx.get("model_assisted_assertions", []))
        row["human_review_required"] = fx.get("human_review_required", False)
        results[str(name)] = row

    summary = {
        "vertical": "vertical-01-ai-act",
        "fixtures": len(fixture_files),
        "assertions_total": total_assertions,
        "assertions_passed": passed_assertions,
        "fixtures_failed": sorted({str(f) for f in failed}),
        "results": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    ok = passed_assertions == total_assertions and not failed
    print("\nRESULT:", "PASS" if ok else "FAIL",
          f"({passed_assertions}/{total_assertions} assertions, "
          f"{len(fixture_files) - len(summary['fixtures_failed'])}/{len(fixture_files)} fixtures)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
