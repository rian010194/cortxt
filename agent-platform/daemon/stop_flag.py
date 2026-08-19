"""Emergency stop via a flag file the loop polls each iteration (spec:
Windows is the primary runtime platform -- POSIX signals are not a reliable
cross-process mechanism there, so a polled file is used instead).
"""
from __future__ import annotations

from pathlib import Path

_STOP_FILENAME = "STOP"


def request_stop(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / _STOP_FILENAME).touch()


def is_stop_requested(state_dir: Path) -> bool:
    return (state_dir / _STOP_FILENAME).exists()


def clear_stop(state_dir: Path) -> None:
    (state_dir / _STOP_FILENAME).unlink(missing_ok=True)
