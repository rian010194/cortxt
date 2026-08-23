#!/usr/bin/env python3
"""Offline checks for the Usage and Cost widget and chart primitives (#349).

Run: python scripts/test_widget_usage_cost.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. Chart primitives (bar, line) registered in widget contract with closed props.
2. Strict loading of usage-cost-0.1.yaml spec.
3. Safe adapter projection read_usage_cost_v1 and fail-closed validation.
4. CLI artifact generation with injected usage reader and error handling.
5. Maker.js and index.html renderer support and pulse animation markers.
6. Multi-state living fixture sequence (>= 3 snapshots with growing usage).
7. TUI text fallback rendering for bar and line charts.
8. Manifest row presence and node --check validation.
9. Zero a/o/u-with-diacritics across all touched files.
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

from cli.unified_cli import _run_widget  # noqa: E402
from widget_contract.adapters.store_reads import ReadAdapterError, read_usage_cost_v1  # noqa: E402
from widget_contract.chart_text import render_bar_text, render_line_text  # noqa: E402
from widget_contract.loader import ContractError, load_widget_file  # noqa: E402
from widget_contract.registry import PRIMITIVES, READ_OPERATIONS, TYPES  # noqa: E402
from widget_contract.renderer import render  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def sample_usage_snapshot():
    return {
        "schema_version": 1,
        "period": "2026-08-23",
        "total_cost_usd": 0.42,
        "total_tokens": 24800,
        "runtimes": [
            {"id": "hermes", "name": "Hermes", "tokens_in": 8000, "tokens_out": 4000, "cost_usd": 0.12, "model": "hermes-3-70b", "tokens": 12000},
            {"id": "codex", "name": "Codex", "tokens_in": 6000, "tokens_out": 2500, "cost_usd": 0.15, "model": "gpt-4o", "tokens": 8500},
            {"id": "claude", "name": "Claude", "tokens_in": 2000, "tokens_out": 1200, "cost_usd": 0.10, "model": "claude-3-7-sonnet", "tokens": 3200},
            {"id": "dsh", "name": "DSH", "tokens_in": 800, "tokens_out": 300, "cost_usd": 0.05, "model": "deepseek-v3", "tokens": 1100},
        ],
        "history": [
            {"at": "10:00", "tokens": 3000, "cost_usd": 0.05},
            {"at": "10:15", "tokens": 7500, "cost_usd": 0.12},
            {"at": "10:30", "tokens": 14000, "cost_usd": 0.22},
            {"at": "10:45", "tokens": 19500, "cost_usd": 0.31},
            {"at": "11:00", "tokens": 24800, "cost_usd": 0.42},
        ],
    }


def main() -> int:
    # 1. Chart primitives registration
    check("bar primitive registered in PRIMITIVES", "bar" in PRIMITIVES)
    bar_entry = PRIMITIVES.get("bar")
    check("bar primitive has closed props and values binding",
          bar_entry is not None
          and bar_entry.props == frozenset({"label", "categories", "empty", "error"})
          and bar_entry.bindings == {"values": "core.array.v1"})

    check("line primitive registered in PRIMITIVES", "line" in PRIMITIVES)
    line_entry = PRIMITIVES.get("line")
    check("line primitive has closed props and series binding",
          line_entry is not None
          and line_entry.props == frozenset({"label", "points", "empty", "error"})
          and line_entry.bindings == {"series": "core.array.v1"})

    # 2. Spec strictly declares usage-cost identity and reads
    spec = AP / "widget_contract" / "specs" / "usage-cost-0.1.yaml"
    check("usage-cost-0.1.yaml spec file exists", spec.is_file())
    widget = load_widget_file(spec)
    check("spec declares usage-cost identity and version",
          widget.id == "usage-cost" and widget.version == "0.1" and widget.title == "Usage & Cost")
    check("spec declares no actions", widget.actions == ())
    check("spec declares read:usage-cost capability", set(widget.capabilities) == {"read:usage-cost"})
    check("spec has 1 read declaring usage-cost.v1 store operation",
          len(widget.reads) == 1
          and widget.reads[0].id == "usage"
          and widget.reads[0].source == "store"
          and widget.reads[0].operation == "usage-cost.v1"
          and widget.reads[0].output_type == "usage-cost.v1")

    # 3. Registry types and read operations
    check("usage-cost.v1 registered in TYPES",
          "usage-cost.v1" in TYPES and TYPES["usage-cost.v1"].data_class == "operational")
    check("usage-cost.v1 registered in READ_OPERATIONS",
          "usage-cost.v1" in READ_OPERATIONS
          and READ_OPERATIONS["usage-cost.v1"].capability == "read:usage-cost"
          and READ_OPERATIONS["usage-cost.v1"].source == "store")

    # 4. Safe projection and adapter validation
    data = sample_usage_snapshot()
    proj = read_usage_cost_v1(data)
    check("adapter produces valid projection with derived arrays",
          proj["total_tokens"] == 24800
          and proj["total_cost_usd"] == 0.42
          and proj["runtime_tokens"] == [12000, 8500, 3200, 1100]
          and proj["model_costs"] == [0.12, 0.15, 0.10, 0.05]
          and len(proj["history_tokens"]) == 5)

    callable_proj = read_usage_cost_v1(lambda: data)
    check("adapter accepts callable data source", callable_proj["total_tokens"] == 24800)

    # Malformed inputs fail closed
    bad_inputs = [
        "not_a_dict",
        {"runtimes": "not_a_list", "history": []},
        {"runtimes": [], "history": "not_a_list"},
        {"runtimes": [{"name": "MissingFields"}], "history": []},
        {"runtimes": [{"id": "h", "name": "H", "tokens_in": -1, "tokens_out": 0, "cost_usd": 0.1, "model": "m"}], "history": []},
        {"runtimes": [], "history": [{"at": "10:00", "tokens": "not_an_int", "cost_usd": 0.1}]},
        {"runtimes": [], "history": [], "total_cost_usd": -5.0},
    ]
    for i, bad in enumerate(bad_inputs):
        failed_closed = False
        try:
            read_usage_cost_v1(bad)
        except ReadAdapterError:
            failed_closed = True
        check(f"malformed input case {i + 1} fails closed", failed_closed)

    # 5. Render tree shape
    tree = render(widget, {"usage": proj}, {"usage": "fresh"})
    check("render tree primitive is stack", tree["render"]["primitive"] == "stack")
    children = tree["render"]["children"]
    check("rendered tree contains 5 expected children (2 metrics, 2 bars, 1 line)",
          len(children) == 5
          and children[0]["primitive"] == "metric"
          and children[1]["primitive"] == "metric"
          and children[2]["primitive"] == "bar"
          and children[3]["primitive"] == "bar"
          and children[4]["primitive"] == "line")
    check("first bar has runtime tokens and categories",
          children[2]["props"]["label"] == "Tokens by runtime"
          and children[2]["props"]["values"] == [12000, 8500, 3200, 1100]
          and children[2]["props"]["categories"] == ["Hermes", "Codex", "Claude", "DSH"])
    check("second bar has model costs",
          children[3]["props"]["label"] == "Cost by model"
          and children[3]["props"]["values"] == [0.12, 0.15, 0.1, 0.05])
    check("line chart has points and series",
          children[4]["props"]["label"] == "Usage over time"
          and children[4]["props"]["series"] == [3000, 7500, 14000, 19500, 24800]
          and children[4]["props"]["points"] == ["10:00", "10:15", "10:30", "10:45", "11:00"])

    # 6. CLI view artifact generation and error handling
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out_ready = tmp_path / "usage-cost.json"

        res = _run_widget(
            Namespace(widget_command=None, view="usage-cost", repo=None, snapshot=out_ready),
            usage_reader=lambda: data,
        )
        check("CLI usage-cost view succeeds with valid reader", res.status == "succeeded")
        check("CLI output artifact exists", out_ready.is_file())
        art_ready = json.loads(out_ready.read_text(encoding="utf-8"))
        check("artifact has usage-cost identity and no error",
              art_ready["widget"] == {"id": "usage-cost", "version": "0.1"} and art_ready["error"] is None)
        check("artifact render state is ready", art_ready["render"]["state"] == "ready")

        # Failing reader
        def broken_reader():
            raise OSError("usage ledger unreachable")

        out_err = tmp_path / "usage-cost-err.json"
        res_err = _run_widget(
            Namespace(widget_command=None, view="usage-cost", repo=None, snapshot=out_err),
            usage_reader=broken_reader,
        )
        check("CLI settles succeeded on reader exception", res_err.status == "succeeded")
        art_err = json.loads(out_err.read_text(encoding="utf-8"))
        check("error artifact has kind usage_cost_read and error-state primitive",
              art_err["error"]["kind"] == "usage_cost_read"
              and "usage ledger unreachable" in art_err["error"]["message"]
              and art_err["render"]["primitive"] == "error-state"
              and art_err["render"]["state"] == "error")

        # Malformed reader
        out_mal = tmp_path / "usage-cost-mal.json"
        res_mal = _run_widget(
            Namespace(widget_command=None, view="usage-cost", repo=None, snapshot=out_mal),
            usage_reader=lambda: {"runtimes": "corrupted"},
        )
        check("CLI settles succeeded on malformed reader data", res_mal.status == "succeeded")
        art_mal = json.loads(out_mal.read_text(encoding="utf-8"))
        check("malformed artifact has kind usage_cost_read and error-state primitive",
              art_mal["error"]["kind"] == "usage_cost_read"
              and art_mal["render"]["primitive"] == "error-state")

    # 7. TUI text fallback rendering
    bar_node = children[2]
    bar_text = render_bar_text(bar_node)
    check("render_bar_text produces non-empty output with label and categories",
          "Tokens by runtime" in bar_text and "Hermes" in bar_text and "12,000" in bar_text and "#" in bar_text)

    line_node = children[4]
    line_text = render_line_text(line_node)
    check("render_line_text produces non-empty output with series and points",
          "Usage over time" in line_text and "10:00" in line_text and "24,800" in line_text)

    # Empty node fallback
    empty_bar_text = render_bar_text({"primitive": "bar", "props": {"label": "Empty Bar", "empty": "No items"}})
    check("render_bar_text handles empty node gracefully", "No items" in empty_bar_text)

    # 8. Living fixture multi-state sequence
    fixture_paths = [
        REPO / "scripts" / "fixtures" / "widget_maker" / "usage_data.json",
        AP / "widget" / "fixtures" / "usage_data.json",
        REPO / "site" / "public" / "widgets" / "fixtures" / "usage_data.json",
    ]
    for fp in fixture_paths:
        check(f"fixture file exists: {fp.relative_to(REPO)}", fp.is_file())
        if fp.is_file():
            fix_json = json.loads(fp.read_text(encoding="utf-8"))
            states = fix_json.get("states", [])
            check(f"fixture {fp.name} contains multi-state sequence with >= 3 states", len(states) >= 3)
            # Verify growing tokens over time across states
            token_counts = [s["usage"]["total_tokens"] for s in states if "usage" in s and "total_tokens" in s["usage"]]
            check(f"fixture {fp.name} states exhibit growing usage sequence",
                  len(token_counts) >= 3 and token_counts == sorted(token_counts) and token_counts[0] < token_counts[-1])

    # 9. Maker.js and index.html branches and animation markers
    maker_code = (AP / "widget" / "maker.js").read_text(encoding="utf-8")
    index_html = (AP / "widget" / "index.html").read_text(encoding="utf-8")

    check("maker.js has bar primitive branch", 'primitive === "bar"' in maker_code)
    check("maker.js has line primitive branch", 'primitive === "line"' in maker_code)
    check("maker.js includes pulse-dot / chart-latest markers",
          "pulse-dot" in maker_code and "chart-latest" in maker_code)
    check("maker.js exports createSequenceStepper", "createSequenceStepper" in maker_code)

    check("index.html has bar primitive branch", 'node.primitive==="bar"' in index_html)
    check("index.html has line primitive branch", 'node.primitive==="line"' in index_html)
    check("index.html has pulse-dot CSS class", ".pulse-dot" in index_html)
    check("index.html has keyframes pulse animation", "@keyframes pulse" in index_html)
    check("index.html has chart-bar-track and chart-bar-fill CSS",
          ".chart-bar-track" in index_html and ".chart-bar-fill" in index_html)

    # 10. Manifest row
    manifest = json.loads((AP / "widget" / "widgets.json").read_text(encoding="utf-8"))
    usage_row = next((w for w in manifest.get("widgets", []) if w.get("id") == "usage"), None)
    check("manifest contains usage row", usage_row is not None)
    if usage_row:
        check("usage manifest row declares title 'Usage & Cost'", usage_row.get("title") == "Usage & Cost")
        check("usage manifest row declares spec 'widget_contract/specs/usage-cost-0.1.yaml'",
              usage_row.get("spec") == "widget_contract/specs/usage-cost-0.1.yaml")
        check("usage manifest row declares artifact 'usage-cost.json'",
              usage_row.get("artifact") == "usage-cost.json")
        check("usage manifest row declares hint", "usage-cost" in str(usage_row.get("hint")))

    # 11. Node check on maker.js and index.html
    res_m = subprocess.run(["node", "--check", str(AP / "widget" / "maker.js")], capture_output=True, text=True)
    check("node --check passes on maker.js", res_m.returncode == 0)

    # Extract script from index.html to check syntax
    script_match = re.search(r"<script>(.*?)</script>", index_html, re.DOTALL)
    if script_match:
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w", encoding="utf-8") as f:
            f.write(script_match.group(1))
            f_path = f.name
        res_idx = subprocess.run(["node", "--check", f_path], capture_output=True, text=True)
        Path(f_path).unlink(missing_ok=True)
        check("node --check passes on index.html inline script", res_idx.returncode == 0)

    # 12. Diacritics check on touched files
    touched_files = [
        AP / "widget_contract" / "registry.py",
        AP / "widget_contract" / "chart_text.py",
        AP / "widget_contract" / "adapters" / "store_reads.py",
        AP / "widget_contract" / "specs" / "usage-cost-0.1.yaml",
        AP / "cli" / "unified_cli.py",
        AP / "widget" / "maker.js",
        AP / "widget" / "index.html",
        AP / "widget" / "widgets.json",
        AP / "widget" / "fixtures" / "usage_data.json",
        AP / "widget" / "fixtures" / "usage-cost.json",
        REPO / "scripts" / "test_widget_usage_cost.py",
    ]
    diacritic_re = re.compile(r"[\u00e0-\u00ff\u0100-\u017f\u00c0-\u00df]")
    diacritic_fails = []
    for tf in touched_files:
        if tf.is_file():
            text = tf.read_text(encoding="utf-8")
            if diacritic_re.search(text):
                diacritic_fails.append(str(tf.relative_to(REPO)))
    check("zero a/o/u-with-diacritics in touched files", len(diacritic_fails) == 0)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
