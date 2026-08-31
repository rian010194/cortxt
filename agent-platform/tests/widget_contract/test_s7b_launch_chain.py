"""S7b (#471) integration proof through the real action-host -> projection -> launcher chain.

These tests exercise the actual `ActionHost.execute` claim-run path with the
real `gh_claim_run_resume` projection wiring (only the GitHub issue reader and
the launcher are injected fakes): a confirmed launch re-reads the Issue, binds
the authoritative dispatch request (approval reference + request snapshot id),
and then routes through the execution-map-gated launcher with every dispatch
limit carried. AC5/AC8/AC4 scenarios -- double click/submit, replay, another
active Run, stale receipt, label drift, stale mandate, approval mismatch --
must all fail closed without a second launch.
"""
from functools import partial
from pathlib import Path
import json
import threading
import urllib.error
import urllib.request

import pytest

from widget.action_host import (
    ActionHost, AuthorizationFailure, DispatchDenied, GateDenied,
    StaleDispatchDenied, _make_handler, _ReusableThreadingHTTPServer,
)
from widget_contract.adapters.cli_ports import gh_claim_run_resume

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"

CLAIM_APPROVAL = (
    "Operator approved this exact scope, route, and limits on 2026-08-30. "
    "Implementation start is approved for the worker in the isolated worktree."
)


def _issue(number=471, *, approval=CLAIM_APPROVAL, labels=None):
    return {
        "number": number,
        "title": "Build: S7b — Operator launch from Work through the gated launcher",
        "body": (
            "## Scope\n\nMake a real workflow:ready Workstream launchable.\n\n"
            "## Deterministic acceptance criteria\n\n"
            "1. Launch only when the mandate is complete.\n"
            "2. No browser widening.\n\n"
            "## Approval status\n\n" + approval + "\n\n"
            "## Worker role and limits\n\n"
            "- Workflow: work-launcher/v1\n"
            "- Worker role: builder.\n"
            "- Max runtime: 5400 seconds.\n"
            "- Max cost: USD 8.00 hard ceiling; target <= USD 5.00.\n"
            "- Max parallel workers: 2, one writer only.\n"
            "- Delegation depth: 1.\n\n"
            "## Artifact policy\n\nIsolated worktree; approved source/tests/docs only.\n\n"
            "## Engine policy\n\nReliability: unverified\nEngine: hermes-free\n"
        ),
        "state": "open",
        "labels": [{"name": "workflow:ready"}, {"name": "background-task"}] if labels is None else labels,
        "url": f"https://github.com/owner/repo/issues/{number}",
        "milestone": None,
    }


class ExecutionGateError(RuntimeError):
    """Shapes like scripts/work_launcher.ExecutionGateError (stable code attr)."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _GateLauncher:
    """Fake WorkLauncher.resume: records the carried mandate and simulates the
    execution-map gate (fresh receipt + durable claim) with stable codes."""

    def __init__(self, gate_codes=()):
        self.gate_codes = list(gate_codes)
        self.calls = []

    def resume(self, issue_id, **kwargs):
        self.calls.append({"issue_id": issue_id, **kwargs})
        if self.gate_codes:
            code = self.gate_codes.pop(0)
            if code:
                raise ExecutionGateError(code)
        return {"issue_id": issue_id, "run_id": "run-1", "claim_id": "claim-1",
                "receipt_id": "receipt-1", "store_session_id": "s1",
                "engine_session_id": "e1", "worktree": "trees/run-1",
                "branch": "work/run-1"}


def _chain(issue_reader, *, gate_codes=()):
    """Real host + real gh_claim_run_resume projection wiring; only the issue
    reader and the launcher are fakes."""
    launcher = _GateLauncher(gate_codes=gate_codes)
    resume = partial(gh_claim_run_resume, registry=Path("unused-runs.json"),
                     scripts_dir=SCRIPTS_DIR, issue_reader=issue_reader, launcher=launcher)
    host = ActionHost(issue_reader=issue_reader, resume=resume, token="test-token")
    return host, launcher


def _confirm(host, number=471):
    """Preview the authoritative request exactly as the confirmation view would."""
    request = host.dispatch_request("owner/repo", number)
    assert request["eligible"] is True, request["missing"]
    return request


def _launch(host, request, number=471):
    return host.execute(action_id="claim-run", issue_id=f"owner/repo#{number}",
                        approval_ref=request["approval_reference"],
                        request_id=request["request_id"],
                        confirm=True, token="test-token")


def test_full_chain_launch_carries_every_dispatch_limit():
    host, launcher = _chain(lambda repo, number: _issue(number))
    request = _confirm(host)
    result = _launch(host, request)
    assert result["status"] == "ok"
    assert result["result"]["run_id"] == "run-1"
    call = launcher.calls[0]
    assert call["runtime"] == "hermes-free"
    assert call["workflow"] == "work-launcher/v1"
    assert call["worker_role"] == "builder"
    assert call["max_runtime_seconds"] == 5400
    assert call["max_cost_usd"] == 8.0
    assert call["max_parallel_workers"] == 2
    assert call["delegation_depth"] == 1
    assert call["artifact_policy"]
    assert call["request_id"] == request["request_id"]
    assert call.get("approval_ref") is None  # approval binding stays in the projection adapter


def test_full_chain_double_click_fails_closed_after_launch():
    """A second click after a successful launch must not create a second run:
    the issue left workflow:ready, so the re-read at confirmation rejects it."""
    state = {"launched": False}

    def reader(repo, number):
        labels = ([{"name": "workflow:in-progress"}, {"name": "background-task"}]
                  if state["launched"] else None)
        return _issue(number, labels=labels)

    host, launcher = _chain(reader)
    request = _confirm(host)
    first = _launch(host, request)
    assert first["status"] == "ok"
    state["launched"] = True  # the dispatcher claim moved ready -> in-progress

    with pytest.raises(DispatchDenied) as exc:
        _launch(host, request)
    assert exc.value.code == "dispatch_request_not_eligible"
    assert any(e["code"] == "workflow_ready" for e in exc.value.errors)
    assert len(launcher.calls) == 1  # no second launch reached the launcher


def test_full_chain_replayed_request_fails_closed():
    """Replay of the same confirmed POST body must not launch a second run
    even when the issue reader stays ready (gate-level active-Run rejection)."""
    host, launcher = _chain(lambda repo, number: _issue(number),
                            gate_codes=("", "resource_collision"))
    request = _confirm(host)
    assert _launch(host, request)["status"] == "ok"
    with pytest.raises(GateDenied) as exc:
        _launch(host, request)
    assert exc.value.code == "resource_collision"
    assert exc.value.category == "claim_conflict"
    assert exc.value.recovery
    assert len(launcher.calls) == 2


def test_full_chain_active_run_rejected_with_gate_code():
    """Another active Run for the same issue is rejected by the execution-map
    gate with the stable resource_collision code and recovery guidance."""
    host, launcher = _chain(lambda repo, number: _issue(number),
                            gate_codes=("resource_collision",))
    request = _confirm(host)
    with pytest.raises(GateDenied) as exc:
        _launch(host, request)
    assert exc.value.code == "resource_collision"
    assert exc.value.recovery
    assert launcher.calls[0]["request_id"] == request["request_id"]


def test_full_chain_stale_receipt_rejected_with_gate_code():
    host, launcher = _chain(lambda repo, number: _issue(number),
                            gate_codes=("stale_receipt",))
    request = _confirm(host)
    with pytest.raises(GateDenied) as exc:
        _launch(host, request)
    assert exc.value.code == "stale_receipt"
    assert exc.value.recovery


def test_full_chain_label_drift_rejected_before_launch():
    """The Issue moved off workflow:ready between preview and confirmation:
    the confirmation rebuild is ineligible and nothing reaches the launcher."""
    state = {"reads": 0}

    def reader(repo, number):
        state["reads"] += 1
        labels = ([{"name": "workflow:ready"}, {"name": "background-task"}]
                  if state["reads"] == 1 else
                  [{"name": "workflow:blocked"}, {"name": "background-task"}])
        return _issue(number, labels=labels)

    host, launcher = _chain(reader)
    request = _confirm(host)  # preview read #1
    with pytest.raises(DispatchDenied) as exc:
        _launch(host, request)  # confirmation read #2 sees workflow:blocked
    assert any(e["code"] == "workflow_ready" for e in exc.value.errors)
    assert launcher.calls == []


def test_full_chain_stale_mandate_rejected_when_issue_changed():
    """The Issue text changed between preview and confirmation (still eligible
    on paper, but a different mandate): the request snapshot id no longer
    matches, so the confirmed launch is rejected as stale."""
    state = {"reads": 0}

    def reader(repo, number):
        state["reads"] += 1
        approval = (CLAIM_APPROVAL if state["reads"] == 1 else
                    "Operator approved a DIFFERENT scope and limits on 2026-08-30.")
        return _issue(number, approval=approval)

    host, launcher = _chain(reader)
    request = _confirm(host)  # preview of the original mandate
    with pytest.raises(StaleDispatchDenied):
        _launch(host, request)  # confirmation sees the changed mandate
    assert launcher.calls == []


def test_full_chain_approval_mismatch_rejected():
    host, launcher = _chain(lambda repo, number: _issue(number))
    request = _confirm(host)
    with pytest.raises(AuthorizationFailure, match="approval reference"):
        host.execute(action_id="claim-run", issue_id="owner/repo#471",
                     approval_ref="not-the-issue-approval",
                     request_id=request["request_id"],
                     confirm=True, token="test-token")
    assert launcher.calls == []


# --- HTTP layer: the real POST /api/action route, end to end ----------------

def test_full_chain_http_double_click_returns_409_with_recovery():
    state = {"launched": False}

    def reader(repo, number):
        labels = ([{"name": "workflow:in-progress"}, {"name": "background-task"}]
                  if state["launched"] else None)
        return _issue(number, labels=labels)

    launcher = _GateLauncher()
    resume = partial(gh_claim_run_resume, registry=Path("unused-runs.json"),
                     scripts_dir=SCRIPTS_DIR, issue_reader=reader, launcher=launcher)
    host = ActionHost(issue_reader=reader, resume=resume, token="test-token")
    httpd = _ReusableThreadingHTTPServer(("127.0.0.1", 0), _make_handler(host))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/api/dispatch-request?issue=owner/repo%23471", timeout=10) as resp:
            request = json.loads(resp.read().decode("utf-8"))
        assert request["eligible"] is True

        def post(payload):
            req = urllib.request.Request(
                f"{base}/api/action", method="POST",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Cortxt-Token": "test-token"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

        payload = {"action_id": "claim-run", "issue_id": "owner/repo#471",
                   "approval_ref": request["approval_reference"],
                   "request_id": request["request_id"], "confirm": True}
        status, body = post(payload)
        assert status == 200 and body["status"] == "ok"

        state["launched"] = True
        status, body = post(payload)  # double click
        assert status == 409
        assert body["error"]["kind"] == "dispatch_request_denied"
        assert body["error"]["code"] == "dispatch_request_not_eligible"
        assert any(e["code"] == "workflow_ready" for e in body["error"]["errors"])
        assert body["error"]["errors"][0]["recovery"]
        assert len(launcher.calls) == 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
