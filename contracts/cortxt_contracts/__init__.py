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

__version__ = "2.0.0"

__all__ = [
    "WORKER_SCHEMA_FILES",
    "__version__",
    "load_schema",
    "schema_names",
    "worker_contract_grammar",
]


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


# -- worker contract surface (VLT-D-007 step 2, issue #604) -----------------

#: The worker-facing schema pair, packaged alongside the projection exports so
#: a consumer validates against the *pinned* contract instead of reading a
#: core checkout. Copied verbatim from the repo's ``contracts/`` by
#: ``scripts/export_contracts.py`` -- never hand-edited.
WORKER_SCHEMA_FILES: tuple[str, ...] = (
    "dispatch-request",
    "result-envelope",
)


def worker_contract_grammar() -> dict:
    """The worker-contract grammar, as packaged (read-only).

    Mirrors the core's ``agent-platform/routing/worker_contract.py``
    declarations. The congruence test
    (``tests/widget_contract/test_contract_distribution.py``) fails closed if
    the core declarations change without this copy being regenerated.
    """
    return {
        "contract_version": "worker.result.v1",
        "attestation_prefix": "CORTXT-OUTCOME:",
        "attestable": ("completed", "declined"),
        "source": "packaged",
    }
