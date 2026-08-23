"""Unit tests for the usage-cost widget and chart primitives (#349)."""

from __future__ import annotations

import json
import tempfile
from argparse import Namespace
from pathlib import Path

import pytest

from cli.unified_cli import _run_widget
from widget_contract.adapters.store_reads import ReadAdapterError, read_usage_cost_v1
from widget_contract.chart_text import render_bar_text, render_line_text
from widget_contract.loader import ContractError, load_widget_file
from widget_contract.models import RenderNode
from widget_contract.registry import ALLOWED_CAPABILITIES, PRIMITIVES, READ_OPERATIONS, TYPES
from widget_contract.renderer import render


def sample_usage_data():
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


def test_chart_primitives_registered_in_contract():
    assert "bar" in PRIMITIVES
    bar = PRIMITIVES["bar"]
    assert bar.props == frozenset({"label", "categories", "empty", "error"})
    assert bar.bindings == {"values": "core.array.v1"}
    assert bar.empty_state == "empty"
    assert bar.error_state == "error"

    assert "line" in PRIMITIVES
    line = PRIMITIVES["line"]
    assert line.props == frozenset({"label", "points", "empty", "error"})
    assert line.bindings == {"series": "core.array.v1"}
    assert line.empty_state == "empty"
    assert line.error_state == "error"


def test_usage_cost_type_and_read_operation_registered():
    assert "usage-cost.v1" in TYPES
    assert TYPES["usage-cost.v1"].data_class == "operational"

    assert "usage-cost.v1" in READ_OPERATIONS
    op = READ_OPERATIONS["usage-cost.v1"]
    assert op.source == "store"
    assert op.output_type == "usage-cost.v1"
    assert op.capability == "read:usage-cost"
    assert "read:usage-cost" in ALLOWED_CAPABILITIES


def test_spec_loads_strictly():
    spec_path = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "usage-cost-0.1.yaml"
    widget = load_widget_file(spec_path)
    assert widget.id == "usage-cost"
    assert widget.version == "0.1"
    assert widget.title == "Usage & Cost"
    assert widget.actions == ()
    assert widget.capabilities == ("read:usage-cost",)
    assert len(widget.reads) == 1
    assert widget.reads[0].id == "usage"
    assert widget.reads[0].operation == "usage-cost.v1"


def test_adapter_read_usage_cost_v1_valid():
    raw = sample_usage_data()
    proj = read_usage_cost_v1(raw)
    assert proj["schema_version"] == 1
    assert proj["period"] == "2026-08-23"
    assert proj["total_cost_usd"] == 0.42
    assert proj["total_tokens"] == 24800
    assert len(proj["runtimes"]) == 4
    assert len(proj["history"]) == 5
    assert proj["runtime_tokens"] == [12000, 8500, 3200, 1100]
    assert proj["model_costs"] == [0.12, 0.15, 0.10, 0.05]
    assert proj["history_tokens"] == [3000, 7500, 14000, 19500, 24800]


def test_adapter_read_usage_cost_v1_callable():
    raw = sample_usage_data()
    proj = read_usage_cost_v1(lambda: raw)
    assert proj["total_tokens"] == 24800


def test_adapter_read_usage_cost_v1_malformed_fails_closed():
    with pytest.raises(ReadAdapterError):
        read_usage_cost_v1("invalid_string")
    with pytest.raises(ReadAdapterError):
        read_usage_cost_v1({"runtimes": "not_list"})
    with pytest.raises(ReadAdapterError):
        read_usage_cost_v1({"runtimes": [], "history": "not_list"})
    with pytest.raises(ReadAdapterError):
        read_usage_cost_v1({"runtimes": [{"name": "Hermes"}], "history": []})
    with pytest.raises(ReadAdapterError):
        read_usage_cost_v1({
            "runtimes": [{"id": "h", "name": "H", "tokens_in": -5, "tokens_out": 0, "cost_usd": 0.1, "model": "m"}],
            "history": [],
        })


def test_renderer_with_usage_cost_spec():
    spec_path = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "usage-cost-0.1.yaml"
    widget = load_widget_file(spec_path)
    proj = read_usage_cost_v1(sample_usage_data())
    tree = render(widget, {"usage": proj}, {"usage": "fresh"})

    assert tree["contract_version"] == "0.1"
    assert tree["widget"]["id"] == "usage-cost"
    assert tree["render"]["primitive"] == "stack"
    children = tree["render"]["children"]
    assert len(children) == 5

    assert children[0]["primitive"] == "metric"
    assert children[0]["props"]["label"] == "Total cost"
    assert children[0]["props"]["value"] == 0.42

    assert children[1]["primitive"] == "metric"
    assert children[1]["props"]["label"] == "Total tokens"
    assert children[1]["props"]["value"] == 24800

    assert children[2]["primitive"] == "bar"
    assert children[2]["props"]["label"] == "Tokens by runtime"
    assert children[2]["props"]["values"] == [12000, 8500, 3200, 1100]

    assert children[3]["primitive"] == "bar"
    assert children[3]["props"]["label"] == "Cost by model"
    assert children[3]["props"]["values"] == [0.12, 0.15, 0.1, 0.05]

    assert children[4]["primitive"] == "line"
    assert children[4]["props"]["label"] == "Usage over time"
    assert children[4]["props"]["series"] == [3000, 7500, 14000, 19500, 24800]


def test_tui_text_fallback_bar_and_line():
    bar_node = {
        "primitive": "bar",
        "props": {
            "label": "Tokens by runtime",
            "categories": ["Hermes", "Codex", "Claude", "DSH"],
            "values": [12000, 8500, 3200, 1100],
        },
    }
    bar_text = render_bar_text(bar_node)
    assert "Tokens by runtime" in bar_text
    assert "Hermes" in bar_text
    assert "12,000" in bar_text
    assert "#" in bar_text

    empty_bar = render_bar_text({"primitive": "bar", "props": {"label": "Empty", "empty": "None"}})
    assert "None" in empty_bar

    line_node = {
        "primitive": "line",
        "props": {
            "label": "Usage over time",
            "points": ["10:00", "10:15", "10:30"],
            "series": [3000, 7500, 14000],
        },
    }
    line_text = render_line_text(line_node)
    assert "Usage over time" in line_text
    assert "10:00" in line_text
    assert "14,000" in line_text

    empty_line = render_line_text({"primitive": "line", "props": {"label": "Empty Line", "empty": "No points"}})
    assert "No points" in empty_line


def test_cli_usage_cost_view(tmp_path):
    target = tmp_path / "usage-cost.json"
    res = _run_widget(
        Namespace(widget_command=None, view="usage-cost", repo=None, snapshot=target),
        usage_reader=sample_usage_data,
    )
    assert res.status == "succeeded"
    assert target.is_file()
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["widget"] == {"id": "usage-cost", "version": "0.1"}
    assert artifact["render"]["state"] == "ready"
    assert len(artifact["render"]["children"]) == 5
    assert artifact["error"] is None


def test_cli_usage_cost_view_error_state(tmp_path):
    target = tmp_path / "usage-cost-err.json"

    def broken_reader():
        raise RuntimeError("Ledger down")

    res = _run_widget(
        Namespace(widget_command=None, view="usage-cost", repo=None, snapshot=target),
        usage_reader=broken_reader,
    )
    assert res.status == "succeeded"
    assert target.is_file()
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["error"]["kind"] == "usage_cost_read"
    assert "Ledger down" in artifact["error"]["message"]
    assert artifact["render"]["primitive"] == "error-state"
    assert artifact["render"]["state"] == "error"
