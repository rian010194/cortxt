#!/usr/bin/env python3
"""Deterministic regression tests for #45: JSON-semantic type checking in the
eval runner (run-vertical-evals.py).

Verifies that:
  - bool is NOT accepted as integer / number in `type_is`;
  - JSON-semantic equality treats True != 1 (booleans are not numbers);
  - numeric equality still works (1 == 1.0);
  - unknown type_is values error cleanly.

Run directly:  python harness/scripts/test_eval_json_semantics.py   (0 = pass)
"""
import importlib.util, sys, tempfile, os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MOD = REPO / "harness" / "scripts" / "run-vertical-evals.py"

spec = importlib.util.spec_from_file_location("reve", MOD)
rv = importlib.util.module_from_spec(spec); spec.loader.exec_module(rv)

fail = []
def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond: fail.append(name)

def _type(actual, expected):
    # eval against a doc with /x = actual
    return rv.check_assertion({"x": actual}, {"path": "/x", "operator": "type_is", "expected_value": expected})[0]
def aeq(actual, expected):
    return rv.check_assertion({"x": actual}, {"path": "/x", "operator": "equals", "expected_value": expected})[0]

print("== #45 type_is: bool not integer/number ==")
check("True is boolean", _type(True, "boolean"))
check("True is NOT integer", not _type(True, "integer"))
check("True is NOT number", not _type(True, "number"))
check("1 IS integer", _type(1, "integer"))
check("1.5 IS number", _type(1.5, "number"))
check("1.5 NOT integer", not _type(1.5, "integer"))
check("'x' is string", _type("x", "string"))
check("unknown type errors", not rv.check_assertion({"x": 1}, {"path": "/x", "operator": "type_is", "expected_value": "nope"})[0])

print("== #45 json_eq: bool vs number, numeric equality ==")
check("True != 1 (bool not number)", not aeq(True, 1))
check("True == True", aeq(True, True))
check("1 == 1.0 (numeric)", aeq(1, 1.0))
check("equals(1) matches 1", aeq(1, 1))
check("False != 0 (bool not number)", not aeq(False, 0))
check("string == string", aeq("x", "x"))
check("large ints keep precision (2^53 != 2^53+1)", not aeq(9007199254740992, 9007199254740993))
check("int == float still equal (1 == 1.0)", aeq(1, 1.0))
check("mixed big int/float not falsely equal (2^53+1 != 2^53.0)",
      not aeq(9007199254740993, 9007199254740992.0))

print()
if fail:
    print(f"#45 REGRESSION: {len(fail)} FAILURE(S): {fail}")
    sys.exit(1)
print("#45 REGRESSION: all JSON-semantic checks passed (bool distinct from "
      "number; numeric equality intact).")