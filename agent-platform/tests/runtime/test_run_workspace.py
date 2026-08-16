"""run_workspace: disposable copy-in workspace, pristine baseline, guaranteed cleanup.

The agent never gets a handle on the repository — containment is structural
first and policy second (design spec decision 4, part 1).
"""
from __future__ import annotations

from pathlib import Path
import pytest
from runtime.coding.run_workspace import RunWorkspace, RunWorkspaceError, run_workspace


def _source(tmp_path: Path) -> Path:
    src = tmp_path / "fixture-workspace"
    src.mkdir()
    (src / "ranges.py").write_text("def sum_to(n):\n    return 0\n", encoding="utf-8")
    return src


def test_creates_work_and_baseline_copies(tmp_path):
    src = _source(tmp_path)
    with run_workspace(src) as ws:
        assert isinstance(ws, RunWorkspace)
        assert ws.work.is_dir() and ws.baseline.is_dir()
        assert (ws.work / "ranges.py").read_text(encoding="utf-8") == \
               (src / "ranges.py").read_text(encoding="utf-8")
        assert (ws.baseline / "ranges.py").read_text(encoding="utf-8") == \
               (src / "ranges.py").read_text(encoding="utf-8")


def test_work_and_baseline_are_independent_copies(tmp_path):
    src = _source(tmp_path)
    with run_workspace(src) as ws:
        (ws.work / "ranges.py").write_text("MUTATED\n", encoding="utf-8")
        assert (ws.baseline / "ranges.py").read_text(encoding="utf-8") != "MUTATED\n"
        assert (src / "ranges.py").read_text(encoding="utf-8") != "MUTATED\n"


def test_root_is_removed_on_normal_exit(tmp_path):
    src = _source(tmp_path)
    with run_workspace(src) as ws:
        root = ws.root
        assert root.exists()
    assert not root.exists()


def test_root_is_removed_when_the_body_raises(tmp_path):
    src = _source(tmp_path)
    captured: list[Path] = []
    with pytest.raises(ZeroDivisionError):
        with run_workspace(src) as ws:
            captured.append(ws.root)
            raise ZeroDivisionError("simulated mid-run crash")
    assert not captured[0].exists()


def test_workspace_root_is_outside_the_source_tree(tmp_path):
    src = _source(tmp_path)
    with run_workspace(src) as ws:
        assert src.resolve() not in ws.root.resolve().parents
        assert ws.root.resolve() != src.resolve()


def test_refuses_a_missing_source(tmp_path):
    with pytest.raises(RunWorkspaceError) as exc:
        with run_workspace(tmp_path / "nope"):
            pass
    assert exc.value.reason == "source_missing"


def test_refuses_an_empty_source(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RunWorkspaceError) as exc:
        with run_workspace(empty):
            pass
    assert exc.value.reason == "source_empty"
