"""Swimlane text renderer for terminal and TUI fallback (#345, #347).

Provides both node-based multi-lane rendering and item-list rendering with
optional visual token colors for CLI/TUI surfaces.
"""
from __future__ import annotations

from typing import Any, Mapping


def _format_item(item: Any) -> str:
    if isinstance(item, Mapping):
        title = str(item.get("title") or item.get("label") or item.get("name") or item.get("id") or "task")
        state = str(item.get("state") or item.get("status") or "")
        is_active = bool(item.get("active")) or state.lower() == "running"
        if is_active:
            return f"{title} \u25cf"
        return title
    return str(item)


def render_swimlane_lanes(node: Mapping[str, Any]) -> str:
    """Render a swimlane node to plain text for terminal/TUI fallback.

    Contract:
      - Header with label / columns when present
      - Each lane rendered as: `<label> | <item1> <item2 \u25cf> ...` (\u25cf = active)
      - Empty state when no rows are available
    """
    props = node.get("props") if isinstance(node, Mapping) and "props" in node and isinstance(node["props"], Mapping) else node
    if not isinstance(props, Mapping):
        return "No swimlane data."

    label = props.get("label")
    columns = props.get("columns")
    rows = props.get("rows")
    empty_msg = str(props.get("empty") or "No lanes.")

    lines: list[str] = []

    if label:
        lines.append(str(label))

    if columns and isinstance(columns, list):
        col_header = " | ".join(str(c) for c in columns)
        lines.append(col_header)
        lines.append("-" * max(len(col_header), 20))

    if not rows or not isinstance(rows, list):
        lines.append(empty_msg)
        return "\n".join(lines)

    for row in rows:
        if not isinstance(row, Mapping):
            lines.append(str(row))
            continue
        lane_label = str(row.get("label") or row.get("name") or row.get("id") or "Lane")
        items_raw = row.get("items") or row.get("tasks") or []
        if isinstance(items_raw, list) and items_raw:
            items_str = " ".join(_format_item(item) for item in items_raw)
            lines.append(f"{lane_label} | {items_str}")
        else:
            lines.append(f"{lane_label} | (idle)")

    return "\n".join(lines)


def render_swimlane_items(
    items: list[Mapping[str, Any]] | list[Any],
    label: str = "",
    colors: Mapping[str, str] | None = None,
) -> str:
    """Render swimlane items as formatted text with visual token colors.

    Format:
        [label | ]item1 ●  item2 ○  item3 ✖

    Parameters:
        items: List of item dictionaries (with label/name/id and active/status) or strings.
        label: Optional prefix label for the swimlane.
        colors: Optional mapping of color names to ANSI escape codes.

    Returns:
        Formatted swimlane line.
    """
    col_map = colors or {}
    accent = col_map.get("accent", "")
    ok = col_map.get("ok", "")
    warn = col_map.get("warn", "")
    bad = col_map.get("bad", "")
    dim = col_map.get("dim", "")
    reset = col_map.get("reset", "")

    rendered_items: list[str] = []
    for item in items:
        if isinstance(item, Mapping):
            name = str(item.get("label") or item.get("name") or item.get("id") or item.get("workstream_id") or "item")
            active = item.get("active")
            status = str(item.get("status", "")).lower()
            if active is True or status in ("running", "active", "open"):
                marker = f"{accent}●{reset}" if accent else "●"
            elif active is False or status in ("closed", "done", "completed", "idle"):
                marker = f"{dim}○{reset}" if dim else "○"
            elif status in ("blocked", "failed", "error"):
                marker = f"{bad}✖{reset}" if bad else "✖"
            elif status in ("warn", "warning", "attention", "pending"):
                marker = f"{warn}▲{reset}" if warn else "▲"
            else:
                # "ok" (and any other unmatched status) is its own structural
                # shape -- a filled diamond -- so it never collides with
                # "running"'s filled circle (issue #376: status roles must be
                # distinguishable by shape, not just color).
                marker = f"{ok}◆{reset}" if ok else "◆"
            rendered_items.append(f"{name} {marker}")
        else:
            rendered_items.append(str(item))

    joined = "  ".join(rendered_items) if rendered_items else "(empty)"
    if label:
        return f"{label} | {joined}"
    return joined


def render_swimlane_text(
    target: Any,
    label: str = "",
    colors: Mapping[str, str] | None = None,
) -> str:
    """Polymorphic swimlane text renderer.

    Supports both:
      - node Mapping (swimlane primitive node with rows/columns/props)
      - item list (list of swimlane items with optional label and colors)
    """
    if isinstance(target, Mapping):
        return render_swimlane_lanes(target)
    if isinstance(target, list):
        return render_swimlane_items(target, label=label, colors=colors)
    return "No swimlane data."


__all__ = [
    "render_swimlane_text",
    "render_swimlane_lanes",
    "render_swimlane_items",
]
