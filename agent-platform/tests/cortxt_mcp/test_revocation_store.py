from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from cortxt_mcp.revocation_store import KeyRevocationStore


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def _snapshot(path, generation=1, entries=()):
    path.write_text(json.dumps({"generation": generation, "revocations": list(entries)}), encoding="utf-8")


def _entry(revoked_at="2026-08-22T12:00:00Z"):
    return {"granted_by": "operator", "kid": "key-1", "revoked_at": revoked_at,
            "reason": "rotation incident"}


def test_missing_initial_snapshot_fails_closed(tmp_path):
    clock = FakeClock()
    store = KeyRevocationStore(tmp_path / "missing.json", clock=clock)
    assert not store.configured
    assert store.is_revoked("operator", "key-1", clock())


def test_refresh_interval_and_atomic_replacement_without_restart(tmp_path):
    clock = FakeClock()
    path = tmp_path / "revocations.json"
    _snapshot(path)
    store = KeyRevocationStore(path, refresh_interval_seconds=10, freshness_seconds=60, clock=clock)
    replacement = tmp_path / "replacement.json"
    _snapshot(replacement, 2, [_entry()])
    os.replace(replacement, path)
    clock.advance(9)
    assert not store.is_revoked("operator", "key-1", clock())
    clock.advance(1)
    assert store.is_revoked("operator", "key-1", clock())


def test_malformed_newer_snapshot_and_generation_rollback_fail_closed(tmp_path):
    clock = FakeClock()
    path = tmp_path / "revocations.json"
    _snapshot(path, 2, [_entry()])
    store = KeyRevocationStore(path, refresh_interval_seconds=0, clock=clock)
    path.write_text("{bad", encoding="utf-8")
    assert store.is_revoked("other", "key-2", clock())

    _snapshot(path, 1, [_entry()])
    assert store.is_revoked("other", "key-2", clock())


def test_removal_timestamp_change_and_stale_source_fail_closed(tmp_path):
    clock = FakeClock()
    path = tmp_path / "revocations.json"
    _snapshot(path, 1, [_entry()])
    store = KeyRevocationStore(path, refresh_interval_seconds=0, freshness_seconds=60, clock=clock)
    _snapshot(path, 2, [])
    assert store.is_revoked("other", "key-2", clock())

    # A separate unchanged valid source becomes stale after its bounded LKG window.
    path2 = tmp_path / "revocations2.json"
    _snapshot(path2)
    store2 = KeyRevocationStore(path2, refresh_interval_seconds=1, freshness_seconds=60, clock=clock)
    clock.advance(61)
    assert store2.is_revoked("other", "key-2", clock())


def test_future_revocation_only_applies_at_effective_time(tmp_path):
    clock = FakeClock()
    path = tmp_path / "revocations.json"
    _snapshot(path, 1, [_entry("2026-08-22T12:01:00Z")])
    store = KeyRevocationStore(path, clock=clock)
    assert not store.is_revoked("operator", "key-1", clock())
    clock.advance(60)
    assert store.is_revoked("operator", "key-1", clock())
