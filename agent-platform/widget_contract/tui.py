"""Terminal UI (TUI) renderer for widget render trees using shared visual tokens."""

from __future__ import annotations

import json
import sys
from typing import Any, Mapping, Sequence

from widget_contract.chart_text import render_bar_gauge, render_line_spark
from widget_contract.swimlane_text import render_swimlane_text
from widget_contract.tokens import DEFAULT_ANSI_MAP, ansi_map, load_preset_tokens, truecolor_ansi_map
from widget_contract.product_packaging.ops_api import OpsApiError, PackagingOpsApi
from widget_contract.product_packaging.revision import RevisionError, build_revision, revision_identity


def _get_colors(
    tokens: Mapping[str, Any] | None,
    force_ansi: bool | None,
    truecolor: bool = False,
) -> dict[str, str]:
    """Determine the active ANSI color map based on tokens and TTY/force settings."""
    if force_ansi is True:
        use_ansi = True
    elif force_ansi is False:
        use_ansi = False
    else:
        use_ansi = bool(getattr(sys.stdout, "isatty", lambda: False)())

    if not use_ansi:
        return {k: "" for k in DEFAULT_ANSI_MAP}

    if truecolor:
        return truecolor_ansi_map(tokens)

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
        rows = props.get("rows", [])
        items = props.get("items", [])
        label = props.get("label", "")
        if rows:
            # Multi-lane rendering: one line per lane with its items.
            for row in rows:
                lane_label = row.get("label") or row.get("name") or row.get("id") or "Lane"
                lane_items = row.get("items") or row.get("tasks") or []
                lane_line = lane_label
                for it in lane_items:
                    t = it.get("title") or it.get("name") or it.get("id") or "task"
                    state = str(it.get("state") or it.get("status") or "").lower()
                    if state in ("running", "active"):
                        mark = _c("glow_accent" if "glow_accent" in colors else "accent", "●", colors)
                    else:
                        mark = _c("dim", "○", colors)
                    lane_line += f"  {mark} {t}"
                lines.append(_c("strong", f"{lane_line}", colors))
            return lines
        lines.append(render_swimlane_text(items, label=label, colors=colors))
        return lines

    if primitive == "bar":
        if "values" in props:
            from widget_contract.chart_text import render_bar_text
            lines.append(render_bar_text(node))
        else:
            label = props.get("label", "")
            value = props.get("value", 0)
            max_value = props.get("max_value", 100)
            width = props.get("width", 10)
            lines.append(render_bar_gauge(label, value, max_value=max_value, width=width, colors=colors))
        return lines

    if primitive == "line":
        if "series" in props:
            from widget_contract.chart_text import render_line_text
            lines.append(render_line_text(node))
        else:
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
    truecolor: bool = False,
) -> str:
    """Render a widget render tree into styled terminal text using shared visual tokens.

    Parameters:
        tree: The render tree dictionary (either full envelope with 'render' or bare node).
        tokens: Optional visual tokens mapping. If omitted, default tokens are loaded.
        force_ansi: If True, force ANSI codes. If False, suppress ANSI codes.
                    If None, auto-detect based on whether stdout is a TTY.
        truecolor: If True, derive 24-bit ANSI codes directly from the token
                   hex values (requires a 24-bit-capable terminal).

    Returns:
        Formatted terminal UI text string.
    """
    if tokens is None:
        try:
            # Resolve which preset applies through the shared resolver
            # (widget_contract.theme_resolver -- session/persisted/default
            # precedence, issue #374) rather than always loading the fixed
            # v1 tokens.json, so `cortxt theme use <preset>` changes TUI
            # output consistently with every other surface (issue #376).
            from widget_contract.theme_resolver import ThemeResolverError, resolve_theme

            tokens = load_preset_tokens(resolve_theme())
        except ThemeResolverError as err:
            # A corrupted/invalid persisted theme preference should not
            # silently change the user's palette with no explanation --
            # surface it, then fall through to the built-in default tokens.
            print(f"warning: could not resolve theme preference ({err}); using default tokens", file=sys.stderr)
            tokens = None
        except Exception:
            tokens = None

    colors = _get_colors(tokens, force_ansi, truecolor=truecolor)

    if isinstance(tree, Mapping) and "render" in tree:
        node = tree["render"]
    else:
        node = tree

    if not isinstance(node, Mapping) or "primitive" not in node:
        return str(tree)

    lines = _render_node(node, colors)
    return "\n".join(lines)


class PackagingTuiSession:
    """Genuine interactive packaging lifecycle over the shared ops-API (W-3, #612).

    The pin's TUI (``render_tui`` above) is rendering-only; this session adds
    the client lifecycle that consumes the SAME shared ``PackagingOpsApi`` the
    web action host routes use, driven by real Core-store state:

    - ``workstream`` renders the kriterium-oracle Packaging Workstream
      (mandate/objective/scope/non-goals/repo-refs) from the shared
      projection -- the same dict the web route serves.
    - ``list``/``show`` are pure reads over the store.
    - ``create-revision`` and ``record-decision`` are interactive mutation
      flows: each shows what will be appended and requires typing an explicit
      confirmation phrase before calling the ops-API; the store's outcome
      envelope (appended / re-delivery / conflict) is rendered verbatim.
      Any validation error renders as an error line with no mutation.

    ``input_fn``/``output_fn`` are injectable so tests drive the lifecycle
    without a real terminal. No GitHub or network calls (ADR-048).
    """

    MUTATION_CONFIRM = "yes"
    HELP_TEXT = (
        "commands: help | workstream | list revisions|operations|decisions|evidence | "
        "show revision <identity-prefix> | create-revision | record-decision | quit")

    def __init__(self, ops_api: Any, *, input_fn: Any = None, output_fn: Any = None) -> None:
        if not isinstance(ops_api, PackagingOpsApi):
            raise ValueError("ops_api must be a PackagingOpsApi instance")
        self._api = ops_api
        self._input = input_fn or input
        self._output = output_fn or print

    # --- plumbing ---------------------------------------------------------

    def _emit(self, line: str) -> None:
        self._output(line)

    def _error(self, message: str) -> None:
        self._emit(f"[error] {message}")

    def _ask(self, prompt: str) -> str:
        raw = self._input(prompt)
        return raw.strip() if isinstance(raw, str) else str(raw).strip()

    def _confirm_mutation(self, summary_lines: list[str]) -> bool:
        self._emit("about to append to the Core store:")
        for line in summary_lines:
            self._emit(f"  {line}")
        answer = self._ask(f"type {self.MUTATION_CONFIRM!r} to confirm: ")
        return answer == self.MUTATION_CONFIRM

    # --- command loop -----------------------------------------------------

    def run(self) -> None:
        self._emit("Cortxt packaging TUI (W-3). " + self.HELP_TEXT)
        while True:
            try:
                line = self._ask("packaging> ")
            except (EOFError, KeyboardInterrupt):
                self._emit("bye")
                return
            if not line:
                continue
            head, _, rest = line.partition(" ")
            if head in ("quit", "exit"):
                self._emit("bye")
                return
            if head in ("help", "?"):
                self._emit(self.HELP_TEXT)
            elif head == "workstream":
                self._cmd_workstream()
            elif head == "list":
                self._cmd_list(rest.strip())
            elif head == "show":
                self._cmd_show(rest.strip())
            elif head == "create-revision":
                self._cmd_create_revision()
            elif head == "record-decision":
                self._cmd_record_decision()
            else:
                self._error(f"unknown command {head!r}; " + self.HELP_TEXT)

    # --- commands ---------------------------------------------------------

    def _cmd_workstream(self) -> None:
        projection = self._api.workstream()
        for line in self.render_workstream(projection["workstream"]):
            self._emit(line)

    def _cmd_list(self, what: str) -> None:
        try:
            if what == "revisions":
                views = self._api.list_revisions()
                self._emit(f"revisions: {len(views)}")
                for view in views:
                    parent = view["parent_revision_identity"]
                    parent_text = (parent[:12] + "…") if parent else "genesis"
                    self._emit(f"  {view['revision_identity'][:12]}  "
                               f"{view['package_id']}  parent={parent_text}  "
                               f"at={view['appended_at']}")
            elif what == "operations":
                views = self._api.list_operations()
                self._emit(f"operations: {len(views)}")
                for view in views:
                    self._emit(f"  {view['operation_id']}  {view['status']}  "
                               f"result={view['result_revision_identity'] or '-'}")
            elif what == "decisions":
                views = self._api.list_decisions()
                self._emit(f"decisions: {len(views)}")
                for view in views:
                    self._emit(f"  {view['decision_record_identity'][:12]}  "
                               f"{view['verdict']}  scope={view['decision_scope']}  "
                               f"operator={view['operator']}")
            elif what == "evidence":
                views = self._api.list_evidence()
                self._emit(f"evidence: {len(views)}")
                for view in views:
                    self._emit(f"  {view['entry_id']}  payload={view['payload_digest'][:12]}…")
            else:
                self._error("list what? revisions | operations | decisions | evidence")
        except OpsApiError as exc:
            self._error(f"{exc.kind}: {exc}")

    def _cmd_show(self, rest: str) -> None:
        parts = rest.split()
        if len(parts) != 2 or parts[0] != "revision":
            self._error("usage: show revision <identity-prefix>")
            return
        prefix = parts[1]
        try:
            revisions = self._api.list_revisions()
        except OpsApiError as exc:
            self._error(f"{exc.kind}: {exc}")
            return
        matches = [view for view in revisions
                   if view["revision_identity"].startswith(prefix)]
        if not matches:
            self._error(f"no revision matches prefix {prefix!r}")
            return
        if len(matches) > 1:
            self._error(f"ambiguous prefix {prefix!r}: {len(matches)} matches")
            return
        view = matches[0]
        self._emit(f"revision_identity: {view['revision_identity']}")
        self._emit(f"package_id: {view['package_id']}")
        self._emit(f"parent_revision_identity: {view['parent_revision_identity'] or '-'}")
        self._emit(f"record_digest: {view['record_digest']}")
        self._emit(f"appended_at: {view['appended_at']}")
        self._emit("content: " + json.dumps(view["revision"].get("content"),
                                            sort_keys=True, ensure_ascii=True))

    def _cmd_create_revision(self) -> None:
        try:
            package_id = self._ask("package_id: ")
            parent_text = self._ask("parent revision identity (blank for genesis): ")
            content_text = self._ask("content JSON: ")
            try:
                content = json.loads(content_text)
            except ValueError as exc:
                self._error(f"content is not valid JSON: {exc}")
                return
            revision = build_revision(package_id, content,
                                      parent_revision_identity=parent_text or None)
        except RevisionError as exc:
            self._error(str(exc))
            return
        except (EOFError, KeyboardInterrupt):
            self._emit("bye")
            return
        try:
            candidate = revision_identity(revision)
        except RevisionError as exc:
            self._error(str(exc))
            return
        if not self._confirm_mutation([
                f"action: packaging.create-revision",
                f"package_id: {package_id}",
                f"parent: {revision['parent_revision_identity'] or 'genesis'}",
                f"revision_identity: {candidate}"]):
            self._emit("aborted (not confirmed); nothing appended")
            return
        try:
            outcome = self._api.create_revision(revision)
        except OpsApiError as exc:
            self._error(f"{exc.kind}: {exc}")
            return
        self._render_outcome(outcome)

    def _cmd_record_decision(self) -> None:
        try:
            package_id = self._ask("package_id: ")
            revision_digest = self._ask("revision digest: ")
            decision_scope = self._ask("decision scope: ")
            operator = self._ask("operator: ")
            verdict = self._ask("verdict (accepted/rejected): ")
        except (EOFError, KeyboardInterrupt):
            self._emit("bye")
            return
        if not self._confirm_mutation([
                "action: packaging.record-decision",
                f"package_id: {package_id}",
                f"revision_digest: {revision_digest}",
                f"decision_scope: {decision_scope}",
                f"operator: {operator}",
                f"verdict: {verdict}"]):
            self._emit("aborted (not confirmed); nothing appended")
            return
        try:
            outcome = self._api.record_decision(
                package_id=package_id, revision_digest=revision_digest,
                decision_scope=decision_scope, operator=operator, verdict=verdict)
        except OpsApiError as exc:
            self._error(f"{exc.kind}: {exc}")
            return
        self._render_outcome(outcome)

    # --- rendering --------------------------------------------------------

    def _render_outcome(self, outcome: Mapping[str, Any]) -> None:
        self._emit(f"outcome: {outcome.get('outcome')}")
        self._emit(f"appended: {str(bool(outcome.get('appended'))).lower()}")
        self._emit(f"identity: {outcome.get('identity')}")
        self._emit(f"record_digest: {outcome.get('record_digest')}")
        if outcome.get("existing_record_digest"):
            self._emit(f"existing_record_digest: {outcome['existing_record_digest']}")
        if isinstance(outcome.get("conflict"), Mapping):
            conflict = outcome["conflict"]
            values = ", ".join(str(v) for v in conflict.get("values", []))
            self._emit(f"conflict: {conflict.get('field')} = [{values}]")

    def render_workstream(self, workstream: Mapping[str, Any]) -> list[str]:
        """Text projection of the Packaging Workstream (both-client oracle)."""
        lines = ["=== Packaging Workstream ==="]
        for field in ("id", "issue_id", "title"):
            lines.append(f"  {field}: {workstream.get(field, '')}")
        lines.append(f"  objective: {workstream.get('objective', '')}")
        lines.append(f"  mandate: {workstream.get('mandate', '')}")
        lines.append("  scope:")
        for item in workstream.get("scope", []):
            lines.append(f"    - {item}")
        lines.append("  non-goals:")
        for item in workstream.get("non_goals", []):
            lines.append(f"    - {item}")
        lines.append("  repo-refs:")
        for item in workstream.get("repo_refs", []):
            lines.append(f"    - {item}")
        return lines
