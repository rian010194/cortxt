"""Dialogue session store: durable ACP dialogue sessions over session_state.py.

A dialogue session is an ordinary hash-chained session log (task_id
"dialogue", runtime "acp") whose Cortxt identity is the session_<32hex> id
session_state issues. The agent-issued ACP sessionId is recorded once, as
content of a dialogue.acp.bound event -- a recorded correlation, never a key,
path or identity (ADR-049 D1/D2).

Only live updates are persisted. A session load is recorded as one
dialogue.session.loaded marker whose replay_boundary is a sequence number;
replayed events are never passed to this store, so reopening a session never
duplicates its conversation (ADR-049 D3). Every read marks persisted turns
with origin "history".

The root is required and injected: this module never decides where durable
state lives, and it must not share a root with the run-session store, whose
consumers read every directory in it as a workstream.
"""
from __future__ import annotations

import copy
import re
import threading
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime import session_state
from runtime.session_writer import SessionWriter

DIALOGUE_TASK_ID = "dialogue"
DIALOGUE_RUNTIME = "acp"
EV_BOUND = "dialogue.acp.bound"
EV_TURN = "dialogue.turn.started"
EV_UPDATES = "dialogue.updates"
EV_FINISHED = "dialogue.turn.finished"
EV_LOADED = "dialogue.session.loaded"
TURN_OUTCOMES = ("completed", "failed", "cancelled", "interrupted")
TURN_ID_RE = re.compile(r"^turn_[0-9a-f]{32}$")


class DialogueStoreError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message

    @classmethod
    def from_session_error(cls, error: session_state.SessionError) -> "DialogueStoreError":
        return cls(error.category, error.message)


class _Folded:
    """The dialogue view of one session document, derived from its events alone."""

    def __init__(self, doc: dict) -> None:
        events = doc["events"]
        self.session_id = doc["session_id"]
        self.created_at = events[0]["timestamp"]
        self.last_sequence = session_state.latest_sequence(doc)
        self.acp_session_id: str | None = None
        self.turns: list[dict] = []
        self.loads: list[dict] = []
        by_id: dict[str, dict] = {}
        for event in events[1:]:
            kind, payload = event["event_type"], event["payload"]
            if kind == EV_BOUND and self.acp_session_id is None:
                self.acp_session_id = payload["acp_session_id"]
            elif kind == EV_TURN:
                turn = {"turn_id": payload["turn_id"], "prompt_text": payload["prompt_text"],
                        "events": [], "outcome": None, "stop_reason": None,
                        "origin": "history", "last_wire_seq": None}
                by_id[payload["turn_id"]] = turn
                self.turns.append(turn)
            elif kind == EV_UPDATES:
                turn = by_id[payload["turn_id"]]
                turn["events"].extend(payload["events"])
                if payload["events"]:
                    turn["last_wire_seq"] = payload["events"][-1]["wire_seq"]
            elif kind == EV_FINISHED:
                turn = by_id[payload["turn_id"]]
                turn["outcome"] = payload["outcome"]
                turn["stop_reason"] = payload["stop_reason"]
            elif kind == EV_LOADED:
                self.loads.append({"sequence": event["sequence"],
                                   "replay_boundary": payload["replay_boundary"],
                                   "replayed_update_count": payload["replayed_update_count"],
                                   "out_of_turn_count": payload["out_of_turn_count"]})

    @property
    def open_turn(self) -> dict | None:
        if self.turns and self.turns[-1]["outcome"] is None:
            return self.turns[-1]
        return None

    @property
    def open_turn_id(self) -> str | None:
        turn = self.open_turn
        return turn["turn_id"] if turn else None


class DialogueStore:
    def __init__(self, root: str | Path) -> None:
        root = Path(root)
        if not root.is_absolute():
            raise DialogueStoreError("not_absolute", "dialogue store root must be an absolute path")
        self._root = root
        self._guard = threading.Lock()
        self._writers: dict[str, tuple[SessionWriter, threading.RLock]] = {}

    # -- internals -----------------------------------------------------------

    def _writer(self, session_id: str) -> tuple[SessionWriter, threading.RLock]:
        with self._guard:
            entry = self._writers.get(session_id)
            if entry is None:
                entry = (SessionWriter(self._root, session_id), threading.RLock())
                self._writers[session_id] = entry
            return entry

    def _load(self, session_id: str) -> dict:
        try:
            return session_state.load(self._root, session_id)
        except session_state.SessionError as error:
            raise DialogueStoreError.from_session_error(error) from error

    def _load_dialogue(self, session_id: str) -> dict:
        doc = self._load(session_id)
        if doc["events"][0]["payload"].get("task_id") != DIALOGUE_TASK_ID:
            raise DialogueStoreError("foreign_session", f"{session_id} is not a dialogue session")
        return doc

    def _fold(self, session_id: str) -> _Folded:
        return _Folded(self._load_dialogue(session_id))

    def _write(self, session_id: str, check, event_type: str, build) -> dict:
        """Validate against the current log and append, as one step per session; returns the new event."""
        writer, lock = self._writer(session_id)
        with lock:
            folded = self._fold(session_id)
            check(folded)
            try:
                doc = writer.append(event_type, build(folded))
            except session_state.SessionError as error:
                raise DialogueStoreError.from_session_error(error) from error
            return doc["events"][-1]

    @staticmethod
    def _require_bound(folded: _Folded) -> None:
        if folded.acp_session_id is None:
            raise DialogueStoreError("not_bound", f"{folded.session_id} is not bound to an ACP session")

    @staticmethod
    def _require_open(folded: _Folded, turn_id: str) -> None:
        if folded.open_turn_id is None or folded.open_turn_id != turn_id:
            raise DialogueStoreError("turn_not_open", f"{turn_id} is not the open turn")

    # -- writes --------------------------------------------------------------

    def create_session(self) -> str:
        try:
            doc = session_state.create(self._root, DIALOGUE_TASK_ID, runtime=DIALOGUE_RUNTIME)
        except session_state.SessionError as error:
            raise DialogueStoreError.from_session_error(error) from error
        return doc["session_id"]

    @staticmethod
    def new_turn_id() -> str:
        return "turn_" + uuid.uuid4().hex

    def bind_acp_session(self, session_id: str, acp_session_id: str, *, agent_info: Mapping) -> None:
        if not isinstance(acp_session_id, str) or not acp_session_id:
            raise DialogueStoreError("invalid_input", "acp_session_id must be a non-empty string")
        if not isinstance(agent_info, Mapping):
            raise DialogueStoreError("invalid_input", "agent_info must be a mapping")

        def check(folded: _Folded) -> None:
            if folded.acp_session_id is not None:
                raise DialogueStoreError("already_bound", f"{session_id} is already bound to an ACP session")

        self._write(session_id, check, EV_BOUND,
                    lambda _: {"acp_session_id": acp_session_id, "agent_info": copy.deepcopy(dict(agent_info))})

    def start_turn(self, session_id: str, turn_id: str, prompt_text: str) -> int:
        if not isinstance(turn_id, str) or not TURN_ID_RE.fullmatch(turn_id):
            raise DialogueStoreError("invalid_turn_id", "turn_id must match turn_<32hex>")
        if not isinstance(prompt_text, str):
            raise DialogueStoreError("invalid_input", "prompt_text must be a string")

        def check(folded: _Folded) -> None:
            self._require_bound(folded)
            if folded.open_turn_id is not None:
                raise DialogueStoreError("turn_in_progress", f"turn {folded.open_turn_id} is still open")

        return self._write(session_id, check, EV_TURN,
                           lambda _: {"turn_id": turn_id, "prompt_text": prompt_text})["sequence"]

    def append_live_updates(self, session_id: str, turn_id: str, events: Sequence[Mapping]) -> int:
        if isinstance(events, (str, bytes)) or not isinstance(events, Sequence):
            raise DialogueStoreError("invalid_input", "events must be a sequence of mappings")
        if not events:
            raise DialogueStoreError("empty_batch", "a live update batch must not be empty")
        for event in events:
            if not isinstance(event, Mapping):
                raise DialogueStoreError("invalid_input", "every event must be a mapping")
            if event.get("origin") != "live":
                raise DialogueStoreError("not_live", f"refusing a batch containing origin {event.get('origin')!r}")
            if event.get("turn_id") != turn_id:
                raise DialogueStoreError("turn_mismatch", f"an event names turn {event.get('turn_id')!r}, not {turn_id}")
            wire_seq = event.get("wire_seq")
            if not isinstance(wire_seq, int) or isinstance(wire_seq, bool):
                raise DialogueStoreError("invalid_input", "every event needs an integer wire_seq")
        batch = [copy.deepcopy(dict(event)) for event in events]

        def check(folded: _Folded) -> None:
            self._require_open(folded, turn_id)
            previous = folded.open_turn["last_wire_seq"]
            for event in batch:
                if previous is not None and event["wire_seq"] <= previous:
                    raise DialogueStoreError("wire_seq_regression",
                                             f"wire_seq {event['wire_seq']} does not exceed {previous}")
                previous = event["wire_seq"]

        return self._write(session_id, check, EV_UPDATES,
                           lambda _: {"turn_id": turn_id, "events": batch})["sequence"]

    def finish_turn(self, session_id: str, turn_id: str, outcome: str, *,
                    stop_reason: str | None = None, detail: str | None = None) -> int:
        if outcome not in TURN_OUTCOMES:
            raise DialogueStoreError("invalid_outcome", f"outcome must be one of {TURN_OUTCOMES}")

        return self._write(session_id, lambda folded: self._require_open(folded, turn_id), EV_FINISHED,
                           lambda _: {"turn_id": turn_id, "outcome": outcome,
                                      "stop_reason": stop_reason, "detail": detail})["sequence"]

    def record_load(self, session_id: str, *, replayed_update_count: int, out_of_turn_count: int) -> int:
        for name, value in (("replayed_update_count", replayed_update_count),
                            ("out_of_turn_count", out_of_turn_count)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise DialogueStoreError("invalid_input", f"{name} must be a non-negative integer")

        def check(folded: _Folded) -> None:
            self._require_bound(folded)
            if folded.open_turn_id is not None:
                raise DialogueStoreError("turn_in_progress",
                                         f"turn {folded.open_turn_id} is open; finish it before recording a load")

        event = self._write(session_id, check, EV_LOADED,
                            lambda folded: {"replay_boundary": folded.last_sequence,
                                            "replayed_update_count": replayed_update_count,
                                            "out_of_turn_count": out_of_turn_count})
        return event["payload"]["replay_boundary"]

    # -- reads ---------------------------------------------------------------

    def _scan(self) -> tuple[list[_Folded], list[dict]]:
        sessions: list[_Folded] = []
        unreadable: list[dict] = []
        for entry in sorted(self._root.iterdir(), key=lambda path: path.name):
            name = entry.name
            if name.startswith("."):
                continue
            if not session_state.SESSION_ID_RE.fullmatch(name):
                unreadable.append({"entry": name, "kind": "unexpected_entry"})
                continue
            try:
                sessions.append(self._fold(name))
            except DialogueStoreError as error:
                unreadable.append({"entry": name, "kind": error.kind})
        return sessions, unreadable

    def resolve(self, acp_session_id: str) -> dict | None:
        if not isinstance(acp_session_id, str) or not acp_session_id:
            raise DialogueStoreError("invalid_input", "acp_session_id must be a non-empty string")
        if not self._root.is_dir():
            return None
        sessions, _ = self._scan()
        matches = [folded for folded in sessions if folded.acp_session_id == acp_session_id]
        if len(matches) > 1:
            ids = ", ".join(folded.session_id for folded in matches)
            raise DialogueStoreError("ambiguous_binding",
                                     f"ACP session {acp_session_id} is bound by several dialogue sessions: {ids}")
        if not matches:
            return None
        folded = matches[0]
        return {"cortxt_session_id": folded.session_id,
                "acp_session_id": folded.acp_session_id,
                "replay_boundary": folded.loads[-1]["replay_boundary"] if folded.loads else None,
                "last_persisted_sequence": folded.last_sequence,
                "open_turn_id": folded.open_turn_id}

    def list_sessions(self) -> dict:
        if not self._root.is_dir():
            return {"sessions": [], "unreadable": [], "root_exists": False}
        sessions, unreadable = self._scan()
        sessions.sort(key=lambda folded: (folded.created_at, folded.session_id))
        return {"sessions": [{"cortxt_session_id": folded.session_id,
                              "acp_session_id": folded.acp_session_id,
                              "created_at": folded.created_at,
                              "turn_count": len(folded.turns),
                              "open_turn_id": folded.open_turn_id,
                              "last_persisted_sequence": folded.last_sequence}
                             for folded in sessions],
                "unreadable": unreadable,
                "root_exists": True}

    def history(self, session_id: str) -> dict:
        folded = self._fold(session_id)
        turns = [{key: value for key, value in turn.items() if key != "last_wire_seq"}
                 for turn in folded.turns]
        return {"cortxt_session_id": folded.session_id,
                "acp_session_id": folded.acp_session_id,
                "turns": turns,
                "loads": folded.loads,
                "last_persisted_sequence": folded.last_sequence}

    def events_since(self, session_id: str, after_sequence: int) -> dict:
        if not isinstance(after_sequence, int) or isinstance(after_sequence, bool) or after_sequence < -1:
            raise DialogueStoreError("invalid_cursor", "after_sequence must be an integer >= -1")
        doc = self._load_dialogue(session_id)
        last = session_state.latest_sequence(doc)
        if after_sequence > last:
            raise DialogueStoreError("cursor_ahead",
                                     f"cursor {after_sequence} is beyond the last persisted sequence {last}")
        return {"events": [event for event in doc["events"] if event["sequence"] > after_sequence],
                "last_persisted_sequence": last,
                "origin": "history"}
