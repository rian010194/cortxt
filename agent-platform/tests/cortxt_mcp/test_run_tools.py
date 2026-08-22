"""Mandate chokepoint and lifecycle tests with no network or worker process."""
from types import SimpleNamespace

from cortxt_mcp import mandate, tools


class AcceptingVerifier:
    def verify(self, envelope, **kwargs):
        return SimpleNamespace(accepted=True, reason="accepted")


def binding(scope):
    return {"mandate_id": "m1", "granted_by": "operator", "issue_ref": "o/r#1",
            "scope_fingerprint": mandate.compute_scope_fingerprint(scope),
            "budget_usd_max": 2.0, "max_runtime_seconds": 60, "data_class_max": "L1"}


def test_run_lifecycle_and_mandate_binding(tmp_path):
    store = tmp_path / "runs.json"
    scope = "Build one bounded feature"
    envelope = binding(scope)
    created = tools.call_tool("cortxt_run_create", {"scope_text": scope, "store": str(store)},
                              allow_dispatch=True, allow_credentials=False, mandate=envelope,
                              mandate_verifier=AcceptingVerifier())
    assert created["status"] == "succeeded"
    resumed = tools.call_tool("cortxt_run_resume", {"run_id": created["run_id"], "store": str(store)},
                              allow_dispatch=True, allow_credentials=False, mandate=envelope,
                              mandate_verifier=AcceptingVerifier())
    assert resumed["status"] == "succeeded"
    submitted = tools.call_tool(
        "cortxt_run_submit_for_review",
        {"run_id": created["run_id"], "store": str(store), "result": {"status": "succeeded"}},
        allow_dispatch=True, allow_credentials=False, mandate=envelope,
        mandate_verifier=AcceptingVerifier(),
    )
    assert submitted["status"] == "succeeded"


def test_handler_never_runs_without_mandate(tmp_path):
    try:
        tools.call_tool("cortxt_run_create", {"scope_text": "x", "store": str(tmp_path / "x")},
                        allow_dispatch=True, allow_credentials=False)
    except tools.MandateRejectedError:
        pass
    else:
        raise AssertionError("missing mandate must fail before handler")
    assert not (tmp_path / "x").exists()
