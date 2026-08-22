"""AC 7 proof for issue #206 / ADR-032: a real external MCP client (a
separate OS process speaking MCP stdio, framing requests exactly as a
real client would -- not a Python unit test importing `cortxt_mcp`
in-process) demonstrates (a) an accepted Tier-1+ tool call with a valid
mandate envelope and (b) a rejected Tier-1+ tool call with a valid-looking
but disallowed envelope (wrong `issue_ref`), against a live
`cortxt mcp serve --allow-dispatch` process.

Tool choice for this demo: `cortxt_daemon_status`, not `cortxt_dispatch`.
Both are TIER_DISPATCH tools, so both exercise exactly the same mandate
verification path inside `cortxt_mcp.tools.call_tool` -- the mandate
check does not know or care which Tier-1+ tool is being called.
`cortxt_daemon_status` reads a JSON snapshot file (or treats a
missing/unparseable one as `{}`, per `_run_daemon`'s "status" branch in
`cli/unified_cli.py`) and returns a read-only status view -- no engine
subprocess, no worker, no side effect beyond this demo's own throwaway
snapshot file and the session ledger it's pointed at. `cortxt_dispatch`
would invoke a real engine adapter (Hermes/Codex/...) as a side effect of
a *successful* call, which would be unsafe and non-deterministic to run
as an unattended proof script. This choice is exactly the fallback the
step-2b brief anticipated ("show accepted+denied on cortxt_daemon_status
with a snapshot path").

Self-contained: generates its own Ed25519 keypair, issues both a valid
and an issue_ref-mismatched envelope in-process, then launches the server
as a genuinely separate subprocess (`python -c "from cortxt_mcp.server
import serve; serve(...)"`) speaking MCP stdio and drives it with
hand-framed JSON-RPC requests over that subprocess's stdin/stdout --
never by importing `cortxt_mcp` into this process and calling
`handle_request`/`call_tool` directly, which would not prove anything
about the real wire protocol.

Run: `python cortxt_mcp/ac7_client_demo.py` from `agent-platform/`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_PLATFORM_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_DIR))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from cortxt_mcp import mandate  # noqa: E402

GRANTED_BY = "ac7-demo-operator"
ISSUE_REF = "owner/repo#206"
WRONG_ISSUE_REF = "owner/repo#999"


def _send(proc: subprocess.Popen, request: dict) -> None:
    line = json.dumps(request) + "\n"
    assert proc.stdin is not None
    proc.stdin.write(line)
    proc.stdin.flush()
    print(">>>", line.strip())


def _recv(proc: subprocess.Popen) -> dict:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"server closed stdout with no response; stderr:\n{stderr}")
    print("<<<", line.strip())
    return json.loads(line)


def _issue(private_key: Ed25519PrivateKey, *, issue_ref: str) -> dict:
    return mandate.issue_mandate(
        private_key=private_key,
        granted_by=GRANTED_BY,
        issue_ref=issue_ref,
        allowed_tools=["cortxt_daemon_status"],
        data_class_max="L2",
        budget_usd_max=25.0,
        max_runtime_seconds=3600,
        expires_at="2099-01-01T00:00:00Z",
        scope_text="AC7 demo scope",
    ).envelope


def main() -> int:
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = mandate.public_key_hex_from_private_key(private_key)

    with tempfile.TemporaryDirectory(prefix="ac7-mandate-demo-") as tmp:
        tmp_path = Path(tmp)
        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps({"daemon": {"status": "idle"}}), encoding="utf-8")
        sessions_dir = tmp_path / "sessions"
        mandate_state_dir = tmp_path / "mandate"

        accepted_envelope = _issue(private_key, issue_ref=ISSUE_REF)
        denied_envelope = _issue(private_key, issue_ref=WRONG_ISSUE_REF)

        env = dict(os.environ)
        env["CORTXT_MCP_MANDATE_PUBLIC_KEYS"] = json.dumps({GRANTED_BY: public_key_hex})
        env["CORTXT_MCP_MANDATE_STATE_DIR"] = str(mandate_state_dir)
        env["PYTHONPATH"] = str(AGENT_PLATFORM_DIR) + os.pathsep + env.get("PYTHONPATH", "")

        server_code = (
            "from pathlib import Path\n"
            "from cortxt_mcp.server import serve\n"
            f"serve(allow_dispatch=True, store=Path(r'{sessions_dir}'))\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", server_code],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(AGENT_PLATFORM_DIR), env=env,
        )

        try:
            _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            init_response = _recv(proc)
            assert init_response["result"]["serverInfo"]["name"] == "cortxt-mcp"

            _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

            _send(proc, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {
                    "name": "cortxt_daemon_status",
                    "arguments": {
                        "snapshot": str(snapshot_path),
                        "mandate": accepted_envelope,
                        "mandate_context": {"issue_ref": ISSUE_REF},
                    },
                },
            })
            accepted_response = _recv(proc)
            assert "result" in accepted_response, f"expected acceptance, got {accepted_response}"
            print("ACCEPTED CASE: PASS -- valid envelope executed cortxt_daemon_status\n")

            _send(proc, {
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {
                    "name": "cortxt_daemon_status",
                    "arguments": {
                        "snapshot": str(snapshot_path),
                        "mandate": denied_envelope,
                        "mandate_context": {"issue_ref": ISSUE_REF},
                    },
                },
            })
            denied_response = _recv(proc)
            error = denied_response.get("error", {})
            assert error.get("code") == -32002, f"expected mandate rejection (-32002), got {denied_response}"
            reason = error.get("data", {}).get("reason")
            assert reason == mandate.REASON_ISSUE_REF_MISMATCH, f"expected issue_ref_mismatch, got {reason}"
            print(f"DENIED CASE: PASS -- disallowed envelope (wrong issue_ref) rejected with reason {reason!r}\n")
        finally:
            if proc.stdin:
                proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            if proc.stderr:
                stderr = proc.stderr.read()
                if stderr.strip():
                    print("--- server stderr ---")
                    print(stderr)

    print("AC 7 proof complete: accepted + rejected Tier-1+ calls both demonstrated over real MCP stdio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
