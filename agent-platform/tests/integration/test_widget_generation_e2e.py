"""End-to-end: prompt -> MCP tool -> CLI -> generation -> strict loader -> installed spec.

Uses a fake LLM client (no network) so this runs in the default
`not real_inference` test lane.
"""
import textwrap

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


def test_widget_generate_tool_end_to_end_installs_valid_spec(monkeypatch, tmp_path):
    import widget_contract.generation as gen_mod
    from cortxt_mcp.tools import _tool_cortxt_widget_generate
    from widget_contract.loader import load_widget_file

    monkeypatch.setattr(gen_mod, "generate_text", lambda prompt, **kw: VALID_SPEC)

    result = _tool_cortxt_widget_generate({
        "prompt": "build a pulse widget",
        "confirm": True,
        "specs_dir": str(tmp_path),
    })

    assert result["status"] == "succeeded"
    installed = tmp_path / "pulse-0.1.yaml"
    assert installed.exists()
    widget = load_widget_file(installed)
    assert widget.id == "pulse"
    assert widget.capabilities == ("read:sessions",)
