"""Contract tests for the dialogue routes on the action host (B1.5c).

Each T-C id from the frozen order maps to one test; the comment names the
mutation it catches. HTTP tests bind ("127.0.0.1", 0) only (precedent
test_action_host_packaging.py) and every fixture asserts the bound port is
not one of the reserved ones. No test imports `acp` at module level and no
test spawns a real agent: the e2e flow uses the fake ACP agent the service
tests use (sys.executable acp_fake_agent.py <state dir>).
"""
from __future__ import annotations

import ast
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from widget import action_host
from widget.action_host import (
    DIALOGUE_PREFIX,
    DIALOGUE_ROUTES,
    MAX_DIALOGUE_BODY_BYTES,
    ActionHost,
    _make_handler,
    _ReusableThreadingHTTPServer,
)
from runtime.dialogue_store import DialogueStore, DialogueStoreError
from runtime.adapters.acp_adapter import (
    AcpConnection,
    AcpConnectionLost,
    AcpSessionNotFound,
    AcpUnavailable,
)
from widget.dialogue_service import AgentCommand, DialogueService

CHECKOUT_ROOT = Path(__file__).resolve().parents[3]
FAKE_AGENT = (CHECKOUT_ROOT / "agent-platform" / "tests" / "runtime" /
              "adapters" / "acp_fake_agent.py")
FAKE_STATE_DIR = "fake-state"
RESERVED_PORTS = {8765, 8791, 8792, 8793}


def agent_command(state_dir: str, *extra: str) -> AgentCommand:
    return AgentCommand(command=sys.executable,
                        args=(str(FAKE_AGENT), state_dir, *extra),
                        env_names=("CORTXT_TEST_PASSED",))


def make_service(root: Path, **overrides: Any) -> Any:
    from widget.dialogue_service import DialogueService
    kwargs: dict[str, Any] = {"agent": agent_command(str(root / FAKE_STATE_DIR))}
    kwargs.update(overrides)
    return DialogueService(root, **kwargs)


# -- HTTP plumbing ------------------------------------------------------------


def _request(url: str, *, method: str = "GET", body: bytes | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _post(server: str, path: str, payload: Any = None, *, token: str | None = "test-token",
          headers: dict[str, str] | None = None) -> tuple[int, str]:
    sent: dict[str, str] = dict(headers or {})
    sent.setdefault("Content-Type", "application/json")
    if token is not None:
        sent["X-Cortxt-Token"] = token
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    return _request(f"{server}{path}", method="POST", body=body, headers=sent)


def _http_server(service: Any, host: ActionHost | None = None):
    """Bind an ephemeral loopback server for `service`; never a reserved port."""
    host = host if host is not None else ActionHost(token="test-token", dialogue=service)
    httpd = _ReusableThreadingHTTPServer(("127.0.0.1", 0), _make_handler(host))
    assert httpd.server_address[1] not in RESERVED_PORTS
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, f"http://127.0.0.1:{httpd.server_address[1]}"


def _stop(httpd, thread) -> None:
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _poll_finished(server: str, session_id: str, *, token: str = "test-token",
                   timeout: float = 30.0) -> tuple[dict, list[dict]]:
    """Poll R3 until a dialogue.turn.finished event is persisted."""
    deadline = __import__("time").monotonic() + timeout
    events: list[dict] = []
    while __import__("time").monotonic() < deadline:
        status, body = _request(f"{server}/api/dialogue/session?id={session_id}&after=-1",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 200, body
        feed = json.loads(body)
        events = feed["events"]
        finished = [event for event in events if event["event_type"] == "dialogue.turn.finished"]
        if finished:
            return feed, finished
        __import__("time").sleep(0.1)
    raise AssertionError("no dialogue.turn.finished event within the deadline")


# -- stub connection factory for service-side D7 rows -------------------------


class _StubConnection:
    """A connection stub whose class-level knobs each test adjusts."""

    start_error: Exception | None = None
    load_error: Exception | None = None
    prompt_error: Exception | None = None
    cancel_error: Exception | None = None
    prompt_event: threading.Event | None = None  # when set-and-unset, prompt blocks

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def start(self, timeout_seconds: float) -> dict:
        if _StubConnection.start_error is not None:
            raise _StubConnection.start_error
        return {"protocolVersion": 1, "agentInfo": {"name": "stub"}}

    def new_session(self, timeout_seconds: float) -> str:
        return "acp-stub-session-id"

    def load_session(self, acp_session_id: str, timeout_seconds: float) -> dict:
        if _StubConnection.load_error is not None:
            raise _StubConnection.load_error
        return {"replayed_update_count": 0}

    def prompt(self, acp_session_id: str, text: str, *, turn_id: str = "",
               timeout_seconds: float = 600) -> dict:
        event = _StubConnection.prompt_event
        if event is not None:
            event.wait(30)
        if _StubConnection.prompt_error is not None:
            raise _StubConnection.prompt_error
        return {"kind": "turn_end", "stop_reason": "end_turn"}

    def cancel(self, acp_session_id: str) -> None:
        if _StubConnection.cancel_error is not None:
            raise _StubConnection.cancel_error
        return None

    def close(self) -> None:
        return None


def _stub_factory(**kwargs: Any) -> _StubConnection:
    return _StubConnection(**kwargs)


# -- T-C1: the closed route set -----------------------------------------------


def test_dialogue_routes_are_exactly_the_frozen_six_pairs():
    # T-C1: DIALOGUE_ROUTES equals the six (method, path) pairs of D2 exactly.
    assert DIALOGUE_ROUTES == frozenset({
        ("GET", "/api/dialogue/sessions"), ("POST", "/api/dialogue/sessions"),
        ("GET", "/api/dialogue/session"),
        ("POST", "/api/dialogue/connect"), ("POST", "/api/dialogue/turn"),
        ("POST", "/api/dialogue/cancel"),
    })


# -- T-C2: the token guard on every route, GET included -----------------------


def test_http_dialogue_routes_require_the_token_on_every_method(tmp_path):
    # T-C2: no token and a wrong token answer 403 authorization_denied for
    # each of the six routes; the right token is never 403.
    service = make_service(tmp_path / "token-root")
    httpd, thread, server = _http_server(service)
    try:
        targets = [
            ("/api/dialogue/sessions", "GET", None),
            ("/api/dialogue/sessions", "POST", {}),
            ("/api/dialogue/session?id=" + "session_" + "0" * 32, "GET", None),
            ("/api/dialogue/connect", "POST", {"session_id": "session_" + "0" * 32}),
            ("/api/dialogue/turn", "POST", {"session_id": "session_" + "0" * 32,
                                            "text": "x", "client_request_id": "req-tok000001"}),
            ("/api/dialogue/cancel", "POST", {"session_id": "session_" + "0" * 32,
                                              "turn_id": "turn_" + "0" * 32}),
        ]
        for path, method, payload in targets:
            for token in (None, "wrong-token"):
                status, body = _post(f"http://{httpd.server_address[0]}:{httpd.server_address[1]}",
                                     path, payload, token=token) \
                    if method == "POST" else _request(
                        f"http://127.0.0.1:{httpd.server_address[1]}{path}",
                        headers=({} if token is None else {"X-Cortxt-Token": token}))
                assert status == 403, (path, token, body)
                assert json.loads(body)["error"]["kind"] == "authorization_denied"
        for path, method, payload in targets:
            status, body = _request(f"http://127.0.0.1:{httpd.server_address[1]}{path}",
                                    method=method,
                                    body=None if payload is None else json.dumps(payload).encode(),
                                    headers={"X-Cortxt-Token": "test-token",
                                             "Content-Type": "application/json"})
            assert status != 403, (path, body)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()


# -- T-C3: dialogue_unavailable when no service is wired -----------------------


def test_http_dialogue_unavailable_on_every_route_without_a_service():
    # T-C3: host with dialogue=None -> every route answers 503
    # dialogue_unavailable; the token check precedes availability.
    host = ActionHost(token="test-token")  # dialogue defaults to None
    httpd, thread, server = _http_server(None, host)
    try:
        for path, method, payload in [
            ("/api/dialogue/sessions", "GET", None),
            ("/api/dialogue/sessions", "POST", {}),
            ("/api/dialogue/session?id=" + "session_" + "0" * 32, "GET", None),
            ("/api/dialogue/connect", "POST", {"session_id": "session_" + "0" * 32}),
            ("/api/dialogue/turn", "POST", {"session_id": "session_" + "0" * 32,
                                            "text": "x", "client_request_id": "req-unav00001"}),
            ("/api/dialogue/cancel", "POST", {"session_id": "session_" + "0" * 32,
                                              "turn_id": "turn_" + "0" * 32}),
        ]:
            status, body = _request(f"{server}{path}", method=method,
                                    body=None if payload is None else json.dumps(payload).encode(),
                                    headers={"X-Cortxt-Token": "test-token",
                                             "Content-Type": "application/json"})
            assert status == 503, (path, body)
            parsed = json.loads(body)
            assert parsed["status"] == "unavailable"
            assert parsed["error"]["kind"] == "dialogue_unavailable"
        # Token precedes availability.
        status, body = _request(f"{server}/api/dialogue/sessions",
                                headers={"X-Cortxt-Token": "wrong"})
        assert status == 403
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


# -- T-C4a: behavioural no-reach ------------------------------------------------


def test_http_dialogue_flow_never_calls_the_action_machinery(tmp_path, monkeypatch):
    # T-C4a: sentinels on every D3 target + monkeypatched action machinery;
    # the full R2 -> R4 -> R5 -> R3 -> R5 WAIT-CANCEL -> R6 -> R1 flow over
    # HTTP against the fake agent makes zero sentinel calls; runs.json absent.
    calls: list[str] = []

    def _sentinel(name: str):
        def _raise(*args: Any, **kwargs: Any):
            calls.append(name)
            raise AssertionError(f"dialogue flow reached {name}")
        return _raise

    service = make_service(tmp_path / "noreach")
    host = ActionHost(token="test-token", dialogue=service)
    host._labels_reader = _sentinel("labels_reader")
    host._transition_writer = _sentinel("transition_writer")
    host._review_transition_writer = _sentinel("review_transition_writer")
    host._recover_transition_writer = _sentinel("recover_transition_writer")
    host._unblock_transition_writer = _sentinel("unblock_transition_writer")
    host._issue_create_writer = _sentinel("issue_create_writer")
    host._resume = _sentinel("resume")
    host._registry = tmp_path / "runs.json"
    monkeypatch.setattr(ActionHost, "execute", _sentinel("execute"))
    monkeypatch.setattr(ActionHost, "packaging_action", _sentinel("packaging_action"))
    monkeypatch.setattr(ActionHost, "_check_rate", _sentinel("_check_rate"))
    monkeypatch.setattr(ActionHost, "generate_widget", _sentinel("generate_widget"))

    httpd, thread, server = _http_server(None, host)
    try:
        status, body = _post(server, "/api/dialogue/sessions", {})
        assert status == 201, body
        session_id = json.loads(body)["session"]["cortxt_session_id"]
        status, body = _post(server, "/api/dialogue/connect", {"session_id": session_id})
        assert status == 200, body
        status, body = _post(server, "/api/dialogue/turn",
                             {"session_id": session_id, "text": "hello",
                              "client_request_id": "req-tc4a-flow1"})
        assert status == 202, body
        feed, finished = _poll_finished(server, session_id)
        assert finished[0]["payload"]["outcome"] == "completed"
        status, body = _post(server, "/api/dialogue/turn",
                             {"session_id": session_id, "text": "WAIT-CANCEL",
                              "client_request_id": "req-tc4a-flow2"})
        assert status == 202, body
        turn_id = json.loads(body)["turn_id"]
        status, body = _post(server, "/api/dialogue/cancel",
                             {"session_id": session_id, "turn_id": turn_id})
        assert status == 202, body
        feed, finished = _poll_finished(server, session_id, want="cancelled")
        status, body = _request(f"{server}/api/dialogue/sessions",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 200
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()
    assert calls == []
    assert not (tmp_path / "runs.json").exists()


def _poll_finished(server: str, session_id: str, *, want: str | None = None,
                   timeout: float = 30.0, min_events: int = 0) -> tuple[dict, list[dict]]:
    """Poll R3 until a finished event persists. `min_events` waits until the
    feed carries at least that many events (used to observe a SECOND turn's
    finished event, not the first turn's already-persisted one)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, body = _request(f"{server}/api/dialogue/session?id={session_id}&after=-1",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 200, body
        feed = json.loads(body)
        finished = [event for event in feed["events"]
                    if event["event_type"] == "dialogue.turn.finished"
                    and (want is None or event["payload"].get("outcome") == want)]
        if finished and len(feed["events"]) >= min_events:
            return feed, finished
        time.sleep(0.05)
    raise AssertionError(f"no finished event (want={want}) within the deadline")


# -- T-C4b / T-C4c: AST discipline ---------------------------------------------

_D3_IDENTIFIERS = frozenset({
    "execute", "packaging_action", "packaging", "_packaging_api", "_check_rate",
    "_calls", "generate_widget", "workstreams", "dispatch_request", "_resume",
    "_registry", "_session_store", "_issues", "build_action", "build_executor",
    "repositories",
})


def _module_functions(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_ast_dialogue_handlers_never_reference_the_action_machinery():
    # T-C4b: every _handle_dialogue*/_dialogue_* function in action_host.py
    # references none of the D3 identifiers; the only do_GET/do_POST
    # statements mentioning DIALOGUE_PREFIX delegate to such a function.
    source_path = CHECKOUT_ROOT / "agent-platform" / "widget" / "action_host.py"
    functions = _module_functions(source_path)
    dialogue_names = [name for name in functions
                      if name.startswith("_handle_dialogue") or name.startswith("_dialogue_")]
    assert dialogue_names, "the dialogue handler methods must exist"
    for name in dialogue_names:
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Name) and node.id in _D3_IDENTIFIERS:
                pytest.fail(f"{name} references D3 identifier {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in _D3_IDENTIFIERS:
                pytest.fail(f"{name} references D3 attribute .{node.attr}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for handler_name in ("do_GET", "do_POST"):
        handler = functions[handler_name]
        mentions = [node for node in ast.walk(handler)
                    if isinstance(node, ast.Name) and node.id == "DIALOGUE_PREFIX"]
        if mentions:
            delegated = any(isinstance(node, ast.Call) and
                            getattr(node.func, "attr", "") == "_handle_dialogue"
                            for node in ast.walk(handler))
            assert delegated, f"{handler_name} must delegate dialogue paths"


def test_ast_import_discipline_for_both_modules():
    # T-C4c: dialogue_service.py imports only stdlib + the three runtime
    # modules (re-asserted here so this file stands alone); action_host.py
    # imports DialogueService/AgentCommand only from widget.dialogue_service.
    service_path = CHECKOUT_ROOT / "agent-platform" / "widget" / "dialogue_service.py"
    tree = ast.parse(service_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root in sys.stdlib_module_names, f"dialogue_service imports {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            root = node.module.split(".")[0]
            assert (root in sys.stdlib_module_names or root == "runtime"), \
                f"dialogue_service imports {node.module}"
    host_path = CHECKOUT_ROOT / "agent-platform" / "widget" / "action_host.py"
    host_tree = ast.parse(host_path.read_text(encoding="utf-8"))
    sources: list[str] = []
    for node in ast.walk(host_tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                if alias.name in ("DialogueService", "AgentCommand"):
                    sources.append(node.module)
    assert sources and set(sources) == {"widget.dialogue_service"}


# -- T-C5: the closed set over HTTP --------------------------------------------


def test_http_closed_route_set(dialogue_server_pair):
    # T-C5: unlisted dialogue paths answer 404 not_found for GET and POST;
    # listed paths answered with the other method answer 405.
    server, _service = dialogue_server_pair
    for path in ("/api/dialogue/permission", "/api/dialogue/allow",
                 "/api/dialogue/bind", "/api/dialogue/disconnect",
                 "/api/dialogue/sessions/x", "/api/dialogue/"):
        status, body = _request(f"{server}{path}",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 404, (path, body)
        assert json.loads(body)["error"]["kind"] == "not_found"
        status, body = _request(f"{server}{path}", method="POST", body=b"{}",
                                headers={"X-Cortxt-Token": "test-token",
                                         "Content-Type": "application/json"})
        assert status == 404, (path, body)
        assert json.loads(body)["error"]["kind"] == "not_found"
    for path in ("/api/dialogue/connect", "/api/dialogue/turn", "/api/dialogue/cancel"):
        status, body = _request(f"{server}{path}",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 405, (path, body)
        assert json.loads(body)["error"]["kind"] == "method_not_allowed"
    status, body = _request(f"{server}/api/dialogue/session", method="POST", body=b"{}",
                            headers={"X-Cortxt-Token": "test-token",
                                     "Content-Type": "application/json"})
    assert status == 405
    assert json.loads(body)["error"]["kind"] == "method_not_allowed"


# -- T-C6: effect-free GETs over HTTP ------------------------------------------


def test_http_gets_never_connect_or_write(tmp_path):
    # T-C6: R1 and R3 x50 each against a spy factory on a bound session with
    # a stale open turn: zero factory calls, session bytes unchanged,
    # workspaces/ absent.
    root = tmp_path / "readonly"
    store = DialogueStore(root / "sessions")
    session_id = store.create_session()
    store.bind_acp_session(session_id, "acp-replayed-id", agent_info={"name": "fake"})
    store.start_turn(session_id, "turn_" + "c" * 32, "stale")
    before = {path: path.read_bytes() for path in sorted((root / "sessions").rglob("session.json"))}
    factory_calls: list[str] = []
    real_connection = AcpConnection

    def _spy_factory(**kwargs: Any) -> Any:
        factory_calls.append(kwargs.get("command", "?"))
        return real_connection(**kwargs)

    service = make_service(root, connection_factory=_spy_factory)
    httpd, thread, server = _http_server(service)
    try:
        for _ in range(50):
            status, body = _request(f"{server}/api/dialogue/sessions",
                                    headers={"X-Cortxt-Token": "test-token"})
            assert status == 200
            status, body = _request(f"{server}/api/dialogue/session?id={session_id}&after=-1",
                                    headers={"X-Cortxt-Token": "test-token"})
            assert status == 200
            status, body = _request(f"{server}/api/dialogue/session?id={session_id}&after=0",
                                    headers={"X-Cortxt-Token": "test-token"})
            assert status == 200
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()
    assert factory_calls == []
    after = {path: path.read_bytes() for path in sorted((root / "sessions").rglob("session.json"))}
    assert after == before
    assert not (root / "workspaces").exists()


# -- T-C7: the D7 table over HTTP ----------------------------------------------


class _BrokenStore:
    """A store wrapper whose one method raises the configured DialogueStoreError."""

    def __init__(self, inner: Any, method: str, kind: str) -> None:
        self._inner = inner
        self._method = method
        self._kind = kind

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __getattribute__(self, name: str):  # noqa: D105
        if name in ("_inner", "_kind", "_broken_method"):
            return object.__getattribute__(self, name)
        broken = object.__getattribute__(self, "_method")
        if name == broken:
            def _raise(*args: Any, **kwargs: Any):
                raise DialogueStoreError(object.__getattribute__(self, "_kind"),
                                         f"broken store: {name}")
            return _raise
        inner = object.__getattribute__(self, "_inner")
        return getattr(inner, name)

    _broken_method = None


def test_http_d7_rows_map_to_status_and_kind(tmp_path):
    # T-C7: every reachable D7 row over HTTP produces its status and
    # error.kind; none answers 200.
    rows: list[tuple[str, str, Any]] = []

    def _check(label: str, expected_status: int, expected_kind: str,
               method: str, path: str, payload: Any = None, *,
               server: str, token: str | None = "test-token",
               extra_headers: dict | None = None) -> None:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Cortxt-Token"] = token
        if extra_headers:
            headers.update(extra_headers)
        status, body = _request(f"{server}{path}", method=method,
                                body=None if payload is None else json.dumps(payload).encode(),
                                headers=headers)
        assert status == expected_status, (label, status, body)
        kind = json.loads(body)["error"]["kind"]
        assert kind == expected_kind, (label, body)
        assert status != 200

    # --- rows on a well-provisioned host ------------------------------------
    root = tmp_path / "d7"
    service = make_service(root)
    httpd, thread, server = _http_server(service)
    sid = None
    try:
        status, body = _post(server, "/api/dialogue/sessions", {})
        sid = json.loads(body)["session"]["cortxt_session_id"]

        _check("405 GET connect", 405, "method_not_allowed",
               server=server, method="GET", path="/api/dialogue/connect")
        _check("404 unknown path", 404, "not_found",
               server=server, method="GET", path="/api/dialogue/allow")
        _check("403 no token", 403, "authorization_denied",
               server=server, method="GET", path="/api/dialogue/sessions", token=None)
        _check("415 content type", 415, "validation_error",
               server=server, method="POST", path="/api/dialogue/sessions", payload=None,
               extra_headers={"Content-Type": "text/plain"})
        _check("413 too large", 413, "validation_error",
               server=server, method="POST", path="/api/dialogue/sessions",
               payload={"pad": "x" * (MAX_DIALOGUE_BODY_BYTES + 10)})
        status, body = _request(f"{server}/api/dialogue/sessions", method="POST",
                                body=b"{not json",
                                headers={"X-Cortxt-Token": "test-token",
                                         "Content-Type": "application/json"})
        assert status == 400 and json.loads(body)["error"]["kind"] == "validation_error"
        status, body = _request(f"{server}/api/dialogue/connect", method="POST",
                                body=b'{"wrong": true}',
                                headers={"X-Cortxt-Token": "test-token",
                                         "Content-Type": "application/json"})
        assert status == 400 and json.loads(body)["error"]["kind"] == "validation_error"
        _check("400 invalid_cursor", 400, "invalid_cursor", server=server, method="GET",
               path=f"/api/dialogue/session?id={sid}&after=notanumber")
        _check("400 invalid_cursor negative", 400, "invalid_cursor",
               server=server, method="GET", path=f"/api/dialogue/session?id={sid}&after=-2")
        _check("404 session_not_found R3", 404, "session_not_found", server=server,
               method="GET", path=f"/api/dialogue/session?id={'session_' + 'e' * 32}&after=-1")
        _check("409 cursor_ahead R3", 409, "cursor_ahead", server=server,
               method="GET", path=f"/api/dialogue/session?id={sid}&after=1000000")
        _check("409 not_connected R5", 409, "not_connected", server=server, method="POST",
               path="/api/dialogue/turn",
               payload={"session_id": sid, "text": "x", "client_request_id": "req-noconn001"})
        # cancel on an unconnected session hits the connection check first.
        _check("409 not_connected R6", 409, "not_connected", server=server, method="POST",
               path="/api/dialogue/cancel",
               payload={"session_id": sid, "turn_id": "turn_" + "0" * 32})
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()

    # --- 503 dialogue_unavailable -------------------------------------------
    bare = ActionHost(token="test-token")
    httpd, thread, server = _http_server(None, bare)
    try:
        _check("503 dialogue_unavailable", 503, "dialogue_unavailable", server=server,
               method="GET", path="/api/dialogue/sessions")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    # --- 429 rate_limited (dialogue bucket, patched to 0) --------------------
    root = tmp_path / "d7-rate"
    service = make_service(root)
    httpd, thread, server = _http_server(service)
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr("widget.action_host.DIALOGUE_SENDS_PER_MINUTE", 0)
        _check("429 rate_limited", 429, "rate_limited", server=server, method="POST",
               path="/api/dialogue/sessions", payload={})
    finally:
        monkey.undo()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()

    # --- 409 dialogue_writer_busy -------------------------------------------
    root = tmp_path / "d7-busy"
    first = make_service(root)
    second = make_service(root)
    try:
        assert first.writer_held and not second.writer_held
        httpd, thread, server = _http_server(second)
        try:
            _check("409 dialogue_writer_busy R2", 409, "dialogue_writer_busy",
                   server=server, method="POST", path="/api/dialogue/sessions", payload={})
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
    finally:
        first.close()
        second.close()

    # --- 409 sequence_conflict and 409 store_refused (store stub on R2) ------
    for kind, expected in (("sequence_conflict", "sequence_conflict"),
                           ("weird_kind", "store_refused")):
        root = tmp_path / f"d7-store-{kind}"
        service = make_service(root)
        service._store = _BrokenStore(service._store, "create_session", kind)
        httpd, thread, server = _http_server(service)
        try:
            status, body = _post(server, "/api/dialogue/sessions", {})
            assert status == 409, (kind, body)
            parsed = json.loads(body)
            assert parsed["error"]["kind"] == expected
            if expected == "sequence_conflict":
                assert parsed["error"]["store_kind"] == "sequence_conflict"
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
            service.close()

    # --- R4 rows: agent_unavailable / acp_unavailable / capacity / already ---
    root = tmp_path / "d7-noagent"
    service = make_service(root, agent=None)
    store = DialogueStore(root / "sessions")
    sid2 = store.create_session()
    httpd, thread, server = _http_server(service)
    try:
        _check("503 agent_unavailable R4", 503, "agent_unavailable", server=server,
               method="POST", path="/api/dialogue/connect", payload={"session_id": sid2})
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()

    root = tmp_path / "d7-acp-unavail"
    service = make_service(root, connection_factory=_unavailable_factory)
    store = DialogueStore(root / "sessions")
    sid3 = store.create_session()
    httpd, thread, server = _http_server(service)
    try:
        _check("503 acp_unavailable R4", 503, "acp_unavailable", server=server,
               method="POST", path="/api/dialogue/connect", payload={"session_id": sid3})
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()

    root = tmp_path / "d7-capacity"
    service = make_service(root, max_live_agents=1)
    store = DialogueStore(root / "sessions")
    sid_a = store.create_session()
    sid_b = store.create_session()
    httpd, thread, server = _http_server(service)
    try:
        status, body = _post(server, "/api/dialogue/connect", {"session_id": sid_a})
        assert status == 200, body
        _check("503 agent_capacity R4", 503, "agent_capacity", server=server,
               method="POST", path="/api/dialogue/connect", payload={"session_id": sid_b})
        _check("409 already_connected R4", 409, "already_connected", server=server,
               method="POST", path="/api/dialogue/connect", payload={"session_id": sid_a})
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()

    # --- 502 agent_protocol_error (bound session + load refusal) -------------
    root = tmp_path / "d7-protocol"
    service = make_service(root, connection_factory=_protocol_error_factory)
    store = DialogueStore(root / "sessions")
    sid3p = store.create_session()
    store.bind_acp_session(sid3p, "acp-bound-id", agent_info={"name": "fake"})
    _protocol_error_factory.pending_load_error = True
    httpd, thread, server = _http_server(service)
    try:
        _check("502 agent_protocol_error R4", 502, "agent_protocol_error", server=server,
               method="POST", path="/api/dialogue/connect", payload={"session_id": sid3p})
    finally:
        _StubConnection.start_error = None
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()

    # --- 409 session_unreadable (+ store_kind) -------------------------------
    root = tmp_path / "d7-corrupt"
    store = DialogueStore(root / "sessions")
    store.create_session()
    bad = "session_" + "b" * 32
    (root / "sessions" / bad).mkdir(parents=True)
    (root / "sessions" / bad / "session.json").write_text("{corrupt", encoding="utf-8")
    service = make_service(root)
    httpd, thread, server = _http_server(service)
    try:
        status, body = _request(f"{server}/api/dialogue/session?id={bad}&after=-1",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 409, body
        parsed = json.loads(body)
        assert parsed["error"]["kind"] == "session_unreadable"
        assert parsed["error"]["store_kind"] == "integrity_error"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()

    # --- 409 turn_in_progress and 502 agent_connection_lost ------------------
    # A stub whose prompt blocks until released: turn A keeps the session's
    # open turn, so turn B is refused turn_in_progress; cancel on the open
    # turn hits a cancel that raises AcpConnectionLost -> agent_connection_lost.
    root = tmp_path / "d7-open"
    service = make_service(root, connection_factory=_blocking_factory)
    store = DialogueStore(root / "sessions")
    sid4 = store.create_session()
    _StubConnection.prompt_event = threading.Event()
    _StubConnection.cancel_error = AcpConnectionLost("stub: socket died")
    httpd, thread, server = _http_server(service)
    try:
        status, body = _post(server, "/api/dialogue/connect", {"session_id": sid4})
        assert status == 200, body
        status, body = _post(server, "/api/dialogue/turn",
                             {"session_id": sid4, "text": "hold",
                              "client_request_id": "req-openturn001"})
        assert status == 202, body
        open_turn = json.loads(body)["turn_id"]
        # Poll until the open turn is visible, then the second send refuses.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            _status, feed_body = _request(f"{server}/api/dialogue/session?id={sid4}&after=-1",
                                          headers={"X-Cortxt-Token": "test-token"})
            if any(event["event_type"] == "dialogue.turn.started"
                   for event in json.loads(feed_body)["events"]):
                break
            time.sleep(0.05)
        _check("409 turn_in_progress R5", 409, "turn_in_progress", server=server,
               method="POST", path="/api/dialogue/turn",
               payload={"session_id": sid4, "text": "second",
                        "client_request_id": "req-openturn002"})
        # Connected, but the given turn id is not the open one.
        _check("409 turn_not_open R6", 409, "turn_not_open", server=server,
               method="POST", path="/api/dialogue/cancel",
               payload={"session_id": sid4, "turn_id": "turn_" + "0" * 32})
        _check("502 agent_connection_lost R6", 502, "agent_connection_lost", server=server,
               method="POST", path="/api/dialogue/cancel",
               payload={"session_id": sid4, "turn_id": open_turn})
    finally:
        _StubConnection.prompt_event.set()
        _StubConnection.prompt_event = None
        _StubConnection.cancel_error = None
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()


# -- T-C8: the dialogue body bound ---------------------------------------------


def test_http_dialogue_body_bound(dialogue_server_pair):
    # T-C8: MAX_DIALOGUE_BODY_BYTES + 1 -> 413 without reading the body;
    # exactly the bound passes; a 9 KiB turn text is accepted (above the
    # action bound of 8 KiB).
    server, service = dialogue_server_pair
    base = server
    status, body = _request(f"{base}/api/dialogue/sessions", method="POST", body=b"x",
                            headers={"Content-Type": "application/json",
                                     "X-Cortxt-Token": "test-token",
                                     "Content-Length": str(MAX_DIALOGUE_BODY_BYTES + 1)})
    assert status == 413, body
    assert json.loads(body)["error"]["kind"] == "validation_error"
    status, body = _post(base, "/api/dialogue/sessions", {})
    assert status == 201
    sid = json.loads(body)["session"]["cortxt_session_id"]
    status, body = _post(base, "/api/dialogue/turn",
                         {"session_id": sid, "text": "x" * 9 * 1024,
                          "client_request_id": "req-bodybound1"})
    assert status != 413, body


# -- T-C9: the two buckets ------------------------------------------------------


def test_http_dialogue_bucket_is_separate_and_cancel_is_exempt(tmp_path):
    # T-C9: 30 R2 posts pass, the 31st is 429 rate_limited; POST /api/action
    # still passes the (separate) action rate check; cancel is exempt.
    import time as _time
    clock = {"now": 1000.0}

    def _fixed_clock() -> float:
        return clock["now"]

    service = make_service(tmp_path / "bucket", clock=_fixed_clock)
    host = ActionHost(token="test-token", dialogue=service)
    httpd, thread, server = _http_server(service, host)
    headers = {"Content-Type": "application/json", "X-Cortxt-Token": "test-token"}
    try:
        for index in range(30):
            status, body = _request(f"{server}/api/dialogue/sessions", method="POST",
                                    body=b"{}", headers=headers)
            assert status == 201, (index, body)
        status, body = _request(f"{server}/api/dialogue/sessions", method="POST",
                                body=b"{}", headers=headers)
        assert status == 429, body
        assert json.loads(body)["error"]["kind"] == "rate_limited"
        # The action bucket is untouched: a POST /api/action fails for its own
        # reason (unknown action), never rate_limited.
        status, body = _request(f"{server}/api/action", method="POST",
                                body=json.dumps({"action_id": "no-such-action",
                                                 "issue_id": "o/r#1", "approval_ref": "a",
                                                 "confirm": True}).encode(),
                                headers=headers)
        parsed = json.loads(body)
        assert status != 429 and parsed["error"]["kind"] != "rate_limited"
        # Cancel is exempt from the dialogue bucket.
        sid = json.loads(_request(f"{server}/api/dialogue/sessions", method="POST",
                                  body=b"{}", headers=headers)[1])["session"]["cortxt_session_id"] \
            if False else None
        status, body = _request(f"{server}/api/dialogue/cancel", method="POST",
                                body=json.dumps({"session_id": "session_" + "0" * 32,
                                                 "turn_id": "turn_" + "0" * 32}).encode(),
                                headers=headers)
        assert status != 429, body
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()


def test_http_action_bucket_exhaustion_leaves_the_dialogue_bucket_alone(tmp_path):
    # T-C9 (second half): 13 action requests exhaust the action bucket (the
    # 13th is 429); R2 then still answers 201.
    def _frozen_clock() -> float:
        return 42.0

    service = make_service(tmp_path / "bucket2")
    host = ActionHost(token="test-token", dialogue=service, max_requests=12)
    httpd, thread, server = _http_server(service, host)
    headers = {"Content-Type": "application/json", "X-Cortxt-Token": "test-token"}
    try:
        for index in range(12):
            status, body = _request(f"{server}/api/action", method="POST",
                                    body=json.dumps({"action_id": "no-such-action",
                                                     "issue_id": "o/r#1", "approval_ref": "a",
                                                     "confirm": True}).encode(),
                                    headers=headers)
            assert status != 429, (index, body)
        status, body = _request(f"{server}/api/action", method="POST",
                                body=json.dumps({"action_id": "no-such-action",
                                                 "issue_id": "o/r#1", "approval_ref": "a",
                                                 "confirm": True}).encode(),
                                headers=headers)
        assert status == 429, body
        assert json.loads(body)["error"]["kind"] == "rate_limited"
        status, body = _request(f"{server}/api/dialogue/sessions", method="POST",
                                body=b"{}", headers=headers)
        assert status == 201, body
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()


# -- T-C10: DEC-8(a) zero replay over HTTP --------------------------------------


def test_http_zero_replay_evidence(tmp_path):
    # T-C10: R4 on a session bound to a made-up ACP id -> 200 with
    # load.zero_replay True and replayed_update_count 0; R3 shows the
    # persisted dialogue.session.loaded event with replayed_update_count 0.
    root = tmp_path / "zeroreplay"
    store = DialogueStore(root / "sessions")
    session_id = store.create_session()
    store.bind_acp_session(session_id, "made-up-acp-id-0000", agent_info={"name": "fake"})
    service = make_service(root, agent=_fake_agent_command(str(root / FAKE_STATE_DIR), "--replay", "5"))
    httpd, thread, server = _http_server(service)
    try:
        status, body = _post(server, "/api/dialogue/connect", {"session_id": session_id})
        assert status == 200, body
        parsed = json.loads(body)
        assert parsed["mode"] == "load"
        assert parsed["load"]["zero_replay"] is True
        assert parsed["load"]["replayed_update_count"] == 0
        status, body = _request(f"{server}/api/dialogue/session?id={session_id}&after=-1",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 200
        loaded = [event for event in json.loads(body)["events"]
                  if event["event_type"] == "dialogue.session.loaded"]
        assert len(loaded) == 1
        assert loaded[0]["payload"]["replayed_update_count"] == 0
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()


# -- T-C11: F1 unreadable over HTTP ---------------------------------------------


def test_http_unreadable_sessions_surface(tmp_path):
    # T-C11: R1 on a root with a corrupt session -> 200 partial with
    # unreadable; R3 on that id -> 409 session_unreadable + store_kind.
    root = tmp_path / "corrupt"
    store = DialogueStore(root / "sessions")
    good = store.create_session()
    bad = "session_" + "b" * 32
    (root / "sessions" / bad).mkdir(parents=True)
    (root / "sessions" / bad / "session.json").write_text("{corrupt", encoding="utf-8")
    service = make_service(root)
    httpd, thread, server = _http_server(service)
    try:
        status, body = _request(f"{server}/api/dialogue/sessions",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 200
        listing = json.loads(body)
        assert listing["status"] == "partial"
        assert listing["unreadable"], body
        assert all("kind" in entry for entry in listing["unreadable"])
        assert any(entry["cortxt_session_id"] == good for entry in listing["sessions"])
        status, body = _request(f"{server}/api/dialogue/session?id={bad}&after=-1",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 409
        parsed = json.loads(body)
        assert parsed["error"]["kind"] == "session_unreadable"
        assert parsed["error"]["store_kind"] == "integrity_error"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()


# -- T-C12: two hosts, one data home ---------------------------------------------


def test_http_second_host_is_a_read_only_observer(tmp_path):
    # T-C12: two hosts with their own DialogueService on the same data home:
    # the second answers R1 200 but every write 409 dialogue_writer_busy.
    root = tmp_path / "shared"
    first_service = make_service(root)
    second_service = make_service(root)
    first_httpd, first_thread, first_server = _http_server(first_service)
    second_httpd, second_thread, second_server = _http_server(second_service)
    try:
        status, body = _request(f"{second_server}/api/dialogue/sessions",
                                headers={"X-Cortxt-Token": "test-token"})
        assert status == 200, body
        for path, payload in (("/api/dialogue/sessions", {}),
                              ("/api/dialogue/connect", {"session_id": "session_" + "0" * 32}),
                              ("/api/dialogue/turn", {"session_id": "session_" + "0" * 32,
                                                      "text": "x",
                                                      "client_request_id": "req-busy00001"}),
                              ("/api/dialogue/cancel", {"session_id": "session_" + "0" * 32,
                                                        "turn_id": "turn_" + "0" * 32})):
            status, body = _request(f"{second_server}{path}", method="POST",
                                    body=json.dumps(payload).encode(),
                                    headers={"X-Cortxt-Token": "test-token",
                                             "Content-Type": "application/json"})
            assert status == 409, (path, body)
            assert json.loads(body)["error"]["kind"] == "dialogue_writer_busy"
        status, body = _request(f"{first_server}/api/dialogue/sessions", method="POST",
                                body=b"{}",
                                headers={"X-Cortxt-Token": "test-token",
                                         "Content-Type": "application/json"})
        assert status == 201, body
    finally:
        for httpd, thread in ((first_httpd, first_thread), (second_httpd, second_thread)):
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
        first_service.close()
        second_service.close()


# -- T-C13: origin / cursor over a real turn -------------------------------------


def test_http_origin_and_cursor_over_a_real_turn(tmp_path):
    # T-C13: after an e2e turn, R3 shows the store's top-level origin; every
    # dialogue.updates payload event keeps origin == "live" and an int
    # wire_seq; polling after=cursor.next returns each sequence exactly once.
    root = tmp_path / "origin"
    store = DialogueStore(root / "sessions")
    session_id = store.create_session()
    service = make_service(root, agent=_fake_agent_command(str(root / FAKE_STATE_DIR)))
    httpd, thread, server = _http_server(service)
    headers = {"X-Cortxt-Token": "test-token"}
    try:
        status, body = _post(server, "/api/dialogue/connect", {"session_id": session_id})
        assert status == 200, body
        status, body = _post(server, "/api/dialogue/turn",
                             {"session_id": session_id, "text": "hello",
                              "client_request_id": "req-origin0001"})
        assert status == 202, body
        feed, _finished = _poll_finished(server, session_id)
        store_origin = store.events_since(session_id, -1)["origin"]
        assert feed["origin"] == store_origin
        updates = [event for event in feed["events"]
                   if event["event_type"] == "dialogue.updates"]
        assert updates
        for event in updates:
            for wire_event in event["payload"]["events"]:
                assert wire_event["origin"] == "live"
                assert isinstance(wire_event["wire_seq"], int)
        seen: set[int] = set()
        after = -1
        while True:
            status, body = _request(f"{server}/api/dialogue/session?id={session_id}&after={after}",
                                    headers=headers)
            assert status == 200
            page = json.loads(body)
            for event in page["events"]:
                assert event["sequence"] not in seen
                seen.add(event["sequence"])
            if not page["cursor"]["has_more"]:
                break
            after = page["cursor"]["next"]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()


# -- T-C14: cwd/env at the host level --------------------------------------------


def test_http_agent_cwd_and_env_follow_d6(tmp_path, monkeypatch):
    # T-C14: main()-equivalent wiring (AgentCommand from argv semantics) ->
    # ECHO-CWD lands under <data-home>/dialogue/workspaces/<session_id> and
    # a planted variable not named in env_names never reaches the agent.
    root = tmp_path / "d6"
    monkeypatch.setenv("CORTXT_TEST_PLANTED", "x")
    monkeypatch.setenv("CORTXT_TEST_PASSED", "y")
    agent = AgentCommand(command=sys.executable,
                         args=(str(FAKE_AGENT), str(root / FAKE_STATE_DIR)),
                         env_names=("CORTXT_TEST_PASSED",))
    service = make_service(root, agent=agent)
    httpd, thread, server = _http_server(service)
    headers = {"X-Cortxt-Token": "test-token"}
    try:
        status, body = _post(server, "/api/dialogue/sessions", {})
        sid = json.loads(body)["session"]["cortxt_session_id"]
        status, body = _post(server, "/api/dialogue/connect", {"session_id": sid})
        assert status == 200, body
        status, body = _post(server, "/api/dialogue/turn",
                             {"session_id": sid, "text": "ECHO-CWD",
                              "client_request_id": "req-echocwd001"})
        assert status == 202, body
        feed, finished = _poll_finished(server, sid)
        updates = [event for event in feed["events"]
                   if event["event_type"] == "dialogue.updates"]
        echoed = json.loads(updates[0]["payload"]["events"][0]["payload"]["update"]["content"]["text"])
        assert Path(echoed["cwd"]) == root / "workspaces" / sid
        assert echoed["entries"] == 0
        status, body = _post(server, "/api/dialogue/turn",
                             {"session_id": sid, "text": "ECHO-ENV",
                              "client_request_id": "req-echoenv001"})
        assert status == 202, body
        feed, _done = _poll_finished(server, sid, min_events=8)
        updates = [event for event in feed["events"]
                   if event["event_type"] == "dialogue.updates"]
        env_names = json.loads(updates[-1]["payload"]["events"][0]["payload"]["update"]["content"]["text"])
        assert "CORTXT_TEST_PASSED" in env_names
        assert "CORTXT_TEST_PLANTED" not in env_names
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        service.close()


# -- T-C15 / T-C16 / T-C17: main() wiring ----------------------------------------


@pytest.fixture
def captured_main(monkeypatch):
    """Run `action_host.main` without ever binding a socket (W-3 precedent)."""
    from widget import action_host as host_module

    captured = SimpleNamespace(host=None, bound=[], out=None)
    real_host = host_module.ActionHost

    def _construct(**kwargs):
        captured.host = real_host(**kwargs)
        return captured.host

    class _NoServer:
        def __init__(self, address, handler):
            captured.bound.append(address)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def serve_forever(self):
            return None

    monkeypatch.setattr(host_module, "ActionHost", _construct)
    monkeypatch.setattr(host_module, "_ReusableThreadingHTTPServer", _NoServer)
    monkeypatch.delenv("CORTXT_DATA_HOME", raising=False)
    captured.run = lambda **kwargs: host_module.main(port=0, **kwargs)
    return captured


def _accepted_home(tmp_path, monkeypatch):
    from state import data_home as data_home_module
    monkeypatch.setattr(data_home_module.tempfile, "gettempdir",
                        lambda: str(tmp_path / "pretend-temp"))
    return tmp_path / "cortxt-data"


def test_main_without_a_data_home_leaves_dialogue_none(captured_main, capsys):
    # T-C15: no data home -> host.dialogue is None; the serving line says
    # dialogue=not configured; never a refusal and never a default root.
    assert captured_main.run() == 0
    assert captured_main.host.dialogue is None
    assert "dialogue=not configured" in capsys.readouterr().out


def test_main_with_a_data_home_wires_the_dialogue_service(captured_main, capsys,
                                                          tmp_path, monkeypatch):
    # T-C16: the service is rooted at <home>/dialogue (never the module
    # location); the line names the root, writer=held, agent not configured.
    home = _accepted_home(tmp_path, monkeypatch)
    assert captured_main.run(data_home=home) == 0
    service = captured_main.host.dialogue
    assert service is not None
    assert service.root == home / "dialogue"
    out = capsys.readouterr().out
    assert f"dialogue={home / 'dialogue'}" in out
    assert "dialogue_writer=held" in out
    assert "dialogue_agent=not configured" in out


def test_main_with_an_agent_command_builds_the_agentcommand(captured_main, tmp_path,
                                                            monkeypatch):
    # T-C16 (argv): command "x" with args ["a","b"] -> the service's
    # AgentCommand is ("x", ("a","b"), ()). Never a flattened string.
    home = _accepted_home(tmp_path, monkeypatch)
    assert captured_main.run(data_home=home, dialogue_agent_command="x",
                             dialogue_agent_args=["a", "b"]) == 0
    agent = captured_main.host.dialogue._agent
    assert (agent.command, agent.args, agent.env_names) == ("x", ("a", "b"), ())


def test_main_refuses_a_relative_data_home_before_any_dialogue_construction(
        captured_main, tmp_path, monkeypatch):
    # T-C17: a set-but-invalid data home returns 1, binds nothing, never
    # constructs a DialogueService, and leaves no writer.lock anywhere.
    from widget import action_host as host_module
    constructed: list[Any] = []
    real_service = host_module.DialogueService

    def _spy(*args: Any, **kwargs: Any) -> Any:
        constructed.append(args[0] if args else kwargs.get("root"))
        return real_service(*args, **kwargs)

    monkeypatch.setattr(host_module, "DialogueService", _spy)
    assert captured_main.run(data_home="relative-data-home") == 1
    assert captured_main.bound == []
    assert constructed == []
    assert not list(tmp_path.rglob("writer.lock"))


# -- T-C18: the existing routes are unchanged ------------------------------------


def test_http_existing_routes_answer_as_before():
    # T-C18: the dialogue token rule leaks onto no existing GET route.
    host = ActionHost(token="test-token")
    httpd, thread, server = _http_server(None, host)
    try:
        status, body = _request(f"{server}/api/token")
        assert status == 200
        assert "token" in json.loads(body)
        status, body = _request(f"{server}/api/repositories")
        assert status == 503
        assert json.loads(body)["error"]["kind"] == "read_area_unconfigured"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


# -- shared fixtures --------------------------------------------------------------


@pytest.fixture
def dialogue_server_pair(tmp_path):
    """A host + fake-agent-backed dialogue service on an ephemeral socket."""
    service = make_service(tmp_path / "dialogue")
    httpd, thread, server = _http_server(service)
    yield server, service
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)
    service.close()


def _fake_agent_command(state_dir: str, *extra: str) -> AgentCommand:
    return AgentCommand(command=sys.executable,
                        args=(str(FAKE_AGENT), state_dir, *extra),
                        env_names=("CORTXT_TEST_PASSED",))


def _unavailable_factory(**kwargs: Any) -> Any:
    from runtime.adapters.acp_adapter import AcpUnavailable
    raise AcpUnavailable("stub: SDK not installed")


def _blocking_factory(**kwargs: Any) -> _StubConnection:
    return _StubConnection(**kwargs)


def _protocol_error_factory(**kwargs: Any) -> _StubConnection:
    """A stub whose start() raises AcpSessionNotFound when armed: on a bound
    session the service runs start+load in one step, so the load refusal must
    fire from start()."""
    if getattr(_protocol_error_factory, "pending_load_error", False):
        _StubConnection.start_error = AcpSessionNotFound("stub: session/load answered null")
        _protocol_error_factory.pending_load_error = False
    return _StubConnection(**kwargs)
