from __future__ import annotations

import pytest

from security.credential_broker import (
    CredentialBroker,
    CredentialNotFoundError,
    IntegrityError,
    NotOperatorConfirmedError,
)

# Fake encrypt/decrypt standing in for DPAPI in tests -- a trivial reversible
# transform, injected the same way discovery.py injects `which`. Real DPAPI
# is exercised separately in test_dpapi.py, Windows-only.
def _fake_encrypt(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


def _fake_decrypt(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


def _broker(tmp_path, **overrides):
    kwargs = dict(store_dir=tmp_path / "broker", encrypt=_fake_encrypt, decrypt=_fake_decrypt)
    kwargs.update(overrides)
    return CredentialBroker(**kwargs)


# --- write path: operator-gated, always (threat model §3.2.1) ---


def test_store_without_operator_confirmed_is_rejected(tmp_path):
    broker = _broker(tmp_path)
    with pytest.raises(NotOperatorConfirmedError):
        broker.store("hermes-api-key", "sk-real-secret", operator_confirmed=False)


def test_store_with_operator_confirmed_succeeds(tmp_path):
    broker = _broker(tmp_path)
    broker.store("hermes-api-key", "sk-real-secret", operator_confirmed=True)
    value = broker.inject("hermes-api-key", requesting_runtime="hermes", purpose="config injection")
    assert value == "sk-real-secret"


def test_denied_store_leaves_no_trace_of_the_plaintext_on_disk(tmp_path):
    broker = _broker(tmp_path)
    with pytest.raises(NotOperatorConfirmedError):
        broker.store("hermes-api-key", "sk-should-never-land", operator_confirmed=False)
    for path in (tmp_path / "broker").rglob("*"):
        if path.is_file():
            assert b"sk-should-never-land" not in path.read_bytes()


# --- per-record encryption at rest (threat model §3.1.1/3.1.2) ---


def test_stored_record_on_disk_is_not_plaintext(tmp_path):
    broker = _broker(tmp_path)
    broker.store("hermes-api-key", "sk-real-secret", operator_confirmed=True)
    record_files = [p for p in (tmp_path / "broker").rglob("*") if p.is_file() and "audit" not in p.name]
    assert record_files, "expected at least one credential record file"
    for path in record_files:
        assert b"sk-real-secret" not in path.read_bytes()


def test_each_credential_is_encrypted_independently(tmp_path):
    """A container-level key compromise shouldn't be the only isolation --
    two different credentials must produce independently decryptable
    records, not share one blob."""
    broker = _broker(tmp_path)
    broker.store("cred-a", "secret-a", operator_confirmed=True)
    broker.store("cred-b", "secret-b", operator_confirmed=True)
    assert broker.inject("cred-a", requesting_runtime="x", purpose="p") == "secret-a"
    assert broker.inject("cred-b", requesting_runtime="x", purpose="p") == "secret-b"


# --- read path: runtime-bound and purpose-bound (threat model §3.2.2) ---


def test_inject_requires_requesting_runtime_and_purpose(tmp_path):
    broker = _broker(tmp_path)
    broker.store("hermes-api-key", "sk-real-secret", operator_confirmed=True)
    with pytest.raises(TypeError):
        broker.inject("hermes-api-key")  # missing required kwargs


def test_inject_unknown_credential_id_raises_not_found(tmp_path):
    broker = _broker(tmp_path)
    with pytest.raises(CredentialNotFoundError):
        broker.inject("does-not-exist", requesting_runtime="hermes", purpose="x")


# --- no credential enumeration (threat model §3.2.3) ---


def test_broker_exposes_no_list_all_method(tmp_path):
    broker = _broker(tmp_path)
    public_methods = {name for name in dir(broker) if not name.startswith("_") and callable(getattr(broker, name))}
    forbidden = {"list", "list_ids", "list_credentials", "enumerate", "get_all", "all_credentials"}
    assert not (public_methods & forbidden)


# --- audit log (threat model §3.2.5) ---


def test_store_and_inject_are_both_audited_without_plaintext(tmp_path):
    broker = _broker(tmp_path)
    broker.store("hermes-api-key", "sk-real-secret", operator_confirmed=True)
    broker.inject("hermes-api-key", requesting_runtime="hermes", purpose="config injection")

    records = broker.audit_log()
    actions = [r.action for r in records]
    assert "store" in actions
    assert "inject" in actions

    inject_record = next(r for r in records if r.action == "inject")
    assert inject_record.credential_id == "hermes-api-key"
    assert inject_record.requesting_runtime == "hermes"
    assert inject_record.purpose == "config injection"
    assert inject_record.result == "ok"

    for record in records:
        for field_value in (record.action, record.credential_id, record.requesting_runtime, record.purpose, record.result):
            if field_value:
                assert "sk-real-secret" not in field_value


def test_denied_store_is_audited_as_denied(tmp_path):
    broker = _broker(tmp_path)
    with pytest.raises(NotOperatorConfirmedError):
        broker.store("hermes-api-key", "sk-x", operator_confirmed=False)
    records = broker.audit_log()
    denied = [r for r in records if r.action == "store" and r.result == "denied"]
    assert len(denied) == 1


# --- fail closed on integrity doubt (threat model §3.3.2) ---


def test_inject_fails_closed_when_decrypt_raises(tmp_path):
    def _broken_decrypt(_data: bytes) -> bytes:
        raise ValueError("key material no longer decrypts cleanly")

    broker = _broker(tmp_path)
    broker.store("hermes-api-key", "sk-real-secret", operator_confirmed=True)

    broken_broker = _broker(tmp_path, decrypt=_broken_decrypt)
    with pytest.raises(IntegrityError):
        broken_broker.inject("hermes-api-key", requesting_runtime="hermes", purpose="x")

    records = broken_broker.audit_log()
    assert any(r.action == "inject" and r.result == "error" for r in records)


def test_inject_fails_closed_on_corrupted_record_file(tmp_path):
    broker = _broker(tmp_path)
    broker.store("hermes-api-key", "sk-real-secret", operator_confirmed=True)

    record_files = [p for p in (tmp_path / "broker").rglob("*") if p.is_file() and "audit" not in p.name]
    record_files[0].write_bytes(b"not a valid encrypted record")

    with pytest.raises(IntegrityError):
        broker.inject("hermes-api-key", requesting_runtime="hermes", purpose="x")
