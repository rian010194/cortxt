"""Terminal UI (TUI) renderer for widget render trees using shared visual tokens."""

from __future__ import annotations

import sys
from typing import Any, Mapping, Sequence

from widget_contract.chart_text import render_bar_gauge, render_line_spark
from widget_contract.swimlane_text import render_swimlane_text
from widget_contract.tokens import DEFAULT_ANSI_MAP, ansi_map, load_tokens


def _get_colors(tokens: Mapping[str, Any] | None, force_ansi: bool | None) -> dict[str, str]:
    """Determine the active ANSI color map based on tokens and TTY/force settings."""
    if force_ansi is True:
        use_ansi = True
    elif force_ansi is False:
        use_ansi = False
    else:
        use_ansi = bool(getattr(sys.stdout, "isatty", lambda: False)())

    if not use_ansi:
        return {k: "" for k in DEFAULT_ANSI_MAP}

    return ansi_map(tokens)


def _c(name: str, text: str, colors: Mapping[str, str]) -> str:
    """Wrap text in color escape codes if the color exists and is non-empty."""
    code = colors.get(name, "")
    reset = colors.get("reset", "")
    if not code or not text:
        return text
    return f"{code}{text}{reset}"


def colorize_status(val: Any, colors: Mapping[str, str]) -> str:
    """Colorize status values according to visual tokens (ok=green, warn=yellow, bad=red, muted=dim)."""
    if val is None:
        return _c("muted", "-", colors)
    if isinstance(val, bool):
        return _c("ok" if val else "bad", str(val).lower(), colors)

    s = str(val)
    s_lower = s.lower().strip()
    if s_lower in ("ok", "running", "fresh", "ready", "true", "active", "completed", "success", "succeeded", "workflow:ready"):
        return _c("ok", s, colors)
    elif s_lower in ("warn", "warning", "stale", "attention", "pending", "paused", "workflow:inbox", "workflow:in-progress"):
        return _c("warn", s, colors)
    elif s_lower in ("bad", "error", "failed", "blocked", "false", "inactive", "denied", "workflow:blocked") or "violation" in s_lower:
        return _c("bad", s, colors)
    elif s_lower in ("muted", "idle", "none", "null", "-", "n/a", "no"):
        return _c("muted", s, colors)
    return s


def _is_status_field(col_name: str, val: Any) -> bool:
    """Check if a table column or value should be status-colorized."""
    if isinstance(val, bool):
        return True
    col_lower = str(col_name).lower().strip()
    if any(k in col_lower for k in ("status", "state", "active", "launchable", "stage", "workflow")):
        return True
    s_lower = str(val).lower().strip()
    return s_lower in (
        "ok", "warn", "bad", "fresh", "stale", "error", "running", "blocked",
        "attention", "ready", "denied", "idle", "true", "false", "active",
        "inactive", "workflow:ready", "workflow:inbox", "workflow:in-progress", "workflow:blocked",
    ) or "violation" in s_lower


def _render_node(node: Mapping[str, Any], colors: Mapping[str, str], depth: int = 0) -> list[str]:
    """Recursively render a render-tree node into formatted lines."""
    primitive = node.get("primitive", "")
    props = node.get("props", {})
    state = node.get("state", "ready")
    children = node.get("children", [])

    lines: list[str] = []

    # Handle error / empty states
    if state == "error" and primitive != "error-state":
        err_msg = props.get("error") or props.get("message") or "Component error"
        return [f"  {_c('bad', f'[error] {err_msg}', colors)}"]

    if primitive in ("stack", "row", "grid", "tabs", "panel"):
        label = props.get("label")
        if label:
            lines.append(_c("strong", f"=== {label} ===", colors))
        for child in children:
            child_lines = _render_node(child, colors, depth + 1)
            if child_lines:
                if lines and lines[-1] != "":
                    lines.append("")
                lines.extend(child_lines)
        return lines

    if primitive == "heading":
        val = props.get("value") or props.get("label", "")
        lines.append(_c("strong", f"## {val}", colors))
        return lines

    if primitive == "text":
        label = props.get("label")
        val = props.get("value", "")
        if label:
            lines.append(f"{_c('dim', str(label) + ':', colors)} {val}")
        else:
            lines.append(str(val))
        return lines

    if primitive == "badge":
        val = props.get("value") or props.get("label", "")
        colored_val = colorize_status(val, colors)
        lines.append(f"[{colored_val}]")
        return lines

    if primitive == "timestamp":
        label = props.get("label")
        val = props.get("value", "")
        if label:
            lines.append(f"{_c('dim', str(label) + ':', colors)} {_c('dim', str(val), colors)}")
        else:
            lines.append(_c("dim", str(val), colors))
        return lines

    if primitive == "metric":
        label = props.get("label", "Metric")
        val = props.get("value", "-")
        lines.append(f"{_c('accent', str(label) + ':', colors)} {_c('strong', str(val), colors)}")
        return lines

    if primitive == "key-value":
        val_obj = props.get("value")
        if isinstance(val_obj, Mapping):
            for k, v in val_obj.items():
                if isinstance(v, Mapping):
                    lines.append(f"  {_c('dim', str(k) + ':', colors)}")
                    for sub_k, sub_v in v.items():
                        colored_v = colorize_status(sub_v, colors) if _is_status_field(str(sub_k), sub_v) else str(sub_v)
                        lines.append(f"    {_c('dim', str(sub_k) + ':', colors)} {colored_v}")
                elif isinstance(v, list):
                    list_str = ", ".join(str(x) for x in v) if v else "-"
                    lines.append(f"  {_c('dim', str(k) + ':', colors)} {list_str}")
                else:
                    colored_v = colorize_status(v, colors) if _is_status_field(str(k), v) else str(v)
                    lines.append(f"  {_c('dim', str(k) + ':', colors)} {colored_v}")
        elif val_obj is not None:
            lines.append(f"  {val_obj}")
        return lines

    if primitive == "table":
        label = props.get("label")
        if label:
            lines.append(_c("strong", f"[{label}]", colors))
        columns = list(props.get("columns", []))
        rows = props.get("rows", [])
        if not rows:
            empty_msg = props.get("empty", "No entries")
            lines.append(f"  {_c('dim', f'({empty_msg})', colors)}")
            return lines

        if not columns and isinstance(rows[0], Mapping):
            columns = list(rows[0].keys())

        # Build clean string representations of all cells
        formatted_rows: list[dict[str, str]] = []
        for row in rows:
            row_dict: dict[str, str] = {}
            for col in columns:
                if isinstance(row, Mapping):
                    raw_val = row.get(col, "")
                else:
                    raw_val = getattr(row, col, "")
                if isinstance(raw_val, Sequence) and not isinstance(raw_val, (str, bytes)):
                    cell_str = ", ".join(str(x) for x in raw_val) if raw_val else "-"
                elif raw_val is None:
                    cell_str = "-"
                elif isinstance(raw_val, bool):
                    cell_str = str(raw_val).lower()
                else:
                    cell_str = str(raw_val)
                row_dict[col] = cell_str
            formatted_rows.append(row_dict)

        # Compute column widths
        col_widths: dict[str, int] = {}
        for col in columns:
            header_w = len(str(col))
            max_cell_w = max((len(r[col]) for r in formatted_rows), default=0)
            col_widths[col] = max(header_w, max_cell_w)

        # Build header and separator lines
        header_cells = [str(col).ljust(col_widths[col]) for col in columns]
        sep_cells = ["-" * col_widths[col] for col in columns]
        lines.append("  " + _c("dim", "  ".join(header_cells), colors))
        lines.append("  " + _c("dim", "  ".join(sep_cells), colors))

        # Build data row lines
        for r in formatted_rows:
            row_cells: list[str] = []
            for col in columns:
                raw_text = r[col]
                if _is_status_field(col, raw_text):
                    cell_colored = colorize_status(raw_text, colors)
                else:
                    cell_colored = raw_text
                pad = " " * max(0, col_widths[col] - len(raw_text))
                row_cells.append(cell_colored + pad)
            lines.append("  " + "  ".join(row_cells))
        return lines

    if primitive == "list":
        label = props.get("label")
        if label:
            lines.append(_c("strong", f"{label}:", colors))
        items = props.get("items", [])
        if not items:
            empty_msg = props.get("empty", "No items")
            lines.append(f"  {_c('dim', f'({empty_msg})', colors)}")
        else:
            for item in items:
                if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
                    item_str = ", ".join(str(x) for x in item)
                else:
                    item_str = str(item)
                lines.append(f"  • {item_str}")
        return lines

    if primitive == "empty-state":
        message = props.get("message", "No data")
        lines.append(f"  {_c('dim', f'(empty) {message}', colors)}")
        return lines

    if primitive == "error-state":
        message = props.get("message", "Error")
        lines.append(f"  {_c('bad', f'[error] {message}', colors)}")
        return lines

    if primitive == "swimlane":
        items = props.get("items", [])
        label = props.get("label", "")
        lines.append(render_swimlane_text(items, label=label, colors=colors))
        return lines

    if primitive == "bar":
        label = props.get("label", "")
        value = props.get("value", 0)
        max_value = props.get("max_value", 100)
        width = props.get("width", 10)
        lines.append(render_bar_gauge(label, value, max_value=max_value, width=width, colors=colors))
        return lines

    if primitive == "line":
        points = props.get("points") or props.get("items", [])
        label = props.get("label", "")
        width = props.get("width", 20)
        lines.append(render_line_spark(points, label=label, width=width, colors=colors))
        return lines

    if primitive == "divider":
        lines.append(_c("dim", "------------------------------------------------------------", colors))
        return lines

    if primitive == "spacer":
        lines.append("")
        return lines

    if primitive in ("button", "choice"):
        label = props.get("label", "Action")
        lines.append(f"[{_c('accent', str(label), colors)}]")
        return lines

    # Fallback for generic node
    if props:
        lines.append(str(props))
    return lines


def render_tui(
    tree: Mapping[str, Any] | Any,
    tokens: Mapping[str, Any] | None = None,
    force_ansi: bool | None = None,
) -> str:
    """Render a widget render tree into styled terminal text using shared visual tokens.

    Parameters:
        tree: The render tree dictionary (either full envelope with 'render' or bare node).
        tokens: Optional visual tokens mapping. If omitted, default tokens are loaded.
        force_ansi: If True, force ANSI codes. If False, suppress ANSI codes.
                    If None, auto-detect based on whether stdout is a TTY.

    Returns:
        Formatted terminal UI text string.
    """
    if tokens is None:
        try:
            tokens = load_tokens()
        except Exception:
            tokens = None

    colors = _get_colors(tokens, force_ansi)

    if isinstance(tree, Mapping) and "render" in tree:
        node = tree["render"]
    else:
        node = tree

    if not isinstance(node, Mapping) or "primitive" not in node:
        return str(tree)

    lines = _render_node(node, colors)
    return "\n".join(lines)
