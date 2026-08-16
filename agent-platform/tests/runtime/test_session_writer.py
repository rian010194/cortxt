from __future__ import annotations

import threading

from runtime import session_state as state
from runtime.session_writer import SessionWriter


def test_concurrent_appends_from_two_threads_never_lose_events(tmp_path):
    store = tmp_path / "sessions"
    session = state.create(store, task_id="writer-race")
    session_id = session["session_id"]
    writer = SessionWriter(store, session_id)

    errors: list[Exception] = []

    def _write_many(prefix: str, count: int) -> None:
        try:
            for i in range(count):
                writer.append(f"{prefix}.tick", {"i": i})
        except Exception as error:  # pragma: no cover - failure path under test
            errors.append(error)

    t1 = threading.Thread(target=_write_many, args=("work", 50))
    t2 = threading.Thread(target=_write_many, args=("heartbeat", 50))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors == []
    doc = state.load(store, session_id)
    assert len(doc["events"]) == 101  # session.created + 100 appended events
    assert [e["sequence"] for e in doc["events"]] == list(range(101))
