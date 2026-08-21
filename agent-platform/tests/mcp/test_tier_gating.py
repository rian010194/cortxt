from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from mcp import tools


def test_unknown_tool_raises_tool_not_found():
    with pytest.raises(tools.ToolNotFoundError):
        tools.call_tool("no_such_tool", {}, allow_dispatch=True, allow_credentials=True)


def test_tier1_tool_locked_by_default():
    with pytest.raises(tools.ToolTierLockedError) as excinfo:
        tools.call_tool(
            "cortxt_dispatch", {"tags": "research", "task_id": "x", "prompt": "y"},
            allow_dispatch=False, allow_credentials=False,
        )
    assert excinfo.value.tool == "cortxt_dispatch"
    assert excinfo.value.tier == tools.TIER_DISPATCH


def test_tier1_tool_unlocked_with_allow_dispatch(tmp_path):
    result = tools.call_tool(
        "cortxt_addons_submit",
        {"candidate_id": "addon@x", "store": str(tmp_path / "sessions"), "snapshot": str(tmp_path / "snap.json")},
        allow_dispatch=True, allow_credentials=False,
    )
    assert result["status"] in {"succeeded", "failed"}  # unlocked -> handler actually ran


def test_tier0_tool_never_needs_any_flag():
    result = tools.call_tool(
        "route_engine", {"task_tags": ["widget-ui"]}, allow_dispatch=False, allow_credentials=False,
    )
    assert result["engine_id"] == "claude-direct"


@pytest.mark.parametrize("name", ["cortxt_dispatch", "cortxt_addons_submit", "cortxt_daemon_status"])
def test_all_tier1_tools_reject_when_locked(name):
    with pytest.raises(tools.ToolTierLockedError):
        tools.call_tool(name, {}, allow_dispatch=False, allow_credentials=False)


def test_allow_credentials_alone_does_not_unlock_tier1():
    with pytest.raises(tools.ToolTierLockedError):
        tools.call_tool(
            "cortxt_dispatch", {"tags": "research", "task_id": "x", "prompt": "y"},
            allow_dispatch=False, allow_credentials=True,
        )
