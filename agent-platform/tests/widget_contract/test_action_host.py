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
    ActionDenied, ActionHost, AuthorizationFailure, GateDenied, InvalidRequest,
    NotFound, RateLimited, _make_handler, _ReusableThreadingHTTPServer,
)

SPEC_PATH = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "candidates-0.1.yaml"
DECISIONS_SPEC_PATH = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "decisions-0.1.yaml"


def _host(**overrides):
    kwargs = {
        "spec_path": SPEC_PATH,
        "labels_reader": lambda issue_id: ["workflow:inbox"],
        "transition_writer": lambda issue_id: {"issue_id": issue_id, "status": "ok"},
        "review_transition_writer": lambda issue_id: {"issue_id": issue_id, "status": "ok"},
        "resume": lambda issue_id: {"run_id": "run-1", "issue_id": issue_id},
        "token": "test-token",
    }
    kwargs.update(overrides)
    return ActionHost(**kwargs)


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
    host = _host(resume=lambda issue_id: {"run_id": "run-9", "issue_id": issue_id})
    result = host.execute(action_id="claim-run", issue_id="owner/repo#2",
                          approval_ref="approval-1", confirm=True, token="test-token")
    assert result["status"] == "ok"
    assert result["result"]["run_id"] == "run-9"


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


def test_host_claim_run_gate_error_propagates_stable_code():
    def gated(issue_id):
        raise ExecutionGateError("resource_collision")

    host = _host(resume=gated)
    with pytest.raises(GateDenied) as exc:
        host.execute(action_id="claim-run", issue_id="owner/repo#4",
                     approval_ref="approval-1", confirm=True, token="test-token")
    assert exc.value.code == "resource_collision"


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
    assert {a["id"] for a in caps["actions"]} == {"mark-ready", "claim-run"}
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
