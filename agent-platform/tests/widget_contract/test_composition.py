import copy

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
