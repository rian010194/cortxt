from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

from routing.discovery import RuntimeStatus

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


def test_run_credentials_store_writes_snapshot_metadata_only(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "snapshot.json"
    store_dir = tmp_path / ".credentials"
    monkeypatch.setattr("sys.stdin", io.StringIO("super-secret-value\n"))

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
