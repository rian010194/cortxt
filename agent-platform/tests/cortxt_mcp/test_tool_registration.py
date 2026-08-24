from __future__ import annotations

import sys
from pathlib import Path

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from cortxt_mcp import tools

TIER0_NAMES = {
    "route_engine",
    "list_engine_manifests",
    "cortxt_status",
    "cortxt_sessions",
    "cortxt_runtimes",
    "cortxt_orchestrator",
    "cortxt_pipeline",
    "cortxt_run_status",
}
TIER1_NAMES = {
    "cortxt_dispatch", "cortxt_addons_submit", "cortxt_daemon_status",
    "cortxt_widget_generate", "cortxt_widget_edit", "cortxt_widget_remove", "cortxt_widget_reset",
    "cortxt_run_create", "cortxt_run_resume", "cortxt_run_submit_for_review",
}


def test_registry_contains_exactly_the_locked_first_slice():
    assert set(tools.TOOL_REGISTRY) == TIER0_NAMES | TIER1_NAMES


def test_tier0_tools_are_tagged_tier_read_only():
    for name in TIER0_NAMES:
        assert tools.TOOL_REGISTRY[name].tier == tools.TIER_READ_ONLY


def test_tier1_tools_are_tagged_tier_dispatch():
    for name in TIER1_NAMES:
        assert tools.TOOL_REGISTRY[name].tier == tools.TIER_DISPATCH


def test_no_tier2_tools_registered_yet():
    assert not [spec for spec in tools.TOOL_REGISTRY.values() if spec.tier == tools.TIER_CREDENTIALS]


def test_default_server_start_only_advertises_tier0():
    listed = {spec.name for spec in tools.list_tools(allow_dispatch=False, allow_credentials=False)}
    assert listed == TIER0_NAMES


def test_allow_dispatch_advertises_tier0_and_tier1():
    listed = {spec.name for spec in tools.list_tools(allow_dispatch=True, allow_credentials=False)}
    assert listed == TIER0_NAMES | TIER1_NAMES


def test_every_tool_has_a_description_and_a_callable_handler():
    for spec in tools.TOOL_REGISTRY.values():
        assert spec.description
        assert callable(spec.handler)
