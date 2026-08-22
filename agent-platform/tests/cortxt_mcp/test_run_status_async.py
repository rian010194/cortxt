"""Network-free async create/status coverage for issue #245."""
from __future__ import annotations

from cortxt_mcp import protocol, run_lifecycle, tools
from cortxt_mcp.audit import AuditLog
from tests.cortxt_mcp.test_run_lifecycle_tools import (
    AcceptingVerifier, FakeAdapter, FakeEngineContext, ISSUE_REF, _clock, create_arguments,
)


class QueuedWorker:
    def __init__(self):
        self.turns = []

    def start(self, turn):
        self.turns.append(turn)

    def drain(self):
        while self.turns:
            self.turns.pop(0)()


def service_for(tmp_path, adapter=None):
    worker = QueuedWorker()
    context = FakeEngineContext({"hermes": adapter or FakeAdapter({
        "status": "succeeded", "session_id": "opaque-1", "cost": 2.5,
        "cost_status": "measured", "usage": {"input_tokens": 4},
        "artifacts": [{"ref": "pr:245", "sha256": "abc"}],
        "evidence": ["test:green"],
    })})
    service = run_lifecycle.RunLifecycleService(context, tmp_path / "sessions", _clock, worker.start)
    return service, context, worker


def create(service):
    return tools.call_tool("cortxt_run_create", create_arguments(), allow_dispatch=True,
                           allow_credentials=False, mandate={"issue_ref": ISSUE_REF, "scope_fingerprint":
                           run_lifecycle.compute_scope_fingerprint(create_arguments()["scope"])},
                           mandate_verifier=AcceptingVerifier(), lifecycle=service)


def test_created_running_terminal_without_threads_or_sleeps(tmp_path):
    service, context, worker = service_for(tmp_path)
    result = create(service)
    assert result["status"] == "running"
    assert result["finished_at"] is None and result["session_id"] is None
    assert context.adapters["hermes"].calls == []
    assert service.status_of(result["run_id"])["status"] == "running"
    worker.drain()
    terminal = service.status_of(result["run_id"])
    assert terminal["status"] == "succeeded"
    assert terminal["session_id"] == "opaque-1"
    assert terminal["usage"] == {"input_tokens": 4}
    assert terminal["cost"] == 2.5 and terminal["cost_status"] == "measured"
    assert terminal["artifacts"] == [{"ref": "pr:245", "sha256": "abc"}]
    assert terminal["evidence"] == ["test:green"]


def test_running_is_not_resumable_and_claim_conflicts_before_adapter(tmp_path):
    service, context, _worker = service_for(tmp_path)
    result = create(service)
    binding = {"issue_ref": ISSUE_REF}
    args = {"run_id": result["run_id"], "issue_ref": ISSUE_REF, "prompt": "continue",
            "max_runtime_seconds": 60, "data_class": "L1", "estimated_cost_usd": 1.0}
    try:
        service.resume_run(args, binding)
        assert False
    except run_lifecycle.RunLifecycleError as error:
        assert error.code == run_lifecycle.CODE_RUN_NOT_RESUMABLE
    try:
        service.create_run(create_arguments(), {"issue_ref": ISSUE_REF,
                           "scope_fingerprint": run_lifecycle.compute_scope_fingerprint(create_arguments()["scope"])})
        assert False
    except run_lifecycle.RunLifecycleError as error:
        assert error.code == run_lifecycle.CODE_CLAIM_CONFLICT
    assert context.adapters["hermes"].calls == []


def test_adapter_failure_is_terminal_and_does_not_escape_create(tmp_path):
    service, _context, worker = service_for(tmp_path, FakeAdapter(failures=[RuntimeError("boom")]))
    result = create(service)
    worker.drain()
    terminal = service.status_of(result["run_id"])
    assert terminal["status"] == "failed"
    assert terminal["error"]["category"] == run_lifecycle.CODE_ADAPTER_FAILED


def test_status_tool_schema_unknown_protocol_and_tier0_audit(tmp_path):
    service, _context, _worker = service_for(tmp_path)
    spec = tools.TOOL_REGISTRY["cortxt_run_status"]
    assert spec.tier == tools.TIER_READ_ONLY and spec.lifecycle_required and not spec.mandate_binding
    listed = protocol.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                                     allow_dispatch=False, allow_credentials=False)
    assert "cortxt_run_status" in {row["name"] for row in listed["result"]["tools"]}
    audit = AuditLog(tmp_path / "audit")
    response = protocol.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "cortxt_run_status", "arguments": {"run_id": "20260822T120000Z_deadbeef"}}},
        allow_dispatch=False, allow_credentials=False, lifecycle=service, audit=audit)
    assert response["error"]["code"] == -32003
    assert response["error"]["data"]["code"] == run_lifecycle.CODE_RUN_NOT_FOUND
    from runtime import session_state
    row = session_state.load(tmp_path / "audit", audit.session_id)["events"][-1]["payload"]
    assert row["mandate_id"] is None and row["mandate_decision"] is None
