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
import re
import secrets
import time
from collections import deque
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Deque, Mapping
from urllib.parse import parse_qs

from widget_contract.action_executor import AuthorizationDenied
from widget_contract.action_ports import UnknownAction, build_action, build_executor
from widget_contract.adapters.cli_ports import ClaimRunDenied, gh_claim_run_resume
from widget_contract.adapters.github_ports import (
    LastGoodIssues, TransitionDenied, gh_inbox_to_ready, gh_issue_workflow_labels, gh_review_to_done,
    read_issue_detail,
)
from widget_contract.adapters.store_reads import (
    read_dispatch_request_v1,
    read_run_summaries_v1,
    read_workstream_detail_v1,
)
from widget_contract.run_authority import correlate_run_summaries, summaries_from_sessions
from widget_contract.workstreams import build_workstream_projection
from widget_contract.generation import generate_widget_spec
from widget_contract.loader import load_widget_file
from widget_contract.validation import ValidationError, validate

WIDGET_DIR = Path(__file__).parent
AGENT_PLATFORM_DIR = WIDGET_DIR.parent
SPEC_PATH = AGENT_PLATFORM_DIR / "widget_contract" / "specs" / "candidates-0.1.yaml"
DECISIONS_SPEC_PATH = AGENT_PLATFORM_DIR / "widget_contract" / "specs" / "decisions-0.1.yaml"
DEFAULT_REPO = "rian010194/cortxt"
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
        "request_id": {"type": "string"},
        "confirm": {"type": "boolean"},
    },
}

WIDGET_GENERATE_REQUEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["prompt", "confirm"],
    "properties": {
        "prompt": {"type": "string"},
        "confirm": {"type": "boolean"},
    },
}

# Mirrors cli/unified_cli.py's _WIDGET_VERSION_ID: deliberately conservative,
# stands between LLM-derived widget.version text and a filesystem path.
_WIDGET_VERSION_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,31}$")


class ActionHostError(RuntimeError):
    http_status = 500
    kind = "action_error"
    category = None
    recovery = None

    def __init__(self, message: str | None = None, *, code: str | None = None,
                 errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message or self.kind)
        self.code = code
        self.errors = errors


class InvalidRequest(ActionHostError):
    http_status = 400
    kind = "validation_error"


class AuthorizationFailure(ActionHostError):
    http_status = 403
    kind = "authorization_denied"


class ActionDenied(ActionHostError):
    http_status = 409
    kind = "action_denied"


class DispatchDenied(ActionHostError):
    """The authoritative dispatch request is not eligible (missing mandate fields)."""

    http_status = 409
    kind = "dispatch_request_denied"


class StaleDispatchDenied(ActionHostError):
    """The confirmed request snapshot no longer matches the current Issue."""

    http_status = 409
    kind = "stale_dispatch_request"
    category = "mandate"
    recovery = "Re-fetch the dispatch request and confirm the current snapshot before launching."


class GateDenied(ActionHostError):
    http_status = 409
    kind = "execution_map_gate"

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code, code=code)
        category, recovery = GATE_RECOVERY.get(code, ("execution_map", "Re-run the execution-map gate and retry."))
        self.category = category
        self.recovery = recovery


class RateLimited(ActionHostError):
    http_status = 429
    kind = "rate_limited"


class NotFound(ActionHostError):
    http_status = 404
    kind = "not_found"


class StoreUnavailable(ActionHostError):
    http_status = 503
    kind = "store_unavailable"


class AdapterStartFailure(ActionHostError):
    """Adapter-start failure with a stable category and recovery guidance (AC5)."""

    http_status = 503
    kind = "adapter_start_failed"
    category = "adapter"

    def __init__(self, code: str, message: str | None = None,
                 recovery: str | None = None) -> None:
        super().__init__(message or code, code=code)
        self.recovery = recovery or "Inspect the launcher/worker log and retry with a fresh run."


# Stable recovery guidance per execution-map gate code (AC5).
GATE_RECOVERY = {
    "resource_collision": ("claim_conflict",
                           "Another active Run owns this issue or its resources; wait for it to finish or cancel it."),
    "stale_receipt": ("execution_map",
                      "The execution-map receipt is stale; refresh it and retry."),
    "stale_issue_generation": ("execution_map",
                               "The issue changed between preview and launch; re-confirm the current mandate."),
    "issue_not_ready": ("workflow",
                        "The issue is not workflow:ready; the operator must approve and mark it ready first."),
    "inventory_unavailable": ("execution_map",
                              "Execution-map inventory is unavailable; retry when the store is reachable."),
    "execution_map_store_required": ("execution_map",
                                     "The execution-map claim store is not configured; start the launcher with a store."),
    "claim_not_active": ("execution_map",
                         "The claim is no longer active; re-run the execution-map gate."),
    "claim_release_conflict": ("execution_map",
                               "The claim release conflicted; reconcile the claim store manually."),
    "max_parallel_workers_reached": ("limits",
                                     "The approved max parallel workers ceiling is reached; wait for a slot or amend the issue."),
}


class ActionHost:
    """Operator-gated action boundary behind the loopback HTTP server."""

    def __init__(self, *, spec_path: Path = SPEC_PATH,
                 labels_reader: Callable[[str], list[str]] = gh_issue_workflow_labels,
                 transition_writer: Callable[[str], Mapping[str, Any]] = gh_inbox_to_ready,
                 review_transition_writer: Callable[[str], Mapping[str, Any]] = gh_review_to_done,
                 resume: Callable[[str], Any] | None = None,
                 registry: Path | None = None, scripts_dir: Path | None = None,
                 session_store: Path | None = None,
                 issue_reader: Callable[..., Mapping[str, Any]] | None = None,
                 token: str | None = None, clock: Callable[[], float] = time.monotonic,
                 max_requests: int = MAX_REQUESTS_PER_MINUTE) -> None:
        self._spec_path = Path(spec_path)
        self._labels_reader = labels_reader
        self._transition_writer = transition_writer
        self._review_transition_writer = review_transition_writer
        # Launcher modules live in the repository-level scripts directory,
        # alongside agent-platform, not inside the Python package tree.
        self._scripts_dir = Path(scripts_dir) if scripts_dir else (AGENT_PLATFORM_DIR.parent / "scripts")
        self._registry = Path(registry) if registry else (AGENT_PLATFORM_DIR / ".dispatch" / "runs.json")
        self._session_store = Path(session_store) if session_store else (AGENT_PLATFORM_DIR / ".sessions")
        self._issue_reader = issue_reader or read_issue_detail
        self._resume = resume or (lambda issue_id, *, approval_ref=None, request_id=None: gh_claim_run_resume(
            issue_id, registry=self._registry, scripts_dir=self._scripts_dir,
            approval_ref=approval_ref, request_id=request_id))
        self.token = token or secrets.token_urlsafe(32)
        self._clock = clock
        self._max_requests = max_requests
        self._calls: Deque[float] = deque()
        self._widget = None
        self._decisions_widget = None
        self._issues = LastGoodIssues()

    @property
    def widget(self):
        if self._widget is None:
            self._widget = load_widget_file(self._spec_path)
        return self._widget

    def capabilities(self) -> dict:
        """Declarative capability summary the same-origin page renders against."""
        widgets = [self.widget]
        if self._spec_path != DECISIONS_SPEC_PATH:
            if self._decisions_widget is None:
                self._decisions_widget = load_widget_file(DECISIONS_SPEC_PATH)
            widgets.append(self._decisions_widget)
        actions = [action for widget in widgets for action in widget.actions]
        return {
            "actions_enabled": True,
            "actions": [{"id": a.id, "operation": a.operation, "port": a.port,
                         "effect_class": a.confirm.get("effect_class"),
                         "authorization": dict(a.authorization), "confirm": dict(a.confirm)}
                        for a in actions],
        }

    def workstreams(self, repo: str = DEFAULT_REPO) -> dict:
        raw = self._issues.read(repo)
        return build_workstream_projection(repo, raw["issues"], status=raw["status"], error=raw["error"])

    def _read_dispatcher_runs(self) -> Mapping[str, Any]:
        if not self._registry.exists():
            return {}
        try:
            data = json.loads(self._registry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as error:
            raise StoreUnavailable(f"dispatcher runs registry is unreadable: {error}") from error
        if not isinstance(data, Mapping):
            raise StoreUnavailable("dispatcher runs registry is not a JSON object")
        return data

    def _read_session_docs(self) -> list[Mapping[str, Any]]:
        from runtime import session_state as state

        docs: list[Mapping[str, Any]] = []
        if not self._session_store.is_dir():
            return docs
        for child in sorted(self._session_store.iterdir()):
            if not child.is_dir():
                continue
            session_file = child / "session.json"
            if not session_file.is_file():
                continue
            try:
                docs.append(state.load(self._session_store, child.name))
            except state.SessionError as error:
                # A corrupt/hash-broken record is authoritative-data loss, not
                # "no runs": fail closed rather than silently returning empty.
                if error.category == "integrity_error":
                    raise StoreUnavailable(
                        f"session store record {child.name} is corrupt: {error.message}") from error
                continue
        return docs

    def workstream_detail(self, repo: str, number: int) -> dict:
        issue = self._issue_reader(repo, number)
        issue_ref = f"{repo}#{number}"
        runs = correlate_run_summaries(
            issue_ref, self._read_dispatcher_runs(),
            summaries_from_sessions(self._read_session_docs(), issue_ref))
        return read_workstream_detail_v1(issue, runs, repo=repo, status="fresh", age_seconds=0)

    def run_summaries(self, repo: str, number: int) -> dict:
        issue_ref = f"{repo}#{number}"
        return read_run_summaries_v1(issue_ref, self._read_dispatcher_runs(), self._read_session_docs())

    def _build_dispatch_request(self, repo: str, number: int, *, issue: Mapping[str, Any] | None = None) -> dict:
        """Build the authoritative dispatch request for an issue (shared by the
        read endpoint and the claim-run confirmation binding)."""
        import sys

        from routing.engine_manifest import DEFAULT_FALLBACK_ENGINE, DEFAULT_MANIFESTS
        from widget_contract.dispatch_request import route_for_issue

        issue = issue if issue is not None else self._issue_reader(repo, number)
        choice, tags = route_for_issue(issue, DEFAULT_MANIFESTS, fallback=DEFAULT_FALLBACK_ENGINE)
        # Authoritative dispatchability: eligibility must match what the
        # WorkLauncher can actually dispatch (scripts.worker_adapters registry),
        # so the projection and the real launch can never disagree (S7b #482).
        if str(self._scripts_dir) not in sys.path:
            sys.path.insert(0, str(self._scripts_dir))
        from worker_adapters import is_runtime_dispatchable
        engine_registered = bool(choice and is_runtime_dispatchable(choice.engine_id))
        return read_dispatch_request_v1(
            issue, choice, repo=repo, engine_registered=engine_registered, routable_tags=tags)

    def dispatch_request(self, repo: str, number: int) -> dict:
        """The authoritative dispatch request a confirmation view must render."""
        return self._build_dispatch_request(repo, number)

    def _bind_claim_run(self, issue_id: str, approval_ref: str, request_id: str) -> dict:
        """Re-read the Issue and bind the confirmed action to the current request.

        The authoritative dispatch request is rebuilt from the live Issue at
        execution time (never from the browser): an ineligible request, a stale
        request snapshot (`request_id` mismatch -- the Issue changed between
        preview and confirmation), or a mismatched approval reference all fail
        closed with stable categories before any launch effect.
        """
        repo, number = self._issue_ref(issue_id)
        request = self._build_dispatch_request(repo, number)
        if not request["eligible"]:
            raise DispatchDenied(
                "dispatch request is not eligible; missing: " + ", ".join(request["missing"]),
                code="dispatch_request_not_eligible", errors=request["errors"])
        if request_id != request["request_id"]:
            raise StaleDispatchDenied(
                "dispatch request snapshot has changed; re-fetch and confirm the current request")
        if approval_ref != request["approval_reference"]:
            raise AuthorizationFailure("approval reference does not match the approved issue mandate")
        return request

    @staticmethod
    def _issue_ref(issue_id: str) -> tuple[str, int]:
        if not isinstance(issue_id, str) or "#" not in issue_id:
            raise InvalidRequest("issue_id must be owner/repo#N")
        repo, number = issue_id.rsplit("#", 1)
        if not repo or not number.isdigit():
            raise InvalidRequest("issue_id must be owner/repo#N")
        return repo, int(number)

    def _widget_for_action(self, action_id: str):
        if any(action.id == action_id for action in self.widget.actions):
            return self.widget
        if self._decisions_widget is None:
            self._decisions_widget = load_widget_file(DECISIONS_SPEC_PATH)
        if any(action.id == action_id for action in self._decisions_widget.actions):
            return self._decisions_widget
        raise NotFound(f"unknown action {action_id}")

    def _check_rate(self) -> None:
        now = self._clock()
        self._calls.append(now)
        while self._calls and now - self._calls[0] > 60:
            self._calls.popleft()
        if len(self._calls) > self._max_requests:
            raise RateLimited("too many action requests; wait and retry")

    def execute(self, *, action_id: str, issue_id: str, approval_ref: str,
                confirm: bool, token: str, request_id: str | None = None) -> dict:
        """Validate, re-authorize, and dispatch one action request.

        Raises ActionHostError subclasses on every failure; nothing executes
        unless the operator gate (approval reference + confirm) and the
        registered adapters' own state checks all pass.

        For `workflow.claim-run.v1` the confirmed action is bound to the
        authoritative server-derived dispatch request (AC8): the request
        snapshot id from the confirmation view must match the live Issue's
        digest, the approval reference must match the issue-derived reference,
        and the executor context carries that authoritative reference so a
        caller-supplied value that does not match fails closed.
        """
        if not token or token != self.token:
            raise AuthorizationFailure("missing or invalid session token")
        self._check_rate()
        if not isinstance(issue_id, str) or not issue_id:
            raise InvalidRequest("issue_id is required")
        if not isinstance(approval_ref, str) or not approval_ref:
            raise InvalidRequest("approval_ref is required")
        try:
            widget = self._widget_for_action(action_id)
            action = build_action(widget, action_id, issue_id, approval_ref, confirm)
        except UnknownAction as exc:
            raise NotFound(f"unknown action {action_id}") from exc
        authoritative_reference = None
        if action.operation == "workflow.claim-run.v1":
            if not isinstance(request_id, str) or not request_id:
                raise InvalidRequest(
                    "request_id is required for claim-run; confirm the current dispatch request snapshot")
            request = self._bind_claim_run(issue_id, approval_ref, request_id)
            authoritative_reference = request["approval_reference"]
        executor, context = build_executor(
            widget, action_id=action_id, approval_ref=approval_ref, confirm=confirm,
            labels_reader=self._labels_reader, transition_writer=self._transition_writer,
            resume=partial(self._resume, approval_ref=approval_ref, request_id=request_id),
            review_transition_writer=self._review_transition_writer,
            authoritative_reference=authoritative_reference)
        try:
            result = executor.execute(action, context)
        except AuthorizationDenied as exc:
            raise AuthorizationFailure(str(exc)) from exc
        except (TransitionDenied, ClaimRunDenied) as exc:
            if exc.__class__.__name__ == "DispatchNotEligible" and hasattr(exc, "errors"):
                raise DispatchDenied(
                    str(exc), code="dispatch_request_not_eligible", errors=exc.errors) from exc
            if exc.__class__.__name__ == "ApprovalMismatch":
                raise AuthorizationFailure(str(exc)) from exc
            if exc.__class__.__name__ == "StaleDispatchRequest":
                raise StaleDispatchDenied(str(exc)) from exc
            raise ActionDenied(str(exc)) from exc
        except ValidationError as exc:
            raise InvalidRequest(str(exc)) from exc
        except Exception as exc:
            if exc.__class__.__name__ == "ExecutionGateError" and hasattr(exc, "code"):
                raise GateDenied(exc.code) from exc
            if exc.__class__.__name__ == "LauncherDispatchError" and hasattr(exc, "code"):
                raise AdapterStartFailure(
                    exc.code, message=str(exc),
                    recovery=getattr(exc, "recovery", None)) from exc
            raise
        return {"status": "ok", "operation": action.operation, "result": result}

    def generate_widget(self, *, prompt: str, confirm: bool) -> dict:
        """Studio's describe/proposal/validate flow (issue #339, ADR-038 SS5/SS6).

        `confirm=False` is a dry run: returns `generate_widget_spec`'s raw
        outcome fields (status "ok"|"missing_operation"|"invalid") so the
        browser can render the proposal/validation screen without writing
        anything. `confirm=True` re-runs generation and, only if the result
        is "ok", writes the spec to disk -- mirroring
        `cli.unified_cli._run_widget_generate`'s own confirm gate exactly,
        so this endpoint adds no new authorization surface.
        """
        specs_dir = AGENT_PLATFORM_DIR / "widget_contract" / "specs"
        scaffold_dir = specs_dir.parent / "scaffolds"
        outcome = generate_widget_spec(prompt, scaffold_dir=scaffold_dir)
        if not confirm:
            return {
                "status": outcome.status,
                "spec_text": outcome.spec_text,
                "widget_id": outcome.widget_id,
                "widget_version": outcome.widget_version,
                "capabilities": list(outcome.capabilities),
                "missing_operations": list(outcome.missing_operations),
                "scaffold_paths": list(outcome.scaffold_paths),
                "error_message": outcome.error_message,
            }
        if outcome.status != "ok":
            return {"status": "failed", "error": {"category": "generation_error",
                    "message": outcome.error_message or "generation did not produce a valid spec"}}
        if not _WIDGET_VERSION_ID.fullmatch(outcome.widget_version or ""):
            return {"status": "failed", "error": {"category": "generation_error",
                    "message": f"Generated widget_version {outcome.widget_version!r} is not filename-safe"}}
        target_path = specs_dir / f"{outcome.widget_id}-{outcome.widget_version}.yaml"
        if target_path.exists():
            return {"status": "failed", "error": {"category": "input_error",
                    "message": f"A spec already exists at {target_path}; use 'edit' to modify it, or remove it first."}}
        target_path.write_text(outcome.spec_text or "", encoding="utf-8")
        return {"status": "succeeded", "widget_id": outcome.widget_id,
                "widget_version": outcome.widget_version, "capabilities": list(outcome.capabilities)}


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
        if path in ("/api/workstreams", "/api/workstreams/"):
            try:
                self._json(200, self.host.workstreams())
            except Exception as exc:
                self._json(503, {"schema_version": 1, "mode": "local", "synthetic": False,
                                 "status": "unavailable", "workstreams": [],
                                 "error": {"kind": getattr(exc, "kind", "github_read"), "message": str(exc)}})
            return
        if path in ("/api/workstream-detail", "/api/workstream-detail/"):
            self._handle_read("workstream-detail")
            return
        if path in ("/api/runs", "/api/runs/"):
            self._handle_read("runs")
            return
        if path in ("/api/dispatch-request", "/api/dispatch-request/"):
            self._handle_read("dispatch-request")
            return
        super().do_GET()

    def _issue_ref_from_query(self) -> tuple[str, int] | None:
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        issue = parse_qs(query).get("issue", [""])[0]
        if "#" not in issue:
            return None
        repo, num = issue.rsplit("#", 1)
        if not repo or not num.isdigit():
            return None
        return repo, int(num)

    def _handle_read(self, kind: str) -> None:
        parsed = self._issue_ref_from_query()
        if parsed is None:
            self._json(400, {"schema_version": 1, "status": "unavailable",
                             "error": {"kind": "validation_error",
                                       "message": "issue query parameter must be owner/repo#N"}})
            return
        repo, number = parsed
        try:
            if kind == "workstream-detail":
                self._json(200, self.host.workstream_detail(repo, number))
            elif kind == "runs":
                self._json(200, self.host.run_summaries(repo, number))
            else:
                self._json(200, self.host.dispatch_request(repo, number))
        except Exception as exc:
            self._json(503, {"schema_version": 1, "status": "unavailable",
                             "error": {"kind": getattr(exc, "kind", "read_error"), "message": str(exc)}})

    def do_OPTIONS(self) -> None:
        # No CORS preflight answer: the host is same-origin only, so cross-origin
        # JSON POSTs are blocked by the browser and cross-origin reads cannot work.
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD, POST")
        self.end_headers()

    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0]
        if route not in ("/api/action", "/api/widget-generate"):
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
        if route == "/api/widget-generate":
            try:
                validate(payload, WIDGET_GENERATE_REQUEST_SCHEMA)
            except ValidationError as exc:
                self._json(400, {"status": "error", "error": {"kind": "validation_error", "message": str(exc)}})
                return
            try:
                result = self.host.generate_widget(prompt=payload["prompt"], confirm=payload["confirm"])
            except Exception as exc:  # fail closed, never surface internals as success
                self._json(500, {"status": "failed", "error": {"category": "generation_error", "message": str(exc)}})
                return
            self._json(200, result)
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
                                       token=token, request_id=payload.get("request_id"))
            self._json(200, {"status": "ok", "action_id": payload["action_id"],
                             "issue_id": payload["issue_id"], **result})
        except ActionHostError as exc:
            body = {"status": "error", "error": {"kind": exc.kind, "message": str(exc)}}
            if getattr(exc, "code", None):
                body["error"]["code"] = exc.code
            if getattr(exc, "category", None):
                body["error"]["category"] = exc.category
            if getattr(exc, "recovery", None):
                body["error"]["recovery"] = exc.recovery
            if getattr(exc, "errors", None):
                body["error"]["errors"] = exc.errors
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


def main(*, port: int = PORT, spec_path: Path | None = None) -> int:
    host = ActionHost(spec_path=spec_path) if spec_path else ActionHost()
    with _ReusableThreadingHTTPServer((HOST, port), _make_handler(host)) as httpd:
        print(f"Cortxt widget action host: http://{HOST}:{port}/index.html "
              f"(operator-gated mutations enabled via POST /api/action, spec={host._spec_path.name})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--spec", type=Path, default=None,
                        help="Widget spec to serve actions for (default: candidates-0.1.yaml)")
    args = parser.parse_args()
    raise SystemExit(main(port=args.port, spec_path=args.spec))
