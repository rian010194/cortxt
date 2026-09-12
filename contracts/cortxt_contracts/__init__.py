"""cortxt-contracts: versioned, domain-neutral Cortxt contract schemas.

This package is a **generated distribution artifact** (VLT-D-007). The schema
content is generated from the embedded schema dicts in the core repo
(``agent-platform/widget_contract/registry.py``) by
``scripts/export_contracts.py``. Never hand-edit the files under ``schemas/``.

Distribution: git-tag ``contracts/vX.Y.Z`` in the cortxt repository, consumed
as ``cortxt-contracts @ git+https://github.com/rian010194/cortxt@<tag>#subdirectory=contracts``.
"""

from __future__ import annotations

import json
from importlib import resources

__version__ = "1.0.0"

__all__ = ["__version__", "load_schema", "schema_names"]


def load_schema(name: str) -> dict:
    """Load a packaged contract schema by name (without ``.schema.json``)."""
    text = (
        resources.files("cortxt_contracts")
        .joinpath("schemas", f"{name}.schema.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def schema_names() -> list[str]:
    """All packaged schema names."""
    return sorted(
        path.name.removesuffix(".schema.json")
        for path in (resources.files("cortxt_contracts") / "schemas").iterdir()
        if path.name.endswith(".schema.json")
    )
