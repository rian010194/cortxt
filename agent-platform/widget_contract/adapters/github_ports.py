"""Injected GitHub read and transition adapters."""

from typing import Any, Callable, Mapping

from ..registry import TYPES
from ..validation import validate


def issue_ready_list(call: Callable[[Mapping[str, Any]], Any], request: Mapping[str, Any]) -> dict[str, Any]:
    issues = call(dict(request))
    if not isinstance(issues, list):
        raise ValueError("issue adapter must return a list")
    allowed = ("number", "title", "state", "workflow")
    result = {"schema_version": 1, "issues": [{key: item[key] for key in allowed if key in item} for item in issues]}
    validate(result, TYPES["issues.ready.list.v1"].schema)
    return result


def registered_transition(call: Callable[[str, Mapping[str, Any]], Any], operation: str, request: Mapping[str, Any]) -> Any:
    return call(operation, dict(request))
