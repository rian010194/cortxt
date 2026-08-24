import copy
from pathlib import Path

import pytest

from widget_contract.loader import ContractError, load_composition, load_widget


def _widgets(spec):
    first = load_widget(spec)
    second_spec = copy.deepcopy(spec)
    second_spec["widget"] = {"id": "detail", "version": "2.0.0", "title": "Detail"}
    second = load_widget(second_spec)
    return first, second, {(first.id, first.version): first, (second.id, second.version): second}


def _composition(first, second):
    return {
        "contract_version": "0.1", "composition": {"id": "dashboard", "version": "1.0.0"},
        "widgets": [
            {"namespace": "source", "widget_id": first.id, "version": first.version, "inputs": {}, "outputs": {"items": "core.array.v1"}},
            {"namespace": "target", "widget_id": second.id, "version": second.version, "inputs": {"items": "core.array.v1"}, "outputs": {}},
        ],
        "layout": {"primitive": "row", "children": [{"primitive": "panel", "widget": "source"}, {"primitive": "panel", "widget": "target"}]},
        "connections": [{"from": "source", "output": "items", "to": "target", "input": "items", "type": "core.array.v1"}],
        "capabilities": ["read:active-runs"],
    }


def test_composition_enforces_exact_versions_and_isolated_namespaces(widget_spec):
    first, second, widgets = _widgets(widget_spec)
    spec = _composition(first, second)
    assert load_composition(spec, widgets).connections[0].type_id == "core.array.v1"
    wrong = copy.deepcopy(spec)
    wrong["widgets"][0]["version"] = "9.9.9"
    with pytest.raises(ContractError, match="exact widget version"):
        load_composition(wrong, widgets)
    duplicate = copy.deepcopy(spec)
    duplicate["widgets"][1]["namespace"] = "source"
    with pytest.raises(ContractError, match="duplicate namespace"):
        load_composition(duplicate, widgets)


def test_composition_rejects_cycles_and_type_mismatch(widget_spec):
    first, second, widgets = _widgets(widget_spec)
    spec = _composition(first, second)
    cycle = copy.deepcopy(spec)
    cycle["widgets"][0]["inputs"] = {"back": "core.array.v1"}
    cycle["widgets"][1]["outputs"] = {"back": "core.array.v1"}
    cycle["connections"].append({"from": "target", "output": "back", "to": "source", "input": "back", "type": "core.array.v1"})
    with pytest.raises(ContractError, match="cyclic"):
        load_composition(cycle, widgets)
    mismatch = copy.deepcopy(spec)
    mismatch["connections"][0]["type"] = "core.string.v1"
    with pytest.raises(ContractError, match="type mismatch"):
        load_composition(mismatch, widgets)


def test_composition_rejects_capability_widening(widget_spec):
    first, second, widgets = _widgets(widget_spec)
    spec = _composition(first, second)
    spec["capabilities"].append("read:issues")
    with pytest.raises(ContractError, match="exactly match"):
        load_composition(spec, widgets)


def test_composition_enforces_data_class_limit(widget_spec):
    first, second, widgets = _widgets(widget_spec)
    spec = _composition(first, second)
    spec["widgets"][0]["outputs"] = {"status": "action.status.v1"}
    spec["widgets"][1]["inputs"] = {"status": "action.status.v1"}
    spec["widgets"][1]["data_class"] = "public-metadata"
    spec["connections"] = [{"from": "source", "output": "status", "to": "target", "input": "status", "type": "action.status.v1"}]
    with pytest.raises(ContractError, match="data class"):
        load_composition(spec, widgets)


def test_cli_widget_compose_succeeds_and_writes_composed_artifact(tmp_path):
    import json
    from argparse import Namespace
    from cli.unified_cli import _run_widget_compose

    fixtures_dir = Path(__file__).resolve().parents[3] / "scripts" / "fixtures" / "composition"
    spec_file = fixtures_dir / "composition.yaml"
    target = tmp_path / "composed.json"
    snapshot_input = Path(__file__).resolve().parents[2] / "widget" / "snapshot.json"

    res = _run_widget_compose(Namespace(
        widget_command="compose",
        spec=spec_file,
        widgets_dir=fixtures_dir,
        snapshot=target,
        repo=None,
        snapshot_input=snapshot_input,
        plan_input=None,
    ))
    assert res.status == "succeeded"
    assert target.is_file()
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["composed"] is True
    assert doc["widget"] == {"id": "pulse-dashboard", "version": "0.1"}
    assert doc["render"]["primitive"] == "stack"
    assert len(doc["render"]["children"]) == 2


def test_cli_widget_compose_fails_closed_without_writing_artifact(tmp_path):
    from argparse import Namespace
    from cli.unified_cli import _run_widget_compose

    fixtures_dir = Path(__file__).resolve().parents[3] / "scripts" / "fixtures" / "composition"
    bad_spec = tmp_path / "bad.yaml"
    bad_spec.write_text("contract_version: 0.1\nwidgets: [unclosed", encoding="utf-8")
    target = tmp_path / "composed.json"

    res = _run_widget_compose(Namespace(
        widget_command="compose",
        spec=bad_spec,
        widgets_dir=fixtures_dir,
        snapshot=target,
        repo=None,
        snapshot_input=None,
        plan_input=None,
    ))
    assert res.status == "failed"
    assert res.error["category"] == "contract_error"
    assert not target.exists()


def test_cli_widget_compose_warroom_grid_with_real_specs(tmp_path):
    """The maker-generated warroom format (grid layout, quoted versions,
    capabilities union from real specs) must compose successfully against
    agent-platform/widget/specs -- the CLI's --widgets-dir convention."""
    import json
    from argparse import Namespace
    from cli.unified_cli import _run_widget_compose

    fixtures_dir = Path(__file__).resolve().parents[3] / "scripts" / "fixtures" / "composition"
    spec_file = fixtures_dir / "warroom-grid.yaml"
    specs_dir = Path(__file__).resolve().parents[2] / "widget" / "specs"
    assert spec_file.is_file()
    assert (specs_dir / "session-pulse-0.1.yaml").is_file()
    assert (specs_dir / "usage-cost-0.1.yaml").is_file()

    target = tmp_path / "warroom-composed.json"
    snapshot_input = Path(__file__).resolve().parents[2] / "widget" / "snapshot.json"

    res = _run_widget_compose(Namespace(
        widget_command="compose",
        spec=spec_file,
        widgets_dir=specs_dir,
        snapshot=target,
        repo=None,
        snapshot_input=snapshot_input,
        plan_input=None,
    ))
    assert res.status == "succeeded"
    assert target.is_file()
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["composed"] is True
    assert doc["widget"] == {"id": "warroom", "version": "0.1"}
    assert doc["render"]["primitive"] == "grid"
    children = doc["render"]["children"]
    assert len(children) == 2
    labels = {c.get("props", {}).get("label") for c in children}
    assert labels == {"Session Pulse", "Usage & Cost"}


def test_widget_has_composed_view_and_no_mutation_route():
    import json
    widget_dir = Path(__file__).resolve().parents[2] / "widget"
    html = (widget_dir / "index.html").read_text(encoding="utf-8")
    manifest = json.loads((widget_dir / "widgets.json").read_text(encoding="utf-8"))
    assert any(w["id"] == "composed" and w["artifact"] == "composed.json" for w in manifest["widgets"])
    assert "renderComposed" in html
    assert "do_POST" not in (widget_dir / "serve.py").read_text(encoding="utf-8")

