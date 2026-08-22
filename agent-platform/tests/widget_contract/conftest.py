import copy

import pytest


@pytest.fixture
def widget_spec():
    return {
        "contract_version": "0.1",
        "widget": {"id": "ops", "version": "1.0.0", "title": "Operations"},
        "data": {"reads": [{
            "id": "runs", "source": "store", "operation": "dispatcher.active-runs.v1",
            "input": {}, "select": ["/runs"], "refresh": {"mode": "manual"},
            "output_type": "dispatcher.active-runs.v1", "on_error": "stale",
        }]},
        "render": {"primitive": "stack", "children": [{
            "primitive": "list", "props": {"empty": "No runs", "error": "Unavailable"},
            "bindings": {"items": {"read": "runs", "pointer": "/runs", "type": "core.array.v1"}},
        }]},
        "actions": [],
        "capabilities": ["read:active-runs"],
    }


@pytest.fixture
def copy_spec(widget_spec):
    return lambda: copy.deepcopy(widget_spec)
