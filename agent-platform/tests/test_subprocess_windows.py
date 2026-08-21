from __future__ import annotations

import subprocess
import sys

import pytest

import subprocess_windows


@pytest.mark.skipif(sys.platform != "win32", reason="CREATE_NO_WINDOW is Windows-only")
def test_no_window_kwargs_sets_creationflags_on_windows(monkeypatch):
    monkeypatch.setattr(subprocess_windows.sys, "platform", "win32")
    assert subprocess_windows.no_window_kwargs() == {"creationflags": subprocess.CREATE_NO_WINDOW}


def test_no_window_kwargs_is_empty_on_posix(monkeypatch):
    monkeypatch.setattr(subprocess_windows.sys, "platform", "linux")
    assert subprocess_windows.no_window_kwargs() == {}
