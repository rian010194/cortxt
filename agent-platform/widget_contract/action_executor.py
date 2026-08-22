"""Authorized dispatch to injected registered action adapters."""

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .models import Action
from .registry import ACTIONS
from .validation import validate


class AuthorizationDenied(PermissionError):
    pass


@dataclass(frozen=True)
class ActionContext:
    authorization_reference: str
    approved_operations: frozenset[str]


class ActionExecutor:
    def __init__(self, adapters: Mapping[str, Callable[[str, Mapping[str, Any]], Any]], authorize: Callable[[Action, ActionContext], bool]) -> None:
        self._adapters = dict(adapters)
        self._authorize = authorize

    def execute(self, action: Action, context: ActionContext) -> Any:
        """Recheck current authorization immediately before injected dispatch."""
        entry = ACTIONS.get(action.operation)
        if entry is None or entry.port != action.port:
            raise AuthorizationDenied("action is not registered")
        if action.authorization.get("reference") != context.authorization_reference or action.operation not in context.approved_operations:
            raise AuthorizationDenied("authorization scope does not match")
        if not self._authorize(action, context):
            raise AuthorizationDenied("authorization is not current")
        adapter = self._adapters.get(action.port)
        if adapter is None:
            raise AuthorizationDenied("action port is disabled")
        validate(dict(action.input), entry.input_schema)
        return adapter(action.operation, dict(action.input))
