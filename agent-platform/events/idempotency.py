from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def compute_payload_hash(payload: bytes | str | dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of payload."""
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, dict):
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    else:
        raw = str(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class IdempotencyStore:
    """Crash-safe file-backed idempotency store with bounded replay window."""

    def __init__(self, path: Path | str, window_seconds: int = 300) -> None:
        self.path = Path(path)
        self.window_seconds = int(window_seconds)

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            content = self.path.read_text(encoding="utf-8")
            if not content.strip():
                return {}
            data = json.loads(content)
            if not isinstance(data, dict):
                return {}
            return data
        except Exception:
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.parent / f".{self.path.name}.tmp"
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        # Atomic replace
        os.replace(tmp, self.path)

    def record(self, event_id: str, payload_hash: str, now: datetime | None = None) -> str:
        """Record an event_id with its payload_hash.

        Returns one of:
          - "processed": new event recorded
          - "replayed_within_window": duplicate event within the idempotency window (no-op)
          - "accepted_outside_window": duplicate event outside the window with matching hash
          - "replayed_hash_mismatch": duplicate event outside the window with mismatched hash
        """
        now_dt = now or datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)

        data = self._load()
        entry = data.get(event_id)

        if entry is None:
            data[event_id] = {
                "payload_hash": payload_hash,
                "recorded_at": now_dt.isoformat(),
            }
            self._save(data)
            return "processed"

        recorded_str = entry.get("recorded_at", "")
        stored_hash = entry.get("payload_hash", "")
        try:
            recorded_dt = datetime.fromisoformat(recorded_str.replace("Z", "+00:00"))
            if recorded_dt.tzinfo is None:
                recorded_dt = recorded_dt.replace(tzinfo=timezone.utc)
            age = (now_dt - recorded_dt).total_seconds()
        except Exception:
            age = 0.0

        if age <= self.window_seconds:
            return "replayed_within_window"

        if stored_hash == payload_hash:
            data[event_id] = {
                "payload_hash": payload_hash,
                "recorded_at": now_dt.isoformat(),
            }
            self._save(data)
            return "accepted_outside_window"

        return "replayed_hash_mismatch"

    def prune(self, now: datetime | None = None, max_age_seconds: int | None = None) -> int:
        """Drop entries older than window (or max_age_seconds). Returns count removed."""
        now_dt = now or datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)

        threshold = max_age_seconds if max_age_seconds is not None else self.window_seconds
        data = self._load()
        initial_count = len(data)
        to_keep: dict[str, dict[str, Any]] = {}

        for event_id, entry in data.items():
            recorded_str = entry.get("recorded_at", "")
            try:
                recorded_dt = datetime.fromisoformat(recorded_str.replace("Z", "+00:00"))
                if recorded_dt.tzinfo is None:
                    recorded_dt = recorded_dt.replace(tzinfo=timezone.utc)
                age = (now_dt - recorded_dt).total_seconds()
                if age <= threshold:
                    to_keep[event_id] = entry
            except Exception:
                pass

        removed = initial_count - len(to_keep)
        if removed > 0:
            self._save(to_keep)
        return removed
