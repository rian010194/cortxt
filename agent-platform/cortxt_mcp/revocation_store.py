"""Fail-closed, refreshable mandate signing-key revocation snapshots."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

DEFAULT_REFRESH_INTERVAL_SECONDS = 10.0
DEFAULT_FRESHNESS_SECONDS = 60.0
REFRESH_INTERVAL_ENV = "CORTXT_MCP_MANDATE_REVOCATION_REFRESH_SECONDS"
FRESHNESS_ENV = "CORTXT_MCP_MANDATE_REVOCATION_FRESHNESS_SECONDS"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


class KeyRevocationStore:
    """Reads an operator-published JSON snapshot and denies on uncertainty.

    Shape: ``{"generation": 1, "revocations": [{"granted_by": "...",
    "kid": "...", "revoked_at": "...Z", ...}]}``.
    """

    def __init__(
        self,
        path: Path,
        *,
        refresh_interval_seconds: float | None = None,
        freshness_seconds: float | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.path = Path(path)
        self.refresh_interval_seconds = float(
            os.environ.get(REFRESH_INTERVAL_ENV, DEFAULT_REFRESH_INTERVAL_SECONDS)
            if refresh_interval_seconds is None else refresh_interval_seconds
        )
        self.freshness_seconds = float(
            os.environ.get(FRESHNESS_ENV, DEFAULT_FRESHNESS_SECONDS)
            if freshness_seconds is None else freshness_seconds
        )
        self.clock = clock
        self._generation: int | None = None
        self._entries: dict[tuple[str, str], datetime] = {}
        self._last_valid_at: datetime | None = None
        self._last_check_at: datetime | None = None
        self._metadata: tuple[int, int] | None = None
        self._invalid_newer = False
        self._refresh(force=True)

    @property
    def configured(self) -> bool:
        return self._last_valid_at is not None and not self._invalid_newer

    def _refresh(self, *, force: bool = False) -> None:
        now = self.clock()
        if not force and self._last_check_at is not None:
            if (now - self._last_check_at).total_seconds() < self.refresh_interval_seconds:
                return
        self._last_check_at = now
        try:
            stat = self.path.stat()
            metadata = (stat.st_mtime_ns, stat.st_size)
            if not force and metadata == self._metadata:
                return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            generation, entries = self._validate(raw)
            if self._generation is not None and generation < self._generation:
                raise ValueError("revocation generation rollback")
            for identity, old_time in self._entries.items():
                if identity not in entries or entries[identity] != old_time:
                    raise ValueError("revocation removal or backdating")
            self._generation = generation
            self._entries = entries
            self._metadata = metadata
            self._last_valid_at = now
            self._invalid_newer = False
        except Exception:
            self._invalid_newer = True

    @staticmethod
    def _validate(raw: object) -> tuple[int, dict[tuple[str, str], datetime]]:
        if not isinstance(raw, dict) or set(raw) != {"generation", "revocations"}:
            raise ValueError("invalid revocation snapshot")
        generation = raw["generation"]
        records = raw["revocations"]
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ValueError("invalid generation")
        if not isinstance(records, list):
            raise ValueError("invalid revocations")
        entries: dict[tuple[str, str], datetime] = {}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("invalid revocation")
            granted_by, kid = record.get("granted_by"), record.get("kid")
            if not isinstance(granted_by, str) or not granted_by or not isinstance(kid, str) or not kid:
                raise ValueError("invalid key identity")
            identity = (granted_by, kid)
            revoked_at = _parse_time(record.get("revoked_at"))
            if identity in entries and entries[identity] != revoked_at:
                raise ValueError("duplicate key identity")
            entries[identity] = revoked_at
        return generation, entries

    def is_revoked(self, granted_by: str, kid: str, at: datetime) -> bool:
        self._refresh()
        now = self.clock()
        if self._last_valid_at is None or self._invalid_newer:
            return True
        if (now - self._last_valid_at).total_seconds() > self.freshness_seconds:
            return True
        revoked_at = self._entries.get((granted_by, kid))
        return revoked_at is not None and revoked_at <= at.astimezone(timezone.utc)


class NullKeyRevocationStore:
    """Fail-closed revocation dependency for unconfigured verifiers."""

    configured = False

    def is_revoked(self, granted_by: str, kid: str, at: datetime) -> bool:  # noqa: ARG002
        return True
