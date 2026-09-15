"""Closed eight-field operation record (S4-B3, #606).

The record schema is CLOSED: exactly the eight normative fields

    operation_id, package_id, original_parent, candidate_revision,
    candidate_digest, status, result_revision_identity, recorded_at

with ``additionalProperties: false``. ``candidate_digest`` is
``sha256(canonical_object(candidate_revision))``; ``result_revision_identity``
equals the candidate digest when committed and is null otherwise.

``operation_id`` and ``original_parent`` are fixed before the first attempt
and are never re-read from head on retries. Records carrying ANY undeclared
field are rejected. The non-normative scenario fields ``replayed``,
``current_head`` and ``replayed_after_head_advance`` are scenario metadata the
oracle ignores -- they are never stored, never part of any digest, and a
record carrying them is rejected through the closed schema.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

from .revision import candidate_digest as compute_candidate_digest
from .revision import revision_identity, validate_revision

OPERATION_FIELDS = (
    "operation_id",
    "package_id",
    "original_parent",
    "candidate_revision",
    "candidate_digest",
    "status",
    "result_revision_identity",
    "recorded_at",
)

STATUS_PENDING = "pending"
STATUS_COMMITTED = "committed"
STATUS_REJECTED_CONTENT_MISMATCH = "rejected-op-content-mismatch"
STATUS_REJECTED_CONCURRENT = "rejected-op-concurrent"
STATUSES = (
    STATUS_PENDING,
    STATUS_COMMITTED,
    STATUS_REJECTED_CONTENT_MISMATCH,
    STATUS_REJECTED_CONCURRENT,
)

# Non-normative scenario metadata (the oracle ignores these; never stored).
SCENARIO_METADATA_FIELDS = ("replayed", "current_head", "replayed_after_head_advance")

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


class OperationRecordError(ValueError):
    """Raised when an operation record violates the closed S4-B3 schema."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def validate_operation_record(record: Mapping[str, Any]) -> None:
    """Fail-closed validation of a record against the closed eight-field schema."""
    if not isinstance(record, Mapping):
        raise OperationRecordError("operation record must be a mapping")
    keys = set(record)
    extra = sorted(keys - set(OPERATION_FIELDS))
    if extra:
        raise OperationRecordError(
            "operation record is closed (additionalProperties: false); "
            f"undeclared fields: {', '.join(extra)}"
        )
    missing = [f for f in OPERATION_FIELDS if f not in record]
    if missing:
        raise OperationRecordError(f"operation record missing fields: {', '.join(missing)}")
    for field in ("operation_id", "package_id"):
        if not isinstance(record[field], str) or not record[field]:
            raise OperationRecordError(f"{field} must be a non-empty string")
    if record["status"] not in STATUSES:
        raise OperationRecordError(
            f"status must be one of {', '.join(STATUSES)}; got {record['status']!r}"
        )
    validate_revision(record["candidate_revision"])
    expected_digest = compute_candidate_digest(record["candidate_revision"])
    if record["candidate_digest"] != expected_digest:
        raise OperationRecordError(
            "candidate_digest does not match sha256(canonical_object(candidate_revision))"
        )
    rri = record["result_revision_identity"]
    if record["status"] == STATUS_COMMITTED:
        if rri != expected_digest:
            raise OperationRecordError(
                "committed record must carry result_revision_identity == candidate_digest"
            )
    else:
        if rri is not None:
            raise OperationRecordError(
                "non-committed record must carry result_revision_identity == null"
            )
    if record["original_parent"] is not None:
        from ._digest import normalize_digest

        normalize_digest(record["original_parent"], field="original_parent")
    if not isinstance(record["recorded_at"], str) or not _TIMESTAMP_RE.match(record["recorded_at"]):
        raise OperationRecordError("recorded_at must be an ISO-8601 UTC timestamp ending in Z")


def make_operation_record(
    operation_id: str,
    package_id: str,
    original_parent: str | None,
    candidate_revision: Mapping[str, Any],
    status: str,
    result_revision_identity: str | None,
    recorded_at: str | None = None,
) -> dict:
    """Build a record with candidate_digest derived from the candidate revision.

    ``original_parent`` is the fixed pre-first-attempt parent: it is stored
    once and is never re-read from head on retries.
    """
    record = {
        "operation_id": operation_id,
        "package_id": package_id,
        "original_parent": original_parent,
        "candidate_revision": candidate_revision,
        "candidate_digest": compute_candidate_digest(candidate_revision),
        "status": status,
        "result_revision_identity": result_revision_identity,
        "recorded_at": recorded_at or _now(),
    }
    validate_operation_record(record)
    return record


def strip_scenario_metadata(scenario_record: Mapping[str, Any]) -> dict:
    """Read a frozen scenario example as an oracle: drop non-normative metadata.

    The oracle explicitly ignores ``replayed``, ``current_head`` and
    ``replayed_after_head_advance``; their file digests are used only as an
    integrity check. The returned mapping contains exactly the eight
    normative fields.
    """
    return {f: scenario_record[f] for f in OPERATION_FIELDS if f in scenario_record}


def operation_outcome_identity(record: Mapping[str, Any]) -> str:
    """The revision identity an operation produced (or would produce).

    For a committed record this is ``result_revision_identity``; for any other
    status the operation has produced no revision and the identity is null.
    """
    if record.get("status") == STATUS_COMMITTED:
        return record["result_revision_identity"]
    return None


def replay_result(record: Mapping[str, Any]) -> dict:
    """Idempotent replay view of a committed operation (S4-B3).

    Returns the stored result so a retry with the same ``operation_id`` and
    the same ``candidate_digest`` returns the same ``result_revision_identity``
    without creating a new revision. The scenario metadata fields are echoed
    back to the caller as response-only values (never stored on the record).
    """
    return {
        "operation_id": record["operation_id"],
        "replayed": True,
        "result_revision_identity": operation_outcome_identity(record),
        "candidate_digest": record["candidate_digest"],
    }


__all__ = [
    "OPERATION_FIELDS",
    "OperationRecordError",
    "SCENARIO_METADATA_FIELDS",
    "STATUSES",
    "STATUS_COMMITTED",
    "STATUS_PENDING",
    "STATUS_REJECTED_CONCURRENT",
    "STATUS_REJECTED_CONTENT_MISMATCH",
    "make_operation_record",
    "operation_outcome_identity",
    "replay_result",
    "strip_scenario_metadata",
    "validate_operation_record",
]

# Confirm at import time that the identity helpers agree with revision.py.
_ = revision_identity
