from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

from routing.discovery import RuntimeStatus
from runtime import session_state as state

from cli.unified_cli import main


def test_widget_subcommand_is_registered():
    with patch("widget.serve.main") as fake_serve_main:
        fake_serve_main.return_value = None
        exit_code = main(["widget"])
    fake_serve_main.assert_called_once()
    assert exit_code == 0


def test_widget_subcommand_reports_failure_when_serve_raises():
    with patch("widget.serve.main", side_effect=OSError("port already in use")):
        exit_code = main(["widget"])
    assert exit_code == 1


def test_run_runtimes_writes_snapshot(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    fake_statuses = [
        RuntimeStatus(runtime_id="hermes", installed=True, path="/usr/bin/hermes"),
        RuntimeStatus(runtime_id="buzz", installed=False, path=None),
    ]
    with patch("routing.discovery.discover_installed_runtimes", return_value=fake_statuses):
        exit_code = main(["runtimes", "--snapshot", str(snapshot_path)])

    assert exit_code == 0
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "runtimes" in doc
    assert isinstance(doc["runtimes"], list)


def test_run_runtimes_honors_explicit_store_flag(tmp_path):
    """Review finding: _run_runtimes used to hardcode the session store path
    instead of honoring --store like sessions/dispatch/addons do, so a
    non-default --store would silently drop sessions from the snapshot."""
    snapshot_path = tmp_path / "snapshot.json"
    store = tmp_path / "custom-store"
    session = state.create(store, task_id="pre-existing-session")

    with patch("routing.discovery.discover_installed_runtimes", return_value=[]):
        exit_code = main(["runtimes", "--store", str(store), "--snapshot", str(snapshot_path)])

    assert exit_code == 0
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    task_ids = [s["task_id"] for s in doc["sessions"]]
    assert "pre-existing-session" in task_ids


def _fake_encrypt(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


def _fake_decrypt(data: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in data)


def test_run_credentials_store_writes_snapshot_metadata_only(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "snapshot.json"
    store_dir = tmp_path / ".credentials"
    monkeypatch.setattr("sys.stdin", io.StringIO("super-secret-value\n"))

    with patch("security.credential_broker.CredentialBroker.with_dpapi") as fake_with_dpapi:
        from security.credential_broker import CredentialBroker
        fake_with_dpapi.side_effect = lambda d: CredentialBroker(d, encrypt=_fake_encrypt, decrypt=_fake_decrypt)

        exit_code = main([
            "credentials", "store", "--id", "test-cred", "--confirm",
            "--store-dir", str(store_dir), "--snapshot", str(snapshot_path),
        ])

    assert exit_code == 0
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "credentials" in doc
    ids = [c["credential_id"] for c in doc["credentials"]]
    assert "test-cred" in ids
    assert "super-secret-value" not in snapshot_path.read_text(encoding="utf-8")


def test_run_credentials_store_honors_explicit_store_flag(tmp_path, monkeypatch):
    """Review finding: _refresh_credentials_snapshot used to hardcode the
    session store path instead of honoring --store."""
    snapshot_path = tmp_path / "snapshot.json"
    credentials_store_dir = tmp_path / ".credentials"
    sessions_store = tmp_path / "custom-store"
    session = state.create(sessions_store, task_id="pre-existing-session")
    monkeypatch.setattr("sys.stdin", io.StringIO("super-secret-value\n"))

    with patch("security.credential_broker.CredentialBroker.with_dpapi") as fake_with_dpapi:
        from security.credential_broker import CredentialBroker
        fake_with_dpapi.side_effect = lambda d: CredentialBroker(d, encrypt=_fake_encrypt, decrypt=_fake_decrypt)

        exit_code = main([
            "credentials", "store", "--id", "test-cred", "--confirm",
            "--store-dir", str(credentials_store_dir), "--store", str(sessions_store),
            "--snapshot", str(snapshot_path),
        ])

    assert exit_code == 0
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    task_ids = [s["task_id"] for s in doc["sessions"]]
    assert "pre-existing-session" in task_ids


def test_run_addons_submit_creates_session(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    store = tmp_path / ".sessions"

    exit_code = main([
        "addons", "submit", "--candidate-id", "test-addon-1", "--codex-security-passed",
        "--store", str(store), "--snapshot", str(snapshot_path),
    ])

    assert exit_code == 0
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    task_ids = [s["task_id"] for s in doc["sessions"]]
    assert "addon:test-addon-1" in task_ids
