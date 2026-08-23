"""TUI text fallback renderers for chart primitives (bar and line).

Provides compact ASCII/Unicode fallback representations for terminal environments.
"""

from __future__ import annotations

from typing import Any, Mapping


def _extract_props(node: Any) -> tuple[dict[str, Any], str]:
    """Extract props dictionary and state from dict or RenderNode."""
    if isinstance(node, dict):
        props = dict(node.get("props") or {})
        state = str(node.get("state") or "ready")
        return props, state
    if hasattr(node, "props"):
        props = dict(getattr(node, "props") or {})
        state = str(getattr(node, "state", "ready"))
        return props, state
    return {}, "empty"


def render_bar_text(node: Any, width: int = 20) -> str:
    """Render a bar chart node to a compact text representation.

    Example output:
        Tokens by runtime
        Hermes   |####################| 12,000
        Codex    |##############------| 8,500
        Claude   |#####---------------| 3,200
        DSH      |##------------------| 1,100
    """
    props, state = _extract_props(node)
    label = props.get("label") or "Bar Chart"
    if state in ("empty", "error") and not props.get("values"):
        empty_msg = props.get("empty") or (props.get("message") if state == "error" else "No data")
        return f"{label}: [{empty_msg}]"

    raw_values = props.get("values", [])
    if not isinstance(raw_values, list) or not raw_values:
        empty_msg = props.get("empty") or "No data"
        return f"{label}: [{empty_msg}]"

    categories = props.get("categories") or []
    items: list[tuple[str, float | int]] = []

    for i, item in enumerate(raw_values):
        cat_name = str(categories[i]) if i < len(categories) else ""
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            val = item
            name = cat_name or f"Item {i + 1}"
            items.append((name, val))
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("label") or item.get("model") or item.get("id") or cat_name or f"Item {i + 1}")
            val = item.get("tokens") or item.get("cost_usd") or item.get("value") or item.get("tokens_in", 0) + item.get("tokens_out", 0)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                items.append((name, val))

    if not items:
        empty_msg = props.get("empty") or "No data"
        return f"{label}: [{empty_msg}]"

    max_val = max((val for _, val in items), default=0)
    max_label_len = max(len(name) for name, _ in items)

    lines = [label]
    for name, val in items:
        if max_val > 0:
            filled_len = int(round((val / max_val) * width))
            filled_len = max(1 if val > 0 else 0, min(width, filled_len))
        else:
            filled_len = 0
        unfilled_len = width - filled_len
        bar_str = "#" * filled_len + "-" * unfilled_len
        val_str = f"{val:,.2f}" if isinstance(val, float) else f"{val:,}"
        lines.append(f"{name:<{max_label_len}}  |{bar_str}| {val_str}")

    return "\n".join(lines)


def render_line_text(node: Any) -> str:
    """Render a line chart node to a compact text sparkline/series representation.

    Example output:
        Usage over time
        Points: 10:00 -> 10:15 -> 10:30 -> 10:45 -> 11:00
        Values: 100 -> 250 -> 400 -> 600 -> 800
    """
    props, state = _extract_props(node)
    label = props.get("label") or "Line Chart"
    if state in ("empty", "error") and not props.get("series"):
        empty_msg = props.get("empty") or (props.get("message") if state == "error" else "No data")
        return f"{label}: [{empty_msg}]"

    raw_series = props.get("series", [])
    if not isinstance(raw_series, list) or not raw_series:
        empty_msg = props.get("empty") or "No data"
        return f"{label}: [{empty_msg}]"

    points = props.get("points") or []
    values: list[float | int] = []
    point_labels: list[str] = []

    for i, item in enumerate(raw_series):
        pt_name = str(points[i]) if i < len(points) else ""
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            values.append(item)
            point_labels.append(pt_name)
        elif isinstance(item, dict):
            pt_name = str(item.get("at") or item.get("point") or item.get("label") or pt_name or f"P{i + 1}")
            val = item.get("tokens") or item.get("cost_usd") or item.get("value", 0)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                values.append(val)
                point_labels.append(pt_name)

    if not values:
        empty_msg = props.get("empty") or "No data"
        return f"{label}: [{empty_msg}]"

    val_strs = [f"{v:,.2f}" if isinstance(v, float) else f"{v:,}" for v in values]
    lines = [label]
    if any(point_labels):
        pts_str = " -> ".join(p if p else "-" for p in point_labels)
        lines.append(f"Points: {pts_str}")
    lines.append(f"Series: {' -> '.join(val_strs)}")

    return "\n".join(lines)
