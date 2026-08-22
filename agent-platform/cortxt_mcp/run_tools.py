"""Content-limited MCP run lifecycle with an injected local JSON store."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .mandate import compute_scope_fingerprint

TERMINAL = {"succeeded", "failed", "timed_out", "budget_exceeded", "blocked", "cancelled"}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def create_run(arguments: dict, binding: dict) -> dict:
    scope = arguments.get("scope_text", "")
    issue = binding.get("issue_ref")
    if not issue or not scope:
        return _failed("invalid_args", "issue binding and scope_text are required")
    if compute_scope_fingerprint(scope) != binding.get("scope_fingerprint"):
        return _failed("scope_mismatch", "scope does not match the verified mandate")
    requested = int(arguments.get("max_runtime_seconds", binding["max_runtime_seconds"]))
    if requested > int(binding["max_runtime_seconds"]):
        return _failed("limits_exceed_mandate", "runtime limit exceeds mandate")
    path = Path(arguments.get("store", ".sessions/mcp-runs.json"))
    rows = _read(path)
    run_id = "run_" + uuid.uuid4().hex
    rows[run_id] = {"run_id": run_id, "issue_id": issue, "status": "created",
                    "scope_fingerprint": binding["scope_fingerprint"],
                    "max_runtime_seconds": requested, "budget_usd_max": binding["budget_usd_max"],
                    "runtime": arguments.get("runtime", "hermes"),
                    "worker_role": arguments.get("worker_role", "builder"),
                    "created_at": time.time(), "turns": []}
    _write(path, rows)
    return _ok(run_id, issue, {"store": str(path)})


def resume_run(arguments: dict, binding: dict) -> dict:
    path = Path(arguments.get("store", ".sessions/mcp-runs.json"))
    rows = _read(path)
    run = rows.get(arguments.get("run_id"))
    if not run:
        return _failed("not_found", "run was not found")
    if run["issue_id"] != binding.get("issue_ref"):
        return _failed("scope_mismatch", "run is outside the verified mandate")
    run["status"] = "in_progress"
    run["turns"].append({"resumed_at": time.time()})
    _write(path, rows)
    return _ok(run["run_id"], run["issue_id"], {"status": "in_progress"})


def submit_for_review(arguments: dict, binding: dict) -> dict:
    path = Path(arguments.get("store", ".sessions/mcp-runs.json"))
    rows = _read(path)
    run = rows.get(arguments.get("run_id"))
    if not run:
        return _failed("not_found", "run was not found")
    if run["issue_id"] != binding.get("issue_ref"):
        return _failed("scope_mismatch", "run is outside the verified mandate")
    result = arguments.get("result", {})
    if result.get("status") not in TERMINAL:
        return _failed("invalid_status", "a terminal dispatch status is required")
    if run.get("review_submission_id"):
        return _failed("already_submitted", "run was already submitted")
    handle = "review_" + uuid.uuid4().hex
    run.update(status="review_submitted", review_submission_id=handle,
               result={key: result.get(key) for key in ("status", "runtime", "worker_role", "model",
                                                        "usage", "cost", "artifacts", "error")})
    _write(path, rows)
    return _ok(run["run_id"], run["issue_id"], {"review_submission_id": handle})


def _ok(run_id: str, issue_id: str, evidence: dict) -> dict:
    return {"issue_id": issue_id, "run_id": run_id, "status": "succeeded", "runtime": "cortxt-mcp/v0.1",
            "worker_role": "coordinator", "started_at": None, "finished_at": None, "model": None,
            "usage": {}, "cost": 0.0, "cost_currency": "USD", "artifacts": [],
            "evidence": [evidence], "error": None}


def _failed(category: str, message: str) -> dict:
    data = _ok(None, None, {})
    data.update(status="failed", error={"category": category, "message": message})
    return data
