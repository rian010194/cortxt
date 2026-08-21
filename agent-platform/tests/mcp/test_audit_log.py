from __future__ import annotations

import sys
from pathlib import Path

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from mcp.audit import AuditLog, summarize_args
from runtime import session_state as state


def test_record_appends_a_ledger_event_tagged_caller_mcp(tmp_path):
    store = tmp_path / "sessions"
    audit = AuditLog(store)
    audit.record("route_engine", {"task_tags": ["general"]})

    session = state.load(store, audit.session_id)
    events = [e for e in session["events"] if e["event_type"] == "mcp.tool_call"]
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["caller"] == "mcp"
    assert payload["tool"] == "route_engine"
    assert payload["args_summary"] == {"task_tags": ["general"]}


def test_multiple_calls_reuse_the_same_session_and_increment_sequence(tmp_path):
    store = tmp_path / "sessions"
    audit = AuditLog(store)
    audit.record("route_engine", {})
    first_session_id = audit.session_id
    audit.record("list_engine_manifests", {})

    session = state.load(store, first_session_id)
    tool_calls = [e for e in session["events"] if e["event_type"] == "mcp.tool_call"]
    assert len(tool_calls) == 2
    assert audit.session_id == first_session_id


def test_summarize_args_redacts_known_sensitive_keys_by_length_only():
    summary = summarize_args({"prompt": "this is a secret prompt", "task_id": "abc"})
    assert summary["prompt"] == "<redacted len=23>"
    assert "secret" not in summary["prompt"]
    assert summary["task_id"] == "abc"


def test_summarize_args_truncates_long_non_sensitive_strings():
    long_value = "x" * 500
    summary = summarize_args({"notes": long_value})
    assert len(summary["notes"]) < len(long_value)
    assert "truncated" in summary["notes"]


def test_summarize_args_handles_empty_and_none():
    assert summarize_args(None) == {}
    assert summarize_args({}) == {}


def test_audited_dispatch_call_never_carries_the_full_prompt(tmp_path):
    """Regression guard for the constraint that no full prompt lands in any
    artifact -- including this ledger."""
    store = tmp_path / "sessions"
    audit = AuditLog(store)
    secret_prompt = "the quick brown fox jumps over the lazy dog and reveals nothing secret but is long enough to matter"
    audit.record("cortxt_dispatch", {"tags": "research", "task_id": "t1", "prompt": secret_prompt})

    session = state.load(store, audit.session_id)
    raw_text = session["events"][-1]["payload"]
    assert secret_prompt not in str(raw_text)
