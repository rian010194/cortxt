import copy

import pytest


@pytest.fixture(autouse=True)
def _hermes_free_configured(monkeypatch):
    """Default CORTXT_FREE_MODEL/PROVIDER for this test package.

    S7b #482 follow-on: WorkLauncher._launch (and the eligibility functions
    that must agree with it) now consult `runtime_launch_config_ok`, which
    for `hermes-free` requires these two env vars. Most tests in this
    package exercise routing/limits/claim-release behavior with runtime
    "hermes-free" incidentally, not hermes-free's own config gating (that is
    covered explicitly by scripts/test_worker_adapters.py and by
    test_s7b_dispatch_registry_chain.py's own env handling) -- so default
    them here rather than requiring every test to set them. A test that
    specifically wants the unconfigured case can still
    monkeypatch.delenv(...) within itself.
    """
    monkeypatch.setenv("CORTXT_FREE_MODEL", "test-default-free-model")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "test-default-free-provider")


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
