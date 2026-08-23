#!/usr/bin/env python3
"""Offline check test for CLI TUI widget appearance and shared visual tokens (Issue #345).

Run: python scripts/test_widget_tui.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. TUI module and contracts (tui.py, swimlane_text.py, chart_text.py).
2. Shared token-to-ANSI mapping and status colorizer.
3. ANSI presence with force_ansi=True and suppression with force_ansi=False.
4. Parity across primitives (heading, text, badge, metric, key-value, table, list, empty-state, error-state, swimlane, bar, line).
5. Column padding and tabular alignment across headers and rows.
6. All widget views in TUI mode (candidates, session-pulse, execution-map, docker-status, webhooks).
7. Backward compatibility: plain table, --format json, and default JSON view outputs unchanged.
8. Zero a/o/u-with-diacritics in all checked files.
"""
from __future__ import annotations

import io
import json
import re
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))
sys.path.insert(0, str(REPO / "scripts"))

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def capture_widget_run(args: Namespace, docker_reader: Any = None) -> tuple[Any, str]:
    from cli.unified_cli import _run_widget
    buf = io.StringIO()
    old_stdout = sys.stdout
    try:
        sys.stdout = buf
        result = _run_widget(args, docker_reader=docker_reader)
    finally:
        sys.stdout = old_stdout
    return result, buf.getvalue()


def main() -> int:
    # 1. Module existence and imports
    tui_file = AP / "widget_contract" / "tui.py"
    swimlane_file = AP / "widget_contract" / "swimlane_text.py"
    chart_file = AP / "widget_contract" / "chart_text.py"

    check("agent-platform/widget_contract/tui.py exists", tui_file.is_file())
    check("agent-platform/widget_contract/swimlane_text.py exists", swimlane_file.is_file())
    check("agent-platform/widget_contract/chart_text.py exists", chart_file.is_file())

    from widget_contract.chart_text import render_bar_text, render_line_text
    from widget_contract.loader import load_widget_file
    from widget_contract.renderer import render
    from widget_contract.swimlane_text import render_swimlane_text
    from widget_contract.tokens import DEFAULT_ANSI_MAP, ansi_map, load_tokens
    from widget_contract.tui import colorize_status, render_tui

    # 2. Token-to-ANSI mapping
    tokens = load_tokens()
    colors = ansi_map(tokens)
    check("tokens color map loaded from tokens.json", isinstance(colors, dict) and "accent" in colors)
    check("colorize_status maps ok status to green", "\x1b[32m" in colorize_status("ready", colors))
    check("colorize_status maps warn status to yellow", "\x1b[33m" in colorize_status("stale", colors))
    check("colorize_status maps bad status to red", "\x1b[31m" in colorize_status("failed", colors))
    check("colorize_status maps muted status to dim", "\x1b[90m" in colorize_status("idle", colors))

    # 3. ANSI control: forced vs suppressed
    sample_tree = {
        "primitive": "stack",
        "props": {"label": "Demo"},
        "children": [
            {"primitive": "metric", "props": {"label": "Active", "value": 5}},
            {"primitive": "badge", "props": {"value": "running"}},
        ],
    }
    forced_out = render_tui(sample_tree, force_ansi=True)
    check("render_tui with force_ansi=True contains ANSI codes", "\x1b[" in forced_out)

    plain_out = render_tui(sample_tree, force_ansi=False)
    check("render_tui with force_ansi=False contains zero ANSI codes", "\x1b" not in plain_out)
    check("plain_out contains label and value", "Active: 5" in plain_out and "[running]" in plain_out)

    # 4. Parity across primitives
    primitives_tree = {
        "primitive": "stack",
        "props": {"label": "Test Suite"},
        "children": [
            {"primitive": "heading", "props": {"value": "Main Heading"}},
            {"primitive": "text", "props": {"label": "Description", "value": "A test primitive node"}},
            {"primitive": "badge", "props": {"value": "ready"}},
            {"primitive": "timestamp", "props": {"label": "Updated", "value": "2026-08-23T18:00:00Z"}},
            {"primitive": "metric", "props": {"label": "Queue Depth", "value": 42}},
            {"primitive": "key-value", "props": {"value": {"mode": "auto", "healthy": True}}},
            {"primitive": "list", "props": {"label": "Checklist", "items": ["Item A", "Item B"]}},
            {"primitive": "empty-state", "props": {"message": "No pending alerts"}},
            {"primitive": "error-state", "props": {"message": "Disk full error"}},
            {"primitive": "swimlane", "props": {"label": "Workers", "items": [{"name": "w1", "active": True}, {"name": "w2", "active": False}]}},
            {"primitive": "bar", "props": {"label": "CPU", "value": 75, "max_value": 100, "width": 8}},
            {"primitive": "line", "props": {"label": "Memory", "points": [10, 20, 30, 40]}},
            {"primitive": "divider", "props": {}},
            {"primitive": "spacer", "props": {}},
            {"primitive": "button", "props": {"label": "Execute"}},
        ],
    }
    prim_plain = render_tui(primitives_tree, force_ansi=False)
    check("heading rendered", "## Main Heading" in prim_plain)
    check("text rendered", "Description: A test primitive node" in prim_plain)
    check("badge rendered", "[ready]" in prim_plain)
    check("timestamp rendered", "Updated: 2026-08-23T18:00:00Z" in prim_plain)
    check("metric rendered", "Queue Depth: 42" in prim_plain)
    check("key-value rendered", "mode: auto" in prim_plain and "healthy: true" in prim_plain)
    check("list rendered", "• Item A" in prim_plain and "• Item B" in prim_plain)
    check("empty-state rendered", "(empty) No pending alerts" in prim_plain)
    check("error-state rendered", "[error] Disk full error" in prim_plain)
    check("swimlane rendered", "Workers | w1 ●  w2 ○" in prim_plain)
    check("bar rendered", "CPU" in prim_plain and "|######--| 75" in prim_plain)
    check("line sparkline rendered", "Memory:" in prim_plain)
    check("divider rendered", "---" in prim_plain)
    check("button rendered", "[Execute]" in prim_plain)

    # 5. Table alignment and column padding
    table_tree = {
        "primitive": "table",
        "props": {
            "label": "Processes",
            "columns": ["id", "process_name", "status", "threads"],
            "rows": [
                {"id": "p1", "process_name": "worker", "status": "running", "threads": 4},
                {"id": "p1000", "process_name": "background_indexer", "status": "idle", "threads": 12},
            ],
        },
    }
    table_plain = render_tui(table_tree, force_ansi=False)
    lines = [l for l in table_plain.splitlines() if l.strip()]
    check("table has header, separator, and 2 rows", len(lines) == 5)
    header_line = lines[1]
    sep_line = lines[2]
    row1 = lines[3]
    row2 = lines[4]
    check("header and separator aligned", len(header_line) == len(sep_line))
    check("row cells aligned with header column offsets",
          header_line.index("process_name") == row1.index("worker") == row2.index("background_indexer"))

    # 6. Widget Views TUI Rendering (candidates, session-pulse, execution-map, docker-status, webhooks)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        # Candidates view
        import widget_contract.adapters.github_ports as gp
        orig_list, orig_resolve = gp.list_all_open_issues, gp.resolve_blocker_status
        cand_items = [
            {"number": 345, "title": "Build CLI TUI", "body": "", "labels": [{"name": "workflow:ready"}, {"name": "Area: widget"}], "state": "OPEN", "milestone": None, "url": None},
            {"number": 344, "title": "Host view grid", "body": "", "labels": [{"name": "workflow:in-progress"}], "state": "OPEN", "milestone": None, "url": None},
        ]
        gp.list_all_open_issues = lambda repo: {"schema_version": 1, "complete": True, "issues": cand_items}
        gp.resolve_blocker_status = lambda repo, number: {"status": "closed"}
        try:
            cand_snap = tmp / "candidates.json"
            res_cand, out_cand = capture_widget_run(
                Namespace(widget_command=None, view="candidates", repo="o/r", snapshot=cand_snap, tui=True, format=None)
            )
            check("candidates view TUI succeeded", res_cand.status == "succeeded")
            check("candidates view TUI contains header", "=== Candidates ===" in out_cand)
            check("candidates view TUI contains frontier table", "[frontier]" in out_cand)
            check("candidates view TUI contains issue rows", "345" in out_cand and "Build CLI TUI" in out_cand)
            check("candidates view TUI contains ANSI codes", "\x1b[" in out_cand)

            # Subcommand candidates with --tui
            res_cand_sub, out_cand_sub = capture_widget_run(
                Namespace(widget_command="candidates", repo="o/r", snapshot=cand_snap, tui=True, format="table")
            )
            check("widget candidates --tui succeeded", res_cand_sub.status == "succeeded")
            check("widget candidates --tui contains header", "=== Candidates ===" in out_cand_sub)
            check("widget candidates --tui contains issue rows", "Build CLI TUI" in out_cand_sub)
        finally:
            gp.list_all_open_issues, gp.resolve_blocker_status = orig_list, orig_resolve

        # Session pulse view
        pulse_data = {
            "schema_version": 2,
            "generated_at": "2026-08-23T18:00:00Z",
            "orchestrator": {"status": "running", "active_agent_sessions": 2, "abandoned_agent_sessions": 0,
                             "blocked_agent_sessions": 0, "failed_agent_sessions": 0, "attention_items": 0, "message": "2 active"},
            "workstreams": [{"workstream_id": "ws-1", "status": "running", "updated_at": "2026-08-23T18:01:00Z"}],
            "sessions": [],
            "activity": [{"timestamp": "2026-08-23T18:01:00Z", "event_type": "step", "workstream_id": "ws-1", "actor": "builder"}],
        }
        pulse_src = tmp / "pulse_src.json"
        pulse_src.write_text(json.dumps(pulse_data), encoding="utf-8")
        pulse_snap = tmp / "session-pulse.json"
        res_pulse, out_pulse = capture_widget_run(
            Namespace(view="session-pulse", snapshot_input=pulse_src, snapshot=pulse_snap, tui=True, format=None)
        )
        check("session-pulse view TUI succeeded", res_pulse.status == "succeeded")
        check("session-pulse view TUI contains header", "=== Session Pulse ===" in out_pulse)
        check("session-pulse view TUI contains workstream rows", "ws-1" in out_pulse)
        check("session-pulse view TUI contains ANSI codes", "\x1b[" in out_pulse)

        # Execution map view
        plan_data = {
            "role": "builder",
            "issues": [
                {"issue_id": "owner/repo#345", "body": "", "state": "open", "labels": ["workflow:ready"]},
            ],
        }
        plan_src = tmp / "plan_src.json"
        plan_src.write_text(json.dumps(plan_data), encoding="utf-8")
        plan_snap = tmp / "execution-map.json"
        res_map, out_map = capture_widget_run(
            Namespace(view="execution-map", plan_input=plan_src, snapshot=plan_snap, tui=True, format=None)
        )
        check("execution-map view TUI succeeded", res_map.status == "succeeded")
        check("execution-map view TUI contains header", "=== Execution Map ===" in out_map)
        check("execution-map view TUI contains issue rows", "owner/repo#345" in out_map)
        check("execution-map view TUI contains ANSI codes", "\x1b[" in out_map)

        # Docker status view
        fake_docker = lambda: {
            "engine": {"version": "27.0.0", "status": "running"},
            "containers": [{"id": "c100", "name": "cortxt-daemon", "image": "cortxt:v1", "status": "running"}],
            "images": ["cortxt:v1"],
            "total_containers": 1,
            "running_containers": 1,
        }
        docker_snap = tmp / "docker-status.json"
        res_docker, out_docker = capture_widget_run(
            Namespace(view="docker-status", snapshot=docker_snap, tui=True, format=None),
            docker_reader=fake_docker,
        )
        check("docker-status view TUI succeeded", res_docker.status == "succeeded")
        check("docker-status view TUI contains header", "=== Docker Status ===" in out_docker)
        check("docker-status view TUI contains container rows", "cortxt-daemon" in out_docker and "c100" in out_docker)
        check("docker-status view TUI contains ANSI codes", "\x1b[" in out_docker)

        # Webhooks view
        import cli.unified_cli as ucli
        orig_wh, orig_pd = ucli._gh_webhooks_reader, ucli._pages_deploys_reader
        ucli._gh_webhooks_reader = lambda repo: [{"id": 55, "url": "https://api.example.invalid/webhook", "events": ["push"], "active": True}]
        ucli._pages_deploys_reader = lambda: {
            "project": "cortxt", "account": "acc-1",
            "latest": {"id": "dep-1", "environment": "production", "created_on": "2026-08-23T18:00:00Z", "stage": "deploy", "status": "success"},
            "deployments": [{"id": "dep-1", "environment": "production", "created_on": "2026-08-23T18:00:00Z", "stage": "deploy"}],
        }
        try:
            webhooks_snap = tmp / "webhooks.json"
            res_wh, out_wh = capture_widget_run(
                Namespace(view="webhooks", repo="owner/repo", snapshot=webhooks_snap, tui=True, format=None)
            )
            check("webhooks view TUI succeeded", res_wh.status == "succeeded")
            check("webhooks view TUI contains header", "=== Webhooks ===" in out_wh)
            check("webhooks view TUI contains hook rows", "https://api.example.invalid/webhook" in out_wh)
            check("webhooks view TUI contains ANSI codes", "\x1b[" in out_wh)
        finally:
            ucli._gh_webhooks_reader, ucli._pages_deploys_reader = orig_wh, orig_pd

        # 7. Backward Compatibility Checks
        # Backward comp 1: default candidates subcommand format=table (plain lines)
        gp.list_all_open_issues = lambda repo: {"schema_version": 1, "complete": True, "issues": cand_items}
        gp.resolve_blocker_status = lambda repo, number: {"status": "closed"}
        try:
            res_plain, out_plain = capture_widget_run(
                Namespace(widget_command="candidates", repo="o/r", snapshot=cand_snap, tui=False, format="table")
            )
            check("backward compatible plain table succeeds", res_plain.status == "succeeded")
            check("backward compatible plain table has group header format", "frontier (1)" in out_plain)
            check("backward compatible plain table has issue line format", "#345 Build CLI TUI | workflow:ready" in out_plain)
            check("backward compatible plain table has zero ANSI codes", "\x1b" not in out_plain)

            # Backward comp 2: candidates subcommand format=json
            res_json, out_json = capture_widget_run(
                Namespace(widget_command="candidates", repo="o/r", snapshot=cand_snap, tui=False, format="json")
            )
            check("backward compatible json succeeds", res_json.status == "succeeded")
            parsed_json = json.loads(out_json)
            check("backward compatible json has total and groups", parsed_json.get("total") == 2 and "groups" in parsed_json)

            # Backward comp 3: default view without --tui outputs JSON stdout_tree
            res_view_json, out_view_json = capture_widget_run(
                Namespace(view="session-pulse", snapshot_input=pulse_src, snapshot=pulse_snap, tui=False, format=None)
            )
            check("backward compatible view json succeeds", res_view_json.status == "succeeded")
            parsed_view = json.loads(out_view_json)
            check("backward compatible view json has primitive stack", parsed_view.get("primitive") == "stack")
        finally:
            gp.list_all_open_issues, gp.resolve_blocker_status = orig_list, orig_resolve

    # 8. Zero Swedish / diacritic characters check
    diacritic_pattern = re.compile(r"[\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]")
    checked_files = [
        tui_file,
        swimlane_file,
        chart_file,
        AP / "cli" / "unified_cli.py",
        AP / "tests" / "widget_contract" / "test_tui.py",
        Path(__file__),
    ]
    diacritic_free = True
    for cf in checked_files:
        if cf.is_file():
            text = cf.read_text(encoding="utf-8")
            matches = diacritic_pattern.findall(text)
            if matches:
                diacritic_free = False
                FAILS.append(f"diacritics found in {cf.name}: {matches}")

    check("zero a/o/u-with-diacritics in checked files", diacritic_free)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
