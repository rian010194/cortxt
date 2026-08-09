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

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path

import jsonschema
import referencing
import yaml

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "verticals" / "vertical-01-ai-act"
SCHEMAS = PKG / "schemas"
EVALS = PKG / "evals" / "synthetic"

# JSON type name -> Python type (for the `type_is` operator).
TYPE_MAP = {
    "null": type(None),
    "boolean": bool,
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
}


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


def _as_frac(x):
    """Exact rational value of a JSON number (int or float).

    int -> Fraction(n, 1); float -> Fraction.from_float (exact binary value),
    so cross-type numeric equality NEVER loses integer precision. #45.
    """
    return Fraction(x) if isinstance(x, int) else Fraction.from_float(x)


def json_eq(a, b):
    """JSON-semantic equality.

    Booleans are NOT numbers in JSON (True != 1); numbers compare numerically
    and exactly via Fraction, so 1 == 1.0 but large ints never falsely collide
    (9007199254740993 != 9007199254740992.0); containers recurse. #45.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _as_frac(a) == _as_frac(b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(k in b and json_eq(a[k], b[k]) for k in a)
    return a == b


def json_type_name(val) -> str:
    """JSON canonical type name (bool distinct from number). Fixes #45."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "number"
    if isinstance(val, str):
        return "string"
    if isinstance(val, list):
        return "array"
    if isinstance(val, dict):
        return "object"
    return type(val).__name__


def check_assertion(actual, a: dict):
    """Evaluate one deterministic_assertion. Returns (ok, message)."""
    path = a["path"]
    op = a["operator"]
    expected = a["expected_value"]
    try:
        val = json_pointer_get(actual, path)
    except (KeyError, TypeError, IndexError, ValueError) as e:
        return False, f"path {path}: not resolvable ({e})"

    if op == "equals":
        return json_eq(val, expected), f"{path}: expected {expected!r}, got {val!r}"
    if op == "contains":
        return expected in val, f"{path}: expected to contain {expected!r}"
    if op == "exists":
        return True, f"{path}: exists"
    if op == "type_is":
        if expected not in TYPE_MAP:
            return False, f"{path}: unknown type_is value {expected!r}"
        return (json_type_name(val) == expected,
                f"{path}: expected type {expected!r}, got {json_type_name(val)}")
    return False, f"{path}: unknown operator {op!r}"


def run(report_path: Path | None = None) -> int:
    input_schema = load_json(SCHEMAS / "ai-act-assessment-input.schema.json")
    output_schema = load_json(SCHEMAS / "ai-act-assessment-output.schema.json")
    fixture_schema = load_json(SCHEMAS / "eval-fixture.schema.json")

    fixture_files = sorted(
        p for p in EVALS.rglob("*.yaml") if p.name != "manifest.yaml"
    )

    total_assertions = 0
    passed_assertions = 0
    failed_assertions = []      # list of "fixture :: message"
    failed_fixtures = set()     # fixture keys with any failure
    results = {}

    for fp in fixture_files:
        fx = yaml.safe_load(fp.read_text(encoding="utf-8"))
        name = fp.relative_to(EVALS)
        key = str(name)
        row = {"file": key, "fixture_id": fx.get("fixture_id"),
               "type": fx.get("fixture_type"), "checks": []}

        # structural validation against fixture schema (with $ref resolution)
        try:
            validate_with_refs(fx, fixture_schema)
            row["fixture_schema"] = "valid"
        except jsonschema.ValidationError as e:
            row["fixture_schema"] = f"INVALID: {e.message}"
            failed_fixtures.add(key)

        # validate input and expected_output against their schemas (registry-aware)
        for sub, schema in (("input", input_schema), ("expected_output", output_schema)):
            sub_path = f"{sub}_schema"
            try:
                validate_with_refs(fx[sub], schema)
                row[sub_path] = "valid"
            except jsonschema.ValidationError as e:
                row[sub_path] = f"INVALID: {e.message}"
                failed_fixtures.add(key)

        # run deterministic assertions against expected_output
        for a in fx.get("deterministic_assertions", []):
            total_assertions += 1
            ok, msg = check_assertion(fx.get("expected_output", {}), a)
            passed_assertions += int(ok)
            row["checks"].append({"assertion": a["path"], "ok": ok, "message": msg})
            if not ok:
                failed_assertions.append(msg)
                failed_fixtures.add(key)

        row["model_assisted"] = len(fx.get("model_assisted_assertions", []))
        row["human_review_required"] = fx.get("human_review_required", False)
        results[key] = row

    summary = {
        "vertical": "vertical-01-ai-act",
        "fixtures": len(fixture_files),
        "fixtures_passed": len(fixture_files) - len(failed_fixtures),
        "fixtures_failed": sorted(failed_fixtures),
        "assertions_total": total_assertions,
        "assertions_passed": passed_assertions,
        "assertions_failed": sorted(failed_assertions),
        "results": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if report_path:
        Path(report_path).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    ok = passed_assertions == total_assertions and not failed_fixtures
    print(
        "\nRESULT:", "PASS" if ok else "FAIL",
        f"({passed_assertions}/{total_assertions} assertions, "
        f"{len(fixture_files) - len(failed_fixtures)}/{len(fixture_files)} fixtures)",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", type=Path, default=None,
                    help="Write the JSON report to this path.")
    args = ap.parse_args()
    sys.exit(run(args.report))
