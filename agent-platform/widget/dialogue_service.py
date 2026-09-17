"""Host-side dialogue service: per-session agent connections over the store (B1.5c).

One ``DialogueService`` owns, per Cortxt dialogue session, at most one live
``AcpConnection`` (runtime.adapters.acp_adapter) and writes to one
``DialogueStore`` (runtime.dialogue_store) rooted at ``<root>/sessions``.
There is no HTTP code here: the routes live on the action host (B1.5c
Commit 2) and call this class.

Boundary rules this module encodes:

* Reads never create, connect, start, append or spawn (ADR-038 :141-142):
  ``list_sessions`` and ``session_events`` only read the store and the
  in-memory session state. A stale open turn is closed by ``connect``,
  never by a read.
* One dialogue writer per data home (RC-3): construction takes a
  non-blocking exclusive OS lock on ``<root>/writer.lock`` -- ``flock`` on
  POSIX (``flock``, not ``lockf``: ``flock`` conflicts across two opens in
  the same process, which the in-process single-writer test needs),
  ``msvcrt`` on Windows. A service that does not hold the lock answers
  reads and refuses every write with
  ``DialogueRefused("dialogue_writer_busy", 409)``. The lock is never
  deleted by the service.
* Every refusal is a ``DialogueRefused`` carrying a stable ``kind``, an
  HTTP status and a message; the route maps it 1:1. A
  ``DialogueStoreError`` is translated with its ``kind`` kept verbatim as
  ``store_kind`` -- never swallowed, never retried silently.
* The ACP id is agent-issued and opaque (ADR-049 D1/D2): it is recorded
  through the store's bind event, returned as an opaque field, and never
  used as a request key, file name or directory here.
* An ACP id the agent does not know is not an error (DEC-8(a)): with SDK
  0.9.0 the agent answers session/load like a known id without replay, the
  response carries ``zero_replay: true``, and the persisted
  ``dialogue.session.loaded`` event carries ``replayed_update_count: 0``.
  No invented not-found error kind exists in this unit.
* Replay is never persisted: the load sink only counts replay events. A
  lost connection is never a completed turn. Permissions are never
  answered here -- the adapter's deny-by-default is the only answer, and
  the denied request arrives as a live ``permission_request`` event that
  is persisted like any other live event (D5).

The agent runs with an explicit argv, a per-session empty workspace cwd
(``<root>/workspaces/<cortxt session id>``) and a trimmed environment
(only the configured ``env_names`` present in ``os.environ``; values are
never logged). Its stderr is appended to
``<root>/logs/<cortxt session id>.agent-stderr.log`` (RC-4) -- never an
undrained pipe.

Imports: stdlib plus runtime.dialogue_store, runtime.adapters.acp_adapter
and runtime.adapters.acp_wire only. No widget_contract, no state, no
widget.action_host, no subprocess (process spawning stays in the adapter).
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.adapters.acp_adapter import (
    AcpConnection,
    AcpConnectionLost,
    AcpProtocolError,
    AcpSessionNotFound,
    AcpUnavailable,
)
from runtime.adapters.acp_wire import (
    KIND_LOAD_COMPLETE,
    KIND_PERMISSION_REQUEST,
    KIND_SESSION_UPDATE,
    ORIGIN_LIVE,
    ORIGIN_OUT_OF_TURN,
    ORIGIN_REPLAY,
)
from runtime.dialogue_store import DialogueStore, DialogueStoreError

MAX_EVENTS_PER_READ = 500
LIVE_FLUSH_INTERVAL_SECONDS = 0.25
MAX_LIVE_AGENTS = 2
AGENT_START_TIMEOUT_SECONDS = 60
AGENT_SESSION_TIMEOUT_SECONDS = 60
TURN_TIMEOUT_SECONDS = 600

SESSION_ID_RE = re.compile(r"^session_[0-9a-f]{32}$")
TURN_ID_RE = re.compile(r"^turn_[0-9a-f]{32}$")
CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# The live wire kinds a turn persists (D4: the sink appends only these).
_LIVE_EVENT_KINDS = (KIND_SESSION_UPDATE, KIND_PERMISSION_REQUEST)


@dataclass(frozen=True)
class AgentCommand:
    command: str                      # executable, resolved with shutil.which at connect
    args: tuple[str, ...] = ()
    env_names: tuple[str, ...] = ()   # names copied from os.environ at connect; values never logged


class DialogueRefused(Exception):
    """A service refusal the route maps 1:1: kind + http_status + message.

    ``store_kind`` carries a ``DialogueStoreError.kind`` verbatim when the
    refusal translated one; it is ``None`` for every service-side refusal.
    """

    def __init__(self, kind: str, http_status: int, message: str, *,
                 store_kind: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status
        self.message = message
        self.store_kind = store_kind


# Keyword args of AcpConnection.__init__; returns an object with
# start/new_session/load_session/prompt/cancel/close.
ConnectionFactory = Callable[..., Any]


def _acquire_writer_lock(handle) -> bool:  # type: ignore[no-untyped-def]
    """Take the non-blocking exclusive RC-3 lock over one open file object."""
    if os.name == "nt":
        import msvcrt
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _release_writer_lock(handle) -> None:  # type: ignore[no-untyped-def]
    if os.name == "nt":
        import msvcrt
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _close_quietly(connection: Any) -> None:
    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass


class _Session:
    """In-memory per-session state (one entry per session this service touched)."""

    __slots__ = ("connection", "acp_session_id", "open_turn_id", "worker",
                 "pending", "client_requests", "turn_sequences", "store_error",
                 "pending_event")

    def __init__(self) -> None:
        self.connection: Any = None        # the live connection object
        self.acp_session_id: str | None = None
        self.open_turn_id: str | None = None
        self.worker: threading.Thread | None = None
        self.pending: list[dict] = []      # live events awaiting the next flush
        self.client_requests: dict[str, str] = {}
        # RC-6 records client_request_id -> turn_id; the original turn's
        # started_sequence is kept beside it so a duplicate POST can echo the
        # truthful R5 body. (Private additive state; recorded in the report.)
        self.turn_sequences: dict[str, int] = {}
        self.store_error: dict | None = None
        self.pending_event = threading.Event()


def _open_turn_id_from_history(history: Mapping[str, Any]) -> str | None:
    """The open turn per the store: the last turn without an outcome."""
    turns = history.get("turns") or []
    if turns and turns[-1].get("outcome") is None:
        return turns[-1]["turn_id"]
    return None


class _SessionSink:
    """The per-session event sink (called on the adapter's loop thread).

    Two modes. During a connect's ``load_session`` the sink only *counts*:
    replay events (never persisted) and out_of_turn events other than the
    load_complete itself (R4). Afterwards it routes every live
    ``session_update`` / ``permission_request`` whose ``turn_id`` matches the
    session's open turn into the session's ``pending`` list for the turn
    worker to persist in batches. It never touches the store and never
    blocks on disk.
    """

    def __init__(self, service: "DialogueService", state: _Session) -> None:
        self._service = service
        self._state = state
        self._counting = False
        self._replayed = 0
        self._out_of_turn = 0

    def begin_counting(self) -> None:
        self._counting = True
        self._replayed = 0
        self._out_of_turn = 0

    def counts(self) -> tuple[int, int]:
        return self._replayed, self._out_of_turn

    def __call__(self, event: dict) -> None:
        if self._counting:
            if event.get("kind") == KIND_LOAD_COMPLETE:
                self._counting = False
            elif event.get("origin") == ORIGIN_REPLAY:
                self._replayed += 1
            elif event.get("origin") == ORIGIN_OUT_OF_TURN:
                self._out_of_turn += 1
            return
        if (event.get("origin") == ORIGIN_LIVE
                and event.get("kind") in _LIVE_EVENT_KINDS
                and event.get("turn_id") == self._state.open_turn_id):
            with self._service._lock:
                self._state.pending.append(dict(event))
            self._state.pending_event.set()


class DialogueService:
    def __init__(self, root: Path, *, agent: AgentCommand | None,
                 connection_factory: ConnectionFactory | None = None,
                 store: DialogueStore | None = None,
                 max_live_agents: int = MAX_LIVE_AGENTS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        root = Path(root)
        if not root.is_absolute():
            raise ValueError("dialogue root must be an absolute path")
        self._root = root
        self._agent = agent
        self._connection_factory: ConnectionFactory = (
            connection_factory if connection_factory is not None else AcpConnection)
        self._store = store if store is not None else DialogueStore(root / "sessions")
        self._max_live_agents = max_live_agents
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}
        self._closed = False

        # RC-3, at construction, before any bind: create the root, open the
        # lock file and take the non-blocking exclusive OS lock. On OSError
        # the service keeps serving reads with writer_held False.
        root.mkdir(parents=True, exist_ok=True)
        self._lock_handle = None
        self._writer_held = False
        try:
            handle = open(root / "writer.lock", "a+b")
        except OSError:
            handle = None
        if handle is not None and _acquire_writer_lock(handle):
            self._lock_handle = handle
            self._writer_held = True
        elif handle is not None:
            handle.close()

    # -- lifecycle -------------------------------------------------------------

    @property
    def writer_held(self) -> bool:
        """True exactly when the RC-3 writer lock is held."""
        return self._writer_held

    @property
    def root(self) -> Path:
        return self._root

    def close(self) -> None:
        """Close every live connection, release the lock; idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            states = list(self._sessions.values())
        for state in states:
            connection, state.connection = state.connection, None
            if connection is not None:
                try:
                    connection.close()
                except Exception:  # a closing connection must not mask the rest
                    pass
            state.pending_event.set()
        handle, self._lock_handle = self._lock_handle, None
        if handle is not None:
            if self._writer_held:
                _release_writer_lock(handle)
            handle.close()
        self._writer_held = False

    # -- internal guards -------------------------------------------------------

    def _require_writer(self) -> None:
        if not self._writer_held:
            raise DialogueRefused(
                "dialogue_writer_busy", 409,
                "this host does not hold the dialogue writer lock for this data home")

    def _require_agent(self) -> AgentCommand:
        if self._agent is None:
            raise DialogueRefused(
                "agent_unavailable", 503,
                "no dialogue agent command is configured; connect and turn answer 503")
        return self._agent

    def _state_for(self, session_id: str) -> _Session:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = _Session()
                self._sessions[session_id] = state
            return state

    def _connected_count(self) -> int:
        with self._lock:
            return sum(1 for state in self._sessions.values()
                       if state.connection is not None)

    @staticmethod
    def _refused_from_store(error: DialogueStoreError) -> DialogueRefused:
        """Map a DialogueStoreError per D7 (store_kind stays verbatim)."""
        kind = error.kind
        if kind in ("integrity_error", "foreign_session"):
            return DialogueRefused("session_unreadable", 409, str(error), store_kind=kind)
        if kind == "not_found":
            return DialogueRefused("session_not_found", 404, str(error), store_kind=kind)
        if kind == "invalid_cursor":
            return DialogueRefused("invalid_cursor", 400, str(error), store_kind=kind)
        if kind == "cursor_ahead":
            return DialogueRefused("cursor_ahead", 409, str(error), store_kind=kind)
        if kind == "sequence_conflict":
            return DialogueRefused("sequence_conflict", 409, str(error), store_kind=kind)
        return DialogueRefused("store_refused", 409, str(error), store_kind=kind)

    def _history_for_connect(self, session_id: str) -> dict:
        """store.history for connect, mapped per D4 step 3."""
        try:
            return self._store.history(session_id)
        except DialogueStoreError as error:
            if error.kind == "not_found":
                raise DialogueRefused("session_not_found", 404,
                                      f"dialogue session {session_id} does not exist",
                                      store_kind=error.kind) from error
            raise DialogueRefused("session_unreadable", 409, str(error),
                                  store_kind=error.kind) from error

    # -- reads (never create, connect, start, append or spawn) -------------------

    def list_sessions(self) -> dict:
        listing = self._store.list_sessions()
        with self._lock:
            connected = {session_id for session_id, state in self._sessions.items()
                         if state.connection is not None}
        for entry in listing["sessions"]:
            entry["connected"] = entry["cortxt_session_id"] in connected
        status = "partial" if listing["unreadable"] else "ok"
        return {"schema_version": 1, "status": status,
                "root_exists": listing["root_exists"],
                "sessions": listing["sessions"],
                "unreadable": listing["unreadable"]}

    def session_events(self, session_id: str, after: int) -> dict:
        try:
            feed = self._store.events_since(session_id, after)
        except DialogueStoreError as error:
            raise self._refused_from_store(error) from error
        try:
            history = self._store.history(session_id)
        except DialogueStoreError as error:
            raise self._refused_from_store(error) from error
        with self._lock:
            state = self._sessions.get(session_id)
            connected = state is not None and state.connection is not None
            store_error = (dict(state.store_error)
                           if state is not None and state.store_error else None)
        events = feed["events"][:MAX_EVENTS_PER_READ]
        has_more = len(feed["events"]) > MAX_EVENTS_PER_READ
        next_cursor = events[-1]["sequence"] if events else after
        return {"schema_version": 1, "status": "ok",
                "cortxt_session_id": session_id,
                "acp_session_id": history["acp_session_id"],
                "connected": connected,
                "open_turn_id": _open_turn_id_from_history(history),
                "origin": feed["origin"],
                "events": events,
                "cursor": {"after": after, "next": next_cursor, "has_more": has_more},
                "last_persisted_sequence": feed["last_persisted_sequence"],
                "store_error": store_error}

    # -- writes ------------------------------------------------------------------

    def create_session(self) -> dict:
        self._require_writer()
        try:
            session_id = self._store.create_session()
        except DialogueStoreError as error:
            raise self._refused_from_store(error) from error
        return {"schema_version": 1, "status": "ok",
                "session": {"cortxt_session_id": session_id, "acp_session_id": None,
                            "turn_count": 0, "open_turn_id": None, "connected": False}}

    def connect(self, session_id: str) -> dict:
        self._require_writer()
        if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
            raise DialogueRefused("validation_error", 400,
                                  "session_id must match session_<32 hex>")
        agent = self._require_agent()
        # 2. The command must resolve before anything is spawned.
        resolved = shutil.which(agent.command)
        if resolved is None:
            raise DialogueRefused(
                "agent_unavailable", 503,
                f"the configured dialogue agent command was not found: {agent.command}")
        # 3. The session must exist and be readable before anything spawns.
        history = self._history_for_connect(session_id)
        state = self._state_for(session_id)
        with self._lock:
            if state.connection is not None:
                raise DialogueRefused("already_connected", 409,
                                      f"session {session_id} is already connected")
        if self._connected_count() >= self._max_live_agents:
            raise DialogueRefused("agent_capacity", 503,
                                  f"the live-agent cap ({self._max_live_agents}) is reached")
        # 6. A stale open turn is finished interrupted BEFORE anything spawns.
        stale_open = _open_turn_id_from_history(history)
        if stale_open is not None:
            try:
                self._store.finish_turn(session_id, stale_open, "interrupted",
                                        detail="no_live_connection")
            except DialogueStoreError as error:
                raise self._refused_from_store(error) from error
        # 7. The agent cwd is this service's own per-session workspace --
        # never a checkout, read area or the data-home root.
        cwd = self._root / "workspaces" / session_id
        cwd.mkdir(parents=True, exist_ok=True)
        logs_dir = self._root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = logs_dir / f"{session_id}.agent-stderr.log"
        # 8. Only the configured names, only when present in os.environ.
        env = {name: os.environ[name] for name in agent.env_names if name in os.environ}
        sink = _SessionSink(self, state)
        connection = None
        try:
            connection = self._connection_factory(
                command=resolved, args=agent.args, cwd=cwd, env=env,
                event_sink=sink, stderr_path=stderr_path)
            agent_info = connection.start(AGENT_START_TIMEOUT_SECONDS)
            acp_id = history["acp_session_id"]
            if acp_id is None:
                acp_id = connection.new_session(AGENT_SESSION_TIMEOUT_SECONDS)
                self._store.bind_acp_session(session_id, acp_id, agent_info=agent_info)
                mode, load_body = "new", None
            else:
                sink.begin_counting()
                connection.load_session(acp_id, AGENT_SESSION_TIMEOUT_SECONDS)
                replayed, out_of_turn = sink.counts()
                boundary = self._store.record_load(session_id,
                                                   replayed_update_count=replayed,
                                                   out_of_turn_count=out_of_turn)
                mode = "load"
                load_body = {"replay_boundary": boundary,
                             "replayed_update_count": replayed,
                             "out_of_turn_count": out_of_turn,
                             "zero_replay": replayed == 0}
        except DialogueStoreError as error:
            _close_quietly(connection)
            raise self._refused_from_store(error) from error
        except AcpUnavailable as error:
            _close_quietly(connection)
            raise DialogueRefused("acp_unavailable", 503, str(error)) from error
        except AcpConnectionLost as error:
            _close_quietly(connection)
            raise DialogueRefused("agent_connection_lost", 502, str(error)) from error
        except AcpSessionNotFound as error:
            _close_quietly(connection)
            raise DialogueRefused("agent_protocol_error", 502,
                                  "session/load answered null") from error
        except AcpProtocolError as error:
            _close_quietly(connection)
            raise DialogueRefused("agent_protocol_error", 502, str(error)) from error
        except (FileNotFoundError, PermissionError, OSError) as error:
            _close_quietly(connection)
            raise DialogueRefused("agent_unavailable", 503, str(error)) from error
        with self._lock:
            state.connection = connection
            state.acp_session_id = acp_id
            state.pending = []
            state.pending_event = threading.Event()
        return {"schema_version": 1, "status": "ok",
                "cortxt_session_id": session_id, "acp_session_id": acp_id,
                "mode": mode, "agent_info": agent_info, "load": load_body}

    def send_turn(self, session_id: str, text: str, client_request_id: str) -> dict:
        self._require_writer()
        if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
            raise DialogueRefused("validation_error", 400,
                                  "session_id must match session_<32 hex>")
        if not isinstance(text, str) or not text.strip():
            raise DialogueRefused("validation_error", 400,
                                  "text must be a non-empty string")
        if (not isinstance(client_request_id, str)
                or not CLIENT_REQUEST_ID_RE.fullmatch(client_request_id)):
            raise DialogueRefused(
                "validation_error", 400,
                "client_request_id must match [A-Za-z0-9_-]{8,64}")
        self._require_agent()
        state = self._state_for(session_id)
        with self._lock:
            seen = state.client_requests.get(client_request_id)
            if seen is not None:
                return {"schema_version": 1, "status": "accepted",
                        "cortxt_session_id": session_id, "turn_id": seen,
                        "started_sequence": state.turn_sequences.get(seen, -1),
                        "duplicate": True}
            connection = state.connection
            open_turn = state.open_turn_id
        if connection is None:
            raise DialogueRefused("not_connected", 409,
                                  f"session {session_id} is not connected")
        if open_turn is not None:
            raise DialogueRefused("turn_in_progress", 409,
                                  f"turn {open_turn} is still open")
        turn_id = DialogueStore.new_turn_id()
        try:
            started_sequence = self._store.start_turn(session_id, turn_id, text)
        except DialogueStoreError as error:
            raise self._refused_from_store(error) from error
        with self._lock:
            state.client_requests[client_request_id] = turn_id
            state.turn_sequences[turn_id] = started_sequence
            state.open_turn_id = turn_id
        worker = _TurnWorker(self, session_id, state, turn_id, text)
        with self._lock:
            state.worker = threading.Thread(target=worker.run, daemon=True,
                                            name=f"dialogue-turn-{session_id}")
            state.worker.start()
        return {"schema_version": 1, "status": "accepted",
                "cortxt_session_id": session_id, "turn_id": turn_id,
                "started_sequence": started_sequence, "duplicate": False}

    def cancel_turn(self, session_id: str, turn_id: str) -> dict:
        self._require_writer()
        if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
            raise DialogueRefused("validation_error", 400,
                                  "session_id must match session_<32 hex>")
        if not isinstance(turn_id, str) or not TURN_ID_RE.fullmatch(turn_id):
            raise DialogueRefused("validation_error", 400,
                                  "turn_id must match turn_<32 hex>")
        state = self._state_for(session_id)
        with self._lock:
            connection = state.connection
            acp_id = state.acp_session_id
            open_turn = state.open_turn_id
        if connection is None:
            raise DialogueRefused("not_connected", 409,
                                  f"session {session_id} is not connected")
        if open_turn is None or open_turn != turn_id:
            raise DialogueRefused("turn_not_open", 409,
                                  f"turn {turn_id} is not this session's open turn")
        try:
            connection.cancel(acp_id)
        except AcpConnectionLost as error:
            with self._lock:
                state.connection = None
            _close_quietly(connection)
            raise DialogueRefused("agent_connection_lost", 502, str(error)) from error
        return {"schema_version": 1, "status": "accepted",
                "cortxt_session_id": session_id, "turn_id": turn_id}


class _TurnWorker:
    """One turn on one connection, persisted in bounded batches (D4, R5).

    The session sink appends every live session_update / permission_request
    of the open turn to the session's ``pending`` list (it runs on the
    adapter's loop thread and must not block on disk). This worker runs the
    flusher loop itself and calls ``connection.prompt`` on a helper thread;
    while the prompt blocks it flushes ``pending`` with
    ``store.append_live_updates`` at most every LIVE_FLUSH_INTERVAL_SECONDS
    (Event-wait cadence -- the builder's choice, recorded), then drains once
    more after the terminal event, **before** finish_turn.
    """

    def __init__(self, service: DialogueService, session_id: str,
                 state: _Session, turn_id: str, text: str) -> None:
        self._service = service
        self._session_id = session_id
        self._state = state
        self._turn_id = turn_id
        self._text = text
        self._store_failed = False

    def run(self) -> None:
        self._helper_box: dict = {}
        helper = threading.Thread(target=self._prompt_on_helper, daemon=True,
                                  name=f"dialogue-prompt-{self._session_id}")
        helper.start()
        while helper.is_alive():
            self._state.pending_event.wait(LIVE_FLUSH_INTERVAL_SECONDS)
            self._state.pending_event.clear()
            self._flush_once()
            if self._store_failed:
                return  # surfaced; never finish as completed
        while not self._flush_once():
            if self._store_failed:
                return
        if self._store_failed:
            return
        outcome, stop_reason, detail = self._map_terminal(
            self._helper_box.get("terminal"), self._helper_box.get("error"))
        self._finish(outcome, stop_reason, detail)

    def _prompt_on_helper(self) -> None:
        state = self._state
        try:
            self._helper_box["terminal"] = state.connection.prompt(
                state.acp_session_id, self._text, turn_id=self._turn_id,
                timeout_seconds=TURN_TIMEOUT_SECONDS)
        except Exception as error:  # the outcome mapping handles every case
            self._helper_box["error"] = error

    def _flush_once(self) -> bool:
        """One store append of the pending batch; True when nothing pended.

        A DialogueStoreError here sets ``store_error`` (visible in R3), closes
        and unregisters the connection, then tries one
        ``finish_turn(..., "failed", detail="store_error:<kind>")``. Never
        swallowed, never retried silently.
        """
        with self._service._lock:
            batch, self._state.pending = self._state.pending, []
        if not batch:
            return True
        try:
            self._service._store.append_live_updates(self._session_id, self._turn_id, batch)
        except DialogueStoreError as error:
            self._store_failed = True
            self._store_failure(error)
            return True
        return False

    def _map_terminal(self, terminal: dict | None, prompt_error: Exception | None,
                      ) -> tuple[str, str | None, str | None]:
        if prompt_error is not None:
            if isinstance(prompt_error, AcpConnectionLost):
                return "interrupted", None, "connection_lost"
            return "failed", None, type(prompt_error).__name__
        kind = terminal.get("kind")
        if kind == "turn_end":
            if terminal.get("stop_reason") == "cancelled":
                return "cancelled", "cancelled", None
            return "completed", terminal.get("stop_reason"), None
        payload = terminal.get("payload")
        if isinstance(payload, Mapping) and payload.get("reason") == "connection_lost":
            return "interrupted", None, "connection_lost"
        return "failed", None, "agent_error"

    def _finish(self, outcome: str, stop_reason: str | None, detail: str | None) -> None:
        state = self._state
        try:
            self._service._store.finish_turn(self._session_id, self._turn_id, outcome,
                                             stop_reason=stop_reason, detail=detail)
        except DialogueStoreError as error:
            self._store_failure(error)
            return
        with self._service._lock:
            state.open_turn_id = None
        if outcome == "interrupted":
            # A lost connection is closed and unregistered; never completed.
            with self._service._lock:
                connection, state.connection = state.connection, None
            _close_quietly(connection)

    def _store_failure(self, error: DialogueStoreError) -> None:
        """Surface a store failure: store_error, close, one finish attempt."""
        self._store_failed = True
        with self._service._lock:
            self._state.store_error = {"kind": error.kind, "message": str(error),
                                       "turn_id": self._turn_id}
            connection, self._state.connection = self._state.connection, None
            self._state.open_turn_id = None
        _close_quietly(connection)
        try:
            self._service._store.finish_turn(self._session_id, self._turn_id, "failed",
                                             detail=f"store_error:{error.kind}")
        except DialogueStoreError:
            pass  # the open turn and store_error stay visible
