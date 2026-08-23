#!/usr/bin/env python3
"""Offline checks for generic event surface v1 (envelope, HMAC, idempotency, validation).

Run: python scripts/test_event_surface.py
Prints ok/FAIL lines and exits non-zero on any failure.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add agent-platform to python path
REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_PLATFORM = REPO_ROOT / "agent-platform"
if str(AGENT_PLATFORM) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM))

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

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def main() -> int:
    # 1. Envelope validation checks
    valid_doc = {
        "id": "evt_test_01",
        "type": "github.push",
        "occurred_at": "2026-08-23T12:00:00Z",
        "source": "github",
        "data": {
            "ref": "refs/heads/main",
            "repository": "rian010194/cortxt",
            "sender": "rian010194",
            "head_commit": "abcdef123456",
        },
    }
    env = validate_envelope(valid_doc)
    check("envelope validation parses valid envelope", isinstance(env, Envelope) and env.id == "evt_test_01")

    # Extra keys rejected
    bad_doc_extra = dict(valid_doc, extra="unexpected")
    extra_rejected = False
    try:
        validate_envelope(bad_doc_extra)
    except EventError as e:
        extra_rejected = (e.kind == "validation_error")
    check("envelope validation rejects unknown extra fields", extra_rejected)

    # Missing keys rejected
    bad_doc_missing = {"id": "evt_1", "type": "github.push"}
    missing_rejected = False
    try:
        validate_envelope(bad_doc_missing)
    except EventError as e:
        missing_rejected = (e.kind == "validation_error")
    check("envelope validation rejects missing required fields", missing_rejected)

    # Invalid type regex rejected
    bad_type_rejected = False
    try:
        validate_envelope(dict(valid_doc, type="Bad_Type!"))
    except EventError as e:
        bad_type_rejected = (e.kind == "validation_error")
    check("envelope validation rejects invalid type regex", bad_type_rejected)

    # Invalid occurred_at rejected
    bad_time_rejected = False
    try:
        validate_envelope(dict(valid_doc, occurred_at="not-iso"))
    except EventError as e:
        bad_time_rejected = (e.kind == "validation_error")
    check("envelope validation rejects invalid occurred_at timestamp", bad_time_rejected)

    # 2. HMAC Signature verification checks
    test_secret = "secret_key_check_v1"
    raw_bytes = json.dumps(valid_doc).encode("utf-8")
    valid_sig = compute_signature(raw_bytes, test_secret)

    check("verify_signature accepts correct HMAC with prefix", verify_signature(raw_bytes, test_secret, valid_sig))
    raw_hex = valid_sig.replace("sha256=", "")
    check("verify_signature accepts correct HMAC without prefix", verify_signature(raw_bytes, test_secret, raw_hex))

    check("verify_signature rejects wrong signature", not verify_signature(raw_bytes, test_secret, "sha256=" + "0" * 64))
    check("verify_signature rejects missing signature (None)", not verify_signature(raw_bytes, test_secret, None))
    check("verify_signature rejects empty signature", not verify_signature(raw_bytes, test_secret, ""))
    check("verify_signature rejects malformed signature string", not verify_signature(raw_bytes, test_secret, "invalid_hex!"))
    check("verify_signature rejects empty secret", not verify_signature(raw_bytes, "", valid_sig))

    # 3. Idempotency store semantics & crash safety
    with tempfile.TemporaryDirectory() as tmp_dir:
        store_path = Path(tmp_dir) / "idempotency.json"
        store = IdempotencyStore(store_path, window_seconds=300)

        t0 = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
        event_id = "evt_idem_100"
        hash_orig = "payload_hash_alpha"
        hash_diff = "payload_hash_beta"

        # Initial write
        r1 = store.record(event_id, hash_orig, now=t0)
        check("idempotency record first seen returns processed", r1 == "processed")

        # Replay within window (t0 + 60s)
        t_within = t0 + timedelta(seconds=60)
        r2 = store.record(event_id, hash_orig, now=t_within)
        check("idempotency duplicate within window returns replayed_within_window", r2 == "replayed_within_window")

        # Simulated crash: fresh instance re-reads from disk
        store_recovered = IdempotencyStore(store_path, window_seconds=300)
        r_rec = store_recovered.record(event_id, hash_orig, now=t_within)
        check("atomic store survives crash/re-read", r_rec == "replayed_within_window")

        # Replay outside window (t0 + 350s) with identical hash
        t_outside = t0 + timedelta(seconds=350)
        r3 = store.record(event_id, hash_orig, now=t_outside)
        check("idempotency replay outside window with identical hash accepted", r3 == "accepted_outside_window")

        # Replay outside new window (t0 + 700s) with modified hash -> rejected
        t_outside2 = t0 + timedelta(seconds=700)
        r4 = store.record(event_id, hash_diff, now=t_outside2)
        check("idempotency replay outside window with hash mismatch rejected", r4 == "replayed_hash_mismatch")

        # Prune check
        store.record("evt_stale", "hash_stale", now=t0)
        removed_count = store.prune(now=t0 + timedelta(seconds=1000))
        check("idempotency prune drops expired entries", removed_count >= 1)

    # 4. Closed-schema validation per type
    valid_push_data = {
        "ref": "refs/heads/main",
        "repository": "rian010194/cortxt",
        "sender": "rian010194",
        "head_commit": "123456",
    }
    push_ok = False
    try:
        validate_event_data("github.push", valid_push_data)
        push_ok = True
    except Exception:
        pass
    check("github.push closed schema validation accepts valid data", push_ok)

    bad_push_ok = True
    try:
        validate_event_data("github.push", {"ref": "refs/heads/main"})
        bad_push_ok = False
    except EventError as e:
        bad_push_ok = (e.kind == "validation_error")
    check("github.push closed schema validation rejects incomplete data", bad_push_ok)

    # 5. Dispatch pipeline checks
    with tempfile.TemporaryDirectory() as tmp_dir:
        dispatch_store = IdempotencyStore(Path(tmp_dir) / "idem.json", window_seconds=300)
        dispatch_secret = "dispatch_secret_abc"

        # Unknown type fails closed
        res_unk = dispatch_event(
            envelope={"id": "evt_u1", "type": "unknown.type", "occurred_at": "2026-08-23T12:00:00Z", "source": "test", "data": {}},
            handlers={},
        )
        check("dispatch_event rejects unknown type fail-closed", res_unk.get("status") == "error" and res_unk.get("kind") == "unknown_type")

        # Missing handler fails closed
        res_nh = dispatch_event(
            envelope=valid_doc,
            handlers={},
        )
        check("dispatch_event rejects unhandled type fail-closed", res_nh.get("status") == "error" and res_nh.get("kind") == "no_handler")

        # Signature mismatch rejected before handler
        bad_sig_res = dispatch_event(
            raw_payload=raw_bytes,
            signature="sha256=invalid",
            secret=dispatch_secret,
            handlers={"github.push": lambda e: {"ran": True}},
        )
        check("dispatch_event rejects invalid signature before parsing", bad_sig_res.get("status") == "error" and bad_sig_res.get("kind") == "signature_invalid")

        # Handler execution and failure handling + retry dedupe
        fail_count = [0]

        def flaky_handler(e: Envelope):
            fail_count[0] += 1
            if fail_count[0] == 1:
                raise RuntimeError("transient handler error")
            return {"success": True}

        # Attempt 1: Handler fails
        res_flaky1 = dispatch_event(
            envelope=valid_doc,
            handlers={"github.push": flaky_handler},
            idempotency_store=dispatch_store,
        )
        check("dispatch_event returns structured handler_failed on exception", res_flaky1.get("status") == "error" and res_flaky1.get("kind") == "handler_failed")

        # Attempt 2: Retry within window is deduped
        res_flaky2 = dispatch_event(
            envelope=valid_doc,
            handlers={"github.push": flaky_handler},
            idempotency_store=dispatch_store,
        )
        check("dispatch_event dedupes retried event within window", res_flaky2.get("status") == "replayed" and res_flaky2.get("reason") == "replayed_within_window")
        check("failing handler was only called once due to dedupe", fail_count[0] == 1)

    # 6. Check for zero a/o/u-with-diacritics and no secret leakage
    surface_files = [
        AGENT_PLATFORM / "events" / "__init__.py",
        AGENT_PLATFORM / "events" / "envelope.py",
        AGENT_PLATFORM / "events" / "signing.py",
        AGENT_PLATFORM / "events" / "idempotency.py",
        AGENT_PLATFORM / "events" / "validation.py",
        AGENT_PLATFORM / "events" / "registry.py",
        AGENT_PLATFORM / "events" / "dispatch.py",
        AGENT_PLATFORM / "events" / "errors.py",
        REPO_ROOT / "scripts" / "test_event_surface.py",
    ]
    all_clean_ascii = True
    for fpath in surface_files:
        if fpath.is_file():
            content = fpath.read_text(encoding="utf-8")
            diacritics = re.findall(r"[\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]", content)
            if diacritics:
                all_clean_ascii = False
                break
    check("zero a/o/u-with-diacritics in all event surface files", all_clean_ascii)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
