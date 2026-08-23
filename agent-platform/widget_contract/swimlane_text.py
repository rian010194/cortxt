"""Swimlane text renderer using visual tokens for terminal UI."""

from __future__ import annotations

from typing import Any, Mapping


def render_swimlane_text(
    items: list[Mapping[str, Any]] | list[Any],
    label: str = "",
    colors: Mapping[str, str] | None = None,
) -> str:
    """Render swimlane items as formatted text.

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
                marker = f"{ok}●{reset}" if ok else "●"
            rendered_items.append(f"{name} {marker}")
        else:
            rendered_items.append(str(item))

    joined = "  ".join(rendered_items) if rendered_items else "(empty)"
    if label:
        return f"{label} | {joined}"
    return joined
