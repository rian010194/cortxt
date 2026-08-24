"""Contract tests for CBS Phase 1 (ADR-041): state-category registry and
state-sync request/response shapes. Imports no server code -- these
validate the contract itself, independent of any implementation."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_SCHEMA_PATH = REPO_ROOT / "schemas" / "state-category-registry.schema.json"
REGISTRY_DATA_PATH = REPO_ROOT / "contracts" / "state-categories.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_registry_data_validates_against_its_schema():
    schema = _load(REGISTRY_SCHEMA_PATH)
    registry = _load(REGISTRY_DATA_PATH)
    jsonschema.validate(instance=registry, schema=schema)


def test_registry_has_the_three_known_categories():
    registry = _load(REGISTRY_DATA_PATH)
    category_ids = {entry["category_id"] for entry in registry["categories"]}
    assert category_ids == {"session-state", "widget-state", "atlas-cache"}


def test_only_session_state_is_remote_eligible_in_phase_1():
    registry = _load(REGISTRY_DATA_PATH)
    eligible = {
        entry["category_id"]
        for entry in registry["categories"]
        if entry["backend_eligibility"] == "remote-eligible"
    }
    assert eligible == {"session-state"}


def test_registry_schema_rejects_a_missing_mandate_scope():
    schema = _load(REGISTRY_SCHEMA_PATH)
    bad_registry = {
        "categories": [
            {
                "category_id": "session-state",
                "payload_schema_ref": "schemas/profile-manifest.schema.json",
                "backend_eligibility": "remote-eligible",
                "description": "missing mandate_scope",
            }
        ]
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad_registry, schema=schema)


def test_registry_schema_rejects_an_unknown_backend_eligibility_value():
    schema = _load(REGISTRY_SCHEMA_PATH)
    bad_registry = {
        "categories": [
            {
                "category_id": "session-state",
                "payload_schema_ref": "schemas/profile-manifest.schema.json",
                "backend_eligibility": "always-remote",
                "mandate_scope": "state.session-state",
                "description": "invalid enum value",
            }
        ]
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad_registry, schema=schema)


CONTRACT_SCHEMA_PATH = REPO_ROOT / "contracts" / "state-sync-contract.schema.json"


def _definition(name: str) -> dict:
    contract = _load(CONTRACT_SCHEMA_PATH)
    return {"$ref": f"#/definitions/{name}", "definitions": contract["definitions"]}


def test_state_read_request_accepts_a_valid_call():
    jsonschema.validate(
        instance={"category": "session-state"},
        schema=_definition("state_read_request"),
    )


def test_state_read_response_accepts_a_valid_payload():
    jsonschema.validate(
        instance={
            "category": "session-state",
            "version": 3,
            "updated_at": "2026-08-24T12:00:00+00:00",
            "payload": {"anything": "the category's own schema governs this"},
        },
        schema=_definition("state_read_response"),
    )


def test_state_write_request_requires_a_payload():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"category": "session-state"},
            schema=_definition("state_write_request"),
        )


def test_state_write_request_accepts_optimistic_concurrency_field():
    jsonschema.validate(
        instance={
            "category": "session-state",
            "payload": {"k": "v"},
            "expected_version": 2,
        },
        schema=_definition("state_write_request"),
    )


def test_state_write_response_requires_the_new_version():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"category": "session-state", "updated_at": "2026-08-24T12:00:00+00:00"},
            schema=_definition("state_write_response"),
        )


def test_state_delete_response_shape():
    jsonschema.validate(
        instance={
            "category": "session-state",
            "deleted": True,
            "deleted_at": "2026-08-24T12:00:00+00:00",
        },
        schema=_definition("state_delete_response"),
    )


def test_state_since_request_needs_a_cursor_or_null_for_full_sync():
    jsonschema.validate(
        instance={"category": "session-state", "since_cursor": None},
        schema=_definition("state_since_request"),
    )
    jsonschema.validate(
        instance={"category": "session-state", "since_cursor": "opaque-cursor-1"},
        schema=_definition("state_since_request"),
    )


def test_state_since_response_carries_changes_and_a_new_cursor():
    jsonschema.validate(
        instance={
            "category": "session-state",
            "changes": [
                {"version": 4, "updated_at": "2026-08-24T12:05:00+00:00", "payload": {}}
            ],
            "cursor": "opaque-cursor-2",
        },
        schema=_definition("state_since_response"),
    )


def test_state_since_response_accepts_a_deleted_change_with_no_payload():
    jsonschema.validate(
        instance={
            "category": "session-state",
            "changes": [
                {"version": 5, "updated_at": "2026-08-24T12:10:00+00:00", "deleted": True}
            ],
            "cursor": "opaque-cursor-3",
        },
        schema=_definition("state_since_response"),
    )


def test_state_conflict_error_shape():
    jsonschema.validate(
        instance={
            "category": "session-state",
            "current_version": 5,
            "expected_version": 3,
            "message": "version mismatch",
        },
        schema=_definition("state_conflict_error"),
    )


def test_state_read_request_rejects_an_unknown_category():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"category": "not-a-real-category"},
            schema=_definition("state_read_request"),
        )


def test_state_read_request_rejects_an_unexpected_extra_property():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"category": "session-state", "extra_field": "nope"},
            schema=_definition("state_read_request"),
        )


def test_all_category_values_across_the_contract_match_the_registry():
    registry = _load(REGISTRY_DATA_PATH)
    known_ids = {entry["category_id"] for entry in registry["categories"]}
    contract = _load(CONTRACT_SCHEMA_PATH)

    # All 8 request/response definitions must have consistent category enum
    definitions_with_category = [
        "state_read_request",
        "state_read_response",
        "state_write_request",
        "state_write_response",
        "state_delete_request",
        "state_delete_response",
        "state_since_request",
        "state_since_response",
    ]

    for defn_name in definitions_with_category:
        category_enum = contract["definitions"][defn_name]["properties"]["category"]["enum"]
        assert set(category_enum) == known_ids, f"Category enum mismatch in {defn_name}"
