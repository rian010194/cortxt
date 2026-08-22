"""`cortxt mandate issue/inspect` wiring at the unified_cli level (issue
#281, ADR-032 Open Question: operator issuance UX). The envelope schema,
signature path, and adversarial cases are covered under tests/cortxt_mcp/
test_mandate.py; these tests check the CLI surface: registration, argument
forwarding, the operator-confirmed key persistence gate, and the inspect
verdict path -- without ever touching a real DPAPI credential store.
"""
from __future__ import annotations

import json
from pathlib import Path

from cli.unified_cli import main
from cortxt_mcp.mandate import (
    CallContext,
    MandateVerifier,
    issue_mandate,
    public_key_hex_from_private_key,
)
from cortxt_mcp.revocation_store import NullKeyRevocationStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from security.credential_broker import CredentialNotFoundError


class _FakeBroker:
    """Minimal CredentialBroker stand-in: stores one PEM per credential id,
    raises CredentialNotFoundError for unknown ids -- enough to exercise
    the CLI's load-or-generate-and-persist gate without DPAPI."""

    def __init__(self) -> None:
        self.stored: dict[str, str] = {}
        self.store_calls: list[tuple[str, bool]] = []

    def inject(self, credential_id: str, *, requesting_runtime: str, purpose: str) -> str:
        if credential_id not in self.stored:
            raise CredentialNotFoundError(credential_id)
        return self.stored[credential_id]

    def store(self, credential_id: str, plaintext: str, *, operator_confirmed: bool) -> None:
        self.stored[credential_id] = plaintext
        self.store_calls.append((credential_id, operator_confirmed))


def _first_json(text: str) -> dict:
    """The CLI prints the handler payload first, then the ResultEnvelope;
    return the first complete JSON object on stdout."""
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text.lstrip())
    return obj


def _issue_args(tmp_path: Path, **overrides) -> list[str]:
    args = [
        "mandate", "issue",
        "--granted-by", "op-test",
        "--kid", "k1",
        "--issue-ref", "owner/repo#1",
        "--allowed-tools", "cortxt_daemon_status",
        "--data-class-max", "L2",
        "--budget-usd-max", "25",
        "--max-runtime-seconds", "3600",
        "--expires-at", "2099-01-01T00:00:00Z",
        "--scope-text", "test scope",
        "--max-envelope-ttl-seconds", "10000000000",
        "--store-dir", str(tmp_path / ".credentials"),
    ]
    flags = {"confirm"}
    for key, value in overrides.items():
        flag = f"--{key.replace('_', '-')}"
        if key in flags:
            if value:
                args.append(flag)
            continue
        if value is None:
            args = [a for a in args if not a.startswith(flag)]
        elif flag in args:
            args[args.index(flag) + 1] = str(value)
        else:
            args += [flag, str(value)]
    return args


def test_mandate_issue_registered_and_issues_signed_envelope(tmp_path, capsys, monkeypatch):
    broker = _FakeBroker()
    monkeypatch.setattr("security.credential_broker.CredentialBroker.with_dpapi",
                        lambda store_dir: broker)
    exit_code = main(_issue_args(tmp_path, confirm=True))
    assert exit_code == 0
    out = capsys.readouterr().out
    envelope = _first_json(out)
    for field in ("schema_version", "mandate_id", "granted_by", "kid", "issue_ref",
                  "allowed_tools", "data_class_max", "budget_usd_max", "max_runtime_seconds",
                  "expires_at", "nonce", "scope_fingerprint", "signature"):
        assert field in envelope, f"envelope missing {field}"
    assert envelope["issue_ref"] == "owner/repo#1"
    assert envelope["allowed_tools"] == ["cortxt_daemon_status"]
    assert "PRIVATE KEY" not in out.upper()
    # The fresh keypair must have been persisted (operator-confirmed write).
    assert broker.store_calls and broker.store_calls[0][1] is True


def test_mandate_issue_requires_confirm_for_new_key(tmp_path, capsys, monkeypatch):
    broker = _FakeBroker()
    monkeypatch.setattr("security.credential_broker.CredentialBroker.with_dpapi",
                        lambda store_dir: broker)
    exit_code = main(_issue_args(tmp_path))
    assert exit_code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert result["error"]["category"] == "not_confirmed"
    assert broker.store_calls == []


def test_mandate_issue_loads_existing_key_idempotently(tmp_path, capsys, monkeypatch):
    broker = _FakeBroker()
    monkeypatch.setattr("security.credential_broker.CredentialBroker.with_dpapi",
                        lambda store_dir: broker)
    # First run persists the keypair (--confirm).
    assert main(_issue_args(tmp_path, confirm=True)) == 0
    first = _first_json(capsys.readouterr().out)
    # Second run without --confirm must load the existing key, not fail.
    assert main(_issue_args(tmp_path)) == 0
    second = _first_json(capsys.readouterr().out)
    # Same keypair -> the envelopes verify against the same public key.
    assert first["scope_fingerprint"] == second["scope_fingerprint"]
    assert first["granted_by"] == second["granted_by"]


def test_mandate_issue_rejects_invalid_inputs(tmp_path, capsys, monkeypatch):
    broker = _FakeBroker()
    monkeypatch.setattr("security.credential_broker.CredentialBroker.with_dpapi",
                        lambda store_dir: broker)
    exit_code = main(_issue_args(tmp_path, confirm=True, budget_usd_max="-5"))
    assert exit_code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert result["error"]["category"] == "invalid_args"


def test_mandate_inspect_valid_and_wrong_key(tmp_path, capsys):
    key = Ed25519PrivateKey.generate()
    public_key_hex = public_key_hex_from_private_key(key)
    issued = issue_mandate(
        private_key=key,
        granted_by="op-test",
        kid="k1",
        public_keys={"op-test": {"k1": public_key_hex}},
        issue_ref="owner/repo#1",
        allowed_tools=["cortxt_daemon_status"],
        data_class_max="L2",
        budget_usd_max=25.0,
        max_runtime_seconds=3600,
        expires_at="2099-01-01T00:00:00Z",
        scope_text="test scope", max_envelope_ttl_seconds=10**10,)
    env_path = tmp_path / "envelope.json"
    env_path.write_text(json.dumps(issued.envelope), encoding="utf-8")

    exit_code = main(["mandate", "inspect", "--envelope", str(env_path),
                      "--public-key", public_key_hex])
    assert exit_code == 0
    verdict = _first_json(capsys.readouterr().out)
    assert verdict["accepted"] is True

    wrong_hex = public_key_hex_from_private_key(Ed25519PrivateKey.generate())
    exit_code = main(["mandate", "inspect", "--envelope", str(env_path),
                      "--public-key", wrong_hex])
    assert exit_code == 0
    verdict = _first_json(capsys.readouterr().out)
    assert verdict["accepted"] is False
    assert verdict["reason"] == "invalid_signature"


def test_mandate_inspect_tampered_envelope_rejected(tmp_path, capsys):
    key = Ed25519PrivateKey.generate()
    public_key_hex = public_key_hex_from_private_key(key)
    issued = issue_mandate(
        private_key=key,
        granted_by="op-test",
        kid="k1",
        public_keys={"op-test": {"k1": public_key_hex}},
        issue_ref="owner/repo#1",
        allowed_tools=["cortxt_daemon_status"],
        data_class_max="L2",
        budget_usd_max=25.0,
        max_runtime_seconds=3600,
        expires_at="2099-01-01T00:00:00Z",
        scope_text="test scope", max_envelope_ttl_seconds=10**10,)
    tampered = dict(issued.envelope)
    tampered["budget_usd_max"] = 9999.0
    env_path = tmp_path / "tampered.json"
    env_path.write_text(json.dumps(tampered), encoding="utf-8")

    exit_code = main(["mandate", "inspect", "--envelope", str(env_path),
                      "--public-key", public_key_hex])
    assert exit_code == 0
    verdict = _first_json(capsys.readouterr().out)
    assert verdict["accepted"] is False
    assert verdict["reason"] == "invalid_signature"



