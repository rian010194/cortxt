from __future__ import annotations

from typing import Any

from .errors import EventError
from .validation import validate_data

GITHUB_PUSH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ref", "repository", "sender", "head_commit"],
    "additionalProperties": False,
    "properties": {
        "ref": {"type": "string"},
        "repository": {
            "type": ["string", "object"],
            "properties": {
                "id": {"type": ["integer", "string"]},
                "name": {"type": "string"},
                "full_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "sender": {
            "type": ["string", "object"],
            "properties": {
                "login": {"type": "string"},
                "id": {"type": ["integer", "string"]},
            },
            "additionalProperties": False,
        },
        "head_commit": {
            "type": ["string", "object"],
            "properties": {
                "id": {"type": "string"},
                "message": {"type": "string"},
                "timestamp": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "branch": {"type": "string"},
        "before": {"type": "string"},
        "after": {"type": "string"},
        "commits": {"type": "array", "items": {"type": "object"}},
    },
}

GITHUB_ISSUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action", "issue_number", "actor"],
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": ["opened", "edited", "labeled", "unlabeled", "closed", "reopened", "transferred"],
        },
        "issue_number": {"type": "integer"},
        "labels": {
            "type": "array",
            "items": {"type": "string"},
        },
        "actor": {"type": "string"},
        "repository": {
            "type": ["string", "object"],
            "properties": {
                "id": {"type": ["integer", "string"]},
                "name": {"type": "string"},
                "full_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
}

GITHUB_PULL_REQUEST_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action", "pull_request_number", "review_state", "actor"],
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": ["submitted", "edited", "dismissed"],
        },
        "pull_request_number": {"type": "integer"},
        "review_state": {
            "type": "string",
            "enum": ["approved", "changes_requested", "commented", "dismissed"],
        },
        "actor": {"type": "string"},
        "repository": {
            "type": ["string", "object"],
            "properties": {
                "id": {"type": ["integer", "string"]},
                "name": {"type": "string"},
                "full_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
}

CORTXT_WORKFLOW_TRANSITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["issue_id", "from", "to", "run_id", "claim_id"],
    "additionalProperties": False,
    "properties": {
        "issue_id": {"type": "string"},
        "from": {"type": "string"},
        "to": {"type": "string"},
        "run_id": {"type": "string"},
        "claim_id": {"type": "string"},
    },
}

DEFAULT_SCHEMAS: dict[str, dict[str, Any]] = {
    "github.push": GITHUB_PUSH_SCHEMA,
    "github.issue": GITHUB_ISSUE_SCHEMA,
    "github.pull_request_review": GITHUB_PULL_REQUEST_REVIEW_SCHEMA,
    "cortxt.workflow.transition": CORTXT_WORKFLOW_TRANSITION_SCHEMA,
}

_REGISTRY: dict[str, dict[str, Any]] = dict(DEFAULT_SCHEMAS)


def register_schema(event_type: str, schema: dict[str, Any]) -> None:
    """Register or replace a schema for an event type."""
    if not isinstance(event_type, str) or not event_type.strip():
        raise EventError("validation_error", "Event type must be a non-empty string")
    if not isinstance(schema, dict):
        raise EventError("validation_error", "Schema must be a dictionary")
    _REGISTRY[event_type] = schema


def get_schema(event_type: str) -> dict[str, Any] | None:
    """Get the registered schema for an event type, or None if unknown."""
    return _REGISTRY.get(event_type)


def list_schemas() -> dict[str, dict[str, Any]]:
    """Return a copy of the registered schemas mapping."""
    return dict(_REGISTRY)


def validate_event_data(event_type: str, data: Any) -> None:
    """Validate data against the registered schema for event_type."""
    schema = get_schema(event_type)
    if schema is None:
        raise EventError("unknown_type", f"Unknown event type: {event_type!r}")
    validate_data(data, schema, path="$.data")
