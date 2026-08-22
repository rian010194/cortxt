"""Platform-owned primitive rendering helpers."""

from typing import Any, Mapping


def render_primitive(name: str, props: Mapping[str, Any], children: list[Any], state: str = "ready") -> dict[str, Any]:
    """Return a deterministic data-only primitive representation."""
    result: dict[str, Any] = {"primitive": name, "state": state, "props": dict(sorted(props.items()))}
    if children:
        result["children"] = children
    return result
