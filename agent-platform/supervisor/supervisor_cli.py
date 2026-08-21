"""Operator entry point for Phase 4 Supervisor -- proves the exit criterion is
reachable without Hermes as an intermediary."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime import session_state as state
from supervisor.coordinator import Coordinator
from supervisor.run_tree import NodeDocs, build_index
from reasoning.recursive.bounds import RLMConfig


def _status(store: Path, root_session_id: str) -> dict:
    root_doc = state.load(store, root_session_id)
    child_ids = [e["payload"]["session_id"] for e in root_doc["events"]
                 if e["event_type"] == "child.spawned"]
    child_docs = {sid: state.load(store, sid) for sid in child_ids}
    tree = NodeDocs(session_doc=root_doc,
                     children={sid: NodeDocs(session_doc=doc, children={})
                               for sid, doc in child_docs.items()})
    index = build_index(tree, total_budget=RLMConfig())
    return {"root_status": index.root_status,
            "children": [{"session_id": c.session_id, "status": c.root_status}
                          for c in index.children]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4 Supervisor operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    status_parser = sub.add_parser("status")
    status_parser.add_argument("--store", required=True, type=Path)
    status_parser.add_argument("--root-session-id", required=True)

    cancel_parser = sub.add_parser("cancel")
    cancel_parser.add_argument("--store", required=True, type=Path)
    cancel_parser.add_argument("--root-session-id", required=True)

    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(_status(args.store, args.root_session_id)))
    elif args.command == "cancel":
        coordinator = Coordinator(store=args.store)
        result = coordinator.cancel_root(args.root_session_id)
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
