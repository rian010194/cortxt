"""Append-only, hash-chained, resumable session state for Agent Runtime.

Ports the proven primitives from agent-platform/state/ledger.py (atomic
write via tempfile+os.replace, sha256 event-chain, optimistic-concurrency
append) as Agent Runtime's own code — session persistence and resume is
Agent Runtime's responsibility per the target architecture (§8.2), not a
delegated concern of a separate module. See
docs/superpowers/specs/2026-08-15-fas2-agent-runtime-v01-design.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64
SESSION_ID_RE = re.compile(r"^session_[0-9a-f]{32}$")
EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class SessionError(Exception):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _session_path(store: Path, session_id: str, validate: bool = True) -> Path:
    if validate and not SESSION_ID_RE.fullmatch(session_id):
        raise SessionError("invalid_input", "invalid session_id")
    return store / session_id / "session.json"


def _event(sequence: int, event_type: str, payload: dict, previous_hash: str) -> dict:
    if not EVENT_TYPE_RE.fullmatch(event_type):
        raise SessionError("invalid_input", "invalid event_type")
    unsigned = {
        "sequence": sequence,
        "event_type": event_type,
        "payload": payload,
        "previous_hash": previous_hash,
        "timestamp": utc_now(),
    }
    digest = hashlib.sha256(canonical_json(unsigned)).hexdigest()
    return {**unsigned, "hash": digest}


def _atomic_write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json(doc) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as error:
        raise SessionError("io_error", "could not persist session") from error
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def create(store: Path, task_id: str) -> dict:
    if not isinstance(task_id, str) or not task_id.strip():
        raise SessionError("invalid_input", "task_id must be a non-empty string")
    session_id = "session_" + uuid.uuid4().hex
    doc = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "events": [_event(0, "session.created", {"task_id": task_id}, ZERO_HASH)],
    }
    _atomic_write(_session_path(store, session_id), doc)
    return doc


def _validate_chain(doc: dict, session_id: str) -> None:
    if not isinstance(doc, dict) or set(doc) != {"schema_version", "session_id", "events"}:
        raise SessionError("integrity_error", "session has an invalid shape")
    if doc["schema_version"] != SCHEMA_VERSION or doc["session_id"] != session_id:
        raise SessionError("integrity_error", "session identity is invalid")
    previous = ZERO_HASH
    fields = {"sequence", "event_type", "payload", "previous_hash", "timestamp", "hash"}
    for i, event in enumerate(doc["events"]):
        if not isinstance(event, dict) or set(event) != fields:
            raise SessionError("integrity_error", "event has an invalid shape")
        if event["sequence"] != i or event["previous_hash"] != previous:
            raise SessionError("integrity_error", "event sequence or chain is invalid")
        unsigned = {k: event[k] for k in fields if k != "hash"}
        expected = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        if event["hash"] != expected:
            raise SessionError("integrity_error", "event hash is invalid")
        previous = event["hash"]


def load(store: Path, session_id: str) -> dict:
    path = _session_path(store, session_id, validate=False)
    if not path.is_file():
        raise SessionError("not_found", "session was not found")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise SessionError("integrity_error", "session is not valid JSON") from error
    _validate_chain(doc, session_id)
    return doc


def append(store: Path, session_id: str, expected_sequence: int, event_type: str, payload: dict) -> dict:
    doc = load(store, session_id)
    current = len(doc["events"]) - 1
    if current != expected_sequence:
        raise SessionError("sequence_conflict",
                            f"expected sequence {expected_sequence}, found {current}")
    doc["events"].append(_event(current + 1, event_type, payload, doc["events"][-1]["hash"]))
    _atomic_write(_session_path(store, session_id), doc)
    return doc


def latest_sequence(session: dict) -> int:
    return len(session["events"]) - 1
