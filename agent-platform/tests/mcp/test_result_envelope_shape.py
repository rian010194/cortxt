"""Locked decision (issue #184 step 3): the admin subcommand tools return
`ResultEnvelope.to_dict()` verbatim. These tests pin that shape so a future
refactor of the CLI's ResultEnvelope can't silently drift the MCP surface."""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from mcp import tools

ENVELOPE_KEYS = {
    "issue_id", "run_id", "status", "runtime", "worker_role", "started_at",
    "finished_at", "model", "usage", "cost", "cost_currency", "artifacts",
    "evidence", "error",
}


def _call(name, arguments, tmp_path):
    arguments = {**arguments, "store": str(tmp_path / "sessions"), "snapshot": str(tmp_path / "snap.json")}
    return tools.call_tool(name, arguments, allow_dispatch=False, allow_credentials=False)


def test_cortxt_status_returns_envelope_shape(tmp_path):
    result = _call("cortxt_status", {}, tmp_path)
    assert set(result) == ENVELOPE_KEYS
    assert result["status"] == "succeeded"


def test_cortxt_sessions_returns_envelope_shape(tmp_path):
    result = _call("cortxt_sessions", {}, tmp_path)
    assert set(result) == ENVELOPE_KEYS
    assert result["status"] == "succeeded"


def test_cortxt_runtimes_returns_envelope_shape(tmp_path):
    result = _call("cortxt_runtimes", {}, tmp_path)
    assert set(result) == ENVELOPE_KEYS
    assert result["status"] == "succeeded"


def test_cortxt_orchestrator_returns_envelope_shape(tmp_path):
    result = _call("cortxt_orchestrator", {}, tmp_path)
    assert set(result) == ENVELOPE_KEYS


def test_cortxt_pipeline_returns_envelope_shape(tmp_path):
    result = _call("cortxt_pipeline", {}, tmp_path)
    assert set(result) == ENVELOPE_KEYS
    assert result["status"] == "succeeded"


def test_route_engine_is_not_wrapped_in_a_result_envelope():
    result = tools.call_tool(
        "route_engine", {"task_tags": ["general"]}, allow_dispatch=False, allow_credentials=False,
    )
    assert set(result) == {"engine_id", "reason", "matched_tag", "excluded", "checkpoint_required"}
    assert "status" not in result


def test_list_engine_manifests_returns_manifest_fields():
    result = tools.call_tool(
        "list_engine_manifests", {}, allow_dispatch=False, allow_credentials=False,
    )
    assert result  # DEFAULT_MANIFESTS is non-empty
    for manifest in result:
        assert set(manifest) == {
            "engine_id", "task_shapes", "cost_class", "reliability_class", "notes", "checkpoint_required",
        }
