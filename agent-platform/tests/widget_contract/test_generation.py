import textwrap

from widget_contract.generation import generate_widget_spec
from widget_contract.llm_client import LLMCallError

VALID_SPEC = textwrap.dedent('''\
    contract_version: "0.1"
    widget:
      id: pulse
      version: "0.1"
      title: Pulse
    data:
      reads:
        - id: snapshot
          source: store
          operation: sessions.snapshot.v2
          input: {}
          select: []
          refresh:
            mode: manual
          output_type: sessions.snapshot.v2
          on_error: stale
    render:
      primitive: stack
      props: {label: Pulse}
      children:
        - primitive: heading
          props: {value: Pulse}
          bindings: {}
    actions: []
    capabilities: [read:sessions]
''')

MISSING_OP_SPEC = VALID_SPEC.replace("sessions.snapshot.v2", "widgets.made-up.v1")

INVALID_SPEC = "not: [valid, yaml, widget"


def test_generate_returns_ok_outcome_for_valid_spec(monkeypatch):
    import widget_contract.generation as mod
    monkeypatch.setattr(mod, "generate_text", lambda prompt, **kw: VALID_SPEC)
    outcome = generate_widget_spec("build a pulse widget")
    assert outcome.status == "ok"
    assert outcome.widget_id == "pulse"
    assert outcome.capabilities == ("read:sessions",)
    assert outcome.document_hash


def test_generate_returns_missing_operation_outcome(monkeypatch, tmp_path):
    import widget_contract.generation as mod
    monkeypatch.setattr(mod, "generate_text", lambda prompt, **kw: MISSING_OP_SPEC)
    outcome = generate_widget_spec("build a made-up widget", scaffold_dir=tmp_path)
    assert outcome.status == "missing_operation"
    assert outcome.missing_operations == ("widgets.made-up.v1",)
    assert outcome.scaffold_paths
    assert (tmp_path / "scaffold-widgets.made-up.v1.py").exists()


def test_generate_returns_invalid_outcome_for_unparseable_output(monkeypatch):
    import widget_contract.generation as mod
    monkeypatch.setattr(mod, "generate_text", lambda prompt, **kw: INVALID_SPEC)
    outcome = generate_widget_spec("build something broken")
    assert outcome.status == "invalid"
    assert outcome.error_message


def test_generate_propagates_llm_call_error(monkeypatch):
    import widget_contract.generation as mod

    def raise_llm_error(prompt, **kw):
        raise LLMCallError("not configured")

    monkeypatch.setattr(mod, "generate_text", raise_llm_error)
    outcome = generate_widget_spec("build anything")
    assert outcome.status == "invalid"
    assert "not configured" in outcome.error_message


def test_generate_handles_top_level_non_dict_yaml(monkeypatch):
    """A fake LLM returning a YAML list (not a mapping) instead of a widget
    document must fail closed as 'invalid', not raise or produce 'ok'."""
    import widget_contract.generation as mod
    monkeypatch.setattr(mod, "generate_text", lambda prompt, **kw: "- one\n- two\n- three\n")
    outcome = generate_widget_spec("build a pulse widget")
    assert outcome.status == "invalid"
    assert outcome.error_message
