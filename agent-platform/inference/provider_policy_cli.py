"""Offline JSON CLI for the Cortxt provider-assurance policy."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from provider_policy import AssuranceStatus, ProviderEvidence, evaluate_provider


def _error(code: str) -> dict[str, str]:
    return {"error": code}


def _read_request(path: str | None) -> object:
    if path is None or path == "-":
        return json.load(sys.stdin)
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def _parse_request(value: object) -> tuple[str, ProviderEvidence]:
    if not isinstance(value, dict) or set(value) != {"data_class", "provider_evidence"}:
        raise ValueError("invalid_request_shape")
    data_class = value["data_class"]
    raw_evidence = value["provider_evidence"]
    if not isinstance(data_class, str) or not isinstance(raw_evidence, dict):
        raise ValueError("invalid_request_shape")
    evidence = dict(raw_evidence)
    status = evidence.get("independent_assurance")
    if isinstance(status, str):
        try:
            evidence["independent_assurance"] = AssuranceStatus(status)
        except ValueError:
            pass
    try:
        return data_class, ProviderEvidence(**evidence)
    except TypeError as exc:
        raise ValueError("invalid_provider_evidence_shape") from exc


def run(path: str | None) -> int:
    try:
        request = _read_request(path)
        data_class, evidence = _parse_request(request)
    except json.JSONDecodeError:
        payload, exit_code = _error("invalid_json"), 3
    except (OSError, UnicodeError):
        payload, exit_code = _error("input_read_error"), 3
    except ValueError as exc:
        payload, exit_code = _error(str(exc)), 3
    else:
        decision = evaluate_provider(data_class, evidence)
        payload = asdict(decision)
        payload["reasons"] = list(decision.reasons)
        exit_code = 0 if decision.allowed else 2
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", default="-", help="JSON file, or - for stdin")
    args = parser.parse_args()
    return run(args.request)


if __name__ == "__main__":
    raise SystemExit(main())
