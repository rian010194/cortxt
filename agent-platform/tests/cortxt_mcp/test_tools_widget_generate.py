from cortxt_mcp.tools import TIER_DISPATCH, TOOL_REGISTRY, list_tools


def test_widget_generate_tool_registered_at_dispatch_tier():
    spec = TOOL_REGISTRY["cortxt_widget_generate"]
    assert spec.tier == TIER_DISPATCH


def test_widget_edit_remove_reset_tools_registered():
    for name in ("cortxt_widget_edit", "cortxt_widget_remove", "cortxt_widget_reset"):
        assert name in TOOL_REGISTRY
        assert TOOL_REGISTRY[name].tier == TIER_DISPATCH


def test_widget_generate_tool_not_listed_without_dispatch_allowed():
    names = {spec.name for spec in list_tools(allow_dispatch=False, allow_credentials=False)}
    assert "cortxt_widget_generate" not in names


def test_widget_generate_tool_listed_with_dispatch_allowed():
    names = {spec.name for spec in list_tools(allow_dispatch=True, allow_credentials=False)}
    assert "cortxt_widget_generate" in names


def test_widget_generate_tool_delegates_to_cli(monkeypatch):
    from cortxt_mcp.tools import _tool_cortxt_widget_generate

    calls = {}

    def fake_run(args):
        calls["prompt"] = args.prompt
        calls["confirm"] = args.confirm
        from cli.unified_cli import ResultEnvelope
        return ResultEnvelope(status="succeeded", evidence=[{"widget_id": "pulse"}])

    monkeypatch.setattr("cli.unified_cli._run_widget_generate", fake_run)
    result = _tool_cortxt_widget_generate({"prompt": "build a pulse widget", "confirm": True})
    assert calls == {"prompt": "build a pulse widget", "confirm": True}
    assert result["status"] == "succeeded"
