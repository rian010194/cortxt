from pathlib import Path

import pytest

from widget_contract.action_executor import ActionContext, ActionExecutor, AuthorizationDenied
from widget_contract.models import Action
from widget_contract.registry import ACTIONS, ActionEntry


def _action():
    return Action("advance", "github-transition", "test.transition.v1", {"issue_number": 259}, {"mode": "operator", "reference": "approval-1"}, {"summary": "Advance", "effect_class": "workflow-transition", "required": True}, "action.status.v1", "once-259")


def test_action_executor_rechecks_authorization_and_fails_closed(monkeypatch):
    entry = ActionEntry("github-transition", {"type": "object", "additionalProperties": False, "required": ["issue_number"], "properties": {"issue_number": {"type": "integer"}}}, "action.status.v1", "workflow-transition", frozenset({"operator"}), "act:transition", True)
    monkeypatch.setitem(ACTIONS, "test.transition.v1", entry)
    calls = []
    executor = ActionExecutor({"github-transition": lambda operation, request: calls.append((operation, request)) or {"status": "ok"}}, lambda action, context: False)
    context = ActionContext("approval-1", frozenset({"test.transition.v1"}))
    with pytest.raises(AuthorizationDenied, match="not current"):
        executor.execute(_action(), context)
    assert calls == []


def test_action_executor_dispatches_only_injected_registered_port(monkeypatch):
    entry = ActionEntry("github-transition", {"type": "object", "additionalProperties": False, "required": ["issue_number"], "properties": {"issue_number": {"type": "integer"}}}, "action.status.v1", "workflow-transition", frozenset({"operator"}), "act:transition", True)
    monkeypatch.setitem(ACTIONS, "test.transition.v1", entry)
    calls = []
    executor = ActionExecutor({"github-transition": lambda operation, request: calls.append((operation, request)) or {"status": "ok"}}, lambda action, context: True)
    result = executor.execute(_action(), ActionContext("approval-1", frozenset({"test.transition.v1"})))
    assert result == {"status": "ok"}
    assert calls == [("test.transition.v1", {"issue_number": 259})]


def test_existing_widget_host_remains_loopback_static_and_default_files_exist():
    widget_dir = Path(__file__).resolve().parents[2] / "widget"
    source = (widget_dir / "serve.py").read_text(encoding="utf-8")
    assert 'HOST = "127.0.0.1"' in source
    assert "SimpleHTTPRequestHandler" in source
    assert "do_POST" not in source
    assert (widget_dir / "index.html").is_file()
    assert (widget_dir / "snapshot.json").is_file()


def test_first_actions_are_registered_with_operator_gate():
    from widget_contract.registry import ALLOWED_CAPABILITIES, ACTIONS
    mark = ACTIONS["workflow.mark-ready.v1"]
    assert (mark.port, mark.effect_class, mark.capability) == (
        "github-transition", "workflow-transition", "act:mark-ready")
    assert mark.authorization_modes == frozenset({"operator"}) and mark.retryable
    claim = ACTIONS["workflow.claim-run.v1"]
    assert (claim.port, claim.effect_class, claim.capability) == (
        "cli", "run-dispatch", "act:claim-run")
    assert claim.authorization_modes == frozenset({"operator"}) and claim.retryable
    assert {"act:mark-ready", "act:claim-run"} <= set(ALLOWED_CAPABILITIES)


def test_spec_declaring_actions_loads_and_wrong_action_fails():
    from widget_contract.loader import ContractError, load_widget
    spec = {
        "contract_version": "0.1",
        "widget": {"id": "ops", "version": "1.0.0", "title": "Operations"},
        "data": {"reads": []},
        "render": {"primitive": "stack", "children": []},
        "actions": [{
            "id": "mark-ready", "port": "github-transition", "operation": "workflow.mark-ready.v1",
            "input": {"issue_id": "owner/repo#1"},
            "authorization": {"mode": "operator", "reference": "approval-1"},
            "confirm": {"summary": "Advance", "effect_class": "workflow-transition", "required": True},
            "result_type": "action.status.v1", "idempotency_key": "once-1",
        }],
        "capabilities": ["act:mark-ready"],
    }
    widget = load_widget(spec)
    assert widget.actions[0].id == "mark-ready" and widget.actions[0].port == "github-transition"
    bad = {**spec, "actions": [{
        "id": "mark-ready", "port": "cli", "operation": "workflow.mark-ready.v1",
        "input": {"issue_id": "owner/repo#1"},
        "authorization": {"mode": "operator", "reference": "approval-1"},
        "confirm": {"summary": "Advance", "effect_class": "workflow-transition", "required": True},
        "result_type": "action.status.v1", "idempotency_key": "once-1",
    }]}
    with pytest.raises(ContractError, match="mismatched action"):
        load_widget(bad)


def test_mark_ready_adapter_is_exact_and_never_chains():
    from widget_contract.adapters.github_ports import TransitionDenied, mark_ready_transition
    calls = []

    def reader(issue_id):
        calls.append(("read", issue_id))
        return {"issue_id": issue_id, "labels": [{"name": "workflow:inbox"}]}

    def transition(operation, request):
        calls.append(("transition", operation, request["issue_id"]))
        return {"operation": operation, "issue_id": request["issue_id"], "status": "ok"}

    result = mark_ready_transition("workflow.mark-ready.v1", {"issue_id": "owner/repo#1"},
                                   issue_reader=reader, transition=transition)
    assert result["status"] == "ok"
    assert calls == [("read", "owner/repo#1"), ("transition", "workflow.mark-ready.v1", "owner/repo#1")]

    calls.clear()
    with pytest.raises(TransitionDenied, match="workflow:inbox"):
        mark_ready_transition("workflow.mark-ready.v1", {"issue_id": "owner/repo#2"},
                              issue_reader=lambda i: {"issue_id": i, "labels": [{"name": "workflow:blocked"}]},
                              transition=lambda o, r: calls.append(("TRANSITION",)))
    assert calls == []


def test_claim_run_adapter_routes_only_through_injected_launcher():
    from widget_contract.adapters.cli_ports import ClaimRunDenied, claim_run_via_launcher
    calls = []
    result = claim_run_via_launcher("workflow.claim-run.v1", {"issue_id": "owner/repo#3"},
                                    resume=lambda issue_id: calls.append(issue_id) or {"run_id": "run-3", "issue_id": issue_id})
    assert result["run_id"] == "run-3" and calls == ["owner/repo#3"]
    with pytest.raises(ClaimRunDenied):
        claim_run_via_launcher("workflow.claim-run.v1", {"issue_id": ""}, resume=lambda i: {"run_id": "x"})


def test_claim_run_gate_error_propagates_stable_code():
    from widget_contract.adapters.cli_ports import claim_run_via_launcher

    class GateError(RuntimeError):
        def __init__(self, code):
            self.code = code
            super().__init__(code)

    def gated(issue_id):
        raise GateError("resource_collision")

    with pytest.raises(GateError, match="resource_collision"):
        claim_run_via_launcher("workflow.claim-run.v1", {"issue_id": "owner/repo#4"}, resume=gated)


def test_cli_action_confirm_and_authorization_fail_closed(monkeypatch):
    from argparse import Namespace
    from cli.unified_cli import _run_widget_action
    from widget_contract.action_executor import AuthorizationDenied

    # Without --confirm the authorize callback denies before any adapter side effect.
    monkeypatch.setattr("cli.unified_cli._gh_issue_workflow_labels", lambda issue_id: ["workflow:inbox"])
    monkeypatch.setattr("cli.unified_cli._gh_inbox_to_ready", lambda issue_id: {"status": "ok"})
    result = _run_widget_action(Namespace(widget_command="action", action_id="mark-ready", repo="owner/repo",
                                          issue=1, approval_ref="approval-1", confirm=False))
    assert result.status == "failed" and result.error["category"] == "authorization_denied"


def test_cli_action_mark_ready_succeeds_with_confirm_and_injected_gh(monkeypatch, capsys):
    from argparse import Namespace
    from cli.unified_cli import _run_widget_action
    calls = []
    monkeypatch.setattr("cli.unified_cli._gh_issue_workflow_labels", lambda issue_id: calls.append(("read", issue_id)) or ["workflow:inbox"])
    monkeypatch.setattr("cli.unified_cli._gh_inbox_to_ready", lambda issue_id: calls.append(("write", issue_id)) or {"issue_id": issue_id, "status": "ok"})
    result = _run_widget_action(Namespace(widget_command="action", action_id="mark-ready", repo="owner/repo",
                                          issue=5, approval_ref="approval-1", confirm=True))
    capsys.readouterr()
    assert result.status == "succeeded" and result.issue_id == "owner/repo#5"
    assert ("read", "owner/repo#5") in calls and ("write", "owner/repo#5") in calls
    assert len([c for c in calls if c[0] == "write"]) == 1


def test_cli_action_claim_run_reports_execution_map_gate_code(monkeypatch):
    from argparse import Namespace
    from cli.unified_cli import _run_widget_action

    class ExecutionGateError(RuntimeError):
        def __init__(self, code):
            self.code = code
            super().__init__(code)

    def gated(issue_id, *, registry):
        raise ExecutionGateError("issue_not_ready")

    monkeypatch.setattr("cli.unified_cli._claim_run_resume", gated)
    result = _run_widget_action(Namespace(widget_command="action", action_id="claim-run", repo="owner/repo",
                                          issue=6, approval_ref="approval-1", confirm=True, registry=None))
    assert result.status == "failed" and result.error["category"] == "execution_map_gate"
    assert result.error["code"] == "issue_not_ready"
