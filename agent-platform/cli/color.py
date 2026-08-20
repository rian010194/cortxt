"""ANSI color helpers shared by `cortxt status` and `cortxt pipeline`.

Palette extracted from the operator-approved `prototype/widget-cli-v02`
mockup (`prototype-cli-v02.py`, variant A/B): Windows Terminal's actual
default "Campbell" color scheme, not an invented palette. That prototype
was throwaway by design ("capture the winner, then delete this file") --
this module is the capture.

Detection follows the two conventions the task calls out:
- `NO_COLOR` (https://no-color.org/): presence of the env var (any value,
  including empty string) disables color, full stop.
- tty detection: color only when stdout is a real terminal. Piping to a
  file, or `subprocess.run(capture_output=True)` (what the test suite and
  other tooling use to read this CLI's output as plain text), gives a
  non-tty stream, so color is skipped automatically -- callers don't need
  to remember to pass anything.
"""
from __future__ import annotations

import os
import sys
from typing import Any

RESET = "\033[0m"
BOLD = "\033[1m"


def _fg(hexcode: str) -> str:
    r, g, b = int(hexcode[0:2], 16), int(hexcode[2:4], 16), int(hexcode[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


# Windows Terminal "Campbell" scheme (the actual default dark theme).
WHITE = _fg("F2F2F2")
GREY = _fg("767676")
BLUE = _fg("3B78FF")
GREEN = _fg("16C60C")
YELLOW = _fg("C19C00")
RED = _fg("C50F1F")
CYAN = _fg("3A96DD")

# Terminal-good statuses -> green. Actively bad -> red. In-flight -> cyan.
# Needs-attention/soft-warning -> yellow. Idle/inert -> grey.
STATUS_COLOR: dict[str, str] = {
    "succeeded": GREEN,
    "ok": GREEN,
    "done": GREEN,
    "running": CYAN,
    "info": CYAN,
    "working": CYAN,
    "blocked": YELLOW,
    "warn": YELLOW,
    "attention": YELLOW,
    "waiting": GREY,
    "stale": GREY,
    "idle": GREY,
    "failed": RED,
    "timed_out": RED,
    "error": RED,
}


def supports_color(stream: Any = None) -> bool:
    """True when `stream` (default: sys.stdout) is a real terminal and
    NO_COLOR isn't set. NO_COLOR wins over everything else."""
    if "NO_COLOR" in os.environ:
        return False
    stream = stream if stream is not None else sys.stdout
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def colorize(text: str, status: str, *, enabled: bool | None = None) -> str:
    """Wrap `text` in the ANSI color mapped to `status`.

    `enabled=None` auto-detects via `supports_color()`. An unmapped status
    still gets colored (falls back to WHITE) rather than silently staying
    plain -- callers that pass a status this map doesn't know about yet get
    a visible (if unstyled) result, not silent color loss.
    """
    if enabled is None:
        enabled = supports_color()
    if not enabled:
        return text
    return f"{STATUS_COLOR.get(status, WHITE)}{text}{RESET}"
