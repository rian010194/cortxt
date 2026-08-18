from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from routing.discovery import RuntimeStatus

from cli.unified_cli import main

KNOWN_RUNTIME_IDS = {"hermes", "buzz", "claude-code", "codex", "pi"}


def _fake_encrypt(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


def _fake_decrypt(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


def test_runtimes_lists_all_known_runtimes(capsys):
    fake_statuses = [RuntimeStatus(runtime_id=rid, installed=False, path=None) for rid in KNOWN_RUNTIME_IDS]
    with patch("routing.discovery.discover_installed_runtimes", return_value=fake_statuses):
        exit_code = main(["runtimes"])
    assert exit_code == 0
    out = capsys.readouterr().out
    for rid in KNOWN_RUNTIME_IDS:
        assert rid in out


def test_credentials_store_without_confirm_fails_and_writes_nothing(tmp_path, monkeypatch):
    store_dir = tmp_path / "creds"
    monkeypatch.setattr("sys.stdin", type("_S", (), {"read": staticmethod(lambda: "sk-should-not-land")})())
    exit_code = main(["credentials", "store", "--id", "test-cred", "--store-dir", str(store_dir)])
    assert exit_code == 1
    for path in store_dir.rglob("*") if store_dir.exists() else []:
        if path.is_file():
            assert b"sk-should-not-land" not in path.read_bytes()


def test_credentials_store_without_confirm_is_audited_as_denied(tmp_path, monkeypatch):
    """Review finding: the CLI must not bypass CredentialBroker's own audit
    log by short-circuiting before store() is ever called -- a denied
    attempt through this admin surface must still be traceable."""
    from security.credential_broker import CredentialBroker

    store_dir = tmp_path / "creds"
    monkeypatch.setattr("sys.stdin", type("_S", (), {"read": staticmethod(lambda: "sk-x")})())
    main(["credentials", "store", "--id", "test-cred", "--store-dir", str(store_dir)])

    broker = CredentialBroker(store_dir, encrypt=_fake_encrypt, decrypt=_fake_decrypt)
    records = broker.audit_log()
    assert any(r.action == "store" and r.result == "denied" for r in records)


def test_credentials_store_and_inject_roundtrip_the_real_value(tmp_path, monkeypatch, capsys):
    store_dir = tmp_path / "creds"
    with patch("security.credential_broker.CredentialBroker.with_dpapi") as fake_with_dpapi:
        from security.credential_broker import CredentialBroker
        fake_with_dpapi.side_effect = lambda d: CredentialBroker(d, encrypt=_fake_encrypt, decrypt=_fake_decrypt)

        monkeypatch.setattr("sys.stdin", type("_S", (), {"read": staticmethod(lambda: "sk-real-secret-value")})())
        exit_code = main(["credentials", "store", "--id", "test-cred", "--confirm", "--store-dir", str(store_dir)])
        assert exit_code == 0

        capsys.readouterr()  # discard store's output
        exit_code = main([
            "credentials", "inject", "--id", "test-cred",
            "--runtime", "hermes", "--purpose", "smoke-test",
            "--store-dir", str(store_dir),
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "sk-real-secret-value" in out


def test_credentials_inject_unknown_id_fails(tmp_path):
    store_dir = tmp_path / "creds"
    exit_code = main([
        "credentials", "inject", "--id", "does-not-exist",
        "--runtime", "hermes", "--purpose", "smoke-test",
        "--store-dir", str(store_dir),
    ])
    assert exit_code == 1


def test_credentials_envelope_never_contains_plaintext(tmp_path, monkeypatch, capsys):
    store_dir = tmp_path / "creds"
    with patch("security.credential_broker.CredentialBroker.with_dpapi") as fake_with_dpapi:
        from security.credential_broker import CredentialBroker
        fake_with_dpapi.side_effect = lambda d: CredentialBroker(d, encrypt=_fake_encrypt, decrypt=_fake_decrypt)

        monkeypatch.setattr("sys.stdin", type("_S", (), {"read": staticmethod(lambda: "sk-super-secret-value")})())
        main(["credentials", "store", "--id", "test-cred", "--confirm", "--store-dir", str(store_dir)])
        out = capsys.readouterr().out
        assert "sk-super-secret-value" not in out
