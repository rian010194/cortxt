"""Single-source export of the dispatch-request projection schemas (VLT-D-007).

The embedded schema dicts in ``widget_contract.registry`` are the authoritative
production source: the confirm/launch path validates against them. The JSON
files under ``contracts/`` are **generated exports** of exactly those dicts and
must never be hand-edited; any change is made in ``registry.py`` and
re-exported with ``scripts/export_contracts.py`` (or the congruence test fails).

Export rules (deterministic):
- keys are sorted, indent 2, UTF-8, trailing newline;
- tuples are normalised to lists;
- ``None`` at a schema position becomes ``{}`` (the empty JSON Schema, which
  accepts anything -- mirroring Python-schema semantics where ``None`` is not
  a valid schema but the dicts never rely on it);
- ``None`` **inside an ``enum`` list** is preserved as JSON ``null`` (valid
  draft-07: enum values may be null, e.g. ``charge_policy_route``).
"""

from __future__ import annotations

import json
from pathlib import Path

from widget_contract.registry import (
    DISPATCH_REQUEST_SCHEMA,
    DISPATCH_REQUEST_V2_SCHEMA,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"

EXPORT_FILENAMES = {
    "dispatch.request.v1": "dispatch-request.v1.schema.json",
    "dispatch.request.v2": "dispatch-request.v2.schema.json",
}

_EXPORT_INSTRUCTIONS = (
    "Schemas drifted from the embedded source. Run: "
    "python scripts/export_contracts.py and commit the regenerated files."
)


def export_schema(schema: dict) -> dict:
    """Deep-copy a Python schema dict into a JSON-safe, deterministic dict."""

    def convert(node, key_context=None):
        if isinstance(node, dict):
            return {
                k: convert(v, key_context=k)
                for k, v in node.items()
            }
        if isinstance(node, (list, tuple)):
            if key_context == "enum":
                # None inside an enum is a legitimate enum *value* (null).
                # Enum values are scalars here; only nested containers recurse.
                return [
                    item if item is None else convert(item, key_context=None)
                    for item in node
                ]
            return [convert(item, key_context=None) for item in node]
        if node is None:
            return {}
        return node

    return convert(schema)


def export_dispatch_request_schemas() -> dict[str, dict]:
    """The canonical export mapping, in-memory (never touches disk)."""
    return {
        type_id: export_schema(schema)
        for type_id, schema in (
            ("dispatch.request.v1", DISPATCH_REQUEST_SCHEMA),
            ("dispatch.request.v2", DISPATCH_REQUEST_V2_SCHEMA),
        )
    }


def _canonical_bytes(schema: dict) -> bytes:
    text = json.dumps(
        schema, indent=2, sort_keys=True, ensure_ascii=False
    )
    return (text + "\n").encode("utf-8")


def write_schema_exports(output_dir: Path = CONTRACTS_DIR) -> list[Path]:
    """Write the canonical JSON exports. Returns the paths written."""
    written: list[Path] = []
    for type_id, filename in EXPORT_FILENAMES.items():
        target = output_dir / filename
        target.write_bytes(_canonical_bytes(export_dispatch_request_schemas()[type_id]))
        written.append(target)
    return written


#: The hand-written worker-facing pair, copied verbatim into the packaged
#: schemas directory on export (VLT-D-007 step 2): a consumer validates
#: against the pinned package, not a core checkout. These files are NOT
#: canonicalised -- they are hand-written and validated by the core tests --
#: so they are copied byte-for-byte.
WORKER_SCHEMA_SOURCES: tuple[str, ...] = (
    "dispatch-request.schema.json",
    "result-envelope.schema.json",
)

_WORKER_PACKAGE_RELDIR = "cortxt_contracts/schemas"


def sync_worker_schema_package(output_dir: Path = CONTRACTS_DIR) -> list[Path]:
    """Copy the worker-facing pair into the packaged schemas directory.

    Returns the paths written. The copy is verbatim: these two files are
    hand-written and validated by the core's own tests, so any normalisation
    here would create exactly the second-source drift step 1 removed.
    """
    written: list[Path] = []
    package_schemas = output_dir / _WORKER_PACKAGE_RELDIR
    package_schemas.mkdir(parents=True, exist_ok=True)
    for name in WORKER_SCHEMA_SOURCES:
        target = package_schemas / name
        target.write_bytes((output_dir / name).read_bytes())
        written.append(target)
    return written


def check_worker_schema_package(output_dir: Path = CONTRACTS_DIR) -> list[str]:
    """Return drift findings for the packaged worker pair; empty = congruent."""
    problems: list[str] = []
    for name in WORKER_SCHEMA_SOURCES:
        repo_file = output_dir / name
        packaged = output_dir / _WORKER_PACKAGE_RELDIR / name
        if not packaged.exists():
            problems.append(
                f"{_WORKER_PACKAGE_RELDIR}/{name}: missing "
                f"({_EXPORT_INSTRUCTIONS})"
            )
            continue
        if packaged.read_bytes() != repo_file.read_bytes():
            problems.append(
                f"{_WORKER_PACKAGE_RELDIR}/{name}: drifted from {name} "
                f"({_EXPORT_INSTRUCTIONS})"
            )
    return problems


def check_schema_exports(output_dir: Path = CONTRACTS_DIR) -> list[str]:
    """Return a human-readable list of drift findings; empty means congruent."""
    problems: list[str] = []
    exported = export_dispatch_request_schemas()
    for type_id, filename in EXPORT_FILENAMES.items():
        target = output_dir / filename
        if not target.exists():
            problems.append(f"{filename}: missing ({_EXPORT_INSTRUCTIONS})")
            continue
        on_disk = target.read_bytes()
        if on_disk != _canonical_bytes(exported[type_id]):
            problems.append(f"{filename}: drifted ({_EXPORT_INSTRUCTIONS})")
    return problems
