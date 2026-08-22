"""Mandate-bound run lifecycle service (issue #230 / ADR-034).

Owns the durable run state and the engine-broker invocation for the three
Tier-1 lifecycle tools `cortxt_run_create`, `cortxt_run_resume`, and
`cortxt_run_submit_for_review`. Dependencies (`EngineContext`, store path,
clock) are injectable so the module is network-free in tests (AC11).

Design (operator-approved Q1-Q12 + issue #230 recommendations):

- The run store is `runtime.session_state`: each run is one session created
  with `run_id`/`issue_id` in the `session.created` payload, followed by
  `run.created`, `run.engine_turn`, and `run.review_submitted` events that
  carry envelope-derived limits and engine results. No new repository, no
  launcher-state coupling (Q14).
- `run_id` is server-generated in `scripts/dispatcher.py` format
  `%Y%m%dT%H%M%SZ_<8-hex>` and is distinct from both the session_state
  session id and the opaque engine `session_id` (Q15).
- `cortxt_run_create` takes an explicit `engine_id` and invokes the engine
  adapter synchronously (Q3 recommendation); `cortxt_run_resume` never
  accepts an engine, profile, or session id from the caller -- it loads them
  from the durable run (Q6).
- Resume and submit bind to the stored original create scope fingerprint;
  no replacement scope from the caller (Q7).
- `cortxt_run_submit_for_review` records a local review-request event and
  returns a `review_submission_id`; it performs no GitHub transition, no
  `gh` call, and no label change from the MCP server (Q5). Idempotency is
  caller-supplied `idempotency_key` (Q17/Q18 recommendation): same key and
  same canonical payload returns the prior submission; same key with a
  different payload returns `idempotency_conflict`.
- Result shape is the dispatch-contract envelope with additive `session_id`
  (resume), `review` (submit), and `cost_status` (Q20 recommendation);
  artifacts are structured `{ref, sha256}` (Q19 recommendation), accepting
  plain strings as legacy input and normalizing.

Lifecycle rejections raise `RunLifecycleError` with a stable `code` from
`LIFECYCLE_CODES`; `protocol.py` maps it to JSON-RPC `-32003` with the code
in `error.data.code` and audits it as `rejected:lifecycle:<code>` (AC9,
AC10). Invalid arguments raise `InvalidArgumentsError`, mapped to `-32602`.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .mandate import CallContext, compute_scope_fingerprint

# Terminal dispatch statuses (dispatch-contract.md). `review_submitted` is a
# run-store state, not a dispatch status.
TERMINAL_STATUSES = frozenset({
    "succeeded", "failed", "timed_out", "budget_exceeded", "blocked", "cancelled",
})
# Statuses a run may be resumed from (Q12): fresh (no prior turn) or last
# turn blocked/failed/timed_out. `succeeded` and `cancelled` are terminal.
RESUMABLE_LAST_STATUSES = frozenset({"blocked", "failed", "timed_out"})

# Stable lifecycle error codes (spec "Stable errors" section; AC10). The
# JSON-RPC `-32003` transport carries one of these in `error.data.code`.
CODE_RUN_NOT_FOUND = "run_not_found"
CODE_ISSUE_REF_MISMATCH = "issue_ref_mismatch"
CODE_CLAIM_CONFLICT = "claim_conflict"
CODE_RUN_NOT_RESUMABLE = "run_not_resumable"
CODE_SESSION_ID_UNAVAILABLE = "session_id_unavailable"
CODE_ENGINE_NOT_REGISTERED = "engine_not_registered"
CODE_ADAPTER_FAILED = "adapter_failed"
CODE_RESULT_ENVELOPE_INVALID = "result_envelope_invalid"
CODE_RESULT_NOT_TERMINAL = "result_not_terminal"
CODE_RESULT_CORRELATION_MISMATCH = "result_correlation_mismatch"
CODE_REVIEW_ALREADY_SUBMITTED = "review_already_submitted"
CODE_IDEMPOTENCY_CONFLICT = "idempotency_conflict"
CODE_LIFECYCLE_NOT_CONFIGURED = "lifecycle_not_configured"
LIFECYCLE_CODES = frozenset({
    CODE_RUN_NOT_FOUND, CODE_ISSUE_REF_MISMATCH, CODE_CLAIM_CONFLICT,
    CODE_RUN_NOT_RESUMABLE, CODE_SESSION_ID_UNAVAILABLE,
    CODE_ENGINE_NOT_REGISTERED, CODE_ADAPTER_FAILED,
    CODE_RESULT_ENVELOPE_INVALID, CODE_RESULT_NOT_TERMINAL,
    CODE_RESULT_CORRELATION_MISMATCH, CODE_REVIEW_ALREADY_SUBMITTED,
    CODE_IDEMPOTENCY_CONFLICT, CODE_LIFECYCLE_NOT_CONFIGURED,
})

ISSUE_REF_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+$")
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$")
SESSION_DIR_RE = re.compile(r"^session_[0-9a-f]{32}$")


class RunLifecycleError(RuntimeError):
    """A lifecycle/state conflict, mapped by `protocol.py` to JSON-RPC
    `-32003` with `error.data.code` set to `self.code` (AC10)."""

    def __init__(self, code: str, message: str, *, run_id: str | None = None) -> None:
        if code not in LIFECYCLE_CODES:
            raise ValueError(f"unknown lifecycle code: {code!r}")
        self.code = code
        self.message = message
        self.run_id = run_id
        super().__init__(message)


class InvalidArgumentsError(ValueError):
    """A strict-schema or argument-validation failure, mapped by
    `protocol.py` to JSON-RPC `-32602` (AC10)."""


# --- Strict per-tool JSON schemas (AC1). ------------------------------------
# `additionalProperties: false` and `required` make these strict: an unknown
# key or a missing required key is a schema failure, not a silent ignore.

CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issue_ref": {"type": "string"},
        "task_id": {"type": "string"},
        "workflow": {"type": "string"},
        "worker_role": {"type": "string"},
        "scope": {"type": "string", "minLength": 1},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "engine_id": {"type": "string"},
        "profile": {"type": "string"},
        "max_runtime_seconds": {"type": "integer", "minimum": 1},
        "max_cost_usd": {"type": "number", "minimum": 0},
        "max_parallel_workers": {"type": "integer", "minimum": 1},
        "delegation_depth": {"type": "integer", "minimum": 0},
        "artifact_policy": {"type": "object"},
        "approval_ref": {"type": "string"},
        "data_class": {"type": "string"},
        "estimated_cost_usd": {"type": "number", "minimum": 0},
        "prompt": {"type": "string", "minLength": 1},
        "model": {"type": ["string", "null"]},
        "provider": {"type": ["string", "null"]},
        "worktree": {"type": ["string", "null"]},
    },
    "required": [
        "issue_ref", "task_id", "workflow", "worker_role", "scope",
        "acceptance_criteria", "engine_id", "profile", "max_runtime_seconds",
        "max_cost_usd", "max_parallel_workers", "delegation_depth",
        "artifact_policy", "approval_ref", "data_class", "estimated_cost_usd",
        "prompt",
    ],
    "additionalProperties": False,
}

RESUME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "pattern": "^[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$"},
        "issue_ref": {"type": "string"},
        "prompt": {"type": "string", "minLength": 1},
        "max_runtime_seconds": {"type": "integer", "minimum": 1},
        "data_class": {"type": "string"},
        "estimated_cost_usd": {"type": "number", "minimum": 0},
        "model": {"type": ["string", "null"]},
        "provider": {"type": ["string", "null"]},
    },
    "required": [
        "run_id", "issue_ref", "prompt", "max_runtime_seconds", "data_class",
        "estimated_cost_usd",
    ],
    "additionalProperties": False,
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "pattern": "^[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$"},
        "issue_ref": {"type": "string"},
        "result": {"type": "object"},
        "review_kind": {"type": "string", "enum": ["independent"]},
        "idempotency_key": {"type": "string", "minLength": 1},
        "data_class": {"type": "string"},
        "estimated_cost_usd": {"type": "number", "minimum": 0},
        "max_runtime_seconds": {"type": "integer", "minimum": 0},
    },
    "required": [
        "run_id", "issue_ref", "result", "review_kind", "idempotency_key",
        "data_class",
    ],
    "additionalProperties": False,
}

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "cortxt_run_create": CREATE_SCHEMA,
    "cortxt_run_resume": RESUME_SCHEMA,
    "cortxt_run_submit_for_review": REVIEW_SCHEMA,
}

RUN_TOOLS = frozenset(TOOL_SCHEMAS)

# Keys whose content must never be copied into the audit ledger or run
# events (spec "Audit contract": prompt/scope/acceptance_criteria/result/
# artifacts/evidence are sensitive; the mandate and context are removed by
# protocol.py before handlers run).
_SENSITIVE_RUN_KEYS = frozenset({
    "prompt", "scope", "acceptance_criteria", "result", "artifacts",
    "evidence", "mandate", "mandate_context",
})


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def validate_schema(tool: str, arguments: Mapping[str, Any]) -> None:
    """Strict schema validation (AC1/AC10). Raises
    `InvalidArgumentsError` on any violation: unknown key, missing required
    key, wrong type, or a numeric bound violation. Booleans are rejected for
    integer/number fields because `bool` is an `int` subclass in Python
    (AC4: boolean runtime/cost values fail closed)."""
    schema = TOOL_SCHEMAS.get(tool)
    if schema is None:
        raise InvalidArgumentsError(f"no schema registered for tool {tool!r}")
    properties = schema["properties"]
    required = schema.get("required", [])

    if not isinstance(arguments, dict):
        raise InvalidArgumentsError("arguments must be an object")

    unknown = set(arguments) - set(properties)
    if unknown:
        raise InvalidArgumentsError(f"unknown argument(s): {', '.join(sorted(unknown))}")
    missing = [key for key in required if key not in arguments]
    if missing:
        raise InvalidArgumentsError(f"missing required argument(s): {', '.join(missing)}")

    for key, value in arguments.items():
        prop = properties[key]
        _validate_value(key, value, prop)


def _validate_value(key: str, value: Any, prop: dict[str, Any]) -> None:
    expected = prop.get("type")
    types = expected if isinstance(expected, list) else [expected]

    if value is None:
        if "null" in types:
            return
        raise InvalidArgumentsError(f"argument {key!r} must not be null")

    if "object" in types:
        if not isinstance(value, dict):
            raise InvalidArgumentsError(f"argument {key!r} must be an object")
        return
    if "array" in types:
        if not isinstance(value, list):
            raise InvalidArgumentsError(f"argument {key!r} must be an array")
        item_schema = prop.get("items", {})
        for item in value:
            if item_schema.get("type") == "string" and not isinstance(item, str):
                raise InvalidArgumentsError(f"argument {key!r} items must be strings")
        if "minItems" in prop and len(value) < prop["minItems"]:
            raise InvalidArgumentsError(f"argument {key!r} must have at least {prop['minItems']} item(s)")
        return

    if "string" in types:
        if not isinstance(value, str):
            raise InvalidArgumentsError(f"argument {key!r} must be a string")
        if "minLength" in prop and len(value) < prop["minLength"]:
            raise InvalidArgumentsError(f"argument {key!r} must not be empty")
        if "pattern" in prop and not re.search(prop["pattern"], value):
            raise InvalidArgumentsError(f"argument {key!r} does not match the required pattern")
        if "enum" in prop and value not in prop["enum"]:
            raise InvalidArgumentsError(
                f"argument {key!r} must be one of: {', '.join(prop['enum'])}")
        return

    if "integer" in types or "number" in types:
        # bool is an int subclass; booleans are never valid numerics (AC4).
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidArgumentsError(f"argument {key!r} must be a number")
        if "integer" in types and isinstance(value, float) and not value.is_integer():
            raise InvalidArgumentsError(f"argument {key!r} must be an integer")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise InvalidArgumentsError(f"argument {key!r} must be a finite number") from error
        if number != number or number in (float("inf"), float("-inf")):
            raise InvalidArgumentsError(f"argument {key!r} must be a finite number")
        if "minimum" in prop and number < prop["minimum"]:
            raise InvalidArgumentsError(f"argument {key!r} must be >= {prop['minimum']}")
        return

    raise InvalidArgumentsError(f"argument {key!r} has an unsupported schema type")


def _validate_issue_ref(value: str) -> None:
    if not isinstance(value, str) or not ISSUE_REF_RE.fullmatch(value):
        raise InvalidArgumentsError(
            "issue_ref must be exactly owner/repo#number")


def _validate_run_id(value: str) -> None:
    if not isinstance(value, str) or not RUN_ID_RE.fullmatch(value):
        raise InvalidArgumentsError("run_id is not a valid run identifier")


def _normalize_artifact(item: Any) -> dict[str, Any]:
    """Q19: accept a plain string ref (legacy ResultEnvelope shape) or a
    structured `{ref, sha256}` object; normalize to the structured form."""
    if isinstance(item, str):
        return {"ref": item, "sha256": None}
    if isinstance(item, dict) and isinstance(item.get("ref"), str):
        sha = item.get("sha256")
        return {"ref": item["ref"], "sha256": sha if isinstance(sha, str) else None}
    raise InvalidArgumentsError("artifact entries must be a ref string or {ref, sha256}")


def _result_cost(result: Mapping[str, Any]) -> float:
    raw = result.get("cost", 0.0)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise InvalidArgumentsError("result.cost must be a number")
    cost = float(raw)
    if cost != cost or cost in (float("inf"), float("-inf")) or cost < 0:
        raise InvalidArgumentsError("result.cost must be a finite non-negative number")
    return cost


def _result_status(result: Mapping[str, Any]) -> str:
    status = result.get("status")
    if not isinstance(status, str) or status not in TERMINAL_STATUSES:
        raise InvalidArgumentsError(
            f"result.status must be one of: {', '.join(sorted(TERMINAL_STATUSES))}")
    return status


def generate_run_id(clock: Callable[[], datetime]) -> str:
    """Server-generated run identity in `scripts/dispatcher.py` format
    (Q4/Q15): `%Y%m%dT%H%M%SZ_<8-hex>`. Generated outside the model."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock().timestamp()))
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def generate_review_submission_id() -> str:
    return "review_" + uuid.uuid4().hex


def canonical_payload(value: Any) -> str:
    """Canonical serialization used for idempotency comparisons. Same
    scheme as `runtime.session_state.canonical_json` (sorted keys, fixed
    separators, no NaN)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _session_dir(store: Path, session_id: str) -> Path:
    if not SESSION_DIR_RE.fullmatch(session_id):
        raise RunLifecycleError(CODE_RUN_NOT_FOUND, f"invalid session id {session_id!r}")
    return store / session_id / "session.json"


def _load_session(store: Path, session_id: str) -> dict:
    from runtime import session_state as state

    try:
        return state.load(store, session_id)
    except state.SessionError as error:
        raise RunLifecycleError(CODE_RUN_NOT_FOUND, error.message) from error


def _scan_sessions(store: Path) -> list[dict]:
    """All run sessions in the store (one session per run), network-free.
    Each returned doc has `run_id`/`issue_id` in its `session.created`
    payload. O(n) in total session history; fine at v0.1 scale, a candidate
    to revisit if the store grows large (documented in ADR-034)."""
    from runtime import session_state as state

    if not store.is_dir():
        return []
    found: list[dict] = []
    for session_path in store.glob("session_*/session.json"):
        session_id = session_path.parent.name
        try:
            doc = state.load(store, session_id)
        except state.SessionError:
            continue  # unreadable/corrupt session is not this run's problem to fail on
        created = doc["events"][0]["payload"]
        if "run_id" in created:
            found.append(doc)
    return found


def _run_events(doc: dict) -> list[dict]:
    return [event["payload"] for event in doc["events"]
            if event["event_type"] in {"run.created", "run.engine_turn", "run.review_submitted"}]


def _find_run(store: Path, run_id: str) -> tuple[str, dict] | None:
    """(session_id, session doc) for a run_id, or None."""
    for doc in _scan_sessions(store):
        created = doc["events"][0]["payload"]
        if created.get("run_id") == run_id:
            return doc["session_id"], doc
    return None


def _active_run_for_issue(store: Path, issue_ref: str) -> dict | None:
    """An existing non-terminal, non-submitted run for the same issue
    (claim conflict). A `review_submitted` run has finished its claim, so
    it does not block a new create for the same issue."""
    for doc in _scan_sessions(store):
        created = doc["events"][0]["payload"]
        if created.get("issue_id") != issue_ref:
            continue
        status = _last_run_status(doc)
        if status not in TERMINAL_STATUSES and status != "review_submitted":
            return doc
    return None


def _last_run_status(doc: dict) -> str:
    """Last recorded run status: `review_submitted` once a review has been
    submitted, else the most recent engine-turn result status, else
    `created` for a fresh run."""
    for event in reversed(doc["events"]):
        if event["event_type"] == "run.review_submitted":
            return "review_submitted"
        if event["event_type"] == "run.engine_turn":
            return event["payload"].get("status", "failed")
    return "created"


def _last_engine_turn(doc: dict) -> dict | None:
    events = [event["payload"] for event in doc["events"]
              if event["event_type"] == "run.engine_turn"]
    return events[-1] if events else None


def _run_identity(doc: dict) -> dict[str, Any]:
    """Durable run identity derived from the session without parsing any
    engine-native session id (Q15, AC6): engine, profile, cwd/worktree, and
    the opaque engine `session_id` come from the stored events."""
    created = doc["events"][0]["payload"]
    run_created = next((e["payload"] for e in doc["events"]
                        if e["event_type"] == "run.created"), {})
    turn = _last_engine_turn(doc)
    engine = (turn or {}).get("engine_id") or created.get("runtime") or "hermes"
    profile = (turn or {}).get("profile") or run_created.get("profile") or "builder"
    session_id = (turn or {}).get("session_id") if turn else None
    return {
        "run_id": created.get("run_id"),
        "issue_ref": created.get("issue_id"),
        "engine_id": engine,
        "profile": profile,
        "session_id": session_id,
        "scope_fingerprint": run_created.get("scope_fingerprint"),
        "worktree": run_created.get("worktree"),
        "status": _last_run_status(doc),
        "max_runtime_seconds": run_created.get("max_runtime_seconds"),
        "max_cost_usd": run_created.get("max_cost_usd"),
        "worker_role": created.get("worker_role"),
    }


@dataclass
class RunLifecycleService:
    """The lifecycle service behind the three thin MCP handlers. All
    dependencies are injectable for network-free tests (AC11): a fake
    `EngineContext` with fake adapters, a `tmp_path` store, and a fixed
    clock. Production wiring lives in `cortxt_mcp.server.serve()`."""

    engine_context: Any
    store: Path
    clock: Callable[[], datetime] = field(default=_default_clock)

    @classmethod
    def with_defaults(cls) -> "RunLifecycleService":
        from runtime.default_engine_context import build_default_engine_context
        from pathlib import Path as _Path

        agent_platform_dir = _Path(__file__).resolve().parent.parent
        return cls(
            engine_context=build_default_engine_context(),
            store=agent_platform_dir / ".sessions",
        )

    # --- Authoritative call context (AC3) ---------------------------------

    def build_call_context(self, tool: str, arguments: Mapping[str, Any]) -> CallContext:
        """Derive the authoritative `CallContext` from validated arguments
        and durable state -- never from client `mandate_context` (Q7).
        Called by `protocol.py` before verification; for resume/submit it
        resolves the run read-only to bind the stored scope fingerprint."""
        validate_schema(tool, arguments)
        if tool == "cortxt_run_create":
            _validate_issue_ref(arguments["issue_ref"])
            return CallContext(
                issue_ref=arguments["issue_ref"],
                data_class=arguments["data_class"],
                estimated_cost_usd=float(arguments["estimated_cost_usd"]),
                estimated_runtime_seconds=float(arguments["max_runtime_seconds"]),
                expected_scope_fingerprint=compute_scope_fingerprint(arguments["scope"]),
            )
        if tool == "cortxt_run_resume":
            _validate_issue_ref(arguments["issue_ref"])
            run = self._resolve_for_context(arguments["run_id"])
            return CallContext(
                issue_ref=arguments["issue_ref"],
                data_class=arguments["data_class"],
                estimated_cost_usd=float(arguments["estimated_cost_usd"]),
                estimated_runtime_seconds=float(arguments["max_runtime_seconds"]),
                expected_scope_fingerprint=run["scope_fingerprint"],
            )
        if tool == "cortxt_run_submit_for_review":
            _validate_issue_ref(arguments["issue_ref"])
            run = self._resolve_for_context(arguments["run_id"])
            result = arguments["result"]
            _result_status(result)
            return CallContext(
                issue_ref=arguments["issue_ref"],
                data_class=arguments["data_class"],
                estimated_cost_usd=_result_cost(result),
                estimated_runtime_seconds=float(arguments.get("max_runtime_seconds", 1)),
                expected_scope_fingerprint=run["scope_fingerprint"],
            )
        raise InvalidArgumentsError(f"unknown lifecycle tool {tool!r}")

    def _resolve_for_context(self, run_id: str) -> dict[str, Any]:
        """Read-only run resolution used to build call context before
        verification (spec "Tool 2": resolves the run read-only)."""
        _validate_run_id(run_id)
        found = _find_run(self.store, run_id)
        if found is None:
            raise RunLifecycleError(CODE_RUN_NOT_FOUND, f"run {run_id} was not found", run_id=run_id)
        _session_id, doc = found
        identity = _run_identity(doc)
        if identity["scope_fingerprint"] is None:
            raise RunLifecycleError(CODE_RUN_NOT_FOUND,
                                    f"run {run_id} has no stored scope fingerprint", run_id=run_id)
        return identity

    # --- Tool operations ---------------------------------------------------

    def create_run(self, arguments: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
        """AC5: create exactly one durable run identity outside the model,
        record issue/scope/limits/selected engine and the returned opaque
        `session_id`, and return a dispatch-contract envelope with the new
        `run_id`. Synchronous for v1 (Q3 recommendation): the engine broker
        is invoked and its terminal result returned."""
        validate_schema("cortxt_run_create", arguments)
        _validate_issue_ref(arguments["issue_ref"])
        _check_binding(binding, issue_ref=arguments["issue_ref"],
                       scope_fingerprint=compute_scope_fingerprint(arguments["scope"]))

        issue_ref = arguments["issue_ref"]
        if _active_run_for_issue(self.store, issue_ref) is not None:
            raise RunLifecycleError(
                CODE_CLAIM_CONFLICT,
                f"an active run already exists for issue {issue_ref}", run_id=None)

        run_id = generate_run_id(self.clock)
        engine_id = arguments["engine_id"]
        broker = self.engine_context.get(engine_id)
        if not broker.has_provider:
            raise RunLifecycleError(
                CODE_ENGINE_NOT_REGISTERED,
                f"engine {engine_id!r} has no registered adapter", run_id=run_id)

        started_at = self.clock().isoformat()
        run_created = {
            "run_id": run_id,
            "issue_ref": issue_ref,
            "scope_fingerprint": binding["scope_fingerprint"],
            "engine_id": engine_id,
            "profile": arguments["profile"],
            "data_class": arguments["data_class"],
            "max_runtime_seconds": int(arguments["max_runtime_seconds"]),
            "max_cost_usd": float(arguments["max_cost_usd"]),
            "max_parallel_workers": int(arguments["max_parallel_workers"]),
            "delegation_depth": int(arguments["delegation_depth"]),
            "artifact_policy": dict(arguments["artifact_policy"]),
            "approval_ref": arguments["approval_ref"],
            "model": arguments.get("model"),
            "provider": arguments.get("provider"),
            "worktree": arguments.get("worktree"),
        }

        from runtime import session_state as state

        session = state.create(
            self.store,
            task_id=arguments["task_id"],
            run_id=run_id,
            issue_id=issue_ref,
            worker_role=arguments["worker_role"],
            runtime=engine_id,
        )
        session_id = session["session_id"]
        state.append(self.store, session_id, 0, "run.created", run_created)

        try:
            result = broker.invoke(
                arguments["profile"], arguments["prompt"],
                timeout_seconds=int(arguments["max_runtime_seconds"]),
                model=arguments.get("model"), provider=arguments.get("provider"),
                cwd=Path(arguments["worktree"]) if arguments.get("worktree") else None,
                session_id=None,
            )
        except Exception as error:
            self._append_engine_turn(
                session_id, run_created, run_id, {},
                error={"category": CODE_ADAPTER_FAILED, "message": str(error)})
            raise RunLifecycleError(
                CODE_ADAPTER_FAILED, f"engine adapter failed: {error}", run_id=run_id) from error

        if not isinstance(result, dict):
            self._append_engine_turn(
                session_id, run_created, run_id, {},
                error={"category": CODE_ADAPTER_FAILED, "message": "adapter returned a non-dict result"})
            raise RunLifecycleError(
                CODE_ADAPTER_FAILED, "engine adapter returned a non-dict result", run_id=run_id)

        self._append_engine_turn(session_id, run_created, run_id, result)
        return self._envelope(
            issue_ref=issue_ref, run_id=run_id, session_id=result.get("session_id"),
            engine_id=engine_id, profile=arguments["profile"],
            worker_role=arguments["worker_role"], started_at=started_at,
            result=result, model=arguments.get("model"), provider=arguments.get("provider"),
        )

    def resume_run(self, arguments: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
        """AC6: load the named `run_id`, reject an unknown or non-resumable
        run, verify the same issue and bound scope, and call the stored
        engine broker with the stored opaque `session_id`. Never
        substitutes a client-provided engine, profile, or session id."""
        validate_schema("cortxt_run_resume", arguments)
        _validate_issue_ref(arguments["issue_ref"])
        _validate_run_id(arguments["run_id"])
        _check_binding(binding, issue_ref=arguments["issue_ref"])

        run_id = arguments["run_id"]
        found = _find_run(self.store, run_id)
        if found is None:
            raise RunLifecycleError(CODE_RUN_NOT_FOUND, f"run {run_id} was not found", run_id=run_id)
        session_id, doc = found
        identity = _run_identity(doc)

        if identity["issue_ref"] != arguments["issue_ref"]:
            raise RunLifecycleError(
                CODE_ISSUE_REF_MISMATCH,
                f"run {run_id} belongs to issue {identity['issue_ref']}, not {arguments['issue_ref']}",
                run_id=run_id)

        status = identity["status"]
        if status in TERMINAL_STATUSES and status not in RESUMABLE_LAST_STATUSES:
            raise RunLifecycleError(
                CODE_RUN_NOT_RESUMABLE,
                f"run {run_id} is {status} and cannot be resumed", run_id=run_id)

        engine_id = identity["engine_id"]
        profile = identity["profile"]
        if identity["session_id"] is None and status != "created":
            raise RunLifecycleError(
                CODE_SESSION_ID_UNAVAILABLE,
                f"run {run_id} has no engine session id to resume", run_id=run_id)

        broker = self.engine_context.get(engine_id)
        if not broker.has_provider:
            raise RunLifecycleError(
                CODE_ENGINE_NOT_REGISTERED,
                f"engine {engine_id!r} has no registered adapter", run_id=run_id)

        started_at = self.clock().isoformat()
        try:
            result = broker.invoke(
                profile, arguments["prompt"],
                timeout_seconds=int(arguments["max_runtime_seconds"]),
                model=arguments.get("model"), provider=arguments.get("provider"),
                cwd=Path(identity["worktree"]) if identity.get("worktree") else None,
                session_id=identity["session_id"],
            )
        except Exception as error:
            self._append_engine_turn(
                session_id, {"run_id": run_id, "engine_id": engine_id, "profile": profile},
                run_id, {},
                error={"category": CODE_ADAPTER_FAILED, "message": str(error)})
            raise RunLifecycleError(
                CODE_ADAPTER_FAILED, f"engine adapter failed: {error}", run_id=run_id) from error

        if not isinstance(result, dict):
            self._append_engine_turn(
                session_id, {"run_id": run_id, "engine_id": engine_id, "profile": profile},
                run_id, {},
                error={"category": CODE_ADAPTER_FAILED, "message": "adapter returned a non-dict result"})
            raise RunLifecycleError(
                CODE_ADAPTER_FAILED, "engine adapter returned a non-dict result", run_id=run_id)

        self._append_engine_turn(
            session_id, {"run_id": run_id, "engine_id": engine_id, "profile": profile},
            run_id, result)
        return self._envelope(
            issue_ref=identity["issue_ref"], run_id=run_id,
            session_id=result.get("session_id") or identity["session_id"],
            engine_id=engine_id, profile=profile,
            worker_role=identity.get("worker_role") or "builder",
            started_at=started_at, result=result,
            model=arguments.get("model"), provider=arguments.get("provider"),
        )

    def submit_for_review(self, arguments: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
        """AC7: accept only a complete result envelope whose `issue_id` and
        `run_id` match durable state, record an idempotent review
        submission, return its review reference/status, and never mark the
        issue or run done (Q5)."""
        validate_schema("cortxt_run_submit_for_review", arguments)
        _validate_issue_ref(arguments["issue_ref"])
        _validate_run_id(arguments["run_id"])
        _check_binding(binding, issue_ref=arguments["issue_ref"])

        run_id = arguments["run_id"]
        result = arguments["result"]
        if not isinstance(result, dict):
            raise RunLifecycleError(CODE_RESULT_ENVELOPE_INVALID,
                                    "result must be a dispatch-contract envelope object", run_id=run_id)

        found = _find_run(self.store, run_id)
        if found is None:
            raise RunLifecycleError(CODE_RUN_NOT_FOUND, f"run {run_id} was not found", run_id=run_id)
        session_id, doc = found
        identity = _run_identity(doc)

        if identity["issue_ref"] != arguments["issue_ref"]:
            raise RunLifecycleError(
                CODE_ISSUE_REF_MISMATCH,
                f"run {run_id} belongs to issue {identity['issue_ref']}, not {arguments['issue_ref']}",
                run_id=run_id)

        result_status = _result_status(result)
        if result.get("issue_id") != arguments["issue_ref"] or result.get("run_id") != run_id:
            raise RunLifecycleError(
                CODE_RESULT_CORRELATION_MISMATCH,
                "result issue_id/run_id do not match the run being submitted", run_id=run_id)

        idempotency_key = arguments["idempotency_key"]
        prior = self._find_review_submission(doc, idempotency_key)
        if prior is not None:
            if prior["payload_hash"] == _payload_hash(result):
                return self._review_envelope(identity, prior["review_submission_id"], prior["submitted_at"])
            raise RunLifecycleError(
                CODE_IDEMPOTENCY_CONFLICT,
                f"idempotency_key {idempotency_key!r} was already used for a different payload",
                run_id=run_id)

        review_submission_id = generate_review_submission_id()
        submitted_at = self.clock().isoformat()
        event_payload = {
            "review_submission_id": review_submission_id,
            "review_kind": arguments["review_kind"],
            "idempotency_key": idempotency_key,
            "result_status": result_status,
            "submitted_at": submitted_at,
            "payload_hash": _payload_hash(result),
        }
        from runtime import session_state as state

        current = state.load(self.store, session_id)
        state.append(self.store, session_id, len(current["events"]) - 1,
                     "run.review_submitted", event_payload)
        return self._review_envelope(identity, review_submission_id, submitted_at)

    # --- Internals ---------------------------------------------------------

    def _find_review_submission(self, doc: dict, idempotency_key: str) -> dict | None:
        for event in doc["events"]:
            if event["event_type"] != "run.review_submitted":
                continue
            payload = event["payload"]
            if payload.get("idempotency_key") == idempotency_key:
                return payload
        return None

    def _append_engine_turn(self, session_id: str, run_created: Mapping[str, Any],
                            run_id: str, result: Mapping[str, Any] | None,
                            *, error: dict[str, Any] | None = None) -> None:
        from runtime import session_state as state

        result = result or {}
        turn = {
            "run_id": run_id,
            "engine_id": run_created.get("engine_id") or run_created.get("runtime"),
            "profile": run_created.get("profile"),
            "status": result.get("status", "failed") if error is None else "failed",
            "session_id": result.get("session_id"),
            "model": result.get("model"),
            "provider": result.get("provider"),
            "usage": result.get("usage") if isinstance(result.get("usage"), dict) else {},
            "cost": _safe_cost(result.get("cost")),
            "cost_status": result.get("cost_status", "unknown"),
            "artifacts": _safe_artifacts(result.get("artifacts")),
            "evidence": result.get("evidence") if isinstance(result.get("evidence"), list) else [],
            "error": error or result.get("error") if isinstance(result.get("error"), dict) else None,
        }
        doc = state.load(self.store, session_id)
        state.append(self.store, session_id, len(doc["events"]) - 1, "run.engine_turn", turn)

    def _envelope(self, *, issue_ref: str, run_id: str, session_id: Any,
                  engine_id: str, profile: str, worker_role: str, started_at: str,
                  result: Mapping[str, Any], model: str | None, provider: str | None) -> dict[str, Any]:
        status = result.get("status")
        if not isinstance(status, str) or status not in TERMINAL_STATUSES:
            status = "failed"
        return {
            "issue_id": issue_ref,
            "run_id": run_id,
            "status": status,
            "runtime": f"{engine_id}/v0.1",
            "worker_role": profile or worker_role,
            "started_at": started_at,
            "finished_at": self.clock().isoformat(),
            "model": result.get("model") or model,
            "usage": result.get("usage") if isinstance(result.get("usage"), dict) else {},
            "cost": _safe_cost(result.get("cost")),
            "cost_currency": "USD",
            "cost_status": result.get("cost_status", "unknown"),
            "artifacts": _safe_artifacts(result.get("artifacts")),
            "evidence": result.get("evidence") if isinstance(result.get("evidence"), list) else [],
            "error": result.get("error") if isinstance(result.get("error"), dict) else None,
            "session_id": session_id,
            "review": None,
        }

    def _review_envelope(self, identity: Mapping[str, Any], review_submission_id: str,
                         submitted_at: str) -> dict[str, Any]:
        return {
            "issue_id": identity["issue_ref"],
            "run_id": identity["run_id"],
            "status": "succeeded",
            "runtime": "cortxt-mcp/v0.1",
            "worker_role": identity.get("worker_role") or "coordinator",
            "started_at": None,
            "finished_at": self.clock().isoformat(),
            "model": None,
            "usage": {},
            "cost": 0.0,
            "cost_currency": "USD",
            "cost_status": "unknown",
            "artifacts": [],
            "evidence": [],
            "error": None,
            "session_id": identity.get("session_id"),
            "review": {
                "review_id": review_submission_id,
                "kind": "independent",
                "status": "submitted",
                "submitted_at": submitted_at,
            },
        }


def _check_binding(binding: Mapping[str, Any], *, issue_ref: str,
                   scope_fingerprint: str | None = None) -> None:
    """Defense in depth: the verified envelope's binding must agree with the
    validated arguments (Q7: binding fields come from the VERIFIED envelope;
    the tool-level scope-fingerprint check closes ADR-032's 'omit to skip'
    gap for run creation)."""
    if binding.get("issue_ref") != issue_ref:
        raise RunLifecycleError(
            CODE_ISSUE_REF_MISMATCH,
            f"mandate issue_ref {binding.get('issue_ref')!r} does not match {issue_ref!r}")
    if scope_fingerprint is not None and binding.get("scope_fingerprint") != scope_fingerprint:
        from .mandate import REASON_SCOPE_FINGERPRINT_MISMATCH
        raise RunLifecycleError(
            CODE_ISSUE_REF_MISMATCH, REASON_SCOPE_FINGERPRINT_MISMATCH)


def _payload_hash(result: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(result).encode("utf-8")).hexdigest()


def _safe_cost(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    cost = float(value)
    if cost != cost or cost in (float("inf"), float("-inf")):
        return 0.0
    return cost


def _safe_artifacts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        try:
            normalized.append(_normalize_artifact(item))
        except InvalidArgumentsError:
            continue
    return normalized
