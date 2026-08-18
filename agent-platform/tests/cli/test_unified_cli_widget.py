from __future__ import annotations

from unittest.mock import patch

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
