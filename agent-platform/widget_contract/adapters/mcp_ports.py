"""Injected MCP port with no widget-supplied tool selection."""

from typing import Any, Callable, Mapping


def registered_mcp(call: Callable[[str, Mapping[str, Any]], Any], operation: str, request: Mapping[str, Any]) -> Any:
    return call(operation, dict(request))
