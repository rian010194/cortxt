"""Session state: create/append/load/resume with a hash-chained, atomic-write log."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from runtime import session_state as s


def _store(tmp_path):
    d = tmp_path / "sessions"
    d.mkdir()
    return d


def test_create_returns_session_with_one_event():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="synth-classify-001")
    assert doc["schema_version"] == 1
    assert doc["session_id"].startswith("session_")
    assert len(doc["events"]) == 1
    ev = doc["events"][0]
    assert ev["sequence"] == 0
    assert ev["event_type"] == "session.created"
    assert ev["payload"] == {"task_id": "synth-classify-001"}
    assert ev["previous_hash"] == "0" * 64


def test_create_includes_plan_task_ref_when_given():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1", plan_task_ref="2026-08-20-example-plan#T3")
    assert doc["events"][0]["payload"]["plan_task_ref"] == "2026-08-20-example-plan#T3"


def test_create_omits_plan_task_ref_when_not_given():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    assert "plan_task_ref" not in doc["events"][0]["payload"]


def test_append_extends_chain_and_persists():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    doc2 = s.append(store, doc["session_id"], expected_sequence=0,
                     event_type="tool.admitted", payload={"tool": "read_fixture_file"})
    assert len(doc2["events"]) == 2
    assert doc2["events"][1]["sequence"] == 1
    assert doc2["events"][1]["previous_hash"] == doc2["events"][0]["hash"]


def test_append_rejects_wrong_expected_sequence():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    with pytest.raises(s.SessionError) as exc:
        s.append(store, doc["session_id"], expected_sequence=5,
                  event_type="tool.admitted", payload={})
    assert exc.value.category == "sequence_conflict"


def test_load_resumes_and_validates_chain():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    s.append(store, doc["session_id"], expected_sequence=0,
             event_type="tool.admitted", payload={"tool": "read_fixture_file"})
    reloaded = s.load(store, doc["session_id"])
    assert len(reloaded["events"]) == 2
    assert s.latest_sequence(reloaded) == 1


def test_load_detects_tampered_event():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    path = store / doc["session_id"] / "session.json"
    tampered = path.read_text(encoding="utf-8").replace("t1", "t1-TAMPERED")
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(s.SessionError) as exc:
        s.load(store, doc["session_id"])
    assert exc.value.category == "integrity_error"


def test_load_unknown_session_not_found():
    store = _store(Path(tempfile.mkdtemp()))
    with pytest.raises(s.SessionError) as exc:
        s.load(store, "session_" + "0" * 32)
    assert exc.value.category == "not_found"


def test_load_rejects_malformed_session_id_without_touching_disk():
    store = _store(Path(tempfile.mkdtemp()))
    with pytest.raises(s.SessionError) as exc:
        s.load(store, "../../../etc/passwd")
    assert exc.value.category == "invalid_input"
