"""`cortxt mcp serve` wiring at the unified_cli level -- acceptance criterion
#1 of issue #184 step 3 ("cortxt mcp serve present on the cortxt CLI").
Actual tool behavior/tiering/audit logic is covered under tests/mcp/; this
only checks the subcommand is registered and forwards its flags correctly,
without ever running the real (blocking, stdio-reading) serve loop.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cli.unified_cli import main


def test_mcp_serve_subcommand_is_registered_and_forwards_defaults():
    with patch("mcp.server.serve") as fake_serve:
        fake_serve.return_value = None
        exit_code = main(["mcp", "serve"])
    assert exit_code == 0
    fake_serve.assert_called_once_with(allow_dispatch=False, allow_credentials=False, store=None)


def test_mcp_serve_forwards_allow_dispatch_and_store(tmp_path):
    store = tmp_path / "sessions"
    with patch("mcp.server.serve") as fake_serve:
        fake_serve.return_value = None
        exit_code = main(["mcp", "serve", "--allow-dispatch", "--store", str(store)])
    assert exit_code == 0
    fake_serve.assert_called_once_with(allow_dispatch=True, allow_credentials=False, store=store)


def test_mcp_serve_forwards_allow_credentials():
    with patch("mcp.server.serve") as fake_serve:
        fake_serve.return_value = None
        main(["mcp", "serve", "--allow-credentials"])
    fake_serve.assert_called_once_with(allow_dispatch=False, allow_credentials=True, store=None)


def test_mcp_serve_reports_failure_when_serve_raises():
    with patch("mcp.server.serve", side_effect=OSError("stdin closed")):
        exit_code = main(["mcp", "serve"])
    assert exit_code == 1
