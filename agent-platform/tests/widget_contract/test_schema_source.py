"""Congruence gate: the JSON exports under ``contracts/`` must exactly match
the embedded schema dicts (the production source of truth) in
``widget_contract.registry``.

This is the drift-guard for the single-source contract (VLT-D-007, operator-
adjusted step 1): the confirm/launch path validates against the embedded
dicts, and the JSON files are canonical exports of exactly those dicts. If
someone edits either side without re-running ``scripts/export_contracts.py``,
this test fails with regeneration instructions instead of letting two
sources of truth drift silently.
"""

from pathlib import Path

import pytest

from widget_contract import schema_source
from widget_contract.registry import (
    DISPATCH_REQUEST_SCHEMA,
    DISPATCH_REQUEST_V2_SCHEMA,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "contracts"


def test_exports_are_canonical_bytes_of_embedded_dicts():
    """Every exported file must be byte-identical to the canonical export."""
    problems = schema_source.check_schema_exports(CONTRACTS_DIR)
    assert problems == [], (
        "contracts/ exports drifted from the embedded registry dicts. "
        + "; ".join(problems)
    )


def test_export_schema_normalises_python_only_values():
    """Tuples -> lists; bare None at schema positions -> {} (empty schema)."""
    exported = schema_source.export_dispatch_request_schemas()

    v1 = exported["dispatch.request.v1"]
    # tuple-free and JSON-round-trippable
    json_bytes = schema_source._canonical_bytes(v1)
    assert isinstance(json_bytes, bytes)
    import json

    parsed = json.loads(json_bytes.decode("utf-8"))
    assert parsed == v1
    # the v1 projection binds schema_version const 1
    assert v1["properties"]["schema_version"] == {"const": 1}

    v2 = exported["dispatch.request.v2"]
    # None inside an enum list is preserved as null (charge_policy_route)
    assert v2["properties"]["charge_policy_route"]["enum"][-1] is None
    # bare-None positions (v2 has none at schema level, but the converter
    # must not have destroyed required lists or property objects)
    assert v2["required"][-5:] == [
        "execution_profile_revision",
        "report_channel",
        "charge_policy_id",
        "charge_policy_revision",
        "charge_policy_route",
    ]


def test_v2_superset_property_invariant():
    """v2 required/properties must remain a strict superset of v1's."""
    v1_required = set(DISPATCH_REQUEST_SCHEMA["required"])
    v2_required = set(DISPATCH_REQUEST_V2_SCHEMA["required"])
    assert v1_required < v2_required
    v1_props = set(DISPATCH_REQUEST_SCHEMA["properties"])
    v2_props = set(DISPATCH_REQUEST_V2_SCHEMA["properties"])
    assert v1_props < v2_props


def test_check_reports_drift_instead_of_failing_silently(tmp_path):
    """A tampered export must be detected, with regeneration instructions."""
    exported = schema_source.export_dispatch_request_schemas()
    (tmp_path / "dispatch-request.v1.schema.json").write_bytes(
        schema_source._canonical_bytes(exported["dispatch.request.v1"])
    )
    drifted = dict(exported["dispatch.request.v2"])
    drifted["properties"] = dict(drifted["properties"])
    drifted["properties"]["report_channel"] = {"type": "integer"}  # tamper
    (tmp_path / "dispatch-request.v2.schema.json").write_bytes(
        schema_source._canonical_bytes(drifted)
    )
    problems = schema_source.check_schema_exports(output_dir=tmp_path)
    assert len(problems) == 1
    assert "dispatch-request.v2.schema.json" in problems[0]
    assert "export_contracts.py" in problems[0]
    assert "drifted" in problems[0]


def test_missing_export_is_reported(tmp_path):
    problems = schema_source.check_schema_exports(output_dir=tmp_path)
    assert len(problems) == 2
    assert all("missing" in problem for problem in problems)


@pytest.mark.parametrize("type_id", ["dispatch.request.v1", "dispatch.request.v2"])
def test_exports_are_valid_draft07_schemas(type_id):
    """The exports must themselves be loadable, valid JSON Schemas."""
    import json

    import jsonschema

    exported = schema_source.export_dispatch_request_schemas()
    document = exported[type_id]
    # jsonschema.check_schema raises on an invalid schema document
    jsonschema.validators.validator_for(document).check_schema(document)
    # and the exported file on disk must equal the in-memory export
    filename = schema_source.EXPORT_FILENAMES[type_id]
    on_disk = json.loads((CONTRACTS_DIR / filename).read_text(encoding="utf-8"))
    assert on_disk == document
