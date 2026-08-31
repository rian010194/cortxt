"""S7d (#473): the session-agents emit path was dead, and its write unsafe.

Two defects verified in the S7c session, both in `cli/unified_cli.py`:

- The same tracked file (`agent-platform/widget/session-agents.json`) was the
  default *input* and the default *output* of the session-agents view. The
  formats differ -- the file holds a rendered widget tree, while
  `read_session_agents_v1` requires `{"agents": [...]}` -- so the emit path
  raised on its own committed artifact, and the live-reader fallback beside it
  was unreachable because the default input file always existed.
- `cortxt widget --view session-agents` wrote live local session state over
  that same tracked fixture in a public repository.

The default input is now the live reader (a file is read only when one is
explicitly given), and the default output is a gitignored runtime path.
"""
import json
from argparse import Namespace
from pathlib import Path

import pytest

from cli.unified_cli import (WIDGET_SNAPSHOT_DIR, _run_widget, _run_widget_load,
                             default_widget_snapshot_path)

REPO_ROOT = Path(__file__).resolve().parents[3]
TRACKED_FIXTURE = REPO_ROOT / "agent-platform" / "widget" / "session-agents.json"

AGENTS = {"agents": [{"id": "a1", "name": "Builder", "runtime": "hermes",
                      "status": "running", "current_task": "t1",
                      "tasks": [{"id": "t1", "title": "Build", "state": "running",
                                 "progress": 50}]}]}


def test_the_default_snapshot_path_is_not_a_tracked_artifact():
    target = default_widget_snapshot_path("session-agents")
    assert WIDGET_SNAPSHOT_DIR.name.startswith("."), "runtime snapshots belong in a dot directory"
    assert target != TRACKED_FIXTURE
    assert target.parent == WIDGET_SNAPSHOT_DIR


def test_the_runtime_snapshot_directory_is_gitignored():
    """A public repository must not collect live local session state."""
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    rel = WIDGET_SNAPSHOT_DIR.relative_to(REPO_ROOT).as_posix()
    assert f"{rel}/" in ignored


def test_session_agents_view_does_not_overwrite_the_tracked_fixture(tmp_path):
    before = TRACKED_FIXTURE.read_bytes()
    result = _run_widget(Namespace(widget_command=None, view="session-agents",
                                   repo=None, snapshot=None,
                                   agents_reader=lambda: AGENTS))
    assert result.status == "succeeded"
    assert TRACKED_FIXTURE.read_bytes() == before
    written = Path(str(result.artifacts[0]).split(":", 1)[1])
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["render"]


def test_an_explicit_snapshot_target_is_still_honoured(tmp_path):
    target = tmp_path / "agents.json"
    result = _run_widget(Namespace(widget_command=None, view="session-agents",
                                   repo=None, snapshot=target,
                                   agents_reader=lambda: AGENTS))
    assert result.status == "succeeded"
    assert target.is_file()


def test_the_emitted_path_reads_live_state_not_its_own_rendered_output(tmp_path):
    """The unreachable-fallback defect: with no explicit input the emit path
    must use the live reader, never the rendered tree it wrote last time."""
    from widget_contract.loader import load_widget_file

    spec = tmp_path / "emitted.yaml"
    spec.write_text(
        'contract_version: "0.1"\n'
        "widget:\n  id: emitted-agents\n  version: \"0.1\"\n  title: Emitted\n"
        "data:\n  reads:\n    - id: agents\n      source: store\n"
        "      operation: session-agents.v1\n      input: {}\n      select: []\n"
        "      refresh:\n        mode: manual\n"
        "      output_type: session-agents.v1\n      on_error: stale\n"
        "render:\n  primitive: stack\n  props: {label: Agents}\n  children: []\n"
        "actions: []\n"
        "capabilities: [read:session-agents]\n",
        encoding="utf-8")
    load_widget_file(spec)  # the spec itself must be valid

    calls = []

    def reader():
        calls.append(True)
        return AGENTS

    result = _run_widget_load(Namespace(widget_command="load", spec=spec, view="emitted-agents",
                                        repo=None, snapshot_input=None,
                                        snapshot=tmp_path / "out.json",
                                        agents_reader=reader))
    assert result.status == "succeeded", result.error
    assert calls, "the live session-agents reader was never consulted"


def test_no_session_agents_branch_keeps_the_unsafe_implicit_default():
    """The first fix landed on the emit branch only, leaving the identical
    default alive on the compose (`child_data`) branch, where it kept the live
    reader unreachable in exactly the same way (#473 review).

    This is asserted over the source because the invariant is "no branch here
    has an implicit input default", including branches added later -- a test
    bound to today's two call sites would not catch the third.
    """
    source = (REPO_ROOT / "agent-platform" / "cli" / "unified_cli.py").read_text(encoding="utf-8")
    assert 'agents_input = getattr(args, "agents_input", None) or' not in source
    assert source.count('agents_input = getattr(args, "agents_input", None)') == 2
