#!/usr/bin/env python3
"""Offline checks for the dashboard composition path (cortxt widget compose) (#327).

Run: python scripts/test_widget_compose.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
- Valid composition loads, validates, executes child reads, merges child render trees under layout primitives, and writes composed artifact atomically with composed: true.
- Strict fail-closed error categories on missing version, connection cycle, capability mismatch, unknown layout primitive, malformed YAML, and missing --repo for github reads (no artifact written).
- Browser shell wiring (renderComposed in index.html, node --check, manifest row).
- Read-only host boundary unchanged (serve.py has no POST handler).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))
sys.path.insert(0, str(REPO / "scripts"))

from cli.unified_cli import _run_widget_compose  # noqa: E402
from widget_contract.loader import ContractError, load_composition, load_widget_file  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def main() -> int:
    fixtures_dir = REPO / "scripts" / "fixtures" / "composition"
    valid_spec = fixtures_dir / "composition.yaml"

    # 1. Valid composition loads and composes atomically with composed: true.
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "composed.json"
        res = _run_widget_compose(Namespace(
            widget_command="compose",
            spec=valid_spec,
            widgets_dir=fixtures_dir,
            snapshot=target,
            repo=None,
            snapshot_input=AP / "widget" / "snapshot.json",
            plan_input=None,
        ))
        check("valid composition CLI succeeds", res.status == "succeeded")
        check("composed artifact exists on disk", target.is_file())
        artifact = json.loads(target.read_text(encoding="utf-8"))
        check("composed flag is true", artifact.get("composed") is True)
        check("composition identity present",
              artifact.get("widget") == {"id": "pulse-dashboard", "version": "0.1"})
        check("contract_version is 0.1", artifact.get("contract_version") == "0.1")
        check("layout root primitive is stack", artifact["render"]["primitive"] == "stack")
        children = artifact["render"]["children"]
        check("both child widgets present in layout", len(children) == 2)
        metric_child = children[0]
        table_child = children[1]
        check("metric child rendered",
              metric_child["children"][0]["primitive"] == "metric"
              and metric_child["children"][0]["props"]["label"] == "Active sessions")
        check("table child rendered",
              table_child["children"][0]["primitive"] == "table"
              and table_child["children"][0]["props"]["label"] == "Workstreams")

    # 2. Failure mode: missing exact widget version fails closed with no artifact.
    with tempfile.TemporaryDirectory() as tmp:
        bad_spec = Path(tmp) / "bad_version.yaml"
        bad_spec.write_text("""
contract_version: "0.1"
composition:
  id: pulse-dashboard
  version: "0.1"
widgets:
  - namespace: pulse_metric
    widget_id: pulse-child
    version: "9.9.9"
    inputs: {}
    outputs: {}
layout:
  primitive: stack
  children:
    - primitive: panel
      widget: pulse_metric
connections: []
capabilities: [read:sessions]
""", encoding="utf-8")
        target = Path(tmp) / "composed.json"
        res = _run_widget_compose(Namespace(
            widget_command="compose",
            spec=bad_spec,
            widgets_dir=fixtures_dir,
            snapshot=target,
            repo=None,
            snapshot_input=AP / "widget" / "snapshot.json",
            plan_input=None,
        ))
        check("missing version fails closed", res.status == "failed")
        check("missing version reports contract_error category", res.error["category"] == "contract_error")
        check("missing version produces no artifact", not target.exists())

    # 3. Failure mode: connection cycle fails closed with no artifact.
    with tempfile.TemporaryDirectory() as tmp:
        cycle_spec = Path(tmp) / "cycle.yaml"
        cycle_spec.write_text("""
contract_version: "0.1"
composition:
  id: pulse-dashboard
  version: "0.1"
widgets:
  - namespace: w1
    widget_id: pulse-child
    version: "0.1"
    inputs: {in1: core.array.v1}
    outputs: {out1: core.array.v1}
  - namespace: w2
    widget_id: pulse-table
    version: "0.1"
    inputs: {in2: core.array.v1}
    outputs: {out2: core.array.v1}
layout:
  primitive: stack
  children:
    - primitive: panel
      widget: w1
    - primitive: panel
      widget: w2
connections:
  - from: w1
    output: out1
    to: w2
    input: in2
    type: core.array.v1
  - from: w2
    output: out2
    to: w1
    input: in1
    type: core.array.v1
capabilities: [read:sessions]
""", encoding="utf-8")
        target = Path(tmp) / "composed.json"
        res = _run_widget_compose(Namespace(
            widget_command="compose",
            spec=cycle_spec,
            widgets_dir=fixtures_dir,
            snapshot=target,
            repo=None,
            snapshot_input=AP / "widget" / "snapshot.json",
            plan_input=None,
        ))
        check("cycle fails closed", res.status == "failed")
        check("cycle reports contract_error category", res.error["category"] == "contract_error")
        check("cycle error mentions cyclic", "cyclic" in res.error["message"])
        check("cycle produces no artifact", not target.exists())

    # 4. Failure mode: capability mismatch fails closed with no artifact.
    with tempfile.TemporaryDirectory() as tmp:
        cap_spec = Path(tmp) / "cap_mismatch.yaml"
        cap_spec.write_text("""
contract_version: "0.1"
composition:
  id: pulse-dashboard
  version: "0.1"
widgets:
  - namespace: pulse_metric
    widget_id: pulse-child
    version: "0.1"
    inputs: {}
    outputs: {}
layout:
  primitive: stack
  children:
    - primitive: panel
      widget: pulse_metric
connections: []
capabilities: [read:sessions, read:issues]
""", encoding="utf-8")
        target = Path(tmp) / "composed.json"
        res = _run_widget_compose(Namespace(
            widget_command="compose",
            spec=cap_spec,
            widgets_dir=fixtures_dir,
            snapshot=target,
            repo=None,
            snapshot_input=AP / "widget" / "snapshot.json",
            plan_input=None,
        ))
        check("capability mismatch fails closed", res.status == "failed")
        check("capability mismatch reports contract_error category", res.error["category"] == "contract_error")
        check("capability mismatch mentions match", "match" in res.error["message"])
        check("capability mismatch produces no artifact", not target.exists())

    # 5. Failure mode: unknown layout primitive fails closed with no artifact.
    with tempfile.TemporaryDirectory() as tmp:
        layout_spec = Path(tmp) / "unknown_layout.yaml"
        layout_spec.write_text("""
contract_version: "0.1"
composition:
  id: pulse-dashboard
  version: "0.1"
widgets:
  - namespace: pulse_metric
    widget_id: pulse-child
    version: "0.1"
    inputs: {}
    outputs: {}
layout:
  primitive: carousel
  children:
    - primitive: panel
      widget: pulse_metric
connections: []
capabilities: [read:sessions]
""", encoding="utf-8")
        target = Path(tmp) / "composed.json"
        res = _run_widget_compose(Namespace(
            widget_command="compose",
            spec=layout_spec,
            widgets_dir=fixtures_dir,
            snapshot=target,
            repo=None,
            snapshot_input=AP / "widget" / "snapshot.json",
            plan_input=None,
        ))
        check("unknown layout primitive fails closed", res.status == "failed")
        check("unknown layout reports contract_error category", res.error["category"] == "contract_error")
        check("unknown layout produces no artifact", not target.exists())

    # 6. Failure mode: malformed YAML fails closed with no artifact.
    with tempfile.TemporaryDirectory() as tmp:
        malformed_spec = Path(tmp) / "malformed.yaml"
        malformed_spec.write_text("contract_version: 0.1\nwidgets: [unclosed_bracket", encoding="utf-8")
        target = Path(tmp) / "composed.json"
        res = _run_widget_compose(Namespace(
            widget_command="compose",
            spec=malformed_spec,
            widgets_dir=fixtures_dir,
            snapshot=target,
            repo=None,
            snapshot_input=AP / "widget" / "snapshot.json",
            plan_input=None,
        ))
        check("malformed YAML fails closed", res.status == "failed")
        check("malformed YAML reports contract_error category", res.error["category"] == "contract_error")
        check("malformed YAML produces no artifact", not target.exists())

    # 7. Github read without --repo fails closed with input_error.
    with tempfile.TemporaryDirectory() as tmp:
        gh_spec = Path(tmp) / "gh_comp.yaml"
        gh_spec.write_text("""
contract_version: "0.1"
composition:
  id: candidates-dashboard
  version: "0.1"
widgets:
  - namespace: cand
    widget_id: candidates
    version: "0.1"
    inputs: {}
    outputs: {}
layout:
  primitive: panel
  widget: cand
connections: []
capabilities: [read:issues, act:mark-ready, act:claim-run]
""", encoding="utf-8")
        target = Path(tmp) / "composed.json"
        res = _run_widget_compose(Namespace(
            widget_command="compose",
            spec=gh_spec,
            widgets_dir=AP / "widget_contract" / "specs",
            snapshot=target,
            repo=None,
            snapshot_input=None,
            plan_input=None,
        ))
        check("github read without --repo fails closed", res.status == "failed")
        check("github read without --repo reports input_error", res.error["category"] == "input_error")
        check("github read error mentions --repo", "--repo is required" in res.error["message"])
        check("github read without --repo produces no artifact", not target.exists())

    # 8. Github read with --repo succeeds when mocked.
    import widget_contract.adapters.github_ports as gp
    orig_list, orig_resolve = gp.list_all_open_issues, gp.resolve_blocker_status
    gp.list_all_open_issues = lambda repo: {"schema_version": 1, "complete": True, "issues": [
        {"number": 1, "title": "One", "workflow": "workflow:ready", "body": "",
         "labels": [{"name": "workflow:ready"}], "state": "OPEN", "milestone": None,
         "url": "https://example.invalid/issues/1"}
    ]}
    gp.resolve_blocker_status = lambda repo, number: {"status": "closed"}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            gh_spec = Path(tmp) / "gh_comp.yaml"
            gh_spec.write_text("""
contract_version: "0.1"
composition:
  id: candidates-dashboard
  version: "0.1"
widgets:
  - namespace: cand
    widget_id: candidates
    version: "0.1"
    inputs: {}
    outputs: {}
layout:
  primitive: panel
  widget: cand
connections: []
capabilities: [read:issues, act:mark-ready, act:claim-run]
""", encoding="utf-8")
            target = Path(tmp) / "composed.json"
            res = _run_widget_compose(Namespace(
                widget_command="compose",
                spec=gh_spec,
                widgets_dir=AP / "widget_contract" / "specs",
                snapshot=target,
                repo="o/r",
                snapshot_input=None,
                plan_input=None,
            ))
            check("github read with --repo succeeds", res.status == "succeeded")
            check("composed artifact written for github child", target.is_file())
            art = json.loads(target.read_text(encoding="utf-8"))
            check("github child composed flag true", art.get("composed") is True)
    finally:
        gp.list_all_open_issues, gp.resolve_blocker_status = orig_list, orig_resolve

    # 9. Browser shell verification.
    html = (AP / "widget" / "index.html").read_text(encoding="utf-8")
    serve = (AP / "widget" / "serve.py").read_text(encoding="utf-8")
    check("index.html contains renderComposed", "renderComposed" in html)
    check("index.html branches on tree.composed", "if(tree.composed)" in html or "tree.composed" in html)
    check("default serve.py stays read-only (no POST handler)", "do_POST" not in serve)

    manifest = json.loads((AP / "widget" / "widgets.json").read_text(encoding="utf-8"))
    check("manifest has composed row",
          any(w["id"] == "composed" and w["artifact"] == "composed.json" for w in manifest["widgets"]))

    # 10. Node syntax check on the inline script.
    match = re.search(r"<script>(.*?)</script>", html, re.S)
    check("index.html contains inline script", match is not None)
    if match:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(match.group(1))
            tmp_js = Path(handle.name)
        try:
            proc = subprocess.run(["node", "--check", str(tmp_js)], capture_output=True, text=True)
            check("node --check passes on the inline script", proc.returncode == 0)
            if proc.returncode != 0:
                print(proc.stderr[-500:])
        finally:
            tmp_js.unlink(missing_ok=True)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
