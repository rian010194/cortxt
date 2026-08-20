"""Live per-agent pipeline view: `cortxt pipeline` / `cortxt pipeline --watch`.

Renders the same workstream/lane projection `cli.status` builds (one lane
per agent session) as progress bars instead of a static table, and can
redraw on an interval for a live watch.

Progress here is *indeterminate* -- the domain has no numeric
percent-complete signal for a running agent session, only a status
(running/succeeded/failed/blocked/abandoned/timed_out). A running lane gets a
moving scanner block instead of a fill percentage, so the bar communicates
"this is alive and being redrawn," not a fabricated completion estimate.
"""
from __future__ import annotations

import time
from typing import Any, Callable

# Terminal statuses render as a full bar, distinguished by fill character.
_TERMINAL_FILL = {
    "succeeded": "#",
    "failed": "!",
    "timed_out": "!",
}


def render_lane_bar(status: str, frame: int, *, width: int = 20) -> str:
    """Render one lane's `[bar] status` fragment.

    Deterministic given (status, frame, width) so it's unit-testable without
    real time passing. `frame` only matters for "running" -- it moves the
    scanner block one position per redraw, wrapping at `width`.
    """
    if status in _TERMINAL_FILL:
        fill = _TERMINAL_FILL[status]
        return f"[{fill * width}] {status}"
    if status == "blocked":
        half = width // 2
        return f"[{'?' * half}{' ' * (width - half)}] blocked"
    if status == "abandoned":
        return f"[{'.' * width}] abandoned"
    # running, or any other in-flight status: indeterminate scanner.
    bar = [" "] * width
    if width:
        bar[frame % width] = "#"
    return f"[{''.join(bar)}] running"


def render_frame(
    summary: dict[str, Any],
    workstreams: list[dict[str, Any]],
    *,
    frame: int = 0,
    width: int = 20,
) -> str:
    """Render one full screen: header + one block of lane bars per workstream."""
    lines = [
        f"CORTXT PIPELINE -- {summary.get('status', 'idle')} ({summary.get('message', '')})",
        "=" * 72,
    ]
    if not workstreams:
        lines.append("No workstreams found.")
        return "\n".join(lines)
    for workstream in workstreams:
        lines.append(f"{workstream['workstream_id']} [{workstream['status']}]")
        for lane in workstream.get("lanes", []):
            bar = render_lane_bar(lane.get("status", "running"), frame, width=width)
            lines.append(f"  {lane.get('label', 'agent'):<12} {bar}")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def run_watch(
    collect: Callable[[], tuple[dict[str, Any], list[dict[str, Any]]]],
    *,
    interval: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    clear_fn: Callable[[], None] | None = None,
    out: Callable[[str], None] = print,
    max_iterations: int | None = None,
    width: int = 20,
) -> int:
    """Redraw `render_frame` on an interval until interrupted or `max_iterations` is hit.

    `collect` is called fresh every iteration so a live watch reflects new
    session activity as it happens -- it returns (summary, workstreams),
    the same shape `_collect_orchestrator_projection` produces.
    `sleep_fn`/`clear_fn`/`out` are injected so this loop is testable
    without a real terminal or real time passing: tests pass call-counting
    fakes and cap `max_iterations`. A `KeyboardInterrupt` (Ctrl+C, the
    normal way an operator leaves watch mode) is caught and ends the loop
    cleanly instead of printing a traceback. Returns the number of frames
    drawn.
    """
    frame = 0
    iterations = 0
    try:
        while max_iterations is None or iterations < max_iterations:
            summary, workstreams = collect()
            if clear_fn is not None:
                clear_fn()
            out(render_frame(summary, workstreams, frame=frame, width=width))
            iterations += 1
            frame += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            sleep_fn(interval)
    except KeyboardInterrupt:
        out("\nStopped.")
    return iterations
