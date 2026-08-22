"""Injected CLI port with no widget-supplied command text."""

from typing import Any, Callable, Mapping


def registered_cli(call: Callable[[str, Mapping[str, Any]], Any], operation: str, request: Mapping[str, Any]) -> Any:
    return call(operation, dict(request))
