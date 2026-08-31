from __future__ import annotations

import base64
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from cortxt_mcp import mandate, protocol, tools
from cortxt_mcp.audit import AuditLog
from cortxt_mcp.nonce_store import NonceStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

GRANTED_BY = "operator-demo"
KID = "key-2026-08"
FIXED_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return FIXED_NOW


class FakeNonceStore:
    def __init__(self) -> None:
        self._used: set[str] = set()

    def check_and_consume(self, nonce: str) -> bool:
        if nonce in self._used:
            return False
        self._used.add(nonce)
        return True


class FakeBudgetStore:
    def __init__(self) -> None:
        self._spent: dict[str, float] = {}

    def record_and_check(self, mandate_id, cost, cap) -> bool:
        if not mandate_id:
            return False
        total = self._spent.get(mandate_id, 0.0) + max(float(cost), 0.0)
        self._spent[mandate_id] = total
        return total <= cap


class FakeRevocationStore:
    def is_revoked(self, granted_by, kid, at):  # noqa: ARG002
        return False


@pytest.fixture()
def keypair():
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = mandate.public_key_hex_from_private_key(private_key)
    return private_key, public_key_hex


def _issue(private_key, **overrides):
    public_key_hex = mandate.public_key_hex_from_private_key(private_key)
    defaults = dict(
        granted_by=GRANTED_BY,
        kid=KID,
        issue_ref="owner/repo#206",
        allowed_tools=["cortxt_dispatch"],
        data_class_max="L2",
        budget_usd_max=25.0,
        max_runtime_seconds=3600,
        expires_at="2026-08-22T13:00:00Z",
        scope_text="approved scope text for issue #206",
    )
    defaults.update(overrides)
    defaults.setdefault("public_keys", {defaults["granted_by"]: {defaults["kid"]: public_key_hex}})
    return mandate.issue_mandate(private_key=private_key, **defaults)


def _verify(envelope, public_keys, *, tool="cortxt_dispatch", tier=tools.TIER_DISPATCH,
            call_context=None, nonce_store=None, budget_store=None, clock=_clock,
            revocation_store=None):
    if public_keys and all(isinstance(value, str) for value in public_keys.values()):
        public_keys = {issuer: {KID: value} for issuer, value in public_keys.items()}
    return mandate.verify_mandate(
        envelope,
        tool=tool,
        tier=tier,
        call_context=call_context or mandate.CallContext(issue_ref="owner/repo#206"),
        public_keys=public_keys,
        nonce_store=nonce_store or FakeNonceStore(),
        budget_store=budget_store or FakeBudgetStore(),
        revocation_store=revocation_store or FakeRevocationStore(),
        clock=clock,
    )


# --- Happy path ---------------------------------------------------------

def test_valid_envelope_is_accepted(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    decision = _verify(issued.envelope, {GRANTED_BY: public_key_hex})
    assert decision.accepted
    assert decision.reason == mandate.REASON_ACCEPTED
    assert decision.mandate_id == issued.envelope["mandate_id"]


# --- Adversarial cases (AC 6) --------------------------------------------

def test_bad_signature_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    tampered = {**issued.envelope, "signature": base64.b64encode(b"\x00" * 64).decode("ascii")}
    decision = _verify(tampered, {GRANTED_BY: public_key_hex})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_INVALID_SIGNATURE


@pytest.mark.parametrize("field,value", [
    ("issue_ref", "owner/repo#999"),
    ("allowed_tools", ["some_other_tool"]),
    ("budget_usd_max", 999.0),
    ("data_class_max", "L3"),
    ("nonce", "attacker-chosen-nonce"),
    ("expires_at", "2099-01-01T00:00:00Z"),
])
def test_tampered_payload_any_field_rejected(keypair, field, value):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    tampered = {**issued.envelope, field: value}
    decision = _verify(tampered, {GRANTED_BY: public_key_hex})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_INVALID_SIGNATURE


def test_nonce_replay_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    public_keys = {GRANTED_BY: public_key_hex}
    nonce_store = FakeNonceStore()
    first = _verify(issued.envelope, public_keys, nonce_store=nonce_store)
    second = _verify(issued.envelope, public_keys, nonce_store=nonce_store)
    assert first.accepted
    assert not second.accepted
    assert second.reason == mandate.REASON_NONCE_REPLAYED


def test_nonce_replay_rejected_across_durable_store_reload(keypair, tmp_path):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    public_keys = {GRANTED_BY: public_key_hex}
    path = tmp_path / "used_nonces.json"

    first_process_store = NonceStore(path)
    first = _verify(issued.envelope, public_keys, nonce_store=first_process_store)
    assert first.accepted

    # Simulate a server restart: a fresh NonceStore instance over the same
    # durable path must still see the previously consumed nonce.
    second_process_store = NonceStore(path)
    second = _verify(issued.envelope, public_keys, nonce_store=second_process_store)
    assert not second.accepted
    assert second.reason == mandate.REASON_NONCE_REPLAYED


def test_expired_envelope_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, expires_at="2020-01-01T00:00:00Z")
    decision = _verify(issued.envelope, {GRANTED_BY: public_key_hex})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_EXPIRED


@pytest.mark.parametrize("bad_value", ["not-a-date", "2026-08-22", "", None, 12345])
def test_expires_at_invalid_format_rejected(keypair, bad_value):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    tampered_unsigned = {**issued.envelope}
    tampered_unsigned["expires_at"] = bad_value
    # Re-sign so this exercises the expires_at parser, not the signature check.
    resigned = _resign(tampered_unsigned, private_key)
    decision = _verify(resigned, {GRANTED_BY: public_key_hex})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_EXPIRES_AT_INVALID


def test_wrong_issue_ref_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, issue_ref="owner/repo#206")
    decision = _verify(
        issued.envelope, {GRANTED_BY: public_key_hex},
        call_context=mandate.CallContext(issue_ref="owner/repo#999"),
    )
    assert not decision.accepted
    assert decision.reason == mandate.REASON_ISSUE_REF_MISMATCH


def test_tool_not_in_allowed_tools_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, allowed_tools=["cortxt_addons_submit"])
    decision = _verify(issued.envelope, {GRANTED_BY: public_key_hex}, tool="cortxt_dispatch")
    assert not decision.accepted
    assert decision.reason == mandate.REASON_TOOL_NOT_ALLOWED


def test_data_class_above_max_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, data_class_max="L1")
    decision = _verify(
        issued.envelope, {GRANTED_BY: public_key_hex},
        call_context=mandate.CallContext(issue_ref="owner/repo#206", data_class="L2"),
    )
    assert not decision.accepted
    assert decision.reason == mandate.REASON_DATA_CLASS_EXCEEDED


@pytest.mark.parametrize("requested_runtime", [0.0, 3599.0, 3600.0])
def test_requested_runtime_at_or_below_max_accepted(keypair, requested_runtime):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, max_runtime_seconds=3600)
    decision = _verify(
        issued.envelope, {GRANTED_BY: public_key_hex},
        call_context=mandate.CallContext(
            issue_ref="owner/repo#206",
            estimated_runtime_seconds=requested_runtime,
        ),
    )
    assert decision.accepted


def test_requested_runtime_above_max_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, max_runtime_seconds=60)
    decision = _verify(
        issued.envelope, {GRANTED_BY: public_key_hex},
        call_context=mandate.CallContext(
            issue_ref="owner/repo#206",
            estimated_runtime_seconds=60.1,
        ),
    )
    assert not decision.accepted
    assert decision.reason == mandate.REASON_RUNTIME_EXCEEDED


def test_undeclared_requested_runtime_is_accepted(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, max_runtime_seconds=0)
    decision = _verify(
        issued.envelope, {GRANTED_BY: public_key_hex},
        call_context=mandate.CallContext(
            issue_ref="owner/repo#206",
            estimated_runtime_seconds=None,
        ),
    )
    assert decision.accepted


@pytest.mark.parametrize("bad_value", [-1, "not-a-number"])
def test_malformed_envelope_runtime_rejected(keypair, bad_value):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    tampered_unsigned = {**issued.envelope, "max_runtime_seconds": bad_value}
    resigned = _resign(tampered_unsigned, private_key)
    decision = _verify(resigned, {GRANTED_BY: public_key_hex})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_MALFORMED_ENVELOPE


def test_budget_cumulative_exceeded_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, budget_usd_max=10.0)
    public_keys = {GRANTED_BY: public_key_hex}
    budget_store = FakeBudgetStore()
    context = mandate.CallContext(issue_ref="owner/repo#206", estimated_cost_usd=7.0)
    # First call under cap; must use a fresh nonce-store per call since the
    # nonce is single-use, but budget accumulates against the same mandate_id.
    first = _verify(issued.envelope, public_keys, call_context=context, budget_store=budget_store)
    assert first.accepted

    issued_2 = _issue(private_key, budget_usd_max=10.0, mandate_id=issued.envelope["mandate_id"])
    second = _verify(issued_2.envelope, public_keys, call_context=context, budget_store=budget_store)
    assert not second.accepted
    assert second.reason == mandate.REASON_BUDGET_EXCEEDED


def test_parallel_calls_each_under_cap_but_cumulative_over_rejected(keypair):
    private_key, public_key_hex = keypair
    public_keys = {GRANTED_BY: public_key_hex}
    budget_store = FakeBudgetStore()
    context = mandate.CallContext(issue_ref="owner/repo#206", estimated_cost_usd=6.0)
    shared_mandate_id = "fixed-mandate-id-for-cumulative-test"

    results = []
    for _ in range(3):
        issued = _issue(private_key, budget_usd_max=10.0, mandate_id=shared_mandate_id)
        results.append(_verify(issued.envelope, public_keys, call_context=context, budget_store=budget_store))

    assert results[0].accepted
    assert not results[1].accepted
    assert results[1].reason == mandate.REASON_BUDGET_EXCEEDED
    assert not results[2].accepted


def test_scope_fingerprint_mismatch_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, scope_text="the approved scope")
    decision = _verify(
        issued.envelope, {GRANTED_BY: public_key_hex},
        call_context=mandate.CallContext(issue_ref="owner/repo#206", scope_text="a drifted, different scope"),
    )
    assert not decision.accepted
    assert decision.reason == mandate.REASON_SCOPE_FINGERPRINT_MISMATCH


def test_scope_fingerprint_matches_via_expected_fingerprint_directly(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, scope_text="the approved scope")
    expected_fp = mandate.compute_scope_fingerprint("the approved scope")
    decision = _verify(
        issued.envelope, {GRANTED_BY: public_key_hex},
        call_context=mandate.CallContext(issue_ref="owner/repo#206", expected_scope_fingerprint=expected_fp),
    )
    assert decision.accepted


def test_unknown_schema_version_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    tampered_unsigned = {**issued.envelope, "schema_version": 999}
    resigned = _resign(tampered_unsigned, private_key)
    decision = _verify(resigned, {GRANTED_BY: public_key_hex})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_UNKNOWN_SCHEMA_VERSION


def test_missing_signature_field_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    tampered = {**issued.envelope, "signature": ""}
    decision = _verify(tampered, {GRANTED_BY: public_key_hex})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_MISSING_SIGNATURE


def test_malformed_signature_not_base64_rejected(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    tampered = {**issued.envelope, "signature": "not-valid-base64!!!"}
    decision = _verify(tampered, {GRANTED_BY: public_key_hex})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_INVALID_SIGNATURE


def test_key_order_canonicalization_does_not_affect_verification(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    reordered = dict(reversed(list(issued.envelope.items())))
    assert list(reordered) != list(issued.envelope)  # key insertion order actually differs
    decision = _verify(reordered, {GRANTED_BY: public_key_hex})
    assert decision.accepted


def test_empty_allowed_tools_denies_all_tier1(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, allowed_tools=[])
    decision = _verify(issued.envelope, {GRANTED_BY: public_key_hex})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_TOOL_NOT_ALLOWED


def test_granted_by_with_no_matching_key_rejected(keypair):
    private_key, _public_key_hex = keypair
    issued = _issue(private_key, granted_by="someone-else")
    decision = _verify(issued.envelope, {GRANTED_BY: mandate.public_key_hex_from_private_key(Ed25519PrivateKey.generate())})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_UNKNOWN_GRANTED_BY


def test_missing_envelope_rejected():
    decision = _verify(None, {})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_MANDATE_MISSING


def test_malformed_envelope_wrong_shape_rejected():
    decision = _verify({"not": "a mandate"}, {})
    assert not decision.accepted
    assert decision.reason == mandate.REASON_MALFORMED_ENVELOPE


def test_verify_mandate_is_pure_no_hidden_io(keypair):
    """No filesystem/network access happens inside verify_mandate itself
    -- only through the injected nonce_store/budget_store objects, which
    here are pure in-memory fakes."""
    import os

    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    before = set(os.listdir(Path(__file__).parent))
    _verify(issued.envelope, {GRANTED_BY: public_key_hex})
    after = set(os.listdir(Path(__file__).parent))
    assert before == after


def _resign(envelope_without_valid_signature: dict, private_key: Ed25519PrivateKey) -> dict:
    """Test helper: re-sign a hand-tampered envelope so a test can isolate
    one specific field-level check (e.g. expires_at parsing, schema
    version) from the signature check that would otherwise reject it
    first."""
    from runtime.session_state import canonical_json

    body = {k: v for k, v in envelope_without_valid_signature.items() if k != "signature"}
    signature = private_key.sign(canonical_json(body))
    return {**body, "signature": base64.b64encode(signature).decode("ascii")}


# --- Regression through call_tool (AC 1, 2, 3, 9) -------------------------

def _verifier(public_keys, nonce_store=None, budget_store=None):
    if public_keys and all(isinstance(value, str) for value in public_keys.values()):
        public_keys = {issuer: {KID: value} for issuer, value in public_keys.items()}
    return mandate.MandateVerifier(
        public_keys=public_keys,
        nonce_store=nonce_store or FakeNonceStore(),
        budget_store=budget_store or FakeBudgetStore(),
        revocation_store=FakeRevocationStore(),
        clock=_clock,
    )


def test_ac1_tier1_call_without_mandate_is_rejected_and_handler_not_invoked(monkeypatch):
    called = {"handler_ran": False}

    def spy_handler(_arguments):
        called["handler_ran"] = True
        return {"status": "succeeded"}

    monkeypatch.setitem(tools.TOOL_REGISTRY, "cortxt_dispatch",
                         tools.ToolSpec("cortxt_dispatch", tools.TIER_DISPATCH, "spy", spy_handler))

    with pytest.raises(tools.MandateRejectedError) as excinfo:
        tools.call_tool(
            "cortxt_dispatch", {}, allow_dispatch=True, allow_credentials=False,
            mandate=None, mandate_verifier=_verifier({}),
        )
    assert excinfo.value.reason == mandate.REASON_MANDATE_MISSING
    assert called["handler_ran"] is False


def test_ac1_tier1_call_with_null_mandate_is_rejected(monkeypatch):
    def spy_handler(_arguments):
        raise AssertionError("handler must not run")

    monkeypatch.setitem(tools.TOOL_REGISTRY, "cortxt_dispatch",
                         tools.ToolSpec("cortxt_dispatch", tools.TIER_DISPATCH, "spy", spy_handler))
    with pytest.raises(tools.MandateRejectedError):
        tools.call_tool(
            "cortxt_dispatch", {}, allow_dispatch=True, allow_credentials=False,
            mandate=None, mandate_verifier=_verifier({}),
        )


def test_ac2_valid_envelope_executes_handler_and_disallowed_tool_does_not(keypair, monkeypatch):
    private_key, public_key_hex = keypair
    called = {"count": 0}

    def spy_handler(_arguments):
        called["count"] += 1
        return {"status": "succeeded"}

    monkeypatch.setitem(tools.TOOL_REGISTRY, "cortxt_dispatch",
                         tools.ToolSpec("cortxt_dispatch", tools.TIER_DISPATCH, "spy", spy_handler))
    monkeypatch.setitem(tools.TOOL_REGISTRY, "cortxt_addons_submit",
                         tools.ToolSpec("cortxt_addons_submit", tools.TIER_DISPATCH, "spy2", spy_handler))

    public_keys = {GRANTED_BY: public_key_hex}
    verifier = _verifier(public_keys)
    context = mandate.CallContext(issue_ref="owner/repo#206")

    issued = _issue(private_key, allowed_tools=["cortxt_dispatch"])
    result = tools.call_tool(
        "cortxt_dispatch", {}, allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, call_context=context,
    )
    assert result == {"status": "succeeded"}
    assert called["count"] == 1

    issued_2 = _issue(private_key, allowed_tools=["cortxt_dispatch"])
    with pytest.raises(tools.MandateRejectedError) as excinfo:
        tools.call_tool(
            "cortxt_addons_submit", {}, allow_dispatch=True, allow_credentials=False,
            mandate=issued_2.envelope, mandate_verifier=verifier, call_context=context,
        )
    assert excinfo.value.reason == mandate.REASON_TOOL_NOT_ALLOWED
    assert called["count"] == 1  # second handler never ran


def test_ac2_over_max_runtime_does_not_invoke_handler(keypair, monkeypatch):
    private_key, public_key_hex = keypair
    called = {"handler_ran": False}

    def spy_handler(_arguments):
        called["handler_ran"] = True
        return {"status": "succeeded"}

    monkeypatch.setitem(tools.TOOL_REGISTRY, "cortxt_dispatch",
                         tools.ToolSpec("cortxt_dispatch", tools.TIER_DISPATCH, "spy", spy_handler))
    issued = _issue(private_key, max_runtime_seconds=30)
    context = mandate.CallContext(
        issue_ref="owner/repo#206",
        estimated_runtime_seconds=31.0,
    )

    with pytest.raises(tools.MandateRejectedError) as excinfo:
        tools.call_tool(
            "cortxt_dispatch", {}, allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope,
            mandate_verifier=_verifier({GRANTED_BY: public_key_hex}),
            call_context=context,
        )
    assert excinfo.value.reason == mandate.REASON_RUNTIME_EXCEEDED
    assert called["handler_ran"] is False


def test_ac3_same_nonce_twice_second_call_rejected_first_unaffected(keypair, monkeypatch):
    private_key, public_key_hex = keypair

    def spy_handler(_arguments):
        return {"status": "succeeded"}

    monkeypatch.setitem(tools.TOOL_REGISTRY, "cortxt_dispatch",
                         tools.ToolSpec("cortxt_dispatch", tools.TIER_DISPATCH, "spy", spy_handler))

    public_keys = {GRANTED_BY: public_key_hex}
    verifier = _verifier(public_keys)
    context = mandate.CallContext(issue_ref="owner/repo#206")
    issued = _issue(private_key)

    first = tools.call_tool(
        "cortxt_dispatch", {}, allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, call_context=context,
    )
    assert first == {"status": "succeeded"}

    with pytest.raises(tools.MandateRejectedError) as excinfo:
        tools.call_tool(
            "cortxt_dispatch", {}, allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope, mandate_verifier=verifier, call_context=context,
        )
    assert excinfo.value.reason == mandate.REASON_NONCE_REPLAYED


def test_ac9_tier0_tool_works_with_no_mandate_argument_at_all():
    result = tools.call_tool(
        "route_engine", {"task_tags": ["general"]}, allow_dispatch=False, allow_credentials=False,
    )
    assert result["engine_id"] == "claude"


def test_ac9_tier0_tool_ignores_a_present_mandate_key_instead_of_erroring():
    result = tools.call_tool(
        "route_engine", {"task_tags": ["general"]}, allow_dispatch=False, allow_credentials=False,
        mandate={"garbage": "not a real envelope"},
    )
    assert result["engine_id"] == "claude"


# --- AC 5: ledger carries mandate_id/mandate_decision on every row -------

def test_ac5_ledger_rows_carry_mandate_fields_for_accepted_rejected_and_tier0(keypair, tmp_path):
    private_key, public_key_hex = keypair
    public_keys = {GRANTED_BY: public_key_hex}
    verifier = _verifier(public_keys)
    audit = AuditLog(tmp_path / "sessions")

    # Tier-0 call.
    protocol.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "route_engine", "arguments": {"task_tags": ["general"]}}},
        allow_dispatch=True, allow_credentials=False, audit=audit, mandate_verifier=verifier,
    )

    # Accepted Tier-1 call.
    issued = _issue(private_key, allowed_tools=["cortxt_addons_submit"])
    protocol.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "cortxt_addons_submit", "arguments": {
             "candidate_id": "addon@x",
             "store": str(tmp_path / "sessions2"),
             "snapshot": str(tmp_path / "snap.json"),
             "mandate": issued.envelope,
             "mandate_context": {"issue_ref": "owner/repo#206"},
         }}},
        allow_dispatch=True, allow_credentials=False, audit=audit, mandate_verifier=verifier,
    )

    # Rejected Tier-1 call (no mandate).
    protocol.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "cortxt_dispatch", "arguments": {}}},
        allow_dispatch=True, allow_credentials=False, audit=audit, mandate_verifier=verifier,
    )

    from runtime import session_state as state

    session = state.load(tmp_path / "sessions", audit.session_id)
    rows = [e["payload"] for e in session["events"] if e["event_type"] == "mcp.tool_call"]
    assert len(rows) == 3

    tier0_row, accepted_row, rejected_row = rows
    assert tier0_row["mandate_id"] is None
    assert tier0_row["mandate_decision"] is None

    assert accepted_row["mandate_id"] == issued.envelope["mandate_id"]
    assert accepted_row["mandate_decision"] == "accepted"

    assert rejected_row["mandate_id"] is None
    assert rejected_row["mandate_decision"] == f"rejected:{mandate.REASON_MANDATE_MISSING}"


def test_ac5_tier_locked_rejection_is_now_ledgered(tmp_path):
    audit = AuditLog(tmp_path / "sessions")
    protocol.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "cortxt_dispatch", "arguments": {}}},
        allow_dispatch=False, allow_credentials=False, audit=audit,
    )
    assert audit.session_id is not None
    from runtime import session_state as state

    session = state.load(tmp_path / "sessions", audit.session_id)
    rows = [e["payload"] for e in session["events"] if e["event_type"] == "mcp.tool_call"]
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"
    assert rows[0]["mandate_decision"] == "tier_locked"


def test_protocol_maps_mandate_rejection_to_distinct_error_code(keypair):
    response = protocol.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "cortxt_dispatch", "arguments": {}}},
        allow_dispatch=True, allow_credentials=False,
        mandate_verifier=_verifier({}),
    )
    assert response["error"]["code"] == -32002
    assert response["error"]["code"] != -32001
    assert response["error"]["data"]["reason"] == mandate.REASON_MANDATE_MISSING


# --- ADR-033 AC10-AC20 -------------------------------------------------

def test_ac10_kid_is_signed_and_resolves_exact_key():
    old_key, new_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    keys = {GRANTED_BY: {
        "old": mandate.public_key_hex_from_private_key(old_key),
        "new": mandate.public_key_hex_from_private_key(new_key),
    }}
    issued = _issue(old_key, kid="old", public_keys=keys)
    assert _verify(issued.envelope, keys).accepted
    assert _verify({**issued.envelope, "kid": "new"}, keys).reason == mandate.REASON_INVALID_SIGNATURE
    assert _verify({**issued.envelope, "kid": "missing"}, keys).reason == mandate.REASON_UNKNOWN_KID
    assert _verify({**issued.envelope, "kid": ""}, keys).reason == mandate.REASON_UNKNOWN_KID


def test_ac11_overlap_and_expiry_are_independent():
    old_key, new_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    keys = {GRANTED_BY: {
        "old": mandate.public_key_hex_from_private_key(old_key),
        "new": mandate.public_key_hex_from_private_key(new_key),
    }}
    old = _issue(old_key, kid="old", public_keys=keys, expires_at="2026-08-22T12:01:00Z")
    new = _issue(new_key, kid="new", public_keys=keys, expires_at="2026-08-22T13:00:00Z")
    assert _verify(old.envelope, keys).accepted
    assert _verify(new.envelope, keys).accepted
    later = lambda: datetime(2026, 8, 22, 12, 2, tzinfo=timezone.utc)
    assert _verify(old.envelope, keys, clock=later).reason == mandate.REASON_EXPIRED


def test_ac12_issuance_requires_selected_registered_matching_key(keypair):
    private_key, public_key_hex = keypair
    with pytest.raises(ValueError, match="unknown granted_by/kid"):
        _issue(private_key, kid="unknown", public_keys={GRANTED_BY: {KID: public_key_hex}})
    other = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError, match="does not match"):
        _issue(other, public_keys={GRANTED_BY: {KID: public_key_hex}})


def test_ac13_ttl_accepts_bound_plus_skew_and_rejects_later(keypair):
    private_key, _ = keypair
    _issue(private_key, expires_at="2026-08-22T12:01:05Z", max_envelope_ttl_seconds=60,
           clock_skew_seconds=5, clock=_clock)
    with pytest.raises(ValueError, match="maximum envelope TTL"):
        _issue(private_key, expires_at="2026-08-22T12:01:06Z", max_envelope_ttl_seconds=60,
               clock_skew_seconds=5, clock=_clock)


def test_ac14_revocation_precedes_signature_nonce_expiry_and_budget(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key, expires_at="2020-01-01T00:00:00Z",
                    max_envelope_ttl_seconds=10**10, clock=_clock)
    class Revoked:
        def is_revoked(self, *args):
            return True
    class MustNotRun:
        def check_and_consume(self, nonce):
            raise AssertionError("nonce consumed")
        def record_and_check(self, mandate_id, cost, cap):
            raise AssertionError("budget debited")
    decision = _verify({**issued.envelope, "signature": "bad"}, {GRANTED_BY: public_key_hex},
                       revocation_store=Revoked(), nonce_store=MustNotRun(), budget_store=MustNotRun())
    assert decision.reason == mandate.REASON_KEY_REVOKED


def test_ac19_v1_clean_cutover_is_unknown_schema(keypair):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    v1 = dict(issued.envelope)
    v1.pop("kid")
    v1["schema_version"] = 1
    decision = _verify(v1, {GRANTED_BY: public_key_hex})
    assert decision.reason == mandate.REASON_UNKNOWN_SCHEMA_VERSION


def test_ac18b_credential_id_valid_against_real_credential_broker(keypair, tmp_path):
    """Regression: `_signing_key_credential_id` must produce an id the real
    `CredentialBroker` accepts. A fake in-memory broker (as used by
    test_ac18 below) has no id-format validation, so it previously masked a
    bug where the constructed id embedded literal "/" separators against
    CredentialBroker's [A-Za-z0-9_-]+ validation -- discovered live via
    `cortxt mandate issue --confirm` during the ADR-042 continuity-proof
    dogfood run (2026-08-26)."""
    from security.credential_broker import CredentialBroker

    private_key, _ = keypair
    from cryptography.hazmat.primitives import serialization
    pem = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    broker = CredentialBroker(
        store_dir=tmp_path / "broker",
        encrypt=lambda data: bytes(b ^ 0xFF for b in data),
        decrypt=lambda data: bytes(b ^ 0xFF for b in data),
    )
    mandate.store_signing_key_in_broker(pem, granted_by="rikard", kid="continuity-proof-2026-08-26", broker=broker)
    loaded = mandate.load_signing_key_from_broker(
        granted_by="rikard", kid="continuity-proof-2026-08-26", broker=broker, purpose="test",
    )
    assert mandate.public_key_hex_from_private_key(loaded) == mandate.public_key_hex_from_private_key(private_key)


def test_ac18_broker_credentials_are_tuple_specific_and_collision_safe(keypair):
    private_key, _ = keypair
    from cryptography.hazmat.primitives import serialization
    pem = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    class Broker:
        def __init__(self): self.values = {}; self.loads = []
        def store(self, credential_id, value, operator_confirmed):
            assert operator_confirmed is True; self.values[credential_id] = value
        def inject(self, credential_id, requesting_runtime, purpose):
            self.loads.append((credential_id, requesting_runtime, purpose)); return self.values[credential_id]
    broker = Broker()
    mandate.store_signing_key_in_broker(pem, granted_by="a/b", kid="c", broker=broker)
    mandate.store_signing_key_in_broker(pem, granted_by="a", kid="b/c", broker=broker)
    assert len(broker.values) == 2
    loaded = mandate.load_signing_key_from_broker(granted_by="a/b", kid="c", broker=broker,
                                                   purpose="rotate mandate key")
    assert mandate.public_key_hex_from_private_key(loaded) == mandate.public_key_hex_from_private_key(private_key)
    assert broker.loads[-1][1:] == ("mandate-cli", "rotate mandate key")


def test_ac18c_credential_id_rejects_naive_delimiter_collision():
    """Adversarial regression: a naive `sep.join([encode(granted_by),
    encode(kid)])` scheme is not collision-safe when the separator can also
    appear inside an encoded segment. These two distinct tuples are exactly
    the shape that collides under a "--"-joined, unpadded-base64url naive
    scheme (each pair concatenates to the same joined value across the
    boundary); the real implementation must still tell them apart."""
    id_a = mandate._signing_key_credential_id("granted_by-x", "y-kid")
    id_b = mandate._signing_key_credential_id("granted_by", "x-y-kid")
    assert id_a != id_b


def test_ac18c_credential_id_matches_broker_regex_and_is_deterministic():
    import re
    id_value = mandate._signing_key_credential_id("rikard", "continuity-proof-2026-08-26")
    assert re.fullmatch(r"[A-Za-z0-9_-]+", id_value)
    assert id_value == mandate._signing_key_credential_id("rikard", "continuity-proof-2026-08-26")


@pytest.mark.parametrize("raw", [
    "not-json",
    '{"operator":{"kid":123}}',
    '{"operator":{"kid":"00"}}',
    '{"operator":{"kid":"0000000000000000000000000000000000000000000000000000000000000000",'
    '"kid":"1111111111111111111111111111111111111111111111111111111111111111"}}',
])
def test_ac17_invalid_nested_config_fails_closed(monkeypatch, tmp_path, raw):
    from cortxt_mcp import server
    monkeypatch.setenv(server.MANDATE_PUBLIC_KEYS_ENV, raw)
    monkeypatch.setenv(server.MANDATE_STATE_DIR_ENV, str(tmp_path))
    (tmp_path / "revocations.json").write_text(
        '{"generation":1,"revocations":[]}', encoding="utf-8")
    verifier = server._build_mandate_verifier_from_env(tmp_path)
    assert verifier.public_keys == {}


def test_ac17_missing_initial_revocations_fails_closed(monkeypatch, tmp_path, keypair):
    import json
    from cortxt_mcp import server
    _, public_key_hex = keypair
    monkeypatch.setenv(server.MANDATE_PUBLIC_KEYS_ENV,
                       json.dumps({GRANTED_BY: {KID: public_key_hex}}))
    monkeypatch.setenv(server.MANDATE_STATE_DIR_ENV, str(tmp_path))
    verifier = server._build_mandate_verifier_from_env(tmp_path)
    assert verifier.public_keys == {}


def test_ac20_revoked_audit_has_key_identity_without_key_material(keypair, tmp_path, monkeypatch):
    private_key, public_key_hex = keypair
    issued = _issue(private_key)
    class Revoked:
        def is_revoked(self, *args): return True
    verifier = mandate.MandateVerifier(
        public_keys={GRANTED_BY: {KID: public_key_hex}}, nonce_store=FakeNonceStore(),
        budget_store=FakeBudgetStore(), revocation_store=Revoked(), clock=_clock)
    audit = AuditLog(tmp_path / "sessions")
    protocol.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "cortxt_dispatch", "arguments": {"mandate": issued.envelope}}},
        allow_dispatch=True, allow_credentials=False, audit=audit, mandate_verifier=verifier)
    from runtime import session_state as state
    session = state.load(tmp_path / "sessions", audit.session_id)
    row = next(e["payload"] for e in session["events"] if e["event_type"] == "mcp.tool_call")
    assert row["mandate_decision"] == "rejected:key_revoked"
    assert (row["granted_by"], row["kid"]) == (GRANTED_BY, KID)
    assert public_key_hex not in str(row)


# --- AC 8: cortxt_mcp server-side source never references the private-key
#           credential id or the credential broker. ------------------------

_SERVER_SIDE_MODULES = ["tools.py", "protocol.py", "server.py", "audit.py", "nonce_store.py", "run_lifecycle.py", "__init__.py"]


def test_ac8_server_side_source_never_references_private_key_credential_id():
    package_dir = Path(mandate.__file__).parent
    for filename in _SERVER_SIDE_MODULES:
        text = (package_dir / filename).read_text(encoding="utf-8")
        # The credential id itself must never appear in server-side source.
        assert mandate.MANDATE_SIGNING_KEY_CREDENTIAL_ID not in text, filename
        # No import/importlib statement may reference the credential broker
        # (a comment mentioning it as something to avoid is fine -- the
        # prohibition is structural, not lexical).
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                assert "credential_broker" not in stripped, f"{filename}: {stripped}"
                assert "mandate_signing" not in stripped.lower(), f"{filename}: {stripped}"
