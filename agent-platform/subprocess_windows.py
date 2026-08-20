"""Suppresses the console window Windows otherwise flashes open for every
captured subprocess call (git, hermes, codex, python -c, the cortxt CLI
itself in integration tests) -- harmless on POSIX, where the flag doesn't
exist and there is no window to suppress in the first place.
"""
from __future__ import annotations

import subprocess
import sys


def no_window_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
