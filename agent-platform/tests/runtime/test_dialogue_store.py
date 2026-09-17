"""Dialogue session store: correlation once, live-only turns, replay-idempotent loads."""
from __future__ import annotations

import ast
import json
import sys
import threading
from pathlib import Path

import pytest

from runtime import dialogue_store as ds
from runtime import session_state
from runtime.dialogue_store import DialogueStore, DialogueStoreError

ACP_ID = "d0298f9d-45cc-4a7e-aaba-beffdd5d6eda"
AGENT_INFO = {"name": "fake-agent", "version": "0.0.0"}


def _root(tmp_path: Path) -> Path:
    return tmp_path / "dialogue"


def _live(turn_id: str, wire_seq: int, origin: str = "live") -> dict:
    return {"wire_seq": wire_seq, "origin": origin, "kind": "session_update", "acp_session_id": ACP_ID,
            "turn_id": turn_id, "update_type": "agent_message_chunk",
            "payload": {"text": f"chunk {wire_seq}"}, "decision": None, "stop_reason": None}


def _bound(tmp_path: Path, acp_id: str = ACP_ID) -> tuple[DialogueStore, str]:
    store = DialogueStore(_root(tmp_path))
    session_id = store.create_session()
    store.bind_acp_session(session_id, acp_id, agent_info=AGENT_INFO)
    return store, session_id


def _events(root: Path, session_id: str) -> list[dict]:
    return session_state.load(root, session_id)["events"]


def _latest(root: Path, session_id: str) -> int:
    return session_state.latest_sequence(session_state.load(root, session_id))


def _finished_turn(store: DialogueStore, session_id: str, wire_start: int, *, prompt: str = "hello") -> str:
    turn_id = DialogueStore.new_turn_id()
    store.start_turn(session_id, turn_id, prompt)
    store.append_live_updates(session_id, turn_id, [_live(turn_id, wire_start), _live(turn_id, wire_start + 1)])
    store.finish_turn(session_id, turn_id, "completed", stop_reason="end_turn")
    return turn_id


def test_t1_create_session_is_a_session_state_dialogue_session(tmp_path):
    store = DialogueStore(_root(tmp_path))
    session_id = store.create_session()
    doc = session_state.load(_root(tmp_path), session_id)
    created = doc["events"][0]
    assert created["event_type"] == "session.created"
    assert created["payload"]["task_id"] == "dialogue"
    assert created["payload"]["runtime"] == "acp"
    assert session_state.SESSION_ID_RE.fullmatch(session_id)
    assert doc["session_id"] == session_id


def test_t2_root_is_required_absolute_and_never_module_located(tmp_path):
    with pytest.raises(TypeError):
        DialogueStore()  # type: ignore[call-arg]
    with pytest.raises(DialogueStoreError) as refused:
        DialogueStore("relative/dialogue")
    assert refused.value.kind == "not_absolute"
    source = Path(ds.__file__).read_text(encoding="utf-8")
    assert ".sessions" not in source
    assert "__file__" not in source


def test_t3_a_session_is_correlated_once(tmp_path):
    store, session_id = _bound(tmp_path)
    with pytest.raises(DialogueStoreError) as refused:
        store.bind_acp_session(session_id, "another-agent-session", agent_info={})
    assert refused.value.kind == "already_bound"
    bound = [e for e in _events(_root(tmp_path), session_id) if e["event_type"] == ds.EV_BOUND]
    assert len(bound) == 1
    assert bound[0]["payload"] == {"acp_session_id": ACP_ID, "agent_info": AGENT_INFO}


def test_t4_acp_id_is_content_never_a_name_or_identity(tmp_path):
    store, session_id = _bound(tmp_path)
    names = [path.name for path in _root(tmp_path).rglob("*")]
    assert names
    assert all(ACP_ID not in name for name in names)
    doc = session_state.load(_root(tmp_path), session_id)
    assert json.dumps(doc).count(ACP_ID) == 1
    [bound] = [e for e in doc["events"] if e["event_type"] == ds.EV_BOUND]
    assert bound["payload"]["acp_session_id"] == ACP_ID
    assert ACP_ID != session_id and ACP_ID not in session_id


def test_t5_resolve_reads_the_log_not_memory(tmp_path):
    store, session_id = _bound(tmp_path)
    turn_id = DialogueStore.new_turn_id()
    store.start_turn(session_id, turn_id, "hi")
    reopened = DialogueStore(_root(tmp_path))
    assert reopened.resolve(ACP_ID) == {
        "cortxt_session_id": session_id,
        "acp_session_id": ACP_ID,
        "replay_boundary": None,
        "last_persisted_sequence": _latest(_root(tmp_path), session_id),
        "open_turn_id": turn_id,
    }
    assert reopened.resolve("unknown-acp-session") is None


def test_t6_two_bindings_of_one_acp_id_are_ambiguous(tmp_path):
    store, first = _bound(tmp_path)
    second = store.create_session()
    store.bind_acp_session(second, ACP_ID, agent_info=AGENT_INFO)
    with pytest.raises(DialogueStoreError) as refused:
        DialogueStore(_root(tmp_path)).resolve(ACP_ID)
    assert refused.value.kind == "ambiguous_binding"
    assert first in refused.value.message and second in refused.value.message


@pytest.mark.parametrize("origin", ["replay", "out_of_turn"])
def test_t7_a_batch_with_any_non_live_event_is_refused_whole(tmp_path, origin):
    store, session_id = _bound(tmp_path)
    turn_id = DialogueStore.new_turn_id()
    store.start_turn(session_id, turn_id, "hi")
    before = _latest(_root(tmp_path), session_id)
    batch = [_live(turn_id, 1), _live(turn_id, 2, origin=origin), _live(turn_id, 3)]
    with pytest.raises(DialogueStoreError) as refused:
        store.append_live_updates(session_id, turn_id, batch)
    assert refused.value.kind == "not_live"
    assert _latest(_root(tmp_path), session_id) == before


def test_t7_turn_mismatch_and_empty_batch_are_refused(tmp_path):
    store, session_id = _bound(tmp_path)
    turn_id = DialogueStore.new_turn_id()
    store.start_turn(session_id, turn_id, "hi")
    before = _latest(_root(tmp_path), session_id)
    with pytest.raises(DialogueStoreError) as mismatch:
        store.append_live_updates(session_id, turn_id, [_live(turn_id, 1), _live(DialogueStore.new_turn_id(), 2)])
    assert mismatch.value.kind == "turn_mismatch"
    with pytest.raises(DialogueStoreError) as empty:
        store.append_live_updates(session_id, turn_id, [])
    assert empty.value.kind == "empty_batch"
    assert _latest(_root(tmp_path), session_id) == before


def test_t8_repeated_loads_add_one_marker_each_and_nothing_else(tmp_path):
    store, session_id = _bound(tmp_path)
    for wire_start in (1, 10, 20):
        _finished_turn(store, session_id, wire_start)
    root = _root(tmp_path)

    def update_count() -> int:
        return sum(1 for e in _events(root, session_id) if e["event_type"] == ds.EV_UPDATES)

    updates_before, turns_before, seq_before = update_count(), store.history(session_id)["turns"], _latest(root, session_id)
    for _ in range(3):
        store.record_load(session_id, replayed_update_count=6, out_of_turn_count=0)
    assert update_count() == updates_before
    assert store.history(session_id)["turns"] == turns_before
    assert _latest(root, session_id) == seq_before + 3
    assert len(store.history(session_id)["loads"]) == 3


def test_t9_a_lost_turn_must_be_closed_as_interrupted_before_a_load(tmp_path):
    store, session_id = _bound(tmp_path)
    turn_id = DialogueStore.new_turn_id()
    store.start_turn(session_id, turn_id, "hi")
    with pytest.raises(DialogueStoreError) as refused:
        store.record_load(session_id, replayed_update_count=0, out_of_turn_count=0)
    assert refused.value.kind == "turn_in_progress"
    store.finish_turn(session_id, turn_id, "interrupted")
    store.record_load(session_id, replayed_update_count=0, out_of_turn_count=0)
    [turn] = store.history(session_id)["turns"]
    assert turn["outcome"] == "interrupted"


def test_t10_replay_boundary_is_a_sequence_and_reads_never_consult_the_clock(tmp_path, monkeypatch):
    store, session_id = _bound(tmp_path)
    _finished_turn(store, session_id, 1)
    root = _root(tmp_path)

    before = _latest(root, session_id)
    boundary = store.record_load(session_id, replayed_update_count=2, out_of_turn_count=0)
    assert boundary == before

    monkeypatch.setattr(session_state, "utc_now", lambda: "2000-01-01T00:00:00.000000Z")
    frozen_before = _latest(root, session_id)
    frozen_boundary = store.record_load(session_id, replayed_update_count=2, out_of_turn_count=0)
    assert frozen_boundary == frozen_before

    def no_clock() -> str:
        raise RuntimeError("clock consulted")

    monkeypatch.setattr(session_state, "utc_now", no_clock)
    sequence = _latest(root, session_id)
    with pytest.raises(RuntimeError, match="clock consulted"):
        store.record_load(session_id, replayed_update_count=2, out_of_turn_count=0)
    assert _latest(root, session_id) == sequence

    reopened = DialogueStore(root)
    assert reopened.resolve(ACP_ID)["replay_boundary"] == frozen_boundary
    assert reopened.history(session_id)["loads"][-1]["replay_boundary"] == frozen_boundary


def test_t11_a_batch_is_one_append(tmp_path):
    store, session_id = _bound(tmp_path)
    turn_id = DialogueStore.new_turn_id()
    start = store.start_turn(session_id, turn_id, "hi")
    sequence = store.append_live_updates(session_id, turn_id, [_live(turn_id, n) for n in range(1, 51)])
    assert sequence == start + 1
    assert _latest(_root(tmp_path), session_id) == start + 1
    assert len(store.history(session_id)["turns"][0]["events"]) == 50


def test_t12_wire_seq_must_strictly_increase_within_and_across_batches(tmp_path):
    store, session_id = _bound(tmp_path)
    turn_id = DialogueStore.new_turn_id()
    store.start_turn(session_id, turn_id, "hi")
    root = _root(tmp_path)
    before = _latest(root, session_id)
    for batch in ([_live(turn_id, 2), _live(turn_id, 2)], [_live(turn_id, 3), _live(turn_id, 1)]):
        with pytest.raises(DialogueStoreError) as refused:
            store.append_live_updates(session_id, turn_id, batch)
        assert refused.value.kind == "wire_seq_regression"
    assert _latest(root, session_id) == before
    store.append_live_updates(session_id, turn_id, [_live(turn_id, 5)])
    after_first = _latest(root, session_id)
    for stale in (5, 4):
        with pytest.raises(DialogueStoreError) as refused:
            store.append_live_updates(session_id, turn_id, [_live(turn_id, stale)])
        assert refused.value.kind == "wire_seq_regression"
    assert _latest(root, session_id) == after_first


def test_t13_turns_need_a_binding_a_valid_id_and_no_open_turn(tmp_path):
    store = DialogueStore(_root(tmp_path))
    unbound = store.create_session()
    with pytest.raises(DialogueStoreError) as not_bound:
        store.start_turn(unbound, DialogueStore.new_turn_id(), "hi")
    assert not_bound.value.kind == "not_bound"

    store, session_id = _bound(tmp_path)
    with pytest.raises(DialogueStoreError) as bad_id:
        store.start_turn(session_id, "turn-1", "hi")
    assert bad_id.value.kind == "invalid_turn_id"
    store.start_turn(session_id, DialogueStore.new_turn_id(), "hi")
    with pytest.raises(DialogueStoreError) as overlapping:
        store.start_turn(session_id, DialogueStore.new_turn_id(), "again")
    assert overlapping.value.kind == "turn_in_progress"


def test_t14_finish_is_once_and_outcomes_are_closed(tmp_path):
    store, session_id = _bound(tmp_path)
    turn_id = DialogueStore.new_turn_id()
    store.start_turn(session_id, turn_id, "hi")
    with pytest.raises(DialogueStoreError) as invalid:
        store.finish_turn(session_id, turn_id, "done")
    assert invalid.value.kind == "invalid_outcome"
    store.finish_turn(session_id, turn_id, "completed")
    with pytest.raises(DialogueStoreError) as twice:
        store.finish_turn(session_id, turn_id, "completed")
    assert twice.value.kind == "turn_not_open"


def test_t15_a_corrupt_session_is_listed_as_unreadable(tmp_path):
    store, corrupt = _bound(tmp_path)
    healthy = store.create_session()
    path = _root(tmp_path) / corrupt / "session.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["events"][1]["hash"] = "f" * 64
    path.write_text(json.dumps(doc), encoding="utf-8")
    listing = DialogueStore(_root(tmp_path)).list_sessions()
    assert listing["unreadable"] == [{"entry": corrupt, "kind": "integrity_error"}]
    assert [s["cortxt_session_id"] for s in listing["sessions"]] == [healthy]


def test_t16_foreign_and_unexpected_entries_are_reported_dot_files_ignored(tmp_path):
    store, session_id = _bound(tmp_path)
    root = _root(tmp_path)
    foreign = session_state.create(root, "some-task")["session_id"]
    (root / "notes.txt").write_text("stray", encoding="utf-8")
    (root / ".session-abc.tmp").write_text("partial", encoding="utf-8")
    listing = store.list_sessions()
    assert listing["root_exists"] is True
    assert [s["cortxt_session_id"] for s in listing["sessions"]] == [session_id]
    assert sorted(listing["unreadable"], key=lambda u: u["entry"]) == sorted(
        [{"entry": foreign, "kind": "foreign_session"}, {"entry": "notes.txt", "kind": "unexpected_entry"}],
        key=lambda u: u["entry"])
    assert listing["sessions"][0] == {
        "cortxt_session_id": session_id, "acp_session_id": ACP_ID,
        "created_at": _events(root, session_id)[0]["timestamp"], "turn_count": 0,
        "open_turn_id": None, "last_persisted_sequence": 1,
    }


def test_t17_an_absent_root_is_not_an_empty_root(tmp_path):
    listing = DialogueStore(tmp_path / "never-created").list_sessions()
    assert listing == {"sessions": [], "unreadable": [], "root_exists": False}
    root = _root(tmp_path)
    root.mkdir()
    assert DialogueStore(root).list_sessions()["root_exists"] is True


def test_t18_history_is_marked_history_and_open_turns_have_no_outcome(tmp_path):
    store, session_id = _bound(tmp_path)
    _finished_turn(store, session_id, 1, prompt="first")
    open_turn = DialogueStore.new_turn_id()
    store.start_turn(session_id, open_turn, "second")
    store.append_live_updates(session_id, open_turn, [_live(open_turn, 1)])
    history = DialogueStore(_root(tmp_path)).history(session_id)
    assert history["cortxt_session_id"] == session_id and history["acp_session_id"] == ACP_ID
    assert [t["origin"] for t in history["turns"]] == ["history", "history"]
    assert history["turns"][0]["outcome"] == "completed"
    assert history["turns"][0]["stop_reason"] == "end_turn"
    assert history["turns"][1]["turn_id"] == open_turn
    assert history["turns"][1]["outcome"] is None
    assert history["turns"][1]["events"] == [_live(open_turn, 1)]
    assert set(history["turns"][0]) == {"turn_id", "prompt_text", "events", "outcome", "stop_reason", "origin"}


def test_t19_cursors_the_store_never_issued_are_refused(tmp_path):
    store, session_id = _bound(tmp_path)
    _finished_turn(store, session_id, 1)
    last = _latest(_root(tmp_path), session_id)
    everything = store.events_since(session_id, -1)
    assert [e["sequence"] for e in everything["events"]] == list(range(last + 1))
    assert everything["last_persisted_sequence"] == last
    assert store.events_since(session_id, last)["events"] == []
    with pytest.raises(DialogueStoreError) as ahead:
        store.events_since(session_id, last + 1)
    assert ahead.value.kind == "cursor_ahead"
    with pytest.raises(DialogueStoreError) as invalid:
        store.events_since(session_id, -2)
    assert invalid.value.kind == "invalid_cursor"


def test_t20_concurrent_batches_through_one_store_never_conflict(tmp_path):
    store, session_id = _bound(tmp_path)
    turn_id = DialogueStore.new_turn_id()
    store.start_turn(session_id, turn_id, "hi")
    order = threading.Lock()
    counter = {"next": 1}
    errors: list[Exception] = []

    def _write_batches() -> None:
        try:
            for _ in range(20):
                with order:
                    start = counter["next"]
                    counter["next"] += 2
                    store.append_live_updates(session_id, turn_id, [_live(turn_id, start), _live(turn_id, start + 1)])
        except Exception as error:  # pragma: no cover - failure path under test
            errors.append(error)

    threads = [threading.Thread(target=_write_batches) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    updates = [e for e in _events(_root(tmp_path), session_id) if e["event_type"] == ds.EV_UPDATES]
    assert len(updates) == 40
    assert [e["wire_seq"] for e in store.history(session_id)["turns"][0]["events"]] == list(range(1, 81))


def test_t21_event_types_are_accepted_by_session_state():
    for event_type in (ds.EV_BOUND, ds.EV_TURN, ds.EV_UPDATES, ds.EV_FINISHED, ds.EV_LOADED):
        assert session_state.EVENT_TYPE_RE.fullmatch(event_type), event_type


def test_t22_imports_only_stdlib_and_the_session_primitives():
    tree = ast.parse(Path(ds.__file__).read_text(encoding="utf-8"))
    allowed_runtime = {"runtime.session_state", "runtime.session_writer"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative imports are not allowed"
            if node.module == "runtime":
                modules = [f"runtime.{alias.name}" for alias in node.names]
            else:
                modules = [node.module]
        else:
            continue
        for module in modules:
            top = module.split(".")[0]
            assert module in allowed_runtime or (top != "runtime" and top in sys.stdlib_module_names), module


def test_t23_session_store_refusals_surface_with_their_category(tmp_path):
    store = DialogueStore(_root(tmp_path))
    missing = "session_" + "0" * 32
    with pytest.raises(DialogueStoreError) as not_found:
        store.history(missing)
    assert not_found.value.kind == "not_found"
    with pytest.raises(DialogueStoreError) as invalid:
        store.bind_acp_session("not-a-session-id", ACP_ID, agent_info={})
    assert invalid.value.kind == "invalid_input"
    with pytest.raises(session_state.SessionError) as underlying:
        session_state.load(_root(tmp_path), missing)
    assert underlying.value.category == not_found.value.kind
    assert underlying.value.message == not_found.value.message
    assert isinstance(not_found.value.__cause__, session_state.SessionError)
