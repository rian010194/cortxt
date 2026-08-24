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
