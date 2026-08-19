from pathlib import Path

from daemon.stop_flag import clear_stop, is_stop_requested, request_stop


def test_not_requested_by_default(tmp_path: Path):
    assert not is_stop_requested(tmp_path)


def test_request_then_detected(tmp_path: Path):
    request_stop(tmp_path)
    assert is_stop_requested(tmp_path)


def test_clear_removes_request(tmp_path: Path):
    request_stop(tmp_path)
    clear_stop(tmp_path)
    assert not is_stop_requested(tmp_path)


def test_clear_when_not_requested_is_noop(tmp_path: Path):
    clear_stop(tmp_path)  # must not raise
    assert not is_stop_requested(tmp_path)
