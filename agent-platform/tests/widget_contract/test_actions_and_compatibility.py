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
