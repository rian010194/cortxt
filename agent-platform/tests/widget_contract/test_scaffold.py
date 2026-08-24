from pathlib import Path

from widget_contract.scaffold import find_missing_operations, write_operation_scaffold


def test_find_missing_operations_returns_unregistered_ids():
    raw = {"data": {"reads": [
        {"id": "a", "operation": "sessions.snapshot.v2"},   # registered
        {"id": "b", "operation": "widgets.custom-thing.v1"},  # not registered
    ]}}
    assert find_missing_operations(raw) == ["widgets.custom-thing.v1"]


def test_find_missing_operations_empty_when_all_registered():
    raw = {"data": {"reads": [{"id": "a", "operation": "sessions.snapshot.v2"}]}}
    assert find_missing_operations(raw) == []


def test_find_missing_operations_handles_missing_reads_key():
    assert find_missing_operations({}) == []


def test_write_operation_scaffold_creates_reviewable_file(tmp_path):
    path = write_operation_scaffold("widgets.custom-thing.v1", tmp_path)
    assert path == tmp_path / "scaffold-widgets.custom-thing.v1.py"
    text = path.read_text(encoding="utf-8")
    assert "widgets.custom-thing.v1" in text
    assert "READ_OPERATIONS" in text
    assert "def read_widgets_custom_thing_v1" in text
