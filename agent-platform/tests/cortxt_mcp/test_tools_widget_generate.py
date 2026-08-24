import pytest

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


@pytest.mark.parametrize(
    "tool_name, cli_fn_name, arguments",
    [
        ("_tool_cortxt_widget_generate", "_run_widget_generate",
         {"prompt": "build a pulse widget"}),
        ("_tool_cortxt_widget_edit", "_run_widget_edit",
         {"widget_id": "pulse", "widget_version": "0.1", "prompt": "edit it"}),
        ("_tool_cortxt_widget_remove", "_run_widget_remove",
         {"widget_id": "pulse", "widget_version": "0.1"}),
        ("_tool_cortxt_widget_reset", "_run_widget_reset", {}),
    ],
)
def test_widget_tool_wraps_unexpected_exception_as_result_envelope(monkeypatch, tool_name, cli_fn_name, arguments):
    """An unexpected exception from deep inside the CLI function must come
    back as a {"status": "failed", "error": {...}} dict, not propagate raw --
    these tools call the CLI function directly, bypassing any outer
    try/except the CLI's own dispatch path has."""
    import cortxt_mcp.tools as tools_mod

    def boom(args):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(f"cli.unified_cli.{cli_fn_name}", boom)
    tool_fn = getattr(tools_mod, tool_name)
    result = tool_fn(arguments)
    assert result["status"] == "failed"
    assert result["error"]["category"] == "runtime_error"
    assert "disk exploded" in result["error"]["message"]
