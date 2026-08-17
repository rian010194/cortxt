"""SessionWriter: a per-session, in-process single-writer over session_state.py.

Fas 4 needs a child process's own coding work and its heartbeat timer thread to
both write to the same session log without racing on session_state.append()'s
optimistic-concurrency check (expected_sequence). session_state.py stays a
simple, lock-free primitive (Fas 2 design); SessionWriter is the process-local
serialization point in front of it — one instance per session, shared by every
thread in that process that needs to write.
"""
from __future__ import annotations

import threading
from pathlib import Path

from runtime import session_state as state


class SessionWriter:
    def __init__(self, store: Path, session_id: str) -> None:
        self._store = Path(store)
        self._session_id = session_id
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            return state.load(self._store, self._session_id)

    def latest_sequence(self) -> int:
        with self._lock:
            return state.latest_sequence(state.load(self._store, self._session_id))

    def append(self, event_type: str, payload: dict) -> dict:
        with self._lock:
            seq = state.latest_sequence(state.load(self._store, self._session_id))
            return state.append(self._store, self._session_id, seq, event_type, payload)
