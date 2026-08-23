"""Reviewed loopback host boundary for operator-gated widget action ports (ADR-038).

`serve.py` remains the read-only static widget host. This module is the
separately reviewed boundary ADR-038 requires before any action endpoint: it
serves the same loopback origin (static GET unchanged) plus exactly one
mutation route -- POST /api/action -- which dispatches through the same
ActionExecutor wiring the CLI uses (widget_contract.action_ports). The
boundary is loopback-only, same-origin (no CORS answer, so cross-origin
preflights fail and cross-origin responses cannot be read), token-bound (a
per-process session token must be echoed by the page), body-bounded,
closed-schema validated, rate-limited, and operator-gated (approval reference
plus confirm) before any side effect. Read-only by default: this host is only
mounted through the explicit `--enable-actions` opt-in; `serve.py` is
untouched and remains the default `cortxt widget` surface.
"""
from __future__ import annotations

import json
import secrets
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Deque, Mapping

from widget_contract.action_executor import AuthorizationDenied
from widget_contract.action_ports import UnknownAction, build_action, build_executor
from widget_contract.adapters.cli_ports import ClaimRunDenied, gh_claim_run_resume
from widget_contract.adapters.github_ports import TransitionDenied, gh_inbox_to_ready, gh_issue_workflow_labels
from widget_contract.loader import load_widget_file
from widget_contract.validation import ValidationError, validate

WIDGET_DIR = Path(__file__).parent
AGENT_PLATFORM_DIR = WIDGET_DIR.parent
SPEC_PATH = AGENT_PLATFORM_DIR / "widget_contract" / "specs" / "candidates-0.1.yaml"
HOST = "127.0.0.1"
PORT = 8765
MAX_BODY_BYTES = 8 * 1024
MAX_REQUESTS_PER_MINUTE = 12

ACTION_REQUEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action_id", "issue_id", "approval_ref", "confirm"],
    "properties": {
        "action_id": {"type": "string"},
        "issue_id": {"type": "string"},
        "approval_ref": {"type": "string"},
        "confirm": {"type": "boolean"},
    },
}


class ActionHostError(RuntimeError):
    http_status = 500
    kind = "action_error"


class InvalidRequest(ActionHostError):
    http_status = 400
    kind = "validation_error"


class AuthorizationFailure(ActionHostError):
    http_status = 403
    kind = "authorization_denied"


class ActionDenied(ActionHostError):
    http_status = 409
    kind = "action_denied"


class GateDenied(ActionHostError):
    http_status = 409
    kind = "execution_map_gate"

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class RateLimited(ActionHostError):
    http_status = 429
    kind = "rate_limited"


class NotFound(ActionHostError):
    http_status = 404
    kind = "not_found"


class ActionHost:
    """Operator-gated action boundary behind the loopback HTTP server."""

    def __init__(self, *, spec_path: Path = SPEC_PATH,
                 labels_reader: Callable[[str], list[str]] = gh_issue_workflow_labels,
                 transition_writer: Callable[[str], Mapping[str, Any]] = gh_inbox_to_ready,
                 resume: Callable[[str], Any] | None = None,
                 registry: Path | None = None, scripts_dir: Path | None = None,
                 token: str | None = None, clock: Callable[[], float] = time.monotonic,
                 max_requests: int = MAX_REQUESTS_PER_MINUTE) -> None:
        self._spec_path = Path(spec_path)
        self._labels_reader = labels_reader
        self._transition_writer = transition_writer
        self._scripts_dir = Path(scripts_dir) if scripts_dir else (AGENT_PLATFORM_DIR / "scripts")
        self._registry = Path(registry) if registry else (AGENT_PLATFORM_DIR / ".dispatch" / "runs.json")
        self._resume = resume or (lambda issue_id: gh_claim_run_resume(
            issue_id, registry=self._registry, scripts_dir=self._scripts_dir))
        self.token = token or secrets.token_urlsafe(32)
        self._clock = clock
        self._max_requests = max_requests
        self._calls: Deque[float] = deque()
        self._widget = None

    @property
    def widget(self):
        if self._widget is None:
            self._widget = load_widget_file(self._spec_path)
        return self._widget

    def capabilities(self) -> dict:
        """Declarative capability summary the same-origin page renders against."""
        return {
            "actions_enabled": True,
            "actions": [{"id": a.id, "operation": a.operation, "port": a.port,
                         "effect_class": a.confirm.get("effect_class"),
                         "authorization": dict(a.authorization), "confirm": dict(a.confirm)}
                        for a in self.widget.actions],
        }

    def _check_rate(self) -> None:
        now = self._clock()
        self._calls.append(now)
        while self._calls and now - self._calls[0] > 60:
            self._calls.popleft()
        if len(self._calls) > self._max_requests:
            raise RateLimited("too many action requests; wait and retry")

    def execute(self, *, action_id: str, issue_id: str, approval_ref: str,
                confirm: bool, token: str) -> dict:
        """Validate, re-authorize, and dispatch one action request.

        Raises ActionHostError subclasses on every failure; nothing executes
        unless the operator gate (approval reference + confirm) and the
        registered adapters' own state checks all pass.
        """
        if not token or token != self.token:
            raise AuthorizationFailure("missing or invalid session token")
        self._check_rate()
        if not isinstance(issue_id, str) or not issue_id:
            raise InvalidRequest("issue_id is required")
        if not isinstance(approval_ref, str) or not approval_ref:
            raise InvalidRequest("approval_ref is required")
        try:
            action = build_action(self.widget, action_id, issue_id, approval_ref, confirm)
        except UnknownAction as exc:
            raise NotFound(f"unknown action {action_id}") from exc
        executor, context = build_executor(
            self.widget, action_id=action_id, approval_ref=approval_ref, confirm=confirm,
            labels_reader=self._labels_reader, transition_writer=self._transition_writer,
            resume=self._resume)
        try:
            result = executor.execute(action, context)
        except AuthorizationDenied as exc:
            raise AuthorizationFailure(str(exc)) from exc
        except (TransitionDenied, ClaimRunDenied) as exc:
            raise ActionDenied(str(exc)) from exc
        except ValidationError as exc:
            raise InvalidRequest(str(exc)) from exc
        except Exception as exc:
            if exc.__class__.__name__ == "ExecutionGateError" and hasattr(exc, "code"):
                raise GateDenied(exc.code) from exc
            raise
        return {"status": "ok", "operation": action.operation, "result": result}


class ActionHandler(SimpleHTTPRequestHandler):
    """Static GET (unchanged surface) plus the single operator-gated POST route."""

    host: ActionHost

    def _json(self, code: int, payload: Mapping[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/api/token", "/api/token/"):
            self._json(200, {"token": self.host.token})
            return
        if path in ("/api/capabilities", "/api/capabilities/"):
            self._json(200, self.host.capabilities())
            return
        super().do_GET()

    def do_OPTIONS(self) -> None:
        # No CORS preflight answer: the host is same-origin only, so cross-origin
        # JSON POSTs are blocked by the browser and cross-origin reads cannot work.
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD, POST")
        self.end_headers()

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/action":
            self.send_error(404, "not found")
            return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._json(415, {"status": "error",
                             "error": {"kind": "validation_error", "message": "Content-Type must be application/json"}})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(413, {"status": "error",
                             "error": {"kind": "validation_error", "message": "body too large or missing"}})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(400, {"status": "error",
                             "error": {"kind": "validation_error", "message": "body is not valid JSON"}})
            return
        try:
            validate(payload, ACTION_REQUEST_SCHEMA)
        except ValidationError as exc:
            self._json(400, {"status": "error", "error": {"kind": "validation_error", "message": str(exc)}})
            return
        token = self.headers.get("X-Cortxt-Token") or ""
        try:
            result = self.host.execute(action_id=payload["action_id"], issue_id=payload["issue_id"],
                                       approval_ref=payload["approval_ref"], confirm=payload["confirm"],
                                       token=token)
            self._json(200, {"status": "ok", "action_id": payload["action_id"],
                             "issue_id": payload["issue_id"], **result})
        except ActionHostError as exc:
            body = {"status": "error", "error": {"kind": exc.kind, "message": str(exc)}}
            if isinstance(exc, GateDenied):
                body["error"]["code"] = exc.code
            self._json(exc.http_status, body)
        except Exception as exc:  # fail closed, never surface internals as success
            self._json(500, {"status": "error",
                             "error": {"kind": "action_error", "message": str(exc)}})


def _make_handler(host: ActionHost) -> Callable[..., ActionHandler]:
    # `host` must resolve before the first request: BaseHTTPRequestHandler runs
    # handle() inside __init__, so an instance-level assignment would be too
    # late. A per-host subclass keeps the binding available from the start
    # (assigned after class creation: a class body cannot close over the
    # function parameter it also assigns).
    class BoundActionHandler(ActionHandler):
        pass

    BoundActionHandler.host = host

    def factory(*args: Any, **kwargs: Any) -> BoundActionHandler:
        return BoundActionHandler(*args, directory=str(WIDGET_DIR), **kwargs)
    return factory


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    # Restart within the OS's TIME_WAIT window must not fail with
    # "address already in use" (same as the read-only host).
    allow_reuse_address = True


def main(*, port: int = PORT) -> int:
    host = ActionHost()
    with _ReusableThreadingHTTPServer((HOST, port), _make_handler(host)) as httpd:
        print(f"Cortxt widget action host: http://{HOST}:{port}/index.html "
              f"(operator-gated mutations enabled via POST /api/action)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
