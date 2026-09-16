"""W-3 (#612): packaging routes on the web action host.

Guard-parity with POST /api/action is the point of this module: the new
``POST /api/packaging-action`` route must enforce the SAME guard set in the
SAME order (JSON content-type -> body bounds -> closed schema -> session
token -> operator gate) and the read routes must serve the shared ops-API
projections (including the kriterium-oracle workstream) from real store
state. All adapter ports are injected fakes; HTTP tests run on a loopback
ephemeral socket. No external network.
"""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from state.core_store import CoreStore
from widget.action_host import (
    ActionHost, AuthorizationFailure, InvalidRequest, NotFound, RateLimited,
    _make_handler, _ReusableThreadingHTTPServer,
)
from widget_contract.product_packaging.ops_api import PACKAGING_WORKSTREAM
from widget_contract.product_packaging.revision import build_revision

SPEC_PATH = Path(__file__).resolve().parents[2] / "widget_contract" / "specs" / "candidates-0.1.yaml"


def _host(**overrides):
    kwargs = {
        "spec_path": SPEC_PATH,
        "labels_reader": lambda issue_id: ["workflow:inbox"],
        "transition_writer": lambda issue_id: {"issue_id": issue_id, "status": "ok"},
        "token": "test-token",
    }
    kwargs.update(overrides)
    return ActionHost(**kwargs)


def _packaged_host(**overrides):
    tmp = tempfile.TemporaryDirectory()
    host = _host(packaging_store=Path(tmp.name), **overrides)
    host._w3_tmpdir = tmp  # keep the store root alive for the host's lifetime
    return host


def _revision_body(package_id="cortxt-core", **overrides):
    revision = build_revision(package_id, {
        "audience": "operator", "evidence_refs": [], "features": ["f"],
        "outcome": "an outcome", "problem": "a problem", "prior_binding_refs": [],
        "referenced_repositories": ["rian010194/cortxt"], "scope": ["s"]})
    revision.update(overrides)
    return revision


def _action_payload(**overrides):
    payload = {
        "action_id": "packaging.create-revision",
        "package_id": "cortxt-core",
        "approval_ref": "approval-w3",
        "confirm": True,
        "revision": _revision_body(),
    }
    payload.update(overrides)
    return payload


# --- business logic (ActionHost.packaging_action) ---------------------------


def test_packaging_unconfigured_store_fails_closed():
    host = _host()
    assert host.packaging is None
    with pytest.raises(Exception) as excinfo:
        host.packaging_workstream()
    assert "not configured" in str(excinfo.value)


def test_packaging_create_revision_full_gate_and_envelope():
    host = _packaged_host()
    result = host.packaging_action(
        action_id="packaging.create-revision", package_id="cortxt-core",
        approval_ref="approval-w3", confirm=True, token="test-token",
        revision=_revision_body(), issue_ref="rian010194/cortxt#606")
    assert result["operation"] == "packaging.create-revision"
    outcome = result["outcome"]
    assert outcome["outcome"] == "appended" and outcome["appended"] is True
    revisions = host.packaging_revisions()["revisions"]
    assert len(revisions) == 1
    assert revisions[0]["revision_identity"] == outcome["revision_identity"]


def test_packaging_missing_token_denied():
    host = _packaged_host()
    with pytest.raises(AuthorizationFailure):
        host.packaging_action(action_id="packaging.create-revision", package_id="cortxt-core",
                              approval_ref="a", confirm=True, token="",
                              revision=_revision_body())


def test_packaging_wrong_token_denied():
    host = _packaged_host()
    with pytest.raises(AuthorizationFailure):
        host.packaging_action(action_id="packaging.create-revision", package_id="cortxt-core",
                              approval_ref="a", confirm=True, token="nope",
                              revision=_revision_body())


def test_packaging_confirm_false_refused_fail_closed():
    host = _packaged_host()
    with pytest.raises(AuthorizationFailure):
        host.packaging_action(action_id="packaging.create-revision", package_id="cortxt-core",
                              approval_ref="a", confirm=False, token="test-token",
                              revision=_revision_body())
    assert host.packaging_revisions()["revisions"] == []


def test_packaging_empty_approval_ref_refused():
    host = _packaged_host()
    with pytest.raises(InvalidRequest):
        host.packaging_action(action_id="packaging.create-revision", package_id="cortxt-core",
                              approval_ref="", confirm=True, token="test-token",
                              revision=_revision_body())
    assert host.packaging_revisions()["revisions"] == []


def test_packaging_unknown_action_not_found():
    host = _packaged_host()
    with pytest.raises(NotFound):
        host.packaging_action(action_id="packaging.nope", package_id="cortxt-core",
                              approval_ref="a", confirm=True, token="test-token")


def test_packaging_rate_limit_shared_with_other_actions():
    now = [100.0]
    host = _packaged_host(clock=lambda: now[0], max_requests=2)
    for _ in range(2):
        host.packaging_action(action_id="packaging.create-revision", package_id="cortxt-core",
                              approval_ref="a", confirm=True, token="test-token",
                              revision=_revision_body())
    with pytest.raises(RateLimited):
        host.packaging_action(action_id="packaging.create-revision", package_id="cortxt-core",
                              approval_ref="a", confirm=True, token="test-token",
                              revision=_revision_body())


def test_packaging_record_operation_and_decision_via_host():
    host = _packaged_host()
    created = host.packaging_action(
        action_id="packaging.create-revision", package_id="cortxt-core",
        approval_ref="a", confirm=True, token="test-token", revision=_revision_body())
    digest = created["outcome"]["revision_identity"]
    operation = host.packaging_action(
        action_id="packaging.record-operation", package_id="cortxt-core",
        approval_ref="a", confirm=True, token="test-token",
        operation={"operation_id": "op-w3", "package_id": "cortxt-core",
                   "original_parent": digest},
        candidate_revision=_revision_body("cortxt-core", parent_revision_identity=digest),
        status="committed")
    assert operation["outcome"]["outcome"] == "appended"
    decision = host.packaging_action(
        action_id="packaging.record-decision", package_id="cortxt-core",
        approval_ref="a", confirm=True, token="test-token",
        decision={"package_id": "cortxt-core", "revision_digest": digest,
                  "decision_scope": "acceptance", "operator": "operator-rikard",
                  "verdict": "accepted"})
    assert decision["outcome"]["outcome"] == "appended"
    evidence = host.packaging_action(
        action_id="packaging.append-evidence", package_id="cortxt-core",
        approval_ref="a", confirm=True, token="test-token",
        evidence={"request_id": created["outcome"]["record_digest"],
                  "entry_id": "ev-w3", "payload_digest": created["outcome"]["record_digest"]})
    assert evidence["outcome"]["outcome"] == "appended"
    views = host.packaging_workstream()
    assert views["counts"] == {"revisions": 1, "operations": 1, "decisions": 1, "evidence": 1}


# --- HTTP layer over a loopback ephemeral socket ----------------------------


@pytest.fixture
def packaging_server():
    host = _packaged_host()
    httpd = _ReusableThreadingHTTPServer(("127.0.0.1", 0), _make_handler(host))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


@pytest.fixture
def bare_server():
    host = _host()  # no packaging store configured
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


def _packaging_get(server, path):
    return _request(f"{server}{path}")


def _packaging_post(server, payload, *, token="test-token", ctype="application/json"):
    headers = {"Content-Type": ctype, "X-Cortxt-Token": token}
    return _request(f"{server}/api/packaging-action", method="POST",
                    body=json.dumps(payload).encode("utf-8"), headers=headers)


def test_http_packaging_read_routes_serve_real_store(packaging_server):
    status, body = _packaging_get(packaging_server, "/api/packaging-revisions")
    assert status == 200
    assert json.loads(body) == {"schema_version": 1, "status": "ok", "revisions": []}
    for path in ("/api/packaging-operations", "/api/packaging-decisions",
                 "/api/packaging-evidence"):
        status, body = _packaging_get(packaging_server, path)
        assert status == 200
        assert json.loads(body)["status"] == "ok"


def test_http_packaging_workstream_route_serves_oracle(packaging_server):
    status, body = _packaging_get(packaging_server, "/api/packaging-workstream")
    assert status == 200
    served = json.loads(body)
    assert served["workstream"]["id"] == "WS-606"
    assert served["workstream"]["mandate"] == PACKAGING_WORKSTREAM["mandate"]
    assert served["workstream"]["non_goals"] == PACKAGING_WORKSTREAM["non_goals"]
    assert served["workstream"]["repo_refs"] == PACKAGING_WORKSTREAM["repo_refs"]


def test_http_packaging_action_end_to_end(packaging_server):
    status, body = _packaging_post(packaging_server, _action_payload())
    assert status == 200, body
    served = json.loads(body)
    assert served["status"] == "ok"
    assert served["outcome"]["outcome"] == "appended"
    status, body = _packaging_get(packaging_server, "/api/packaging-revisions")
    assert len(json.loads(body)["revisions"]) == 1


def test_http_packaging_action_wrong_token_denied(packaging_server):
    status, body = _packaging_post(packaging_server, _action_payload(), token="wrong")
    assert status == 403
    assert json.loads(body)["error"]["kind"] == "authorization_denied"


def test_http_packaging_action_missing_token_denied(packaging_server):
    status, body = _packaging_post(packaging_server, _action_payload(), token="")
    assert status == 403
    assert json.loads(body)["error"]["kind"] == "authorization_denied"


def test_http_packaging_action_confirm_false_denied(packaging_server):
    payload = _action_payload(confirm=False)
    status, body = _packaging_post(packaging_server, payload)
    assert status == 403
    assert json.loads(body)["error"]["kind"] == "authorization_denied"


def test_http_packaging_action_missing_approval_ref_denied(packaging_server):
    payload = _action_payload(approval_ref="")
    status, body = _packaging_post(packaging_server, payload)
    assert status == 400
    assert json.loads(body)["error"]["kind"] == "validation_error"


def test_http_packaging_action_unknown_fields_rejected(packaging_server):
    status, body = _packaging_post(packaging_server, _action_payload(surprise=1))
    assert status == 400
    assert json.loads(body)["error"]["kind"] == "validation_error"


def test_http_packaging_action_missing_fields_rejected(packaging_server):
    status, body = _packaging_post(packaging_server, {"action_id": "packaging.create-revision"})
    assert status == 400
    assert json.loads(body)["error"]["kind"] == "validation_error"


def test_http_packaging_action_unknown_action_id_rejected(packaging_server):
    status, body = _packaging_post(packaging_server, _action_payload(action_id="packaging.nope"))
    assert status == 400  # schema enum rejects before any handler logic
    assert json.loads(body)["error"]["kind"] == "validation_error"


def test_http_packaging_action_bad_content_type_rejected(packaging_server):
    status, body = _packaging_post(packaging_server, _action_payload(), ctype="text/plain")
    assert status == 415
    assert json.loads(body)["error"]["kind"] == "validation_error"


def test_http_packaging_action_oversized_body_rejected(packaging_server):
    payload = _action_payload()
    payload["revision"] = _revision_body()
    payload["revision"]["content"] = {"pad": "x" * (9 * 1024)}
    status, body = _packaging_post(packaging_server, payload)
    assert status == 413
    assert json.loads(body)["error"]["kind"] == "validation_error"


def test_http_packaging_read_routes_unconfigured_fail_closed(bare_server):
    # No store configured: every packaging read route answers an explicit
    # 503 store_unavailable, never an empty success.
    for path in ("/api/packaging-workstream", "/api/packaging-revisions",
                 "/api/packaging-operations", "/api/packaging-decisions",
                 "/api/packaging-evidence"):
        status, body = _packaging_get(bare_server, path)
        assert status == 503
        assert json.loads(body)["error"]["kind"] == "store_unavailable"


def test_http_existing_routes_unchanged(packaging_server):
    # Append-only guarantee: the pre-existing routes still behave identically.
    status, body = _request(f"{packaging_server}/api/token")
    assert status == 200 and json.loads(body)["token"] == "test-token"
    # POST /api/action itself is untouched: an unknown action there still
    # fails closed with its own 404 (NotFound), not our packaging route.
    headers = {"Content-Type": "application/json", "X-Cortxt-Token": "test-token"}
    status, body = _request(f"{packaging_server}/api/action", method="POST",
                            body=json.dumps({"action_id": "nope", "issue_id": "owner/repo#5",
                                             "approval_ref": "a", "confirm": True}).encode("utf-8"),
                            headers=headers)
    assert status == 404, body
    assert json.loads(body)["error"]["kind"] == "not_found"


def test_http_unknown_post_route_still_404(packaging_server):
    status, body = _request(f"{packaging_server}/api/definitely-not-a-route", method="POST",
                            body=b"{}", headers={"Content-Type": "application/json"})
    assert status == 404
