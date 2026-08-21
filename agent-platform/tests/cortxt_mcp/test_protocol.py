from __future__ import annotations

import sys
from pathlib import Path

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from cortxt_mcp.audit import AuditLog
from cortxt_mcp.protocol import handle_request


def test_initialize_returns_server_info():
    response = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        allow_dispatch=False, allow_credentials=False,
    )
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "cortxt-mcp"


def test_notification_gets_no_response():
    response = handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        allow_dispatch=False, allow_credentials=False,
    )
    assert response is None


def test_tools_list_only_advertises_unlocked_tiers():
    response = handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        allow_dispatch=False, allow_credentials=False,
    )
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "route_engine" in names
    assert "cortxt_dispatch" not in names


def test_tools_call_route_engine_returns_text_content():
    response = handle_request(
        {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "route_engine", "arguments": {"task_tags": ["general"]}},
        },
        allow_dispatch=False, allow_credentials=False,
    )
    assert "result" in response
    content = response["result"]["content"]
    assert content[0]["type"] == "text"
    assert "claude-direct" in content[0]["text"]


def test_tools_call_locked_tier_returns_error():
    response = handle_request(
        {
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "cortxt_dispatch", "arguments": {}},
        },
        allow_dispatch=False, allow_credentials=False,
    )
    assert response["error"]["code"] == -32001


def test_tools_call_unknown_tool_returns_error():
    response = handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
        allow_dispatch=False, allow_credentials=False,
    )
    assert response["error"]["code"] == -32601


def test_unknown_method_returns_error():
    response = handle_request(
        {"jsonrpc": "2.0", "id": 6, "method": "not/a/method", "params": {}},
        allow_dispatch=False, allow_credentials=False,
    )
    assert response["error"]["code"] == -32601


def test_accepted_call_is_audited(tmp_path):
    audit = AuditLog(tmp_path / "sessions")
    handle_request(
        {
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "route_engine", "arguments": {"task_tags": ["general"]}},
        },
        allow_dispatch=False, allow_credentials=False, audit=audit,
    )
    assert audit.session_id is not None


def test_locked_call_is_not_audited(tmp_path):
    audit = AuditLog(tmp_path / "sessions")
    handle_request(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "cortxt_dispatch", "arguments": {}}},
        allow_dispatch=False, allow_credentials=False, audit=audit,
    )
    assert audit.session_id is None
