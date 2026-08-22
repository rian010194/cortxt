from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from cortxt_mcp import mandate, tools


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


def test_tier1_tool_locked_regardless_of_mandate_when_flag_is_off():
    """The tier flag is still checked first -- a valid-looking mandate does
    not bypass it."""
    with pytest.raises(tools.ToolTierLockedError):
        tools.call_tool(
            "cortxt_dispatch", {"tags": "research", "task_id": "x", "prompt": "y"},
            allow_dispatch=False, allow_credentials=False, mandate={"anything": "goes"},
        )


def test_tier1_tool_unlocked_by_flag_still_requires_a_mandate(tmp_path):
    """ADR-032: the tier flag alone is no longer sufficient for a
    TIER_DISPATCH+ tool -- without a mandate, the call is rejected before
    the handler runs (AC 1), even though the tier itself is unlocked."""
    with pytest.raises(tools.MandateRejectedError) as excinfo:
        tools.call_tool(
            "cortxt_addons_submit",
            {"candidate_id": "addon@x", "store": str(tmp_path / "sessions"), "snapshot": str(tmp_path / "snap.json")},
            allow_dispatch=True, allow_credentials=False,
        )
    assert excinfo.value.reason == mandate.REASON_MANDATE_MISSING


def test_tier1_tool_unlocked_with_allow_dispatch_and_a_valid_mandate(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    public_key_hex = mandate.public_key_hex_from_private_key(private_key)
    issued = mandate.issue_mandate(
        private_key=private_key,
        granted_by="operator-demo",
        issue_ref="owner/repo#206",
        allowed_tools=["cortxt_addons_submit"],
        data_class_max="L2",
        budget_usd_max=25.0,
        max_runtime_seconds=3600,
        expires_at="2099-01-01T00:00:00Z",
        scope_text="test scope",
    )

    class _FakeStore:
        def check_and_consume(self, nonce):  # noqa: ARG002
            return True

        def record_and_check(self, mandate_id, cost, cap):  # noqa: ARG002
            return True

    verifier = mandate.MandateVerifier(
        public_keys={"operator-demo": public_key_hex}, nonce_store=_FakeStore(), budget_store=_FakeStore(),
    )
    result = tools.call_tool(
        "cortxt_addons_submit",
        {"candidate_id": "addon@x", "store": str(tmp_path / "sessions"), "snapshot": str(tmp_path / "snap.json")},
        allow_dispatch=True, allow_credentials=False,
        mandate=issued.envelope, mandate_verifier=verifier,
        call_context=mandate.CallContext(issue_ref="owner/repo#206"),
    )
    assert result["status"] in {"succeeded", "failed"}  # unlocked + mandate accepted -> handler actually ran


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
