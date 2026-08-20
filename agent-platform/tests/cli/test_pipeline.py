from __future__ import annotations

from cli import pipeline


def test_render_lane_bar_succeeded_is_a_full_bar():
    bar = pipeline.render_lane_bar("succeeded", 0, width=10)
    assert bar == "[##########] succeeded"


def test_render_lane_bar_failed_is_a_full_bar_with_error_marker():
    bar = pipeline.render_lane_bar("failed", 0, width=10)
    assert bar == "[!!!!!!!!!!] failed"


def test_render_lane_bar_timed_out_uses_same_marker_as_failed():
    assert pipeline.render_lane_bar("timed_out", 0, width=4) == "[!!!!] timed_out"


def test_render_lane_bar_blocked_is_half_filled():
    bar = pipeline.render_lane_bar("blocked", 0, width=10)
    assert bar == "[?????     ] blocked"


def test_render_lane_bar_abandoned_is_dotted():
    bar = pipeline.render_lane_bar("abandoned", 0, width=5)
    assert bar == "[.....] abandoned"


def test_render_lane_bar_running_is_a_scanner_that_moves_with_frame():
    frame0 = pipeline.render_lane_bar("running", 0, width=5)
    frame1 = pipeline.render_lane_bar("running", 1, width=5)
    frame5 = pipeline.render_lane_bar("running", 5, width=5)

    assert frame0 == "[#    ] running"
    assert frame1 == "[ #   ] running"
    # frame wraps around the bar width instead of indexing out of range
    assert frame5 == frame0


def test_render_lane_bar_has_no_ansi_codes_by_default():
    bar = pipeline.render_lane_bar("succeeded", 0, width=10)
    assert bar == "[##########] succeeded"
    assert "\033[" not in bar


def test_render_lane_bar_colors_when_explicitly_enabled():
    bar = pipeline.render_lane_bar("succeeded", 0, width=10, color=True)
    assert "\033[" in bar
    assert "succeeded" in bar


def test_render_lane_bar_no_color_when_explicitly_disabled_even_if_forced_elsewhere():
    bar = pipeline.render_lane_bar("failed", 0, width=4, color=False)
    assert bar == "[!!!!] failed"


def test_render_frame_colors_status_when_explicitly_enabled():
    summary = {"status": "working", "message": "1 active; 0 need attention"}
    workstreams = [
        {
            "workstream_id": "issue-180",
            "status": "running",
            "lanes": [{"lane_id": "session-1", "label": "builder", "status": "running"}],
        }
    ]

    plain = pipeline.render_frame(summary, workstreams, color=False)
    colored = pipeline.render_frame(summary, workstreams, color=True)

    assert "\033[" not in plain
    assert "\033[" in colored
    assert "issue-180" in colored


def test_render_frame_reports_no_workstreams_when_empty():
    frame = pipeline.render_frame({"status": "idle", "message": "No verified agent work is active"}, [])
    assert "No workstreams found." in frame
    assert "idle" in frame


def test_render_frame_includes_workstream_and_lane_lines():
    summary = {"status": "working", "message": "1 active; 0 need attention"}
    workstreams = [
        {
            "workstream_id": "issue-180",
            "status": "running",
            "lanes": [
                {"lane_id": "session-1", "label": "builder", "status": "running"},
                {"lane_id": "session-2", "label": "reviewer", "status": "succeeded"},
            ],
        }
    ]

    frame = pipeline.render_frame(summary, workstreams, frame=0, width=10)

    assert "issue-180 [running]" in frame
    assert "builder" in frame
    assert "reviewer" in frame
    assert "succeeded" in frame


def test_render_frame_distinguishes_two_same_role_same_runtime_lanes():
    """Regression for the bug this feature fixes: two lanes with the same
    label/runtime used to render as identical text. session_id suffix +
    branch must now tell them apart in the pipeline bars view too."""
    summary = {"status": "working", "message": "m"}
    workstreams = [
        {
            "workstream_id": "issue-180",
            "status": "running",
            "lanes": [
                {
                    "lane_id": "session-1",
                    "session_id": "session_" + "a" * 32,
                    "label": "orchestrator",
                    "runtime": "codex",
                    "branch": "daemon/issue-180-a",
                    "started_at": "2026-08-20T10:00:00.000000Z",
                    "status": "running",
                },
                {
                    "lane_id": "session-2",
                    "session_id": "session_" + "b" * 32,
                    "label": "orchestrator",
                    "runtime": "codex",
                    "branch": "daemon/issue-180-b",
                    "started_at": "2026-08-20T10:05:00.000000Z",
                    "status": "running",
                },
            ],
        }
    ]

    frame = pipeline.render_frame(summary, workstreams, frame=0, width=10)

    lines = [line for line in frame.splitlines() if "orchestrator" in line]
    assert len(lines) == 2
    assert lines[0] != lines[1]
    assert "daemon/issue-180-a" in lines[0]
    assert "daemon/issue-180-b" in lines[1]


def test_run_watch_draws_one_frame_per_iteration_and_stops_at_max_iterations():
    calls = {"collect": 0, "sleep": 0, "clear": 0}
    drawn: list[str] = []

    def collect():
        calls["collect"] += 1
        return {"status": "working", "message": "m"}, []

    def sleep_fn(seconds):
        calls["sleep"] += 1

    def clear_fn():
        calls["clear"] += 1

    iterations = pipeline.run_watch(
        collect,
        interval=0.01,
        sleep_fn=sleep_fn,
        clear_fn=clear_fn,
        out=drawn.append,
        max_iterations=3,
    )

    assert iterations == 3
    assert calls["collect"] == 3
    assert calls["clear"] == 3
    # no sleep after the final iteration -- nothing left to wait for
    assert calls["sleep"] == 2
    assert len(drawn) == 3


def test_run_watch_stops_cleanly_on_keyboard_interrupt():
    def collect():
        raise KeyboardInterrupt

    drawn: list[str] = []
    iterations = pipeline.run_watch(collect, out=drawn.append, sleep_fn=lambda s: None)

    assert iterations == 0
    assert any("Stopped" in line for line in drawn)
