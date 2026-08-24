"""Human-reviewable scaffold for a widget read operation the registry does
not yet have. Never auto-registered, never auto-executed (ADR-038 SS5/SS6):
this module only ever writes a file for a human to review and merge through
the normal PR flow.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .registry import READ_OPERATIONS


def find_missing_operations(raw_spec: dict[str, Any]) -> list[str]:
    reads = raw_spec.get("data", {}).get("reads", []) if isinstance(raw_spec.get("data"), dict) else []
    missing = []
    for item in reads:
        if not isinstance(item, dict):
            continue
        op = item.get("operation")
        if isinstance(op, str) and op not in READ_OPERATIONS and op not in missing:
            missing.append(op)
    return missing


def _function_name(operation_id: str) -> str:
    safe = re.sub(r"[^0-9a-zA-Z]+", "_", operation_id).strip("_")
    return f"read_{safe}"


def write_operation_scaffold(operation_id: str, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fn_name = _function_name(operation_id)
    path = out_dir / f"scaffold-{operation_id}.py"
    path.write_text(
        f'''"""Reviewable scaffold for read operation "{operation_id}".

This file is NOT installed or executed automatically. A human must:
1. Implement {fn_name}() in the appropriate adapters module
   (agent-platform/widget_contract/adapters/).
2. Add a ReadOperation entry for "{operation_id}" to
   READ_OPERATIONS in agent-platform/widget_contract/registry.py.
3. Add a test and open a normal PR.

def {fn_name}(*args, **kwargs) -> dict:
    """Fill in: read logic for {operation_id}."""
    raise NotImplementedError("{operation_id} scaffold not yet implemented")


# Registry entry to add to READ_OPERATIONS in registry.py:
# "{operation_id}": ReadOperation(
#     source="store",  # or "cli" / "github"
#     input_schema=JSON_OBJECT,
#     output_type="{operation_id}",
#     data_class="operational",
#     timeout_ms=500,
#     rate_limit_per_minute=60,
#     cache_ttl_seconds=2,
#     capability="read:CHANGE_ME",
# ),
''',
        encoding="utf-8",
    )
    return path
