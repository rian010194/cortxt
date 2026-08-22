"""Issue #247: real external MCP lifecycle dogfood proof over stdio.

Run ``python cortxt_mcp/mcp_dogfood_proof.py`` from ``agent-platform``.
The client in this module only communicates with the live server subprocess
through JSON-RPC on piped stdio; it never calls a tool handler in-process.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

AGENT_PLATFORM_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_DIR))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from cortxt_mcp import mandate  # noqa: E402
from runtime import session_state  # noqa: E402

ISSUE_REF = "rian010194/cortxt#247"
WRONG_ISSUE_REF = "rian010194/cortxt#999"
SCOPE = "Run the bounded external MCP lifecycle dogfood proof for issue 247"
GRANTED_BY = "issue-247-proof-operator"
KID = "issue-247-proof-key"
ENGINE_ID = "ci-deterministic"
LIFECYCLE_TOOLS = {
    "cortxt_run_create", "cortxt_run_resume", "cortxt_run_status",
    "cortxt_run_submit_for_review",
}


class ProofSubprocessUnavailable(RuntimeError):
    """Piped subprocess creation is unavailable in the local sandbox."""


class DeterministicLifecycleAdapter:
    """Network-free adapter with a filesystem release gate and call counter."""

    def __init__(self, control_dir: Path) -> None:
        self.control_dir = Path(control_dir)

    @property
    def invocation_count(self) -> int:
        counter = self.control_dir / "invocation-count"
        return int(counter.read_text(encoding="ascii")) if counter.exists() else 0

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None,
               cwd=None, session_id=None) -> dict:
        deadline = time.monotonic() + timeout_seconds
        release = self.control_dir / "release"
        while not release.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("deterministic proof release gate timed out")
            time.sleep(0.01)
        count = self.invocation_count + 1
        (self.control_dir / "invocation-count").write_text(str(count), encoding="ascii")
        return {
            "status": "succeeded",
            "session_id": "opaque-ci-session-247",
            "usage": {"input_tokens": 3, "output_tokens": 2},
            "cost": 0.001,
            "cost_status": "measured",
            "artifacts": [{"ref": "proof:issue-247", "sha256": "a" * 64}],
            "evidence": ["pytest:external-stdio"],
        }


def _send(proc: subprocess.Popen, request: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def _recv(proc: subprocess.Popen) -> dict[str, Any]:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"MCP server closed before responding: {stderr}")
    return json.loads(line)


def _call(proc: subprocess.Popen, request_id: int, tool: str, arguments: dict) -> dict:
    _send(proc, {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                 "params": {"name": tool, "arguments": arguments}})
    response = _recv(proc)
    if "result" in response:
        content = response["result"].get("content", [])
        assert len(content) == 1 and content[0].get("type") == "text", response
        response["result"] = json.loads(content[0]["text"])
    return response


def _issue(private_key: Ed25519PrivateKey, public_key_hex: str, tool: str,
           *, issue_ref: str = ISSUE_REF) -> dict:
    return mandate.issue_mandate(
        private_key=private_key,
        granted_by=GRANTED_BY,
        kid=KID,
        public_keys={GRANTED_BY: {KID: public_key_hex}},
        issue_ref=issue_ref,
        allowed_tools=[tool],
        data_class_max="L2",
        budget_usd_max=10.0,
        max_runtime_seconds=300,
        expires_at="2099-01-01T00:00:00Z",
        scope_text=SCOPE,
        max_envelope_ttl_seconds=10**10,
    ).envelope


def _authorized(private_key, public_key_hex, tool: str, arguments: dict,
                *, envelope_issue_ref: str = ISSUE_REF) -> dict:
    result = dict(arguments)
    result["mandate"] = _issue(private_key, public_key_hex, tool,
                                issue_ref=envelope_issue_ref)
    result["mandate_context"] = {"issue_ref": ISSUE_REF}
    return result


def _create_arguments() -> dict[str, Any]:
    return {
        "issue_ref": ISSUE_REF,
        "task_id": "dogfood-247",
        "workflow": "delivery",
        "worker_role": "builder",
        "scope": SCOPE,
        "acceptance_criteria": ["external stdio lifecycle succeeds"],
        "engine_id": ENGINE_ID,
        "profile": "builder",
        "max_runtime_seconds": 60,
        "max_cost_usd": 1.0,
        "max_parallel_workers": 1,
        "delegation_depth": 0,
        "artifact_policy": {"locations": ["proof"]},
        "approval_ref": "operator approval 2026-08-22",
        "data_class": "L1",
        "estimated_cost_usd": 0.01,
        "prompt": "content omitted from proof output",
    }


def _assert_error(response: dict, transport_code: int, stable_code: str | None = None) -> None:
    assert response.get("error", {}).get("code") == transport_code, response
    if stable_code is not None:
        assert response["error"].get("data", {}).get("code") == stable_code, response


def _session_documents(store: Path) -> list[dict]:
    documents = []
    for path in store.glob("session_*"):
        if path.is_dir():
            documents.append(session_state.load(store, path.name))
    return documents


def _audit_rows(store: Path) -> list[dict]:
    return [event["payload"] for doc in _session_documents(store)
            for event in doc["events"] if event["event_type"] == "mcp.tool_call"]


def main(base_dir: str | Path | None = None) -> int:
    owned_temp = tempfile.TemporaryDirectory(prefix="mcp-dogfood-247-") if base_dir is None else None
    root = Path(owned_temp.name if owned_temp else base_dir)
    root.mkdir(parents=True, exist_ok=True)
    store = root / "sessions"
    control = root / "control"
    mandate_state = root / "mandate-state"
    control.mkdir()
    mandate_state.mkdir()
    (mandate_state / "revocations.json").write_text(
        json.dumps({"generation": 1, "revocations": []}), encoding="utf-8")

    private_key = Ed25519PrivateKey.generate()
    public_key_hex = mandate.public_key_hex_from_private_key(private_key)
    env = dict(os.environ)
    env["CORTXT_MCP_MANDATE_PUBLIC_KEYS"] = json.dumps({GRANTED_BY: {KID: public_key_hex}})
    env["CORTXT_MCP_MANDATE_STATE_DIR"] = str(mandate_state)
    env["PYTHONPATH"] = str(AGENT_PLATFORM_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    server_code = (
        "from pathlib import Path\n"
        "from cortxt_mcp.mcp_dogfood_proof import DeterministicLifecycleAdapter\n"
        "from cortxt_mcp.run_lifecycle import RunLifecycleService\n"
        "from cortxt_mcp.server import serve\n"
        "from runtime.engine_registry import EngineContext\n"
        "context = EngineContext()\n"
        f"context.register({ENGINE_ID!r}, DeterministicLifecycleAdapter(Path({str(control)!r})))\n"
        f"store = Path({str(store)!r})\n"
        "lifecycle = RunLifecycleService(engine_context=context, store=store)\n"
        "serve(allow_dispatch=True, store=store, lifecycle=lifecycle)\n"
    )
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", server_code], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(AGENT_PLATFORM_DIR), env=env,
        )
    except (PermissionError, OSError) as error:
        if isinstance(error, PermissionError) or getattr(error, "errno", None) == 1:
            if owned_temp:
                owned_temp.cleanup()
            raise ProofSubprocessUnavailable(
                "local sandbox denied MCP subprocess creation with piped stdio") from error
        raise

    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        initialized = _recv(proc)
        assert initialized["result"]["serverInfo"]["name"] == "cortxt-mcp"
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {row["name"] for row in _recv(proc)["result"]["tools"]}
        assert LIFECYCLE_TOOLS <= names
        print("PASS initialize and lifecycle tool discovery")

        wrong = _call(proc, 3, "cortxt_run_create", _authorized(
            private_key, public_key_hex, "cortxt_run_create", _create_arguments(),
            envelope_issue_ref=WRONG_ISSUE_REF))
        _assert_error(wrong, -32002)
        assert wrong["error"]["data"]["reason"] == mandate.REASON_ISSUE_REF_MISMATCH
        assert DeterministicLifecycleAdapter(control).invocation_count == 0
        print("PASS wrong-issue mandate rejection")

        created = _call(proc, 4, "cortxt_run_create", _authorized(
            private_key, public_key_hex, "cortxt_run_create", _create_arguments()))["result"]
        assert created["status"] == "running" and created["run_id"]
        assert created["finished_at"] is None and created["session_id"] is None
        run_id = created["run_id"]
        run_docs = [doc for doc in _session_documents(store)
                    if doc["events"][0]["payload"].get("run_id") == run_id]
        assert len(run_docs) == 1
        event_types = [event["event_type"] for event in run_docs[0]["events"]]
        assert event_types[:3] == ["session.created", "run.created", "run.running"]
        assert DeterministicLifecycleAdapter(control).invocation_count == 0
        print("PASS async create running envelope and durable events")

        resume_args = {"run_id": run_id, "issue_ref": ISSUE_REF,
                       "prompt": "content omitted from proof output", "max_runtime_seconds": 60,
                       "data_class": "L1", "estimated_cost_usd": 0.01}
        resume = _call(proc, 5, "cortxt_run_resume", _authorized(
            private_key, public_key_hex, "cortxt_run_resume", resume_args))
        _assert_error(resume, -32003, "run_not_resumable")
        conflict = _call(proc, 6, "cortxt_run_create", _authorized(
            private_key, public_key_hex, "cortxt_run_create", _create_arguments()))
        _assert_error(conflict, -32003, "claim_conflict")
        assert DeterministicLifecycleAdapter(control).invocation_count == 0
        print("PASS active-run resume and claim-conflict rejections")

        unknown = _call(proc, 7, "cortxt_run_status", {
            "run_id": "20260822T120000Z_deadbeef"})
        _assert_error(unknown, -32003, "run_not_found")
        (control / "release").write_text("released", encoding="ascii")
        terminal = None
        for request_id in range(8, 48):
            response = _call(proc, request_id, "cortxt_run_status", {"run_id": run_id})
            assert "result" in response, response
            terminal = response["result"]
            if terminal["status"] != "running":
                break
            time.sleep(0.05)
        assert terminal is not None and terminal["status"] == "succeeded"
        assert terminal["session_id"] == "opaque-ci-session-247"
        for field in ("usage", "cost", "cost_status", "artifacts", "evidence"):
            assert terminal[field]
        assert DeterministicLifecycleAdapter(control).invocation_count == 1
        print("PASS Tier-0 status polling to complete terminal envelope")

        review_args = {"run_id": run_id, "issue_ref": ISSUE_REF, "result": terminal,
                       "review_kind": "independent", "idempotency_key": "dogfood-review-247",
                       "data_class": "L1"}
        first = _call(proc, 48, "cortxt_run_submit_for_review", _authorized(
            private_key, public_key_hex, "cortxt_run_submit_for_review", review_args))["result"]
        second = _call(proc, 49, "cortxt_run_submit_for_review", _authorized(
            private_key, public_key_hex, "cortxt_run_submit_for_review", review_args))["result"]
        first_id = first["review"]["review_id"]
        assert first_id and second["review"]["review_id"] == first_id
        different = dict(review_args)
        different["result"] = dict(terminal, evidence=["pytest:different-content"])
        rejected = _call(proc, 50, "cortxt_run_submit_for_review", _authorized(
            private_key, public_key_hex, "cortxt_run_submit_for_review", different))
        _assert_error(rejected, -32003, "idempotency_conflict")
        assert DeterministicLifecycleAdapter(control).invocation_count == 1
        print("PASS review submission idempotency and conflict")

        rows = _audit_rows(store)
        tier_one = [row for row in rows if row["tool"] != "cortxt_run_status"]
        tier_zero = [row for row in rows if row["tool"] == "cortxt_run_status"]
        assert tier_one and tier_zero
        assert all(row["mandate_id"] and row["mandate_decision"] for row in tier_one)
        assert all(row["mandate_id"] is None and row["mandate_decision"] is None
                   for row in tier_zero)
        assert any(row["status"] == "accepted" for row in tier_one)
        assert any(row["status"] == "rejected" and
                   row["mandate_decision"].startswith("rejected:") for row in tier_one)
        serialized = json.dumps(rows, sort_keys=True)
        assert "content omitted from proof output" not in serialized
        assert '"mandate"' not in serialized and '"signature"' not in serialized
        assert all(row["args_summary"].get(key) in (None, "<redacted>")
                   for row in rows for key in ("result", "artifacts", "evidence"))
        print("PASS content-free accepted and rejected audit ledger rows")
    finally:
        if proc.stdin:
            proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        if owned_temp:
            owned_temp.cleanup()

    print("PASS issue 247 external MCP lifecycle dogfood proof")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
