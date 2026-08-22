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


@pytest.fixture()
def keypair():
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = mandate.public_key_hex_from_private_key(private_key)
    return private_key, public_key_hex


def _issue(private_key, **overrides):
    defaults = dict(
        granted_by=GRANTED_BY,
        issue_ref="owner/repo#206",
        allowed_tools=["cortxt_dispatch"],
        data_class_max="L2",
        budget_usd_max=25.0,
        max_runtime_seconds=3600,
        expires_at="2026-08-22T13:00:00Z",
        scope_text="approved scope text for issue #206",
    )
    defaults.update(overrides)
    return mandate.issue_mandate(private_key=private_key, **defaults)


def _verify(envelope, public_keys, *, tool="cortxt_dispatch", tier=tools.TIER_DISPATCH,
            call_context=None, nonce_store=None, budget_store=None, clock=_clock):
    return mandate.verify_mandate(
        envelope,
        tool=tool,
        tier=tier,
        call_context=call_context or mandate.CallContext(issue_ref="owner/repo#206"),
        public_keys=public_keys,
        nonce_store=nonce_store or FakeNonceStore(),
        budget_store=budget_store or FakeBudgetStore(),
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
    return mandate.MandateVerifier(
        public_keys=public_keys,
        nonce_store=nonce_store or FakeNonceStore(),
        budget_store=budget_store or FakeBudgetStore(),
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
    assert result["engine_id"] == "claude-direct"


def test_ac9_tier0_tool_ignores_a_present_mandate_key_instead_of_erroring():
    result = tools.call_tool(
        "route_engine", {"task_tags": ["general"]}, allow_dispatch=False, allow_credentials=False,
        mandate={"garbage": "not a real envelope"},
    )
    assert result["engine_id"] == "claude-direct"


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


# --- AC 8: cortxt_mcp server-side source never references the private-key
#           credential id or the credential broker. ------------------------

_SERVER_SIDE_MODULES = ["tools.py", "protocol.py", "server.py", "audit.py", "nonce_store.py", "__init__.py"]


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
