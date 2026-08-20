from __future__ import annotations

from cli import color


class _FakeStream:
    def __init__(self, is_tty: bool):
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_supports_color_true_for_a_real_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert color.supports_color(_FakeStream(True)) is True


def test_supports_color_false_for_a_non_tty_stream(monkeypatch):
    """Piping to a file or capturing subprocess output (capture_output=True)
    gives a non-tty stream -- must render plain text so existing parsers and
    the test suite aren't broken by escape codes."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert color.supports_color(_FakeStream(False)) is False


def test_supports_color_false_when_no_color_env_set_even_on_a_tty(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert color.supports_color(_FakeStream(True)) is False


def test_supports_color_respects_empty_string_no_color_too(monkeypatch):
    """NO_COLOR convention: presence of the variable disables color,
    regardless of its value (including empty string)."""
    monkeypatch.setenv("NO_COLOR", "")
    assert color.supports_color(_FakeStream(True)) is False


def test_colorize_wraps_text_in_ansi_codes_when_enabled():
    result = color.colorize("succeeded", "succeeded", enabled=True)
    assert result.startswith("\033[")
    assert result.endswith(color.RESET)
    assert "succeeded" in result


def test_colorize_returns_plain_text_when_disabled():
    assert color.colorize("succeeded", "succeeded", enabled=False) == "succeeded"


def test_colorize_falls_back_to_a_default_color_for_unknown_status():
    result = color.colorize("mystery", "some-unmapped-status", enabled=True)
    assert result.startswith("\033[")
    assert "mystery" in result


def test_status_color_map_covers_terminal_and_transient_statuses():
    # Locks in the palette extracted from prototype/widget-cli-v02's
    # Campbell (Windows Terminal default theme) mapping: green=done/ok,
    # red=failed/error, yellow=blocked/warn, cyan=running, grey=stale/idle.
    assert color.STATUS_COLOR["succeeded"] == color.GREEN
    assert color.STATUS_COLOR["failed"] == color.RED
    assert color.STATUS_COLOR["timed_out"] == color.RED
    assert color.STATUS_COLOR["blocked"] == color.YELLOW
    assert color.STATUS_COLOR["running"] == color.CYAN
    assert color.STATUS_COLOR["stale"] == color.GREY
    assert color.STATUS_COLOR["idle"] == color.GREY
