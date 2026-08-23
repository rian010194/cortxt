"""Generic event surface v1 (envelope, HMAC, idempotency, validation, dispatch)."""
from __future__ import annotations

from .dispatch import dispatch_event
from .envelope import Envelope, validate_envelope
from .errors import EventError
from .idempotency import IdempotencyStore, compute_payload_hash
from .registry import DEFAULT_SCHEMAS, get_schema, list_schemas, register_schema, validate_event_data
from .signing import compute_signature, verify_signature
from .validation import validate_data

__all__ = [
    "DEFAULT_SCHEMAS",
    "Envelope",
    "EventError",
    "IdempotencyStore",
    "compute_payload_hash",
    "compute_signature",
    "dispatch_event",
    "get_schema",
    "list_schemas",
    "register_schema",
    "validate_data",
    "validate_envelope",
    "validate_event_data",
    "verify_signature",
]
