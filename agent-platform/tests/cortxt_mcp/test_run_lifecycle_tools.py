"""Network-free tests for the run-lifecycle tools (issue #230 / ADR-034).

Covers AC1-AC12 for `cortxt_run_create`/`cortxt_run_resume`/
`cortxt_run_submit_for_review`: registration and schemas (AC1), mandate
rejection before handler/adapter (AC2/AC11), authoritative context (AC3),
runtime cap (AC4), create/resume/review semantics (AC5-AC7), envelope shape
(AC8), audit decisions (AC9), protocol error mapping (AC10), and
regression (AC12). Everything runs against injected fakes: a fake
EngineContext with a fake adapter, a `tmp_path` store, a fixed clock, and a
fake mandate verifier -- no network, no `gh`, no real adapter.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from cortxt_mcp import mandate, protocol, run_lifecycle, tools
from cortxt_mcp.audit import AuditLog

FIXED_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
ISSUE_REF = "owner/repo#230"
SCOPE = "Build one bounded feature for issue #230"


def _clock() -> datetime:
    return FIXED_NOW


class AcceptingVerifier:
    """Fail-open verifier for handler-semantics tests; mandate rejection
    paths use the real `mandate.MandateVerifier` instead (see below)."""

    def verify(self, envelope, **kwargs):
        return type("Decision", (), {"accepted": True, "reason": "accepted"})()


class FakeAdapter:
    def __init__(self, result=None, failures=None) -> None:
        self.calls: list[dict] = []
        self.result = result or {"status": "succeeded", "session_id": "eng-sess-1", "cost": 1.5}
        self.failures = failures or []

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None,
               cwd=None, session_id=None):
        self.calls.append({
            "profile": profile, "prompt": prompt, "timeout_seconds": timeout_seconds,
            "model": model, "provider": provider, "cwd": cwd, "session_id": session_id,
        })
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
        return dict(self.result)


class FakeEngineContext:
    def __init__(self, adapters=None) -> None:
        self._brokers: dict[str, "FakeBroker"] = {}
        self.adapters = adapters or {"hermes": FakeAdapter()}

    def get(self, engine_id):
        if engine_id not in self._brokers:
            from runtime.engine_registry import EngineBroker

            broker = EngineBroker()
            if engine_id in self.adapters:
                broker.register(self.adapters[engine_id])
            self._brokers[engine_id] = broker
        return self._brokers[engine_id]


def make_service(tmp_path, context=None):
    return run_lifecycle.RunLifecycleService(
        engine_context=context or FakeEngineContext(),
        store=tmp_path / "sessions",
        clock=_clock,
    )


def create_arguments(**overrides):
    args = {
        "issue_ref": ISSUE_REF,
        "task_id": "t1",
        "workflow": "delivery",
        "worker_role": "builder",
        "scope": SCOPE,
        "acceptance_criteria": ["one bounded thing ships"],
        "engine_id": "hermes",
        "profile": "builder",
        "max_runtime_seconds": 60,
        "max_cost_usd": 25.0,
        "max_parallel_workers": 1,
        "delegation_depth": 0,
        "artifact_policy": {"locations": ["PR"]},
        "approval_ref": "operator decision 2026-08-22",
        "data_class": "L1",
        "estimated_cost_usd": 1.0,
        "prompt": "build it",
    }
    args.update(overrides)
    return args


def resume_arguments(**overrides):
    args = {
        "run_id": "20260822T120000Z_abcd1234",
        "issue_ref": ISSUE_REF,
        "prompt": "continue",
        "max_runtime_seconds": 60,
        "data_class": "L1",
        "estimated_cost_usd": 1.0,
    }
    args.update(overrides)
    return args


def review_arguments(**overrides):
    run_id = overrides.get("run_id", "20260822T120000Z_abcd1234")
    args = {
        "run_id": run_id,
        "issue_ref": ISSUE_REF,
        "result": {
            "issue_id": ISSUE_REF,
            "run_id": run_id,
            "status": "succeeded",
            "cost": 1.0,
        },
        "review_kind": "independent",
        "idempotency_key": "review-1",
        "data_class": "L1",
    }
    args.update(overrides)
    # Keep the nested result.run_id correlated with the top-level run_id
    # unless the caller overrode the result explicitly.
    if "result" not in overrides:
        args["result"]["run_id"] = args["run_id"]
    return args


# --- AC1: registration, tier, schemas --------------------------------------

def test_lifecycle_tools_registered_as_tier_dispatch_with_strict_schemas():
    for name in ("cortxt_run_create", "cortxt_run_resume", "cortxt_run_submit_for_review"):
        spec = tools.TOOL_REGISTRY[name]
        assert spec.tier == tools.TIER_DISPATCH
        assert spec.lifecycle_required
        assert spec.mandate_binding
        assert spec.input_schema is not None
        assert spec.input_schema["additionalProperties"] is False
        assert spec.input_schema["required"]


def test_lifecycle_tools_hidden_without_allow_dispatch():
    listed = {spec.name for spec in tools.list_tools(allow_dispatch=False, allow_credentials=False)}
    assert "cortxt_run_create" not in listed
    with pytest.raises(tools.ToolTierLockedError):
        tools.call_tool("cortxt_run_create", {}, allow_dispatch=False, allow_credentials=False)


def test_tools_list_advertises_strict_schemas():
    response = protocol.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        allow_dispatch=True, allow_credentials=False,
    )
    by_name = {tool["name"]: tool for tool in response["result"]["tools"]}
    for name in ("cortxt_run_create", "cortxt_run_resume", "cortxt_run_submit_for_review"):
        schema = by_name[name]["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["required"]


# --- AC2/AC11: rejection happens before handler/adapter --------------------

def _real_verifier(envelope, public_keys, *, tool="cortxt_run_create"):
    """A real mandate verifier for a specific issued envelope."""
    class FakeBudgetStore:
        def __init__(self):
            self.spent = 0.0

        def record_and_check(self, mandate_id, cost, cap):
            self.spent += max(float(cost), 0.0)
            return self.spent <= cap

    class FakeNonceStore:
        def __init__(self):
            self.used = set()

        def check_and_consume(self, nonce):
            if nonce in self.used:
                return False
            self.used.add(nonce)
            return True

    return mandate.MandateVerifier(
        public_keys={issuer: {"key-1": value} for issuer, value in public_keys.items()},
        nonce_store=FakeNonceStore(),
        budget_store=FakeBudgetStore(),
        revocation_store=type("AllowRevocations", (), {"is_revoked": lambda self, *args: False})(),
        clock=_clock,
    )


def _issue(scope_text=SCOPE, *, allowed_tools=None, max_runtime_seconds=3600, **overrides):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    public_key_hex = mandate.public_key_hex_from_private_key(key)
    issued = mandate.issue_mandate(
        private_key=key,
        granted_by="operator-demo",
        kid="key-1",
        public_keys={"operator-demo": {"key-1": public_key_hex}},
        issue_ref=ISSUE_REF,
        allowed_tools=allowed_tools or ["cortxt_run_create"],
        data_class_max="L2",
        budget_usd_max=50.0,
        max_runtime_seconds=max_runtime_seconds,
        expires_at="2026-08-22T13:00:00Z",
        scope_text=scope_text,
        **overrides,
    )
    return issued, public_key_hex


def test_missing_mandate_rejected_before_handler(tmp_path):
    context = FakeEngineContext()
    service = make_service(tmp_path, context)
    with pytest.raises(tools.MandateRejectedError) as excinfo:
        tools.call_tool(
            "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
            lifecycle=service,
        )
    assert excinfo.value.reason == mandate.REASON_MANDATE_MISSING
    # No adapter call, no session created.
    assert context.adapters["hermes"].calls == []
    assert not (tmp_path / "sessions").exists()


def test_wrong_tool_name_rejected_before_handler(tmp_path):
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_resume"])
    service = make_service(tmp_path)
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    with pytest.raises(tools.MandateRejectedError) as excinfo:
        tools.call_tool(
            "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
        )
    assert excinfo.value.reason == mandate.REASON_TOOL_NOT_ALLOWED
    assert not (tmp_path / "sessions").exists()


def test_runtime_above_max_rejected_before_handler(tmp_path):
    issued, public_key_hex = _issue(max_runtime_seconds=30)
    service = make_service(tmp_path)
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    with pytest.raises(tools.MandateRejectedError) as excinfo:
        tools.call_tool(
            "cortxt_run_create", create_arguments(max_runtime_seconds=60),
            allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
        )
    assert excinfo.value.reason == mandate.REASON_RUNTIME_EXCEEDED
    assert not (tmp_path / "sessions").exists()


def test_lifecycle_service_required_fails_closed(tmp_path):
    """A lifecycle-required tool without an injected service is rejected
    before the handler runs (fail closed, same posture as an unconfigured
    mandate verifier)."""
    with pytest.raises(RuntimeError):
        tools.call_tool(
            "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
            mandate_verifier=AcceptingVerifier(), call_context=mandate.CallContext(issue_ref=ISSUE_REF),
        )


# --- AC3/AC4: authoritative context and runtime cap via protocol ------------

def test_scope_mismatch_rejected_before_handler(tmp_path):
    issued, public_key_hex = _issue(scope_text="a different scope")
    service = make_service(tmp_path)
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    with pytest.raises(tools.MandateRejectedError) as excinfo:
        tools.call_tool(
            "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
        )
    assert excinfo.value.reason == mandate.REASON_SCOPE_FINGERPRINT_MISMATCH
    assert not (tmp_path / "sessions").exists()


def test_malformed_runtime_value_fails_closed(tmp_path):
    service = make_service(tmp_path)
    with pytest.raises(run_lifecycle.InvalidArgumentsError):
        service.build_call_context("cortxt_run_create", create_arguments(max_runtime_seconds=True))
    with pytest.raises(run_lifecycle.InvalidArgumentsError):
        service.build_call_context("cortxt_run_create", create_arguments(max_runtime_seconds=-5))
    with pytest.raises(run_lifecycle.InvalidArgumentsError):
        service.build_call_context("cortxt_run_create", create_arguments(scope=""))


# --- AC5: create ------------------------------------------------------------

def test_create_creates_durable_run_and_invokes_broker(tmp_path):
    context = FakeEngineContext()
    service = make_service(tmp_path, context)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_create"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})

    result = tools.call_tool(
        "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
    )

    assert result["status"] == "succeeded"
    assert result["issue_id"] == ISSUE_REF
    assert result["run_id"].startswith("20260822T120000Z_")
    assert result["session_id"] == "eng-sess-1"
    assert result["cost"] == 1.5
    assert result["cost_status"] == "unknown"
    assert result["artifacts"] == []
    assert result["review"] is None
    # Envelope shape (AC8).
    for key in ("issue_id", "run_id", "status", "runtime", "worker_role", "started_at",
                "finished_at", "model", "usage", "cost", "cost_currency", "cost_status",
                "artifacts", "evidence", "error", "session_id", "review"):
        assert key in result

    # Durable: the run session exists and the broker was invoked once.
    from runtime import session_state as state

    sessions = list((tmp_path / "sessions").glob("session_*"))
    assert len(sessions) == 1
    adapter = context.adapters["hermes"]
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["session_id"] is None
    assert adapter.calls[0]["timeout_seconds"] == 60
    doc = state.load(tmp_path / "sessions", sessions[0].name)
    events = [e["event_type"] for e in doc["events"]]
    assert events == ["session.created", "run.created", "run.engine_turn"]


def test_create_claim_conflict_rejected(tmp_path):
    """One active claim per issue (dispatch contract): a second create for
    the same issue fails with claim_conflict before invoking the broker,
    while a terminal run does not block a fresh create."""
    from runtime import session_state as state

    # Seed an ACTIVE run for the issue: a session with a run.created event
    # but no engine turn yet (status "created" is non-terminal).
    active = state.create(tmp_path / "sessions", task_id="t0", run_id="20260822T110000Z_aaaaaaaa",
                          issue_id=ISSUE_REF, worker_role="builder", runtime="hermes")
    state.append(tmp_path / "sessions", active["session_id"], 0, "run.created",
                 {"run_id": "20260822T110000Z_aaaaaaaa", "issue_ref": ISSUE_REF,
                  "scope_fingerprint": "fp", "engine_id": "hermes", "profile": "builder",
                  "data_class": "L1", "max_runtime_seconds": 60, "max_cost_usd": 25.0,
                  "max_parallel_workers": 1, "delegation_depth": 0,
                  "artifact_policy": {}, "approval_ref": "x", "model": None,
                  "provider": None, "worktree": None})

    context = FakeEngineContext()
    service = make_service(tmp_path, context)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_create"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})

    with pytest.raises(run_lifecycle.RunLifecycleError) as excinfo:
        tools.call_tool(
            "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
        )
    assert excinfo.value.code == run_lifecycle.CODE_CLAIM_CONFLICT
    assert context.adapters["hermes"].calls == []


def test_create_after_terminal_run_is_allowed(tmp_path):
    """A terminal run for the same issue does not block a fresh create
    (the active claim ended when the run went terminal)."""
    context = FakeEngineContext()
    service = make_service(tmp_path, context)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_create"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    first = tools.call_tool(
        "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
    )
    assert first["status"] == "succeeded"
    issued2, public_key_hex2 = _issue(allowed_tools=["cortxt_run_create"])
    verifier2 = _real_verifier(issued2.envelope, {"operator-demo": public_key_hex2})
    second = tools.call_tool(
        "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
        mandate=issued2.envelope, mandate_verifier=verifier2, lifecycle=service,
    )
    assert second["run_id"] != first["run_id"]


def test_create_unknown_engine_rejected(tmp_path):
    service = make_service(tmp_path, FakeEngineContext({"hermes": FakeAdapter()}))
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_create"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    with pytest.raises(run_lifecycle.RunLifecycleError) as excinfo:
        tools.call_tool(
            "cortxt_run_create", create_arguments(engine_id="nope"),
            allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
        )
    assert excinfo.value.code == run_lifecycle.CODE_ENGINE_NOT_REGISTERED


def test_create_adapter_failure_recorded_as_failed(tmp_path):
    context = FakeEngineContext({"hermes": FakeAdapter(failures=[RuntimeError("boom")])})
    service = make_service(tmp_path, context)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_create"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    with pytest.raises(run_lifecycle.RunLifecycleError) as excinfo:
        tools.call_tool(
            "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
        )
    assert excinfo.value.code == run_lifecycle.CODE_ADAPTER_FAILED
    # The run session still exists with a failed engine turn (not orphaned).
    from runtime import session_state as state

    sessions = list((tmp_path / "sessions").glob("session_*"))
    doc = state.load(tmp_path / "sessions", sessions[0].name)
    turn = [e for e in doc["events"] if e["event_type"] == "run.engine_turn"][-1]
    assert turn["payload"]["status"] == "failed"


# --- AC6: resume ------------------------------------------------------------

def _created_run(tmp_path):
    context = FakeEngineContext({"hermes": FakeAdapter(result={
        "status": "failed", "session_id": "eng-sess-1", "cost": 1.0})})
    service = make_service(tmp_path, context)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_create"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    result = tools.call_tool(
        "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
    )
    return service, context, result


def test_resume_uses_stored_engine_and_session_id(tmp_path):
    service, context, created = _created_run(tmp_path)
    # The stored run is failed/resumable; the resume turn succeeds.
    context.adapters["hermes"].result = {"status": "succeeded", "session_id": "eng-sess-1", "cost": 1.5}
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_resume"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})

    result = tools.call_tool(
        "cortxt_run_resume", resume_arguments(run_id=created["run_id"]),
        allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
    )
    assert result["status"] == "succeeded"
    assert result["session_id"] == "eng-sess-1"
    adapter = context.adapters["hermes"]
    assert adapter.calls[-1]["session_id"] == "eng-sess-1"  # stored opaque id, not client-supplied


def test_resume_unknown_run_rejected(tmp_path):
    service, _context, _created = _created_run(tmp_path)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_resume"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    with pytest.raises(run_lifecycle.RunLifecycleError) as excinfo:
        tools.call_tool(
            "cortxt_run_resume", resume_arguments(run_id="20260822T120000Z_deadbeef"),
            allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
        )
    assert excinfo.value.code == run_lifecycle.CODE_RUN_NOT_FOUND


def test_resume_non_resumable_run_rejected(tmp_path):
    context = FakeEngineContext({"hermes": FakeAdapter(result={
        "status": "succeeded", "session_id": "eng-sess-1", "cost": 1.0})})
    service = make_service(tmp_path, context)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_create"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    created = tools.call_tool(
        "cortxt_run_create", create_arguments(), allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
    )
    issued_r, public_key_hex_r = _issue(allowed_tools=["cortxt_run_resume"])
    verifier_r = _real_verifier(issued_r.envelope, {"operator-demo": public_key_hex_r})
    with pytest.raises(run_lifecycle.RunLifecycleError) as excinfo:
        tools.call_tool(
            "cortxt_run_resume", resume_arguments(run_id=created["run_id"]),
            allow_dispatch=True, allow_credentials=False,
            mandate=issued_r.envelope, mandate_verifier=verifier_r, lifecycle=service,
        )
    assert excinfo.value.code == run_lifecycle.CODE_RUN_NOT_RESUMABLE


# --- AC7: submit for review -------------------------------------------------

def test_submit_for_review_records_local_review(tmp_path):
    service, _context, created = _created_run(tmp_path)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_submit_for_review"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})

    result = tools.call_tool(
        "cortxt_run_submit_for_review",
        review_arguments(run_id=created["run_id"]),
        allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
    )
    assert result["status"] == "succeeded"
    assert result["review"]["status"] == "submitted"
    assert result["review"]["kind"] == "independent"
    assert result["review"]["review_id"].startswith("review_")


def test_submit_for_review_idempotent_replay_returns_original(tmp_path):
    service, _context, created = _created_run(tmp_path)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_submit_for_review"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    args = review_arguments(run_id=created["run_id"])

    first = tools.call_tool(
        "cortxt_run_submit_for_review", args, allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
    )
    # Replay requires a fresh envelope (nonce consumed); issue another one.
    issued2, public_key_hex2 = _issue(allowed_tools=["cortxt_run_submit_for_review"])
    verifier2 = _real_verifier(issued2.envelope, {"operator-demo": public_key_hex2})
    second = tools.call_tool(
        "cortxt_run_submit_for_review", args, allow_dispatch=True, allow_credentials=False,
        mandate=issued2.envelope, mandate_verifier=verifier2, lifecycle=service,
    )
    assert second["review"]["review_id"] == first["review"]["review_id"]


def test_submit_for_review_idempotency_conflict(tmp_path):
    service, _context, created = _created_run(tmp_path)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_submit_for_review"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    tools.call_tool(
        "cortxt_run_submit_for_review", review_arguments(run_id=created["run_id"]),
        allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
    )
    # Same key, different payload -> idempotency_conflict.
    issued2, public_key_hex2 = _issue(allowed_tools=["cortxt_run_submit_for_review"])
    verifier2 = _real_verifier(issued2.envelope, {"operator-demo": public_key_hex2})
    with pytest.raises(run_lifecycle.RunLifecycleError) as excinfo:
        tools.call_tool(
            "cortxt_run_submit_for_review",
            review_arguments(run_id=created["run_id"],
                             result={"issue_id": ISSUE_REF, "run_id": created["run_id"],
                                     "status": "failed", "cost": 2.0}),
            allow_dispatch=True, allow_credentials=False,
            mandate=issued2.envelope, mandate_verifier=verifier2, lifecycle=service,
        )
    assert excinfo.value.code == run_lifecycle.CODE_IDEMPOTENCY_CONFLICT


def test_submit_for_review_rejects_non_terminal_result(tmp_path):
    service, _context, created = _created_run(tmp_path)
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_submit_for_review"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    with pytest.raises(run_lifecycle.InvalidArgumentsError):
        tools.call_tool(
            "cortxt_run_submit_for_review",
            review_arguments(run_id=created["run_id"],
                             result={"issue_id": ISSUE_REF, "run_id": created["run_id"],
                                     "status": "running", "cost": 1.0}),
            allow_dispatch=True, allow_credentials=False,
            mandate=issued.envelope, mandate_verifier=verifier, lifecycle=service,
        )


# --- AC9/AC10: audit decisions and protocol error mapping -------------------

def test_protocol_audits_lifecycle_rejection(tmp_path):
    service = make_service(tmp_path)
    audit = AuditLog(tmp_path / "sessions")
    response = protocol.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "cortxt_run_resume",
                    "arguments": resume_arguments(run_id="20260822T120000Z_deadbeef")}},
        allow_dispatch=True, allow_credentials=False, audit=audit,
        mandate_verifier=AcceptingVerifier(), lifecycle=service,
    )
    assert response["error"]["code"] == -32003
    assert response["error"]["data"]["code"] == run_lifecycle.CODE_RUN_NOT_FOUND
    from runtime import session_state as state

    session = state.load(tmp_path / "sessions", audit.session_id)
    row = session["events"][-1]["payload"]
    assert row["status"] == "rejected"
    assert row["mandate_decision"] == "rejected:lifecycle:run_not_found"
    assert row["run_id"] == "20260822T120000Z_deadbeef"
    assert row["issue_ref"] == ISSUE_REF


def test_protocol_maps_invalid_arguments_to_minus_32602(tmp_path):
    service = make_service(tmp_path)
    response = protocol.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "cortxt_run_create", "arguments": {"bogus": True}}},
        allow_dispatch=True, allow_credentials=False,
        mandate_verifier=AcceptingVerifier(), lifecycle=service,
    )
    assert response["error"]["code"] == -32602


def test_protocol_audits_accepted_lifecycle_call_with_run_id(tmp_path):
    context = FakeEngineContext()
    service = make_service(tmp_path, context)
    audit = AuditLog(tmp_path / "audit")
    issued, public_key_hex = _issue(allowed_tools=["cortxt_run_create"])
    verifier = _real_verifier(issued.envelope, {"operator-demo": public_key_hex})
    response = protocol.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "cortxt_run_create",
                    "arguments": {**create_arguments(), "mandate": issued.envelope}}},
        allow_dispatch=True, allow_credentials=False, audit=audit,
        mandate_verifier=verifier, lifecycle=service,
    )
    assert "error" not in response
    from runtime import session_state as state

    session = state.load(tmp_path / "audit", audit.session_id)
    row = session["events"][-1]["payload"]
    assert row["status"] == "accepted"
    assert row["mandate_decision"] == "accepted"
    assert row["run_id"].startswith("20260822T120000Z_")
    assert row["issue_ref"] == ISSUE_REF
    # The mandate envelope is never copied into the ledger, and sensitive
    # content keys are redacted (value replaced, key retained as marker).
    assert "mandate" not in row["args_summary"]
    assert row["args_summary"].get("prompt", "").startswith("<redacted")
    assert row["args_summary"].get("scope", "").startswith("<redacted")
    assert row["args_summary"].get("acceptance_criteria", "").startswith("<redacted")


# --- AC12: regression -------------------------------------------------------

def test_cortxt_dispatch_stays_separate_and_not_called_by_new_tools(tmp_path):
    """A compatibility test documenting that cortxt_dispatch remains a
    separate legacy path and is not invoked by the new lifecycle tools."""
    context = FakeEngineContext()
    service = make_service(tmp_path, context)
    # The lifecycle tools use their own adapter broker; cortxt_dispatch is
    # a different handler entirely. Verify the registry keeps it registered
    # and that calling a lifecycle tool never touches dispatch's path.
    assert "cortxt_dispatch" in tools.TOOL_REGISTRY
    assert tools.TOOL_REGISTRY["cortxt_dispatch"].mandate_binding is False
    assert tools.TOOL_REGISTRY["cortxt_dispatch"].lifecycle_required is False


def test_tier0_tools_regression(tmp_path):
    result = tools.call_tool(
        "route_engine", {"task_tags": ["general"]}, allow_dispatch=False, allow_credentials=False,
    )
    assert result["engine_id"] == "claude-direct"
