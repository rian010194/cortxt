from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Mapping

from .envelope import Envelope, validate_envelope
from .errors import EventError
from .idempotency import IdempotencyStore, compute_payload_hash
from .registry import get_schema
from .signing import verify_signature
from .validation import validate_data


def dispatch_event(
    envelope: Envelope | dict[str, Any] | bytes | str | None = None,
    handlers: Mapping[str, Callable[[Envelope], Any]] | None = None,
    idempotency_store: IdempotencyStore | None = None,
    secret: str | None = None,
    raw_payload: bytes | str | None = None,
    signature: str | None = None,
    scheme: str = "sha256",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail-closed dispatch pipeline for generic events.

    Pipeline:
      1. Signature verification (if secret is configured, reject before parsing)
      2. Envelope parsing & strict validation
      3. Type schema lookup & payload validation
      4. Idempotency store recording / replay handling
      5. Handler routing & structured error handling
    """
    # 1. HMAC verification before any parsing
    if secret is not None:
        effective_raw = raw_payload
        if effective_raw is None and isinstance(envelope, (bytes, str)):
            effective_raw = envelope

        if effective_raw is None or signature is None:
            return {
                "status": "error",
                "kind": "signature_invalid",
                "message": "Signature or payload missing for HMAC verification",
            }

        if not verify_signature(effective_raw, secret, signature, scheme=scheme):
            return {
                "status": "error",
                "kind": "signature_invalid",
                "message": "HMAC signature verification failed",
            }

    # 2. Envelope resolution & validation
    raw_for_envelope = envelope if envelope is not None else raw_payload
    if raw_for_envelope is None:
        return {
            "status": "error",
            "kind": "validation_error",
            "message": "No envelope or payload provided",
        }

    doc: Any
    if isinstance(raw_for_envelope, (bytes, str)):
        try:
            raw_text = raw_for_envelope.decode("utf-8") if isinstance(raw_for_envelope, bytes) else raw_for_envelope
            doc = json.loads(raw_text)
        except Exception as exc:
            return {
                "status": "error",
                "kind": "validation_error",
                "message": f"Malformed JSON envelope: {exc}",
            }
    elif isinstance(raw_for_envelope, Envelope):
        doc = raw_for_envelope.to_dict()
    elif isinstance(raw_for_envelope, dict):
        doc = raw_for_envelope
    else:
        return {
            "status": "error",
            "kind": "validation_error",
            "message": "Invalid envelope type; expected dict, str, bytes, or Envelope",
        }

    try:
        validated_envelope = validate_envelope(doc)
    except EventError as err:
        return {
            "status": "error",
            "kind": err.kind,
            "message": err.message,
        }
    except Exception as exc:
        return {
            "status": "error",
            "kind": "validation_error",
            "message": str(exc),
        }

    # 3. Type schema lookup and payload validation
    schema = get_schema(validated_envelope.type)
    if schema is None:
        return {
            "status": "error",
            "kind": "unknown_type",
            "event_id": validated_envelope.id,
            "type": validated_envelope.type,
            "message": f"Unknown event type: {validated_envelope.type!r}",
        }

    try:
        validate_data(validated_envelope.data, schema, path="$.data")
    except EventError as err:
        return {
            "status": "error",
            "kind": "validation_error",
            "event_id": validated_envelope.id,
            "type": validated_envelope.type,
            "message": err.message,
        }
    except Exception as exc:
        return {
            "status": "error",
            "kind": "validation_error",
            "event_id": validated_envelope.id,
            "type": validated_envelope.type,
            "message": str(exc),
        }

    # 4. Idempotency check
    if idempotency_store is not None:
        if raw_payload is not None:
            payload_hash = compute_payload_hash(raw_payload)
        elif isinstance(envelope, (bytes, str)):
            payload_hash = compute_payload_hash(envelope)
        else:
            payload_hash = compute_payload_hash(doc)

        rec_status = idempotency_store.record(validated_envelope.id, payload_hash, now=now)
        if rec_status == "replayed_within_window":
            return {
                "status": "replayed",
                "event_id": validated_envelope.id,
                "type": validated_envelope.type,
                "reason": "replayed_within_window",
            }
        if rec_status == "replayed_hash_mismatch":
            return {
                "status": "error",
                "kind": "replayed_hash_mismatch",
                "event_id": validated_envelope.id,
                "type": validated_envelope.type,
                "message": "Replay rejected due to payload hash mismatch",
            }

    # 5. Handler routing
    handlers_map = handlers or {}
    if validated_envelope.type not in handlers_map:
        return {
            "status": "error",
            "kind": "no_handler",
            "event_id": validated_envelope.id,
            "type": validated_envelope.type,
            "message": f"No handler registered for event type: {validated_envelope.type!r}",
        }

    handler = handlers_map[validated_envelope.type]
    try:
        result = handler(validated_envelope)
        return {
            "status": "ok",
            "event_id": validated_envelope.id,
            "type": validated_envelope.type,
            "result": result,
        }
    except Exception as exc:
        return {
            "status": "error",
            "kind": "handler_failed",
            "event_id": validated_envelope.id,
            "type": validated_envelope.type,
            "error": str(exc),
        }
