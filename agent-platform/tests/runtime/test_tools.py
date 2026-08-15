"""Tool admission gate: sandboxed to allowed_roots, rejects traversal, real read tool."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from runtime.tools import ToolAdmissionError, ToolExecutionError, ToolGate, read_fixture_file


def _fixture_dir(tmp_path):
    d = tmp_path / "fixtures"
    d.mkdir()
    (d / "case.json").write_text(json.dumps({"case_id": "SYNTH-1"}), encoding="utf-8")
    return d


def test_admit_accepts_path_inside_allowed_root(tmp_path):
    fdir = _fixture_dir(tmp_path)
    gate = ToolGate(allowed_roots=[fdir])
    resolved = gate.admit("read_fixture_file", str(fdir / "case.json"))
    assert resolved == (fdir / "case.json").resolve()


def test_admit_rejects_path_outside_allowed_root(tmp_path):
    fdir = _fixture_dir(tmp_path)
    outside = tmp_path / "secret.json"
    outside.write_text("{}", encoding="utf-8")
    gate = ToolGate(allowed_roots=[fdir])
    with pytest.raises(ToolAdmissionError):
        gate.admit("read_fixture_file", str(outside))


def test_admit_rejects_traversal_attempt(tmp_path):
    fdir = _fixture_dir(tmp_path)
    gate = ToolGate(allowed_roots=[fdir])
    with pytest.raises(ToolAdmissionError):
        gate.admit("read_fixture_file", str(fdir / ".." / "secret.json"))


def test_read_fixture_file_returns_parsed_json(tmp_path):
    fdir = _fixture_dir(tmp_path)
    gate = ToolGate(allowed_roots=[fdir])
    data = read_fixture_file(gate, str(fdir / "case.json"))
    assert data == {"case_id": "SYNTH-1"}


def test_read_fixture_file_rejects_admission_before_reading(tmp_path):
    fdir = _fixture_dir(tmp_path)
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({"leak": True}), encoding="utf-8")
    gate = ToolGate(allowed_roots=[fdir])
    with pytest.raises(ToolAdmissionError):
        read_fixture_file(gate, str(outside))


def test_read_fixture_file_raises_execution_error_on_malformed_json(tmp_path):
    fdir = _fixture_dir(tmp_path)
    bad = fdir / "broken.json"
    bad.write_text("{not valid json", encoding="utf-8")
    gate = ToolGate(allowed_roots=[fdir])
    with pytest.raises(ToolExecutionError):
        read_fixture_file(gate, str(bad))
