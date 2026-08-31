"""Tests for the reviewed loopback action host boundary (ADR-038, issue #293).

The host must stay loopback-only, same-origin, token-bound, body-bounded,
closed-schema validated, rate-limited, and operator-gated before any side
effect. All adapter ports are injected fakes; the HTTP layer uses a loopback
socket on an ephemeral port (no external network).
"""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from widget.action_host import (
    ActionDenied, ActionHost, AdapterStartFailure, AuthorizationFailure,
    DispatchDenied, GateDenied, InvalidRequest, NotFound, RateLimited,
    StaleDispatchDenied, _make_handler, _ReusableThreadingHTTPServer,
)

SPEC_PATH = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "candidates-0.1.yaml"
DECISIONS_SPEC_PATH = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "decisions-0.1.yaml"

CLAIM_APPROVAL = (
    "Operator approved this exact scope, route, and limits on 2026-08-30. "
    "Implementation start is approved for the worker in the isolated worktree."
)


def _claim_issue(number=2, **overrides):
    issue = {
        "number": number,
        "title": "Claimable workstream",
        "body": (
            "## Scope\n\nBuild the thing.\n\n"
            "## Deterministic acceptance criteria\n\n"
            "1. Launch only when the mandate is complete.\n"
            "2. No browser widening.\n\n"
            "## Approval status\n\n" + CLAIM_APPROVAL + "\n\n"
            "## Worker role and limits\n\n"
            "- Workflow: work-launcher/v1\n"
            "- Worker role: builder.\n"
            "- Max runtime: 5400 seconds.\n"
            "- Max cost: USD 8.00 hard ceiling.\n"
            "- Max parallel workers: 2.\n"
            "- Delegation depth: 1.\n\n"
            "## Artifact policy\n\nIsolated worktree only.\n\n"
            "## Engine policy\n\nReliability: unverified\nEngine: hermes-free\n"
        ),
        "state": "open",
        "labels": [{"name": "workflow:ready"}, {"name": "background-task"}],
        "url": f"https://github.com/owner/repo/issues/{number}",
        "milestone": None,
    }
    issue.update(overrides)
    return issue


def _host(**overrides):
    kwargs = {
        "spec_path": SPEC_PATH,
        "labels_reader": lambda issue_id: ["workflow:inbox"],
        "transition_writer": lambda issue_id: {"issue_id": issue_id, "status": "ok"},
        "review_transition_writer": lambda issue_id: {"issue_id": issue_id, "status": "ok"},
        "resume": lambda issue_id, **kw: {"run_id": "run-1", "issue_id": issue_id},
        "token": "test-token",
    }
    kwargs.update(overrides)
    return ActionHost(**kwargs)


def _claim_host(number=2, **overrides):
    """Host whose issue_reader serves an eligible claim-run fixture."""
    kwargs = {"issue_reader": lambda repo, n: _claim_issue(number=n)}
    kwargs.update(overrides)
    return _host(**kwargs)


def _claim_request(host, number=2):
    request = host.dispatch_request("owner/repo", number)
    assert request["eligible"] is True, request["missing"]
    return request


def test_default_launcher_scripts_directory_is_repository_level():
    host = _host()
    assert host._scripts_dir == Path(__file__).resolve().parents[3] / "scripts"
    assert (host._scripts_dir / "work_launcher.py").is_file()


class _ExecutionGateError(RuntimeError):
    """Shapes like scripts/work_launcher.ExecutionGateError (stable code attr)."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ExecutionGateError(_ExecutionGateError):
    pass


# --- business logic (ActionHost.execute), network-free ---------------------

def test_host_mark_ready_succeeds_with_operator_gate():
    calls = []

    def reader(issue_id):
        calls.append(("read", issue_id))
        return ["workflow:inbox"]

    def writer(issue_id):
        calls.append(("write", issue_id))
        return {"issue_id": issue_id, "status": "ok"}

    host = _host(labels_reader=reader, transition_writer=writer)
    result = host.execute(action_id="mark-ready", issue_id="owner/repo#1",
                          approval_ref="approval-1", confirm=True, token="test-token")
    assert result["status"] == "ok"
    assert calls == [("read", "owner/repo#1"), ("write", "owner/repo#1")]
    assert len([c for c in calls if c[0] == "write"]) == 1


def test_host_record_decision_succeeds_when_spec_is_decisions():
    calls = []

    def reader(issue_id):
        calls.append(("read", issue_id))
        return ["workflow:review"]

    def writer(issue_id):
        calls.append(("write", issue_id))
        return {"issue_id": issue_id, "status": "ok"}

    host = _host(spec_path=DECISIONS_SPEC_PATH, labels_reader=reader,
                review_transition_writer=writer)
    result = host.execute(action_id="record-decision", issue_id="owner/repo#402",
                          approval_ref="approval-1", confirm=True, token="test-token")
    assert result["status"] == "ok"
    assert calls == [("read", "owner/repo#402"), ("write", "owner/repo#402")]


def test_host_record_decision_uses_review_writer_not_inbox_writer():
    """Regression guard: record-decision must never fall through to the
    inbox -> ready writer, even when both are injected (Task 6 finding)."""
    calls = []

    def mark_ready_writer(issue_id):
        calls.append(("mark-ready-write", issue_id))
        return {"issue_id": issue_id, "status": "ok"}

    def review_writer(issue_id):
        calls.append(("review-write", issue_id))
        return {"issue_id": issue_id, "status": "ok"}

    host = _host(spec_path=DECISIONS_SPEC_PATH,
                labels_reader=lambda issue_id: ["workflow:review"],
                transition_writer=mark_ready_writer,
                review_transition_writer=review_writer)
    host.execute(action_id="record-decision", issue_id="owner/repo#402",
                approval_ref="approval-1", confirm=True, token="test-token")
    assert calls == [("review-write", "owner/repo#402")]


def test_host_record_decision_fails_closed_without_review_writer():
    """review_transition_writer=None must raise, never silently fall back to
    transition_writer (code-review finding on action_ports.py:69)."""
    calls = []

    def mark_ready_writer(issue_id):
        calls.append(("mark-ready-write", issue_id))
        return {"issue_id": issue_id, "status": "ok"}

    host = _host(spec_path=DECISIONS_SPEC_PATH,
                labels_reader=lambda issue_id: ["workflow:review"],
                transition_writer=mark_ready_writer,
                review_transition_writer=None)
    with pytest.raises(ValueError):
        host.execute(action_id="record-decision", issue_id="owner/repo#402",
                    approval_ref="approval-1", confirm=True, token="test-token")
    assert calls == []


def test_host_claim_run_succeeds_through_injected_launcher():
    calls = []

    def resume(issue_id, **kw):
        calls.append((issue_id, kw))
        return {"run_id": "run-9", "issue_id": issue_id}

    host = _claim_host(resume=resume)
    req = _claim_request(host)
    result = host.execute(action_id="claim-run", issue_id="owner/repo#2",
                          approval_ref=req["approval_reference"], request_id=req["request_id"],
                          confirm=True, token="test-token")
    assert result["status"] == "ok"
    assert result["result"]["run_id"] == "run-9"
    assert calls[0][0] == "owner/repo#2"
    assert calls[0][1]["approval_ref"] == req["approval_reference"]
    assert calls[0][1]["request_id"] == req["request_id"]


def test_host_claim_run_requires_request_id_snapshot():
    host = _claim_host()
    req = _claim_request(host)
    with pytest.raises(InvalidRequest, match="request_id"):
        host.execute(action_id="claim-run", issue_id="owner/repo#2",
                     approval_ref=req["approval_reference"], request_id="",
                     confirm=True, token="test-token")


def test_host_claim_run_rejects_stale_request_snapshot():
    host = _claim_host()
    req = _claim_request(host)
    with pytest.raises(StaleDispatchDenied):
        host.execute(action_id="claim-run", issue_id="owner/repo#2",
                     approval_ref=req["approval_reference"],
                     request_id="sha256:" + "0" * 64,
                     confirm=True, token="test-token")


def test_host_claim_run_rejects_approval_mismatch_without_launching():
    calls = []

    def resume(issue_id, **kw):
        calls.append(issue_id)
        return {"run_id": "x"}

    host = _claim_host(resume=resume)
    req = _claim_request(host)
    with pytest.raises(AuthorizationFailure, match="approval reference"):
        host.execute(action_id="claim-run", issue_id="owner/repo#2",
                     approval_ref="someone-else-approves", request_id=req["request_id"],
                     confirm=True, token="test-token")
    assert calls == []


def test_host_claim_run_rejects_label_drift_before_launching():
    """The Issue changed between preview and confirmation (workflow left ready):
    the confirmation must fail closed with the structured eligibility errors."""
    state = {"ready": True}
    calls = []

    def reader(repo, number):
        return _claim_issue(number=number,
                            labels=[{"name": "workflow:ready" if state["ready"] else "workflow:in-progress"},
                                    {"name": "background-task"}])

    def resume(issue_id, **kw):
        calls.append(issue_id)
        return {"run_id": "x"}

    host = _claim_host(issue_reader=reader, resume=resume)
    req = host.dispatch_request("owner/repo", 2)  # preview while ready
    state["ready"] = False  # label drift before confirmation
    with pytest.raises(DispatchDenied) as exc:
        host.execute(action_id="claim-run", issue_id="owner/repo#2",
                     approval_ref=req["approval_reference"], request_id=req["request_id"],
                     confirm=True, token="test-token")
    assert exc.value.code == "dispatch_request_not_eligible"
    assert any(e["code"] == "workflow_ready" for e in exc.value.errors)
    assert calls == []


def test_host_claim_run_gate_error_propagates_stable_code_with_recovery():
    def gated(issue_id, **kw):
        raise ExecutionGateError("resource_collision")

    host = _claim_host(resume=gated)
    req = _claim_request(host)
    with pytest.raises(GateDenied) as exc:
        host.execute(action_id="claim-run", issue_id="owner/repo#2",
                     approval_ref=req["approval_reference"], request_id=req["request_id"],
                     confirm=True, token="test-token")
    assert exc.value.code == "resource_collision"
    assert exc.value.category == "claim_conflict"
    assert exc.value.recovery


def test_host_claim_run_adapter_start_failure_is_stable_with_recovery():
    class LauncherDispatchError(RuntimeError):
        category = "adapter_start_failed"

        def __init__(self, code, recovery=None):
            self.code = code
            self.recovery = recovery or "default recovery"
            super().__init__(code)

    def failing(issue_id, **kw):
        raise LauncherDispatchError("adapter_not_registered", recovery="register an adapter")

    host = _claim_host(resume=failing)
    req = _claim_request(host)
    with pytest.raises(AdapterStartFailure) as exc:
        host.execute(action_id="claim-run", issue_id="owner/repo#2",
                     approval_ref=req["approval_reference"], request_id=req["request_id"],
                     confirm=True, token="test-token")
    assert exc.value.code == "adapter_not_registered"
    assert exc.value.category == "adapter"
    assert exc.value.recovery == "register an adapter"


def test_host_unknown_action_is_not_found():
    host = _host()
    with pytest.raises(NotFound):
        host.execute(action_id="nope", issue_id="owner/repo#1",
                     approval_ref="approval-1", confirm=True, token="test-token")


def test_host_missing_or_wrong_token_fails_closed():
    host = _host()
    with pytest.raises(AuthorizationFailure):
        host.execute(action_id="mark-ready", issue_id="owner/repo#1",
                     approval_ref="approval-1", confirm=True, token="")
    with pytest.raises(AuthorizationFailure):
        host.execute(action_id="mark-ready", issue_id="owner/repo#1",
                     approval_ref="approval-1", confirm=True, token="wrong")


def test_host_confirm_required_fails_closed_without_side_effect():
    calls = []

    def writer(issue_id):
        calls.append(("write", issue_id))
        return {"status": "ok"}

    host = _host(transition_writer=writer)
    with pytest.raises(AuthorizationFailure):
        host.execute(action_id="mark-ready", issue_id="owner/repo#1",
                     approval_ref="approval-1", confirm=False, token="test-token")
    assert calls == []


def test_host_empty_approval_reference_fails_closed():
    calls = []

    def writer(operation, request):
        calls.append(("write", request["issue_id"]))
        return {"status": "ok"}

    host = _host(transition_writer=writer)
    with pytest.raises(InvalidRequest):
        host.execute(action_id="mark-ready", issue_id="owner/repo#1",
                     approval_ref="", confirm=True, token="test-token")
    assert calls == []


def test_host_transition_denied_maps_to_action_denied():
    host = _host(labels_reader=lambda issue_id: ["workflow:blocked"])
    with pytest.raises(ActionDenied):
        host.execute(action_id="mark-ready", issue_id="owner/repo#3",
                     approval_ref="approval-1", confirm=True, token="test-token")


def test_host_rate_limit_enforced():
    now = [100.0]
    host = _host(clock=lambda: now[0], max_requests=3)
    for _ in range(3):
        host.execute(action_id="mark-ready", issue_id="owner/repo#1",
                     approval_ref="approval-1", confirm=True, token="test-token")
    with pytest.raises(RateLimited):
        host.execute(action_id="mark-ready", issue_id="owner/repo#1",
                     approval_ref="approval-1", confirm=True, token="test-token")


def test_host_capabilities_declare_actions():
    host = _host()
    caps = host.capabilities()
    assert caps["actions_enabled"] is True
    assert {a["id"] for a in caps["actions"]} == {"mark-ready", "claim-run", "record-decision"}
    assert all(a["confirm"]["required"] for a in caps["actions"])


# --- HTTP layer over a loopback ephemeral socket ---------------------------

@pytest.fixture
def server():
    host = _host()
    httpd = _ReusableThreadingHTTPServer(("127.0.0.1", 0), _make_handler(host))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _request(url, *, method="GET", body=None, headers=None):
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _post(server, payload, *, token="test-token", ctype="application/json"):
    headers = {"Content-Type": ctype, "X-Cortxt-Token": token}
    return _request(f"{server}/api/action", method="POST",
                    body=json.dumps(payload).encode("utf-8"), headers=headers)


def test_http_token_and_capabilities_served_same_origin(server):
    status, body = _request(f"{server}/api/token")
    assert status == 200 and json.loads(body)["token"] == "test-token"
    status, body = _request(f"{server}/api/capabilities")
    assert status == 200 and json.loads(body)["actions_enabled"] is True


def test_http_static_get_surface_preserved(server):
    status, body = _request(f"{server}/index.html")
    assert status == 200 and "Cortxt" in body


def test_http_mark_ready_success_end_to_end(server):
    status, body = _post(server, {"action_id": "mark-ready", "issue_id": "owner/repo#5",
                                  "approval_ref": "approval-1", "confirm": True})
    data = json.loads(body)
    assert status == 200 and data["status"] == "ok" and data["issue_id"] == "owner/repo#5"


def test_http_wrong_token_denied(server):
    status, body = _post(server, {"action_id": "mark-ready", "issue_id": "owner/repo#5",
                                  "approval_ref": "approval-1", "confirm": True}, token="wrong")
    data = json.loads(body)
    assert status == 403 and data["error"]["kind"] == "authorization_denied"


def test_http_missing_token_denied(server):
    status, body = _post(server, {"action_id": "mark-ready", "issue_id": "owner/repo#5",
                                  "approval_ref": "approval-1", "confirm": True}, token="")
    assert status == 403 and json.loads(body)["error"]["kind"] == "authorization_denied"


def test_http_non_json_content_type_rejected(server):
    status, body = _post(server, {"action_id": "mark-ready"}, ctype="text/plain")
    assert status == 415 and json.loads(body)["error"]["kind"] == "validation_error"


def test_http_oversized_body_rejected(server):
    payload = {"action_id": "mark-ready", "issue_id": "owner/repo#5",
               "approval_ref": "a" * 9000, "confirm": True}
    status, body = _post(server, payload)
    assert status == 413 and json.loads(body)["error"]["kind"] == "validation_error"


def test_http_unknown_fields_rejected(server):
    status, body = _post(server, {"action_id": "mark-ready", "issue_id": "owner/repo#5",
                                  "approval_ref": "approval-1", "confirm": True, "extra": 1})
    data = json.loads(body)
    assert status == 400 and data["error"]["kind"] == "validation_error"


def test_http_missing_fields_rejected(server):
    status, body = _post(server, {"action_id": "mark-ready", "issue_id": "owner/repo#5"})
    assert status == 400 and json.loads(body)["error"]["kind"] == "validation_error"


def test_http_unknown_action_not_found(server):
    status, body = _post(server, {"action_id": "nope", "issue_id": "owner/repo#5",
                                  "approval_ref": "approval-1", "confirm": True})
    assert status == 404 and json.loads(body)["error"]["kind"] == "not_found"


def test_http_unknown_post_route_not_found(server):
    status, _ = _request(f"{server}/api/other", method="POST", body=b"{}",
                         headers={"Content-Type": "application/json", "X-Cortxt-Token": "test-token"})
    assert status == 404


def test_http_options_not_answered(server):
    status, _ = _request(f"{server}/api/action", method="OPTIONS")
    assert status == 405


def test_http_no_cors_headers_on_responses(server):
    request = urllib.request.Request(f"{server}/api/token", method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers.get("Access-Control-Allow-Origin") is None
