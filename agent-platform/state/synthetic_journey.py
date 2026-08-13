"""Reproducible offline T1 journey over the local state ledger."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from ledger import LedgerError, append, canonical_json, create, load, read_json_file


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
    _write_json(terminal, {"artifacts": [{"path": result.name, "sha256": result_hash}],
                           "cost": {"actual_usd": scenario["actual_cost_usd"], "status": "exact"},
                           "status": "succeeded", "synthetic": True})
    run_id = manifest["run_id"]
    append(str(store), run_id, 2, "run.resumed", str(resumed))
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
    if created["policy_decision"].get("allowed") is not True:
        raise JourneyError("authoritative policy decision was not allowed")
    if Decimal(terminal["cost"]["actual_usd"]) > Decimal(created["budget"]["max_cost_usd"]):
        raise JourneyError("terminal cost exceeds the approved budget")
    artifact = terminal["artifacts"][0]
    result_path = output / artifact["path"]
    if not result_path.is_file() or hashlib.sha256(result_path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise JourneyError("result evidence hash does not match")
    if ledger["events"][-1]["hash"] != manifest.get("ledger_head_sha256"):
        raise JourneyError("manifest does not identify the ledger head")
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
