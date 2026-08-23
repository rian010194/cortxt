from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .errors import EventError

TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class Envelope:
    """Inbound or outbound generic event envelope."""

    id: str
    type: str
    occurred_at: str
    source: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_iso8601(timestamp_str: str) -> bool:
    if not isinstance(timestamp_str, str) or not timestamp_str.strip():
        return False
    try:
        ts = timestamp_str.replace("Z", "+00:00")
        datetime.fromisoformat(ts)
        return True
    except (ValueError, TypeError):
        return False


def validate_envelope(doc: Any) -> Envelope:
    """Validate a raw dictionary against the closed Envelope schema."""
    if not isinstance(doc, dict):
        raise EventError("validation_error", "Envelope must be a JSON object")

    allowed_keys = {"id", "type", "occurred_at", "source", "data"}
    extra_keys = set(doc.keys()) - allowed_keys
    if extra_keys:
        raise EventError("validation_error", f"Envelope contains unknown field: {sorted(extra_keys)[0]}")

    missing_keys = allowed_keys - set(doc.keys())
    if missing_keys:
        raise EventError("validation_error", f"Envelope missing required field: {sorted(missing_keys)[0]}")

    event_id = doc["id"]
    if not isinstance(event_id, str) or not event_id.strip():
        raise EventError("validation_error", "Envelope id must be a non-empty string")

    event_type = doc["type"]
    if not isinstance(event_type, str) or not TYPE_PATTERN.match(event_type):
        raise EventError(
            "validation_error",
            f"Envelope type {event_type!r} is invalid; must match pattern {TYPE_PATTERN.pattern}",
        )

    occurred_at = doc["occurred_at"]
    if not _validate_iso8601(occurred_at):
        raise EventError(
            "validation_error",
            f"Envelope occurred_at {occurred_at!r} is not a valid ISO-8601 timestamp",
        )

    source = doc["source"]
    if not isinstance(source, str) or not source.strip():
        raise EventError("validation_error", "Envelope source must be a non-empty string")

    data = doc["data"]
    if not isinstance(data, dict):
        raise EventError("validation_error", "Envelope data must be a JSON object")

    return Envelope(
        id=event_id,
        type=event_type,
        occurred_at=occurred_at,
        source=source,
        data=data,
    )
