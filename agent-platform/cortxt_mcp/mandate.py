"""Signed, nonce-bound mandate envelope for MCP Tier-1+ tool calls (ADR-032).

Two halves, deliberately asymmetric in trust:

- Issuing (`issue_mandate`, `store_signing_key_in_broker`): operator/CLI-side
  only. Generates or accepts an Ed25519 keypair, builds and signs an
  envelope. Never called from cortxt_mcp's server-side runtime path
  (`tools.py`, `protocol.py`, `server.py`, `audit.py`, `nonce_store.py`) --
  see `tests/cortxt_mcp/test_mandate.py`'s AC 8 standing test.
- Verifying (`verify_mandate`, `MandateVerifier`): server-side, pure. Takes
  the envelope dict, the call's tool/tier/context, and injected
  nonce/budget stores + clock; returns a decision. No signing key is ever
  present on this side -- the server can verify, never forge.

Signing uses Ed25519 (`cryptography.hazmat.primitives.asymmetric.ed25519`)
over the envelope's canonical JSON serialization (`runtime.session_state
.canonical_json` -- sorted keys, fixed separators -- reused as-is, not
reimplemented), with the `signature` field itself excluded from what is
signed.
"""
from __future__ import annotations

import base64
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SCHEMA_VERSION = 1
_KNOWN_SCHEMA_VERSIONS = {1}

_REQUIRED_FIELDS = frozenset({
    "schema_version", "mandate_id", "granted_by", "issue_ref", "allowed_tools",
    "data_class_max", "budget_usd_max", "max_runtime_seconds", "expires_at",
    "nonce", "scope_fingerprint", "signature",
})

_DATA_CLASS_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}

# Reason codes -- returned in MandateDecision.reason. "accepted" is the only
# non-rejection value; every other value is a fail-closed rejection reason.
REASON_ACCEPTED = "accepted"
REASON_MANDATE_MISSING = "mandate_missing"
REASON_MALFORMED_ENVELOPE = "malformed_envelope"
REASON_UNKNOWN_SCHEMA_VERSION = "unknown_schema_version"
REASON_UNKNOWN_GRANTED_BY = "unknown_granted_by"
REASON_MISSING_SIGNATURE = "missing_signature"
REASON_INVALID_SIGNATURE = "invalid_signature"
REASON_NONCE_REPLAYED = "nonce_replayed"
REASON_EXPIRES_AT_INVALID = "expires_at_invalid"
REASON_EXPIRED = "expired"
REASON_TOOL_NOT_ALLOWED = "tool_not_allowed"
REASON_INVALID_DATA_CLASS = "invalid_data_class"
REASON_DATA_CLASS_EXCEEDED = "data_class_exceeded"
REASON_BUDGET_EXCEEDED = "budget_exceeded"
REASON_ISSUE_REF_MISMATCH = "issue_ref_mismatch"
REASON_SCOPE_FINGERPRINT_MISMATCH = "scope_fingerprint_mismatch"

# Private-key credential id, used ONLY by the issuing-side helper below.
# A standing test (test_mandate.py, AC 8) asserts this identifier never
# appears in cortxt_mcp's server-side source files.
MANDATE_SIGNING_KEY_CREDENTIAL_ID = "mcp-mandate-signing-key"


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def compute_scope_fingerprint(scope_text: str) -> str:
    import hashlib

    return hashlib.sha256(scope_text.encode("utf-8")).hexdigest()


def _canonical_signing_bytes(envelope: Mapping[str, Any]) -> bytes:
    from runtime.session_state import canonical_json

    body = {key: value for key, value in envelope.items() if key != "signature"}
    return canonical_json(body)


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("expires_at must be a non-empty string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("expires_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class MandateDecision:
    """Result of `verify_mandate`. `accepted` is the single source of
    truth; `reason` is `REASON_ACCEPTED` on success or one of the
    `REASON_*` rejection codes above. `mandate_id` is carried through even
    on rejection when it could be read from the envelope, so the ledger
    can correlate a denial with the mandate that was attempted."""

    accepted: bool
    reason: str
    mandate_id: str | None = None


@dataclass(frozen=True)
class CallContext:
    """Everything about the specific call being verified that the
    envelope itself doesn't carry. `issue_ref` is compared against the
    envelope's own `issue_ref` (empty string skips the check -- used by
    callers that don't yet have a durable issue reference to bind to).
    `expected_scope_fingerprint`, if given, is compared directly to the
    envelope's `scope_fingerprint`; otherwise, if `scope_text` is given,
    its fingerprint is computed and compared. If neither is given, the
    scope-fingerprint check is skipped."""

    issue_ref: str = ""
    data_class: str = "L0"
    estimated_cost_usd: float = 0.0
    scope_text: str | None = None
    expected_scope_fingerprint: str | None = None


class _NullNonceStore:
    """Used only by `MandateVerifier.unconfigured()`. Never reached in
    practice -- an unconfigured verifier has no registered public keys, so
    every envelope is rejected before the nonce check runs -- but returns
    False (fail closed) if it ever is."""

    def check_and_consume(self, nonce: str) -> bool:  # noqa: ARG002
        return False


class _NullBudgetStore:
    def record_and_check(self, mandate_id: str | None, cost: float, cap: float) -> bool:  # noqa: ARG002
        return False


def verify_mandate(
    envelope: dict[str, Any] | None,
    *,
    tool: str,
    tier: int,
    call_context: CallContext,
    public_keys: Mapping[str, str],
    nonce_store: Any,
    budget_store: Any,
    clock: Callable[[], datetime] = _default_clock,
) -> MandateDecision:
    """Pure verification of one mandate envelope for one tool call.

    No I/O of its own: `nonce_store` (an object with
    `check_and_consume(nonce) -> bool`) and `budget_store` (an object with
    `record_and_check(mandate_id, cost, cap) -> bool`) are injected, as is
    `clock`. `public_keys` maps `granted_by` -> a hex-encoded Ed25519
    public key (32 raw bytes). Fails closed on every malformed or missing
    input -- any exception encountered while interpreting the envelope
    itself is treated as a rejection, never propagated.

    Checks run in this order (adversarial-review-required order, so an
    attacker cannot use a later check to probe an earlier one): schema
    version -> signature -> nonce -> expiry -> allowed_tools -> data class
    -> budget -> issue_ref -> scope_fingerprint. The nonce and the budget
    are both consumed/debited as soon as their check runs, regardless of
    whether a later check goes on to reject the call -- this closes the
    replay-via-different-tool-name and the parallel-calls-under-cap bypass
    classes flagged in the adversarial review (HIGH-1, MED-2).
    """
    if envelope is None:
        return MandateDecision(False, REASON_MANDATE_MISSING, None)
    if not isinstance(envelope, dict) or set(envelope) != _REQUIRED_FIELDS:
        return MandateDecision(False, REASON_MALFORMED_ENVELOPE, None)

    mandate_id_raw = envelope.get("mandate_id")
    mandate_id = mandate_id_raw if isinstance(mandate_id_raw, str) and mandate_id_raw else None

    if envelope.get("schema_version") not in _KNOWN_SCHEMA_VERSIONS:
        return MandateDecision(False, REASON_UNKNOWN_SCHEMA_VERSION, mandate_id)

    granted_by = envelope.get("granted_by")
    if not isinstance(granted_by, str) or granted_by not in public_keys:
        return MandateDecision(False, REASON_UNKNOWN_GRANTED_BY, mandate_id)

    signature_b64 = envelope.get("signature")
    if not isinstance(signature_b64, str) or not signature_b64:
        return MandateDecision(False, REASON_MISSING_SIGNATURE, mandate_id)

    try:
        public_key_bytes = bytes.fromhex(public_keys[granted_by])
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        signature_bytes = base64.b64decode(signature_b64, validate=True)
        public_key.verify(signature_bytes, _canonical_signing_bytes(envelope))
    except Exception:
        return MandateDecision(False, REASON_INVALID_SIGNATURE, mandate_id)

    nonce = envelope.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return MandateDecision(False, REASON_MALFORMED_ENVELOPE, mandate_id)
    try:
        nonce_ok = bool(nonce_store.check_and_consume(nonce))
    except Exception:
        nonce_ok = False
    if not nonce_ok:
        return MandateDecision(False, REASON_NONCE_REPLAYED, mandate_id)

    try:
        expires_at = _parse_utc(envelope.get("expires_at"))
    except Exception:
        return MandateDecision(False, REASON_EXPIRES_AT_INVALID, mandate_id)
    if expires_at <= clock():
        return MandateDecision(False, REASON_EXPIRED, mandate_id)

    allowed_tools = envelope.get("allowed_tools")
    if not isinstance(allowed_tools, list) or tool not in allowed_tools:
        return MandateDecision(False, REASON_TOOL_NOT_ALLOWED, mandate_id)

    call_rank = _DATA_CLASS_ORDER.get(call_context.data_class)
    max_rank = _DATA_CLASS_ORDER.get(envelope.get("data_class_max"))
    if call_rank is None or max_rank is None:
        return MandateDecision(False, REASON_INVALID_DATA_CLASS, mandate_id)
    if call_rank > max_rank:
        return MandateDecision(False, REASON_DATA_CLASS_EXCEEDED, mandate_id)

    try:
        cap = float(envelope.get("budget_usd_max"))
    except (TypeError, ValueError):
        return MandateDecision(False, REASON_MALFORMED_ENVELOPE, mandate_id)
    try:
        within_budget = bool(
            budget_store.record_and_check(mandate_id, call_context.estimated_cost_usd, cap)
        )
    except Exception:
        within_budget = False
    if not within_budget:
        return MandateDecision(False, REASON_BUDGET_EXCEEDED, mandate_id)

    if call_context.issue_ref and envelope.get("issue_ref") != call_context.issue_ref:
        return MandateDecision(False, REASON_ISSUE_REF_MISMATCH, mandate_id)

    expected_fingerprint = call_context.expected_scope_fingerprint
    if expected_fingerprint is None and call_context.scope_text is not None:
        expected_fingerprint = compute_scope_fingerprint(call_context.scope_text)
    if expected_fingerprint is not None and envelope.get("scope_fingerprint") != expected_fingerprint:
        return MandateDecision(False, REASON_SCOPE_FINGERPRINT_MISMATCH, mandate_id)

    return MandateDecision(True, REASON_ACCEPTED, mandate_id)


@dataclass
class MandateVerifier:
    """Convenience bundle of `verify_mandate`'s injected dependencies, so
    `cortxt_mcp.tools.call_tool` has one object to thread through instead
    of four separate parameters. Still just plumbing -- `verify()` calls
    the pure `verify_mandate` function above with nothing hidden."""

    public_keys: dict[str, str]
    nonce_store: Any
    budget_store: Any
    clock: Callable[[], datetime] = field(default=_default_clock)

    @classmethod
    def unconfigured(cls) -> "MandateVerifier":
        """Fail-closed default used when no server-level mandate
        configuration was supplied: no public keys are registered, so
        every envelope is rejected (REASON_UNKNOWN_GRANTED_BY), and a
        missing envelope is rejected too (REASON_MANDATE_MISSING) --
        matches AC 1's 'no valid config -> no Tier-1 execution' posture."""
        return cls(public_keys={}, nonce_store=_NullNonceStore(), budget_store=_NullBudgetStore())

    def verify(self, envelope: dict[str, Any] | None, *, tool: str, tier: int, call_context: CallContext) -> MandateDecision:
        return verify_mandate(
            envelope,
            tool=tool,
            tier=tier,
            call_context=call_context,
            public_keys=self.public_keys,
            nonce_store=self.nonce_store,
            budget_store=self.budget_store,
            clock=self.clock,
        )


# --- Issuing side: operator/CLI-only. Never imported by tools.py /
# protocol.py / server.py / audit.py / nonce_store.py. ------------------

@dataclass(frozen=True)
class IssuedMandate:
    envelope: dict[str, Any]
    private_key_pem: bytes
    public_key_hex: str


def issue_mandate(
    *,
    granted_by: str,
    issue_ref: str,
    allowed_tools: list[str],
    data_class_max: str,
    budget_usd_max: float,
    max_runtime_seconds: int,
    expires_at: str,
    scope_text: str,
    private_key: Ed25519PrivateKey | None = None,
    nonce: str | None = None,
    mandate_id: str | None = None,
    schema_version: int = SCHEMA_VERSION,
) -> IssuedMandate:
    """Operator/CLI-side issuing. Builds and signs one mandate envelope.

    `private_key` may be injected (e.g. a key already held by the
    operator, loaded from the credential broker); if omitted, a fresh
    Ed25519 keypair is generated. This function never persists anything
    and never talks to the credential broker itself -- see
    `store_signing_key_in_broker` for that, kept as an explicit separate
    step so a caller who only wants to sign with an already-issued key
    never has to touch broker code at all.
    """
    from runtime.session_state import canonical_json

    key = private_key or Ed25519PrivateKey.generate()
    envelope_without_signature = {
        "schema_version": schema_version,
        "mandate_id": mandate_id or str(uuid.uuid4()),
        "granted_by": granted_by,
        "issue_ref": issue_ref,
        "allowed_tools": list(allowed_tools),
        "data_class_max": data_class_max,
        "budget_usd_max": float(budget_usd_max),
        "max_runtime_seconds": int(max_runtime_seconds),
        "expires_at": expires_at,
        "nonce": nonce or secrets.token_hex(16),
        "scope_fingerprint": compute_scope_fingerprint(scope_text),
    }
    signature = key.sign(canonical_json(envelope_without_signature))
    envelope = {
        **envelope_without_signature,
        "signature": base64.b64encode(signature).decode("ascii"),
    }

    from cryptography.hazmat.primitives import serialization

    private_key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key_hex = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return IssuedMandate(envelope=envelope, private_key_pem=private_key_pem, public_key_hex=public_key_hex)


def store_signing_key_in_broker(private_key_pem: bytes, *, broker: Any) -> None:
    """Operator-only: persist the mandate-signing private key via the
    existing `security.credential_broker.CredentialBroker` (+ `dpapi.py`
    for encryption-at-rest), per ADR-029's credential-isolation principle.
    `broker` is a `CredentialBroker` instance (typically
    `CredentialBroker.with_dpapi(store_dir)`); this function is the only
    place `MANDATE_SIGNING_KEY_CREDENTIAL_ID` is used to *write* a
    credential. Never called from cortxt_mcp's server-side runtime path.
    """
    broker.store(
        MANDATE_SIGNING_KEY_CREDENTIAL_ID,
        private_key_pem.decode("ascii"),
        operator_confirmed=True,
    )


def load_signing_key_from_broker(*, broker: Any, purpose: str = "issue_mandate") -> Ed25519PrivateKey:
    """Operator-only: load the mandate-signing private key back out of the
    broker for use by `issue_mandate(private_key=...)`. Never called from
    cortxt_mcp's server-side runtime path."""
    from cryptography.hazmat.primitives import serialization

    pem = broker.inject(
        MANDATE_SIGNING_KEY_CREDENTIAL_ID,
        requesting_runtime="mandate-cli",
        purpose=purpose,
    )
    return serialization.load_pem_private_key(pem.encode("ascii"), password=None)


def public_key_hex_from_private_key(private_key: Ed25519PrivateKey) -> str:
    from cryptography.hazmat.primitives import serialization

    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
