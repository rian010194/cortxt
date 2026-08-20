from __future__ import annotations

import subprocess

import subprocess_windows


def test_no_window_kwargs_sets_creationflags_on_windows(monkeypatch):
    monkeypatch.setattr(subprocess_windows.sys, "platform", "win32")
    assert subprocess_windows.no_window_kwargs() == {"creationflags": subprocess.CREATE_NO_WINDOW}


def test_no_window_kwargs_is_empty_on_posix(monkeypatch):
    monkeypatch.setattr(subprocess_windows.sys, "platform", "linux")
    assert subprocess_windows.no_window_kwargs() == {}
