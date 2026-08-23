#!/usr/bin/env python3
"""Offline checks for the Map standalone widget view (#306).

Run: python scripts/test_widget_map_view.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: the execution-map render tree shape (role text, issues/claims
tables, waves/collision lists), the empty-list empty state, and the
browser generic-renderer list handling (label + empty message).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))
sys.path.insert(0, str(REPO / "scripts"))

from cli.unified_cli import _run_widget  # noqa: E402
from widget_contract.loader import load_widget_file  # noqa: E402
from widget_contract.renderer import render  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def projection() -> dict:
    return {
        "role": "observer",
        "issues": [
            {"id": "owner/repo#1", "wave": 0, "blockers": [], "drift_codes": [], "launchable": True},
            {"id": "owner/repo#2", "wave": 1, "blockers": ["owner/repo#1"],
             "drift_codes": ["missing_area_or_milestone"], "launchable": False},
        ],
        "waves": [["owner/repo#1"], ["owner/repo#2"]],
        "claims": [{"claim_id": "c1", "issue_id": "owner/repo#1", "run_id": "run-1",
                    "state": "active", "lease_expires_at": 200.0, "driver_id": "cortxt-work"}],
        "collision_codes": ["resource_collision"],
    }


def main() -> int:
    # 1. The spec declares the two lists with labels and empty messages.
    spec = AP / "widget_contract" / "specs" / "execution-map-0.1.yaml"
    widget = load_widget_file(spec)
    lists = [child for child in widget.render.children if child.primitive == "list"]
    check("spec declares two list nodes", len(lists) == 2)
    check("waves list has label and empty message",
          lists[0].props.get("label") == "Waves" and lists[0].props.get("empty") == "No waves")
    check("collision list has label and empty message",
          lists[1].props.get("label") == "Collision codes" and lists[1].props.get("empty") == "No collisions")

    # 2. Render tree shape for a full fixture plan.
    tree = render(widget, {"plan": projection()}, {"plan": "fresh"})
    children = tree["render"]["children"]
    check("role renders as text", children[0]["primitive"] == "text"
          and children[0]["props"]["value"] == "observer")
    check("issues table renders rows", children[1]["primitive"] == "table"
          and len(children[1]["props"]["rows"]) == 2)
    check("claims table renders rows", children[2]["primitive"] == "table"
          and children[2]["props"]["rows"][0]["claim_id"] == "c1")
    waves = children[3]
    check("waves list renders items with label",
          waves["primitive"] == "list" and waves["props"]["label"] == "Waves"
          and waves["props"]["items"] == [["owner/repo#1"], ["owner/repo#2"]])
    collisions = children[4]
    check("collision list renders items with label",
          collisions["primitive"] == "list" and collisions["props"]["label"] == "Collision codes"
          and collisions["props"]["items"] == ["resource_collision"])

    # 3. Empty-list empty state: empty items keep the label and the empty message.
    zero = {"role": "observer", "issues": [], "waves": [], "claims": [], "collision_codes": []}
    zero_tree = render(widget, {"plan": zero}, {"plan": "fresh"})
    zero_lists = [child for child in zero_tree["render"]["children"] if child["primitive"] == "list"]
    check("empty waves keeps label and empty message",
          zero_lists[0]["props"]["label"] == "Waves" and zero_lists[0]["props"]["empty"] == "No waves"
          and zero_lists[0]["props"]["items"] == [])
    check("empty collision list keeps label and empty message",
          zero_lists[1]["props"]["label"] == "Collision codes" and zero_lists[1]["props"]["empty"] == "No collisions"
          and zero_lists[1]["props"]["items"] == [])

    # 4. CLI artifact path: --view execution-map writes the artifact without error.
    import tempfile
    from argparse import Namespace
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        plan_input = tmp_path / "plan.json"
        plan_input.write_text(json.dumps({"issues": [
            {"issue_id": "owner/repo#1", "body": "", "state": "open", "labels": ["workflow:ready"]},
            {"issue_id": "owner/repo#2", "body": "Blocked by: #1\n", "state": "open", "labels": ["workflow:ready"]},
        ], "role": "observer"}), encoding="utf-8")
        target = tmp_path / "execution-map.json"
        result = _run_widget(Namespace(widget_command=None, view="execution-map", repo=None,
                                       snapshot=target, snapshot_input=None, plan_input=plan_input))
        check("CLI execution-map view succeeds", result.status == "succeeded")
        artifact = json.loads(target.read_text(encoding="utf-8"))
        check("artifact has no error", artifact.get("error") is None)
        check("artifact renders table + list sections",
              artifact["widget"] == {"id": "execution-map", "version": "0.1"}
              and any(c["primitive"] == "table" for c in artifact["render"]["children"])
              and any(c["primitive"] == "list" for c in artifact["render"]["children"]))

    # 5. Browser generic renderer handles the list primitive with label + empty.
    html = (AP / "widget" / "index.html").read_text(encoding="utf-8")
    check("browser handles list primitive", 'node.primitive==="list"' in html)
    check("browser list uses empty message", 'p.empty||"No items."' in html)
    check("browser list uses label", 'p.label||"List"' in html)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
