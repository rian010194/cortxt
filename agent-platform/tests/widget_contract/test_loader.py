import json

import pytest

from widget_contract.loader import ContractError, load_widget


def test_canonical_json_and_yaml_load_to_same_identity(widget_spec):
    json_widget = load_widget(json.dumps(widget_spec))
    yaml_text = """contract_version: '0.1'
widget: {id: ops, version: 1.0.0, title: Operations}
data:
  reads:
    - id: runs
      source: store
      operation: dispatcher.active-runs.v1
      input: {}
      select: [/runs]
      refresh: {mode: manual}
      output_type: dispatcher.active-runs.v1
      on_error: stale
render:
  primitive: stack
  children:
    - primitive: list
      props: {empty: No runs, error: Unavailable}
      bindings:
        items: {read: runs, pointer: /runs, type: core.array.v1}
actions: []
capabilities: [read:active-runs]
"""
    yaml_widget = load_widget(yaml_text)
    assert yaml_widget.canonical_json == json_widget.canonical_json
    assert yaml_widget.document_hash == json_widget.document_hash


@pytest.mark.parametrize("text", [
    "a: 1\na: 2\n",
    "a: !unsafe value\n",
    "a: &value x\nb: *value\n",
    "1: value\n",
])
def test_yaml_unsafe_features_fail(text):
    with pytest.raises(ContractError):
        load_widget(text)


@pytest.mark.parametrize(("key", "value"), [
    ("url", "https://example.invalid"), ("command", "echo x"), ("environment", "HOME"),
    ("credential", "value"), ("prompt", "private text"), ("code", "x()"),
])
def test_forbidden_fields_fail_before_any_io(copy_spec, key, value):
    spec = copy_spec()
    spec["widget"][key] = value
    with pytest.raises(ContractError, match="forbidden"):
        load_widget(spec)


@pytest.mark.parametrize("value", ["https://example.invalid", "${HOME}", "../secret", "powershell Get-Item"])
def test_forbidden_values_fail(copy_spec, value):
    spec = copy_spec()
    spec["widget"]["title"] = value
    with pytest.raises(ContractError, match="forbidden"):
        load_widget(spec)


def test_unknown_field_and_undeclared_capability_fail(copy_spec):
    spec = copy_spec()
    spec["render"]["extension"] = {}
    with pytest.raises(ContractError, match="unknown field"):
        load_widget(spec)
    spec = copy_spec()
    spec["capabilities"] = []
    with pytest.raises(ContractError, match="undeclared capability"):
        load_widget(spec)


def test_unregistered_operation_and_type_mismatch_fail(copy_spec):
    spec = copy_spec()
    spec["data"]["reads"][0]["operation"] = "unknown.read.v1"
    with pytest.raises(ContractError, match="unavailable"):
        load_widget(spec)
    spec = copy_spec()
    spec["render"]["children"][0]["bindings"]["items"]["type"] = "core.string.v1"
    with pytest.raises(ContractError, match="type mismatch"):
        load_widget(spec)
