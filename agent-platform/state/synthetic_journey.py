"""Reproducible offline T1 journey over the local state ledger."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from ledger import LedgerError, append, canonical_json, create, load, read_json_file, utc_now


class JourneyError(Exception):
    pass


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json(value) + b"\n")


def _scenario(path: str) -> dict[str, Any]:
    value = read_json_file(path)
    required = {"scenario_id", "workflow", "data_class", "max_cost_usd",
                "actual_cost_usd", "provider_evidence", "synthetic_result"}
    if not isinstance(value, dict) or set(value) != required:
        raise JourneyError("scenario has an invalid schema")
    if not all(isinstance(value[key], str) and value[key]
               for key in ("scenario_id", "workflow", "data_class")):
        raise JourneyError("scenario identity fields must be non-empty strings")
    if not isinstance(value["provider_evidence"], dict) or not isinstance(value["synthetic_result"], dict):
        raise JourneyError("scenario evidence and result must be objects")
    try:
        maximum = Decimal(value["max_cost_usd"])
        actual = Decimal(value["actual_cost_usd"])
    except (InvalidOperation, TypeError):
        raise JourneyError("scenario costs must be decimal strings")
    if not maximum.is_finite() or not actual.is_finite() or maximum < 0 or actual < 0:
        raise JourneyError("scenario costs must be finite and nonnegative")
    if actual > maximum:
        raise JourneyError("scenario actual cost exceeds its budget")
    return value


def _manifest_path(output: Path) -> Path:
    return output / "journey-manifest.json"


def _load_manifest(output: Path) -> dict[str, Any]:
    path = _manifest_path(output)
    if not path.is_file():
        raise JourneyError("journey manifest was not found")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise JourneyError("journey manifest is invalid")
    return value


def start(scenario_name: str, output_name: str) -> dict[str, Any]:
    scenario = _scenario(scenario_name)
    output = Path(output_name).absolute()
    output.mkdir(parents=True, exist_ok=False)
    store = output / "state"
    evidence = output / "provider-evidence.json"
    started = output / "started.json"
    interrupted = output / "interrupted.json"
    store.mkdir()
    _write_json(evidence, scenario["provider_evidence"])
    _write_json(started, {"status": "running", "synthetic": True})
    _write_json(interrupted, {"category": "synthetic_interrupt", "recoverable": True})
    ledger = create(str(store), scenario["scenario_id"], scenario["data_class"],
                    scenario["workflow"], scenario["max_cost_usd"], str(evidence))
    run_id = ledger["run_id"]
    ledger = append(str(store), run_id, 0, "run.started", str(started))
    ledger = append(str(store), run_id, 1, "run.interrupted", str(interrupted))
    manifest = {"schema_version": 1, "scenario": scenario, "run_id": run_id,
                "state_store": "state", "terminal": False,
                "last_sequence": ledger["events"][-1]["sequence"]}
    _write_json(_manifest_path(output), manifest)
    return manifest


def resume(output_name: str) -> dict[str, Any]:
    output = Path(output_name).absolute()
    manifest = _load_manifest(output)
    if manifest.get("terminal") is not False or manifest.get("last_sequence") != 2:
        raise JourneyError("journey is not at the resumable interruption boundary")
    scenario = manifest["scenario"]
    store = output / manifest["state_store"]
    resumed = output / "resumed.json"
    result = output / "synthetic-result.json"
    terminal = output / "terminal.json"
    _write_json(resumed, {"from_sequence": 2, "status": "running", "synthetic": True})
    _write_json(result, scenario["synthetic_result"])
    result_hash = hashlib.sha256(result.read_bytes()).hexdigest()
    run_id = manifest["run_id"]
    ledger = append(str(store), run_id, 2, "run.resumed", str(resumed))
    terminal_payload = {
        "artifacts": [{"path": result.name, "sha256": result_hash}],
        "cost": {"amount_usd": scenario["actual_cost_usd"], "status": "exact"},
        "error": None,
        "evidence": [{"kind": "synthetic_fixture", "ref": "fixture://foundation-101/t1"}],
        "finished_at": utc_now(),
        "issue_id": "rian010194/cortxt#101",
        "model": "offline/deterministic-synthetic-adapter",
        "run_id": run_id,
        "runtime": "cortxt-local-state/1",
        "started_at": ledger["events"][1]["timestamp"],
        "status": "succeeded",
        "usage": {"cache_tokens": 0, "input_tokens": 0, "output_tokens": 0,
                  "reasoning_tokens": 0, "status": "exact"},
        "worker_role": "synthetic-validator",
    }
    _write_json(terminal, terminal_payload)
    ledger = append(str(store), run_id, 3, "run.result", str(terminal))
    manifest.update({"terminal": True, "last_sequence": 4,
                     "result_sha256": result_hash,
                     "ledger_head_sha256": ledger["events"][-1]["hash"]})
    _write_json(_manifest_path(output), manifest)
    return manifest


def verify(output_name: str) -> dict[str, Any]:
    output = Path(output_name).absolute()
    manifest = _load_manifest(output)
    if manifest.get("terminal") is not True:
        raise JourneyError("journey has no terminal result")
    _, ledger = load(str(output / manifest["state_store"]), manifest["run_id"])
    event_types = [event["event_type"] for event in ledger["events"]]
    expected = ["run.created", "run.started", "run.interrupted", "run.resumed", "run.result"]
    if event_types != expected:
        raise JourneyError("journey lifecycle is incomplete or out of order")
    created = ledger["events"][0]["payload"]
    terminal = ledger["events"][-1]["payload"]
    terminal_fields = {"artifacts", "cost", "error", "evidence", "finished_at", "issue_id",
                       "model", "run_id", "runtime", "started_at", "status", "usage",
                       "worker_role"}
    if not isinstance(terminal, dict) or set(terminal) != terminal_fields:
        raise JourneyError("terminal result envelope has an invalid schema")
    if terminal["issue_id"] != "rian010194/cortxt#101" or terminal["run_id"] != manifest["run_id"]:
        raise JourneyError("terminal result correlation does not match")
    if terminal["status"] != "succeeded" or terminal["error"] is not None:
        raise JourneyError("terminal result is not a successful completion")
    if not all(isinstance(terminal[field], str) and terminal[field]
               for field in ("runtime", "worker_role", "started_at", "finished_at", "model")):
        raise JourneyError("terminal result identity is incomplete")
    expected_usage = {"cache_tokens": 0, "input_tokens": 0, "output_tokens": 0,
                      "reasoning_tokens": 0, "status": "exact"}
    cost = terminal["cost"]
    if (not isinstance(cost, dict) or set(cost) != {"amount_usd", "status"}
            or not isinstance(cost["amount_usd"], str) or cost["status"] != "exact"):
        raise JourneyError("terminal cost has an invalid schema")
    if terminal["usage"] != expected_usage:
        raise JourneyError("offline usage or cost is not exact")
    if (not isinstance(terminal["evidence"], list) or not terminal["evidence"]
            or not all(isinstance(item, dict) and set(item) == {"kind", "ref"}
                       and all(isinstance(item[key], str) and item[key] for key in item)
                       for item in terminal["evidence"])):
        raise JourneyError("terminal evidence is missing")
    if created["policy_decision"].get("allowed") is not True:
        raise JourneyError("authoritative policy decision was not allowed")
    try:
        actual_cost = Decimal(cost["amount_usd"])
    except InvalidOperation:
        raise JourneyError("terminal cost is not a decimal string")
    if not actual_cost.is_finite() or actual_cost < 0 or actual_cost > Decimal(created["budget"]["max_cost_usd"]):
        raise JourneyError("terminal cost exceeds the approved budget")
    if not isinstance(terminal["artifacts"], list) or len(terminal["artifacts"]) != 1:
        raise JourneyError("terminal artifact set is invalid")
    artifact = terminal["artifacts"][0]
    if (not isinstance(artifact, dict) or set(artifact) != {"path", "sha256"}
            or not all(isinstance(artifact[key], str) for key in artifact)
            or Path(artifact["path"]).name != artifact["path"]
            or len(artifact["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in artifact["sha256"])):
        raise JourneyError("terminal artifact reference is unsafe or invalid")
    result_path = output / artifact["path"]
    if not result_path.is_file() or hashlib.sha256(result_path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise JourneyError("result evidence hash does not match")
    if ledger["events"][-1]["hash"] != manifest.get("ledger_head_sha256"):
        raise JourneyError("manifest does not identify the ledger head")
    if artifact["sha256"] != manifest.get("result_sha256"):
        raise JourneyError("manifest does not identify the result evidence")
    return {"budget_verified": True, "evidence_verified": True,
            "event_types": event_types, "integrity_verified": True,
            "run_id": manifest["run_id"], "status": terminal["status"], "synthetic": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthetic_journey.py")
    commands = parser.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("start")
    begin.add_argument("--scenario", required=True)
    begin.add_argument("--output", required=True)
    continuation = commands.add_parser("resume")
    continuation.add_argument("--output", required=True)
    check = commands.add_parser("verify")
    check.add_argument("--output", required=True)
    try:
        args = parser.parse_args(argv)
        value = start(args.scenario, args.output) if args.command == "start" else (
            resume(args.output) if args.command == "resume" else verify(args.output))
        sys.stdout.buffer.write(canonical_json(value) + b"\n")
        return 0
    except (JourneyError, LedgerError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        sys.stderr.buffer.write(canonical_json({"error": {"category": "journey_error",
                                                           "message": str(error)}}) + b"\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
