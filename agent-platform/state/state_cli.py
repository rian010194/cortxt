"""Command-line interface for the offline Cortxt state ledger."""

from __future__ import annotations

import argparse
import json
import sys

from ledger import LedgerError, append, canonical_json, create, load


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise LedgerError("usage_error", message, 2)


def parser() -> argparse.ArgumentParser:
    root = Parser(prog="state_cli.py")
    commands = root.add_subparsers(dest="command", required=True)
    make = commands.add_parser("create")
    make.add_argument("--store", required=True)
    make.add_argument("--task-id", required=True)
    make.add_argument("--data-class", required=True)
    make.add_argument("--workflow", required=True)
    make.add_argument("--max-cost-usd", required=True)
    make.add_argument("--provider-evidence-file", required=True)
    add = commands.add_parser("append")
    add.add_argument("--store", required=True)
    add.add_argument("--run-id", required=True)
    add.add_argument("--expected-sequence", required=True, type=int)
    add.add_argument("--event-type", required=True)
    add.add_argument("--payload-file", required=True)
    show = commands.add_parser("show")
    show.add_argument("--store", required=True)
    show.add_argument("--run-id", required=True)
    return root


def emit(value: object, stream=sys.stdout) -> None:
    stream.buffer.write(canonical_json(value) + b"\n")


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = parser().parse_args(argv)
        if arguments.command == "create":
            ledger = create(arguments.store, arguments.task_id, arguments.data_class,
                            arguments.workflow, arguments.max_cost_usd,
                            arguments.provider_evidence_file)
        elif arguments.command == "append":
            ledger = append(arguments.store, arguments.run_id, arguments.expected_sequence,
                            arguments.event_type, arguments.payload_file)
        else:
            _, ledger = load(arguments.store, arguments.run_id)
        emit(ledger)
        return 0
    except LedgerError as error:
        emit({"error": {"category": error.category, "message": error.message}}, sys.stderr)
        return error.exit_code
    except Exception:
        emit({"error": {"category": "internal_error", "message": "unexpected internal failure"}}, sys.stderr)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
