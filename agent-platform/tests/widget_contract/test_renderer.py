import pytest

from widget_contract.loader import load_widget
from widget_contract.renderer import RenderError, render


def test_registered_primitives_and_typed_pointer_render(widget_spec):
    widget = load_widget(widget_spec)
    output = render(widget, {"runs": {"schema_version": 1, "runs": [{"run_id": "r1", "status": "running"}]}})
    rendered_list = output["render"]["children"][0]
    assert rendered_list == {"primitive": "list", "state": "ready", "props": {"empty": "No runs", "error": "Unavailable", "items": [{"run_id": "r1", "status": "running"}]}}
    assert "html" not in str(output).lower()


@pytest.mark.parametrize(("states", "expected"), [({}, "empty"), ({"runs": "stale"}, "stale"), ({"runs": "denied"}, "denied"), ({"runs": "error"}, "error")])
def test_missing_data_produces_declared_state(widget_spec, states, expected):
    widget = load_widget(widget_spec)
    output = render(widget, {}, states)
    assert output["render"]["children"][0]["state"] == expected


def test_render_rejects_runtime_output_type_mismatch(widget_spec):
    widget = load_widget(widget_spec)
    with pytest.raises(RenderError, match="expected array"):
        render(widget, {"runs": {"schema_version": 1, "runs": "wrong"}})


def test_unregistered_primitive_fails_at_load(widget_spec):
    widget_spec["render"]["primitive"] = "html"
    with pytest.raises(ValueError, match="unregistered primitive"):
        load_widget(widget_spec)
