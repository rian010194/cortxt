import pytest

from widget_contract.adapters.github_ports import issue_ready_list
from widget_contract.adapters.store_reads import ReadAdapterError, read_active_runs_v1, read_snapshot_v2


def test_snapshot_v2_is_exact_safe_projection():
    source = {"schema_version": 2, "generated_at": "2026-01-01T00:00:00Z", "orchestrator": {}, "workstreams": [], "sessions": [], "activity": [], "credentials": [{"value": "excluded"}], "profiles": []}
    assert read_snapshot_v2(source) == {key: source[key] for key in ("schema_version", "generated_at", "orchestrator", "workstreams", "sessions", "activity")}


def test_active_runs_v1_normalizes_and_rejects_type_mismatch():
    source = {"runs": [{"run_id": "r1", "status": "running", "issue_number": 259, "private_output": "excluded"}]}
    assert read_active_runs_v1(source) == {"schema_version": 1, "runs": [{"run_id": "r1", "status": "running", "issue_number": 259}]}
    with pytest.raises(ReadAdapterError):
        read_active_runs_v1({"runs": "wrong"})


def test_issue_read_uses_injected_callable_and_exact_output_type():
    calls = []
    result = issue_ready_list(lambda request: calls.append(request) or [{"number": 259, "title": "Foundation", "state": "open", "workflow": "ready", "body": "excluded"}], {"limit": 10})
    assert calls == [{"limit": 10}]
    assert result == {"schema_version": 1, "issues": [{"number": 259, "title": "Foundation", "state": "open", "workflow": "ready"}]}
    with pytest.raises(ValueError):
        issue_ready_list(lambda request: [{"number": "wrong"}], {})
