"""Tests for widget contract TUI renderer and shared tokens visual styling."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from cli.unified_cli import _run_widget
from widget_contract.chart_text import render_bar_gauge, render_line_spark
from widget_contract.loader import load_widget_file
from widget_contract.renderer import render
from widget_contract.swimlane_text import render_swimlane_text
from widget_contract.tokens import DEFAULT_ANSI_MAP, ansi_map, load_tokens
from widget_contract.tui import colorize_status, render_tui

SPECS_DIR = Path(__file__).resolve().parents[2] / "widget_contract" / "specs"


def test_render_tui_heading_text_badge_metric():
    tree = {
        "primitive": "stack",
        "props": {"label": "Summary"},
        "children": [
            {"primitive": "heading", "props": {"value": "Section Title"}},
            {"primitive": "text", "props": {"label": "Status Note", "value": "All systems nominal"}},
            {"primitive": "badge", "props": {"value": "ready"}},
            {"primitive": "metric", "props": {"label": "Active Workers", "value": 4}},
        ],
    }
    plain = render_tui(tree, force_ansi=False)
    assert "=== Summary ===" in plain
    assert "## Section Title" in plain
    assert "Status Note: All systems nominal" in plain
    assert "[ready]" in plain
    assert "Active Workers: 4" in plain
    assert "\x1b" not in plain

    colored = render_tui(tree, force_ansi=True)
    assert "\x1b" in colored
    assert "=== Summary ===" in colored
    assert "Section Title" in colored


def test_render_tui_key_value_and_table_alignment():
    tree = {
        "primitive": "stack",
        "children": [
            {
                "primitive": "key-value",
                "props": {
                    "value": {
                        "environment": "production",
                        "status": "running",
                        "details": {"cluster": "us-east", "healthy": True},
                    }
                },
            },
            {
                "primitive": "table",
                "props": {
                    "label": "Processes",
                    "columns": ["id", "name", "status", "count"],
                    "rows": [
                        {"id": "p1", "name": "scheduler", "status": "running", "count": 10},
                        {"id": "p200", "name": "worker", "status": "blocked", "count": 2},
                    ],
                },
            },
        ],
    }
    plain = render_tui(tree, force_ansi=False)
    assert "environment: production" in plain
    assert "status: running" in plain
    assert "cluster: us-east" in plain
    assert "[Processes]" in plain
    assert "id" in plain and "name" in plain and "status" in plain and "count" in plain
    assert "p1" in plain and "scheduler" in plain
    assert "p200" in plain and "worker" in plain

    lines = plain.splitlines()
    table_lines = [l for l in lines if "p1" in l or "p200" in l or "---" in l]
    assert len(table_lines) >= 3


def test_render_tui_status_color_mapping():
    colors = ansi_map()
    assert "\x1b" in colorize_status("ok", colors)
    assert "\x1b" in colorize_status("running", colors)
    assert "\x1b" in colorize_status("warn", colors)
    assert "\x1b" in colorize_status("stale", colors)
    assert "\x1b" in colorize_status("bad", colors)
    assert "\x1b" in colorize_status("error", colors)
    assert "\x1b" in colorize_status("idle", colors)
    assert "\x1b" in colorize_status(True, colors)
    assert "\x1b" in colorize_status(False, colors)

    no_colors = {k: "" for k in DEFAULT_ANSI_MAP}
    assert "\x1b" not in colorize_status("running", no_colors)
    assert colorize_status("running", no_colors) == "running"


def test_render_tui_empty_and_error_states():
    empty_tree = {
        "primitive": "stack",
        "children": [
            {"primitive": "empty-state", "props": {"message": "No active tasks"}},
            {"primitive": "list", "props": {"label": "Tags", "items": [], "empty": "No tags defined"}},
            {"primitive": "table", "props": {"label": "Items", "columns": ["a", "b"], "rows": [], "empty": "Empty table"}},
        ],
    }
    plain = render_tui(empty_tree, force_ansi=False)
    assert "(empty) No active tasks" in plain
    assert "(No tags defined)" in plain
    assert "(Empty table)" in plain

    err_tree = {
        "primitive": "error-state",
        "props": {"message": "Connection refused to daemon"},
    }
    plain_err = render_tui(err_tree, force_ansi=False)
    assert "[error] Connection refused to daemon" in plain_err


def test_swimlane_text_rendering():
    items = [
        {"id": "w1", "active": True, "status": "running"},
        {"id": "w2", "active": False, "status": "idle"},
        {"id": "w3", "status": "blocked"},
    ]
    plain = render_swimlane_text(items, label="Workstreams")
    assert "Workstreams |" in plain
    assert "w1 ●" in plain
    assert "w2 ○" in plain
    assert "w3 ✖" in plain

    colored = render_swimlane_text(items, label="Workstreams", colors=ansi_map())
    assert "\x1b" in colored


def test_chart_text_bar_and_line():
    bar_plain = render_bar_gauge("Memory", 50, max_value=100, width=10)
    assert "Memory" in bar_plain
    assert "|#####-----| 50" in bar_plain

    bar_colored = render_bar_gauge("Memory", 50, max_value=100, width=10, colors=ansi_map())
    assert "\x1b" in bar_colored

    line_plain = render_line_spark([10, 20, 50, 80, 100], label="Load")
    assert "Load:" in line_plain
    assert len(line_plain) > 5

    line_empty = render_line_spark([], label="Load")
    assert line_empty == "Load: (no points)"


def test_candidates_widget_tui_rendering():
    widget = load_widget_file(SPECS_DIR / "candidates-0.1.yaml")
    data = {
        "schema_version": 1,
        "source": {"complete": True, "status": "fresh", "age_seconds": 10, "error": None},
        "total": 2,
        "groups": [
            {
                "id": "frontier",
                "count": 1,
                "rows": [
                    {
                        "number": 345,
                        "title": "Build CLI TUI",
                        "workflow": "workflow:ready",
                        "area": "widget",
                        "milestone": "M1",
                        "url": "https://example.invalid/345",
                        "open_blocker_count": 0,
                        "dependencies": [],
                        "violations": [],
                    }
                ],
            },
            {
                "id": "in_progress",
                "count": 1,
                "rows": [
                    {
                        "number": 344,
                        "title": "Build host grid",
                        "workflow": "workflow:in-progress",
                        "area": "widget",
                        "milestone": None,
                        "url": "https://example.invalid/344",
                        "open_blocker_count": 0,
                        "dependencies": [],
                        "violations": [],
                    }
                ],
            },
            {"id": "blocked", "count": 0, "rows": []},
            {"id": "other", "count": 0, "rows": []},
            {"id": "violations", "count": 0, "rows": []},
            {"id": "atlas_maps", "count": 0, "rows": []},
        ],
        "handoffs": [],
    }
    tree = render(widget, {"candidates": data}, {"candidates": "fresh"})

    tui_output = render_tui(tree, force_ansi=True)
    assert "=== Candidates ===" in tui_output
    assert "Total:" in tui_output
    assert "2" in tui_output
    assert "[frontier]" in tui_output
    assert "345" in tui_output
    assert "Build CLI TUI" in tui_output
    assert "\x1b" in tui_output

    plain_output = render_tui(tree, force_ansi=False)
    assert "Total: 2" in plain_output
    assert "\x1b" not in plain_output


def test_cli_session_pulse_view_tui(tmp_path, capsys):
    snapshot_data = {
        "schema_version": 2,
        "generated_at": "2026-08-23T18:00:00Z",
        "orchestrator": {
            "status": "running",
            "active_agent_sessions": 3,
            "abandoned_agent_sessions": 0,
            "blocked_agent_sessions": 0,
            "failed_agent_sessions": 0,
            "attention_items": 0,
            "message": "3 active",
        },
        "workstreams": [
            {"workstream_id": "ws-1", "status": "running", "updated_at": "2026-08-23T18:01:00Z"}
        ],
        "sessions": [],
        "activity": [],
    }
    src = tmp_path / "snapshot.json"
    src.write_text(json.dumps(snapshot_data), encoding="utf-8")
    out = tmp_path / "session-pulse.json"

    # Run with --tui
    res = _run_widget(Namespace(view="session-pulse", snapshot_input=src, snapshot=out, tui=True, format=None))
    captured = capsys.readouterr()
    assert res.status == "succeeded"
    assert "=== Session Pulse ===" in captured.out
    assert "Active sessions:" in captured.out
    assert "3" in captured.out
    assert "ws-1" in captured.out
    assert "\x1b" in captured.out

    # Run with --format tui
    res_fmt = _run_widget(Namespace(view="session-pulse", snapshot_input=src, snapshot=out, tui=False, format="tui"))
    captured_fmt = capsys.readouterr()
    assert res_fmt.status == "succeeded"
    assert "=== Session Pulse ===" in captured_fmt.out
    assert "Active sessions: 3" in captured_fmt.out

    # Run without --tui (backward compatible JSON stdout)
    res_default = _run_widget(Namespace(view="session-pulse", snapshot_input=src, snapshot=out, tui=False, format=None))
    captured_default = capsys.readouterr()
    assert res_default.status == "succeeded"
    parsed = json.loads(captured_default.out)
    assert "primitive" in parsed


def test_cli_docker_status_view_tui(tmp_path, capsys):
    fake_docker = lambda: {
        "engine": {"version": "27.0.0", "status": "running"},
        "containers": [{"id": "c123", "name": "cns-agent", "image": "cortxt:latest", "status": "running"}],
        "images": ["cortxt:latest"],
        "total_containers": 1,
        "running_containers": 1,
    }
    out = tmp_path / "docker-status.json"
    res = _run_widget(Namespace(view="docker-status", snapshot=out, tui=True, format=None), docker_reader=fake_docker)
    captured = capsys.readouterr()
    assert res.status == "succeeded"
    assert "=== Docker Status ===" in captured.out
    assert "c123" in captured.out
    assert "cns-agent" in captured.out
    assert "\x1b" in captured.out


def test_cli_execution_map_view_tui(tmp_path, capsys):
    plan_data = {
        "role": "builder",
        "issues": [{"issue_id": "owner/repo#345", "body": "", "state": "open",
                    "labels": ["workflow:ready"]}],
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")
    out = tmp_path / "execution-map.json"

    res = _run_widget(Namespace(view="execution-map", plan_input=plan_file, snapshot=out, tui=True, format=None))
    captured = capsys.readouterr()
    assert res.status == "succeeded"
    assert "=== Execution Map ===" in captured.out
    assert "Role:" in captured.out and "builder" in captured.out
    assert "owner/repo#345" in captured.out
    assert "\x1b" in captured.out


def test_cli_webhooks_view_tui(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("cli.unified_cli._gh_webhooks_reader", lambda repo: [
        {"id": 101, "url": "https://example.invalid/hook", "events": ["push"], "active": True}
    ])
    monkeypatch.setattr("cli.unified_cli._pages_deploys_reader", lambda: {
        "project": "cortxt",
        "account": "acc123",
        "latest": {"id": "d1", "environment": "production", "created_on": "2026-08-23T18:00:00Z", "stage": "deploy", "status": "success"},
        "deployments": [{"id": "d1", "environment": "production", "created_on": "2026-08-23T18:00:00Z", "stage": "deploy"}],
    })
    out = tmp_path / "webhooks.json"
    res = _run_widget(Namespace(view="webhooks", repo="owner/repo", snapshot=out, tui=True, format=None))
    captured = capsys.readouterr()
    assert res.status == "succeeded"
    assert "=== Webhooks ===" in captured.out
    assert "https://example.invalid/hook" in captured.out
    assert "\x1b" in captured.out

