from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from events import (
    DEFAULT_SCHEMAS,
    Envelope,
    EventError,
    IdempotencyStore,
    compute_payload_hash,
    compute_signature,
    dispatch_event,
    get_schema,
    register_schema,
    validate_data,
    validate_envelope,
    validate_event_data,
    verify_signature,
)


def test_envelope_validation_success():
    doc = {
        "id": "evt_12345",
        "type": "github.push",
        "occurred_at": "2026-08-23T12:00:00Z",
        "source": "github",
        "data": {
            "ref": "refs/heads/main",
            "repository": "rian010194/cortxt",
            "sender": "rian010194",
            "head_commit": "abc1234",
        },
    }
    env = validate_envelope(doc)
    assert isinstance(env, Envelope)
    assert env.id == "evt_12345"
    assert env.type == "github.push"
    assert env.occurred_at == "2026-08-23T12:00:00Z"
    assert env.source == "github"
    assert env.data["ref"] == "refs/heads/main"


def test_envelope_validation_rejects_extra_fields():
    doc = {
        "id": "evt_12345",
        "type": "github.push",
        "occurred_at": "2026-08-23T12:00:00Z",
        "source": "github",
        "data": {},
        "extra_field": "disallowed",
    }
    with pytest.raises(EventError) as exc_info:
        validate_envelope(doc)
    assert exc_info.value.kind == "validation_error"
    assert "unknown field" in exc_info.value.message


def test_envelope_validation_rejects_missing_fields():
    doc = {
        "id": "evt_12345",
        "type": "github.push",
        "occurred_at": "2026-08-23T12:00:00Z",
    }
    with pytest.raises(EventError) as exc_info:
        validate_envelope(doc)
    assert exc_info.value.kind == "validation_error"
    assert "missing required field" in exc_info.value.message


def test_envelope_validation_rejects_invalid_type_pattern():
    bad_types = ["123invalid", "UPPERCASE", "has space", "_starting_underscore", ""]
    for bad_type in bad_types:
        doc = {
            "id": "evt_1",
            "type": bad_type,
            "occurred_at": "2026-08-23T12:00:00Z",
            "source": "github",
            "data": {},
        }
        with pytest.raises(EventError) as exc_info:
            validate_envelope(doc)
        assert exc_info.value.kind == "validation_error"


def test_envelope_validation_rejects_invalid_occurred_at():
    doc = {
        "id": "evt_1",
        "type": "github.push",
        "occurred_at": "not-a-timestamp",
        "source": "github",
        "data": {},
    }
    with pytest.raises(EventError) as exc_info:
        validate_envelope(doc)
    assert exc_info.value.kind == "validation_error"


def test_signature_verification():
    secret = "test-secret-key-12345"
    payload = b'{"id":"evt_1","type":"github.push"}'
    valid_sig = compute_signature(payload, secret)

    assert verify_signature(payload, secret, valid_sig)
    # Plain hex without sha256= prefix should also be accepted
    hex_only = valid_sig.split("=", 1)[1]
    assert verify_signature(payload, secret, hex_only)

    # Wrong signature
    wrong_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"
    assert not verify_signature(payload, secret, wrong_sig)

    # Missing signature
    assert not verify_signature(payload, secret, None)
    assert not verify_signature(payload, secret, "")

    # Malformed signatures
    assert not verify_signature(payload, secret, "not-a-valid-hex")
    assert not verify_signature(payload, secret, "sha256=too-short")

    # Wrong secret
    assert not verify_signature(payload, "wrong-secret", valid_sig)


def test_idempotency_store_replay_semantics(tmp_path: Path):
    store_file = tmp_path / "idempotency.json"
    store = IdempotencyStore(store_file, window_seconds=300)

    t0 = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    event_id = "evt_dedupe_01"
    hash_v1 = "hash_alpha"
    hash_v2 = "hash_beta"

    # Initial processing
    res1 = store.record(event_id, hash_v1, now=t0)
    assert res1 == "processed"

    # Replay within window (t0 + 10s) -> no-op dedupe
    t_within = t0 + timedelta(seconds=10)
    res2 = store.record(event_id, hash_v1, now=t_within)
    assert res2 == "replayed_within_window"

    # Replay outside window (t0 + 350s) with matching hash -> accepted
    t_outside = t0 + timedelta(seconds=350)
    res3 = store.record(event_id, hash_v1, now=t_outside)
    assert res3 == "accepted_outside_window"

    # Replay outside new window (t0 + 700s) with mismatched hash -> rejected
    t_mismatch = t0 + timedelta(seconds=700)
    res4 = store.record(event_id, hash_v2, now=t_mismatch)
    assert res4 == "replayed_hash_mismatch"


def test_idempotency_store_crash_safety_and_persistence(tmp_path: Path):
    store_file = tmp_path / "state" / "idempotency.json"
    store1 = IdempotencyStore(store_file, window_seconds=300)

    t0 = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    store1.record("evt_crash_01", "hash_01", now=t0)

    # Read from a separate instance (simulating fresh start after crash)
    store2 = IdempotencyStore(store_file, window_seconds=300)
    res = store2.record("evt_crash_01", "hash_01", now=t0 + timedelta(seconds=5))
    assert res == "replayed_within_window"


def test_idempotency_store_prune(tmp_path: Path):
    store_file = tmp_path / "idempotency.json"
    store = IdempotencyStore(store_file, window_seconds=300)

    t0 = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    store.record("evt_old", "hash_old", now=t0)
    store.record("evt_new", "hash_new", now=t0 + timedelta(seconds=200))

    now = t0 + timedelta(seconds=400)
    # evt_old is 400s old (exceeds 300s window), evt_new is 200s old
    removed = store.prune(now=now)
    assert removed == 1

    # evt_new remains within window
    assert store.record("evt_new", "hash_new", now=now) == "replayed_within_window"


def test_closed_schema_validation():
    # Valid github.push
    push_data = {
        "ref": "refs/heads/main",
        "repository": "rian010194/cortxt",
        "sender": "rian010194",
        "head_commit": "abc1234",
    }
    validate_event_data("github.push", push_data)

    # Invalid github.push (missing head_commit)
    bad_push = {
        "ref": "refs/heads/main",
        "repository": "rian010194/cortxt",
        "sender": "rian010194",
    }
    with pytest.raises(EventError) as exc_info:
        validate_event_data("github.push", bad_push)
    assert exc_info.value.kind == "validation_error"

    # Valid github.issue
    issue_data = {
        "action": "labeled",
        "issue_number": 328,
        "labels": ["workflow:ready"],
        "actor": "rian010194",
    }
    validate_event_data("github.issue", issue_data)

    # Invalid github.issue action enum
    bad_issue = dict(issue_data, action="exploded")
    with pytest.raises(EventError) as exc_info:
        validate_event_data("github.issue", bad_issue)
    assert exc_info.value.kind == "validation_error"

    # Valid github.pull_request_review
    review_data = {
        "action": "submitted",
        "pull_request_number": 123,
        "review_state": "approved",
        "actor": "reviewer1",
    }
    validate_event_data("github.pull_request_review", review_data)

    # Valid cortxt.workflow.transition
    trans_data = {
        "issue_id": "rian010194/cortxt#328",
        "from": "workflow:ready",
        "to": "workflow:in-progress",
        "run_id": "run-001",
        "claim_id": "claim-001",
    }
    validate_event_data("cortxt.workflow.transition", trans_data)


def test_dispatch_pipeline_success(tmp_path: Path):
    store = IdempotencyStore(tmp_path / "idempotency.json")
    secret = "test-secret"

    payload_dict = {
        "id": "evt_push_100",
        "type": "github.push",
        "occurred_at": "2026-08-23T12:00:00Z",
        "source": "github",
        "data": {
            "ref": "refs/heads/main",
            "repository": "rian010194/cortxt",
            "sender": "rian010194",
            "head_commit": "c0ffee",
        },
    }
    raw_payload = json.dumps(payload_dict).encode("utf-8")
    signature = compute_signature(raw_payload, secret)

    invoked = []

    def handle_push(env: Envelope):
        invoked.append(env.id)
        return {"processed": True, "ref": env.data["ref"]}

    handlers = {"github.push": handle_push}

    result = dispatch_event(
        raw_payload=raw_payload,
        signature=signature,
        secret=secret,
        handlers=handlers,
        idempotency_store=store,
    )

    assert result["status"] == "ok"
    assert result["event_id"] == "evt_push_100"
    assert result["result"]["ref"] == "refs/heads/main"
    assert invoked == ["evt_push_100"]


def test_dispatch_pipeline_signature_failure():
    secret = "correct-secret"
    raw_payload = b'{"id":"evt_1","type":"github.push","occurred_at":"2026-08-23T12:00:00Z","source":"github","data":{}}'
    bad_signature = "sha256=badbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadb"

    result = dispatch_event(
        raw_payload=raw_payload,
        signature=bad_signature,
        secret=secret,
        handlers={},
    )
    assert result["status"] == "error"
    assert result["kind"] == "signature_invalid"


def test_dispatch_pipeline_unknown_type():
    doc = {
        "id": "evt_unk_01",
        "type": "unknown.event.type",
        "occurred_at": "2026-08-23T12:00:00Z",
        "source": "test",
        "data": {},
    }
    result = dispatch_event(envelope=doc, handlers={})
    assert result["status"] == "error"
    assert result["kind"] == "unknown_type"


def test_dispatch_pipeline_no_handler():
    doc = {
        "id": "evt_nh_01",
        "type": "github.push",
        "occurred_at": "2026-08-23T12:00:00Z",
        "source": "github",
        "data": {
            "ref": "refs/heads/main",
            "repository": "rian010194/cortxt",
            "sender": "rian010194",
            "head_commit": "c0ffee",
        },
    }
    result = dispatch_event(envelope=doc, handlers={})
    assert result["status"] == "error"
    assert result["kind"] == "no_handler"


def test_dispatch_pipeline_handler_failure_and_retry_dedupe(tmp_path: Path):
    store = IdempotencyStore(tmp_path / "idempotency.json")

    doc = {
        "id": "evt_fail_01",
        "type": "github.push",
        "occurred_at": "2026-08-23T12:00:00Z",
        "source": "github",
        "data": {
            "ref": "refs/heads/main",
            "repository": "rian010194/cortxt",
            "sender": "rian010194",
            "head_commit": "c0ffee",
        },
    }

    call_count = [0]

    def failing_handler(env: Envelope):
        call_count[0] += 1
        raise RuntimeError("database connection failed")

    handlers = {"github.push": failing_handler}

    # First attempt: handler raises exception -> structured handler_failed error
    res1 = dispatch_event(envelope=doc, handlers=handlers, idempotency_store=store)
    assert res1["status"] == "error"
    assert res1["kind"] == "handler_failed"
    assert "database connection failed" in res1["error"]
    assert call_count[0] == 1

    # Retry within window: deduped by idempotency store
    res2 = dispatch_event(envelope=doc, handlers=handlers, idempotency_store=store)
    assert res2["status"] == "replayed"
    assert res2["reason"] == "replayed_within_window"
    # Handler was NOT invoked a second time
    assert call_count[0] == 1
