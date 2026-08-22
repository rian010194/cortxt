"""Issue #252: live MCP review submission to GitHub synchronization proof.

Run ``python cortxt_mcp/review_sync_live_proof.py OWNER/REPO#NUMBER --live``
from ``agent-platform``. Without ``--live``, callers must inject a GitHub
runner; the default subprocess runner is used only by the explicit live arm.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

AGENT_PLATFORM_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_DIR))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from cortxt_mcp import mandate  # noqa: E402
from cortxt_mcp.mcp_dogfood_proof import (  # noqa: E402
    DeterministicLifecycleAdapter,
    ProofSubprocessUnavailable,
    _call,
    _recv,
    _send,
)
from daemon.review_sync import resolve_issue_ref, sync_review_submissions  # noqa: E402

SCOPE = "Run the bounded live review synchronization proof for issue 252"
GRANTED_BY = "issue-252-proof-operator"
KID = "issue-252-proof-key"
ENGINE_ID = "ci-deterministic"


def _issue(private_key: Ed25519PrivateKey, public_key_hex: str, tool: str,
           issue_ref: str) -> dict:
    return mandate.issue_mandate(
        private_key=private_key, granted_by=GRANTED_BY, kid=KID,
        public_keys={GRANTED_BY: {KID: public_key_hex}}, issue_ref=issue_ref,
        allowed_tools=[tool], data_class_max="L2", budget_usd_max=10.0,
        max_runtime_seconds=300, expires_at="2099-01-01T00:00:00Z",
        scope_text=SCOPE, max_envelope_ttl_seconds=10**10,
    ).envelope


def _authorized(private_key, public_key_hex: str, tool: str,
                arguments: dict, issue_ref: str) -> dict:
    result = dict(arguments)
    result["mandate"] = _issue(private_key, public_key_hex, tool, issue_ref)
    result["mandate_context"] = {"issue_ref": issue_ref}
    return result


def _create_arguments(issue_ref: str) -> dict[str, Any]:
    return {
        "issue_ref": issue_ref, "task_id": "review-sync-live-252",
        "workflow": "delivery", "worker_role": "builder", "scope": SCOPE,
        "acceptance_criteria": ["real review synchronization succeeds"],
        "engine_id": ENGINE_ID, "profile": "builder", "max_runtime_seconds": 60,
        "max_cost_usd": 1.0, "max_parallel_workers": 1, "delegation_depth": 0,
        "artifact_policy": {"locations": ["proof"]},
        "approval_ref": "operator approval 2026-08-22", "data_class": "L1",
        "estimated_cost_usd": 0.01, "prompt": "content omitted from proof output",
    }


def _verify_final_labels(issue_ref: str, run_subprocess: Callable) -> list[str]:
    repo, number = resolve_issue_ref(issue_ref)
    args = ["gh", "issue", "view", str(number), "--repo", repo,
            "--json", "state,labels"]
    viewed = run_subprocess(args, capture_output=True, text=True, timeout=30)
    if viewed.returncode != 0:
        raise RuntimeError(f"gh issue view failed: {viewed.stderr.strip()}")
    issue = json.loads(viewed.stdout)
    labels = [label["name"] for label in issue.get("labels", [])]
    workflow_labels = [label for label in labels if label.startswith("workflow:")]
    assert workflow_labels == ["workflow:review"], workflow_labels
    return labels


def main(base_dir: str | Path | None = None, *, issue_ref: str,
         run_subprocess: Callable = subprocess.run, live: bool = False) -> dict:
    if not live and run_subprocess is subprocess.run:
        raise ValueError("non-live proof requires an injected GitHub runner")
    resolve_issue_ref(issue_ref)
    owned_temp = tempfile.TemporaryDirectory(prefix="review-sync-live-252-") if base_dir is None else None
    root = Path(owned_temp.name if owned_temp else base_dir)
    root.mkdir(parents=True, exist_ok=True)
    store, control = root / "sessions", root / "control"
    mandate_state, sync_state = root / "mandate-state", root / "review-state"
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
        "serve(allow_dispatch=True, store=store, "
        "lifecycle=RunLifecycleService(engine_context=context, store=store))\n"
    )
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", server_code], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(AGENT_PLATFORM_DIR), env=env,
        )
    except (PermissionError, OSError) as error:
        if owned_temp:
            owned_temp.cleanup()
        if isinstance(error, PermissionError) or getattr(error, "errno", None) == 1:
            raise ProofSubprocessUnavailable(
                "local sandbox denied MCP subprocess creation with piped stdio") from error
        raise

    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert _recv(proc)["result"]["serverInfo"]["name"] == "cortxt-mcp"
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        print("PASS live MCP server initialized")

        created = _call(proc, 2, "cortxt_run_create", _authorized(
            private_key, public_key_hex, "cortxt_run_create",
            _create_arguments(issue_ref), issue_ref))["result"]
        run_id = created["run_id"]
        assert created["status"] == "running"
        (control / "release").write_text("released", encoding="ascii")
        terminal = None
        for request_id in range(3, 43):
            terminal = _call(proc, request_id, "cortxt_run_status", {"run_id": run_id})["result"]
            if terminal["status"] != "running":
                break
            time.sleep(0.05)
        assert terminal is not None and terminal["status"] == "succeeded"
        print("PASS create completed through deterministic adapter")

        review_args = {
            "run_id": run_id, "issue_ref": issue_ref, "result": terminal,
            "review_kind": "independent", "idempotency_key": "review-sync-live-252",
            "data_class": "L1",
        }
        submitted = _call(proc, 43, "cortxt_run_submit_for_review", _authorized(
            private_key, public_key_hex, "cortxt_run_submit_for_review",
            review_args, issue_ref))["result"]
        submission_id = submitted["review"]["review_id"]
        assert submission_id
        print("PASS durable review submission created")

        first = sync_review_submissions(store, sync_state, run_subprocess=run_subprocess)
        assert first == {"synced": [submission_id], "skipped": [], "failed": []}, first
        markers = json.loads((sync_state / "review_sync.json").read_text(encoding="utf-8"))
        assert submission_id in markers
        second = sync_review_submissions(store, sync_state, run_subprocess=run_subprocess)
        assert second["skipped"] == [{"review_submission_id": submission_id,
                                      "reason": "already_synced"}], second
        assert not second["synced"] and not second["failed"]
        print("PASS review sync marker and second-pass dedupe")

        final_labels = _verify_final_labels(issue_ref, run_subprocess) if live else []
        if live:
            print("PASS live fixture has exactly workflow:review")
        return {"synced": first["synced"], "skipped": second["skipped"],
                "failed": first["failed"] + second["failed"],
                "fixture_issue_ref": issue_ref, "final_labels": final_labels}
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue_ref")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    main(issue_ref=args.issue_ref, live=args.live)
