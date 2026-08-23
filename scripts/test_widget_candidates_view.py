#!/usr/bin/env python3
"""Offline checks for the Candidates standalone widget view (#307).

Run: python scripts/test_widget_candidates_view.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: the candidates render tree shape (frontier-first groups, row
counts), handoff descriptors (mark-ready, claim-run), the CLI artifact
path, the browser action-form surface (action host wiring + read-only
default), and the manifest row.
"""
from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))
sys.path.insert(0, str(REPO / "scripts"))

from cli.unified_cli import _run_widget  # noqa: E402
from widget_contract.candidates import build_candidates_view  # noqa: E402
from widget_contract.loader import load_widget_file  # noqa: E402
from widget_contract.registry import TYPES  # noqa: E402
from widget_contract.renderer import render  # noqa: E402
from widget_contract.validation import validate  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def issue(number, workflow="workflow:ready", body="", *, title=None, labels=(), state="OPEN", area=None):
    names = ([workflow] if workflow else []) + list(labels)
    if area:
        names.append(f"Area: {area}")
    return {"number": number, "title": title or f"Issue {number}", "body": body,
            "labels": [{"name": x} for x in names], "state": state,
            "milestone": {"title": "M1"} if number % 2 else None,
            "url": f"https://example.invalid/issues/{number}"}


def main() -> int:
    # 1. Spec declares the two operator-gated actions.
    spec = AP / "widget_contract" / "specs" / "candidates-0.1.yaml"
    widget = load_widget_file(spec)
    check("spec declares mark-ready and claim-run actions",
          {a.id for a in widget.actions} == {"mark-ready", "claim-run"})
    check("actions are operator-gated with confirm",
          all(a.authorization["mode"] == "operator" and a.confirm["required"] for a in widget.actions))

    # 2. Model validates against the closed type and renders frontier-first.
    action_descriptors = [{"id": a.id, "operation": a.operation, "port": a.port,
                           "effect_class": a.confirm["effect_class"],
                           "authorization": dict(a.authorization), "confirm": dict(a.confirm)}
                          for a in widget.actions]
    items = [issue(2, "workflow:inbox"), issue(1), issue(3, labels=("workflow:blocked",)),
             issue(4, workflow="workflow:in-progress")]
    model = build_candidates_view(items, actions=action_descriptors)
    validate(model, TYPES["candidates.view.v1"].schema)
    check("total equals all-open count", model["total"] == 4)
    check("frontier first, then in_progress",
          [g["id"] for g in model["groups"]][:2] == ["frontier", "in_progress"])
    check("every issue appears exactly once",
          len({r["number"] for g in model["groups"] for r in g["rows"]}) == model["total"])

    # 3. Render tree shape: one table per group, rows bound.
    tree = render(widget, {"candidates": model}, {"candidates": "fresh"})
    tables = [node for node in tree["render"]["children"] if node["primitive"] == "table"]
    check("one table per group with matching counts",
          [(t["props"]["label"], len(t["props"]["rows"])) for t in tables]
          == [(g["id"], g["count"]) for g in model["groups"]])
    frontier = tables[0]
    check("frontier table shows issue number and title",
          frontier["props"]["rows"][0]["number"] == 1 and frontier["props"]["rows"][0]["title"] == "Issue 1")

    # 4. Handoff descriptors are present and enabled.
    handoffs = {h["id"]: h for h in model["handoffs"]}
    check("handoffs include mark-ready and claim-run",
          {"mark-ready", "claim-run"} <= set(handoffs))
    check("mark-ready is a github-transition workflow transition",
          handoffs["mark-ready"]["port"] == "github-transition"
          and handoffs["mark-ready"]["effect_class"] == "workflow-transition")
    check("claim-run is a cli run-dispatch",
          handoffs["claim-run"]["port"] == "cli"
          and handoffs["claim-run"]["effect_class"] == "run-dispatch")

    # 5. CLI artifact path writes the contract artifact with handoffs.
    import widget_contract.adapters.github_ports as gp
    orig_list, orig_resolve = gp.list_all_open_issues, gp.resolve_blocker_status
    gp.list_all_open_issues = lambda repo: {"schema_version": 1, "complete": True, "issues": items}
    gp.resolve_blocker_status = lambda repo, number: {"status": "closed"}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "candidates.json"
            result = _run_widget(Namespace(widget_command=None, view="candidates", repo="o/r", snapshot=target))
            check("CLI candidates view succeeds", result.status == "succeeded")
            artifact = json.loads(target.read_text(encoding="utf-8"))
            check("artifact has widget identity and repo",
                  artifact["widget"] == {"id": "candidates", "version": "0.1"} and artifact["repo"] == "o/r")
            check("artifact handoffs are enabled with effect classes",
                  all(h["enabled"] and h["effect_class"] in ("workflow-transition", "run-dispatch")
                      for h in artifact["handoffs"]))
    finally:
        gp.list_all_open_issues, gp.resolve_blocker_status = orig_list, orig_resolve

    # 6. Browser surface: action forms behind the host, read-only default otherwise.
    html = (AP / "widget" / "index.html").read_text(encoding="utf-8")
    host = (AP / "widget" / "action_host.py").read_text(encoding="utf-8")
    serve = (AP / "widget" / "serve.py").read_text(encoding="utf-8")
    check("browser renders action forms via actionHost probe", "probeActions" in html and "api/action" in html)
    check("action host has exactly the token-bound POST /api/action route",
          'POST /api/action' in host and 'X-Cortxt-Token' in host)
    check("default serve.py stays read-only (no POST handler)", "do_POST" not in serve)
    manifest = json.loads((AP / "widget" / "widgets.json").read_text(encoding="utf-8"))
    check("manifest has the candidates row with artifact",
          any(w["id"] == "candidates" and w["artifact"] == "candidates.json" for w in manifest["widgets"]))

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
