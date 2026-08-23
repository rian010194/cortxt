#!/usr/bin/env python3
"""Offline checks for the Pulse standalone widget view (#308).

Run: python scripts/test_widget_pulse_view.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: the session-pulse render tree shape (orchestrator key-values,
active-sessions metric, workstreams/activity tables), the safe snapshot
projection, the CLI artifact path, the error-state artifact for a
malformed snapshot, and the manifest row.
"""
from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))
sys.path.insert(0, str(REPO / "scripts"))

from cli.unified_cli import _run_widget  # noqa: E402
from widget_contract.adapters.store_reads import ReadAdapterError, read_snapshot_v2  # noqa: E402
from widget_contract.loader import load_widget_file  # noqa: E402
from widget_contract.renderer import render  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def snapshot(orchestrator=None, workstreams=None, activity=None):
    return {
        "schema_version": 2,
        "generated_at": "2026-01-01T00:00:00Z",
        "orchestrator": orchestrator or {"status": "idle", "active_agent_sessions": 0,
                                         "abandoned_agent_sessions": 0, "blocked_agent_sessions": 0,
                                         "failed_agent_sessions": 0, "attention_items": 0,
                                         "message": "idle"},
        "workstreams": workstreams or [],
        "sessions": [],
        "activity": activity or [],
    }


def main() -> int:
    # 1. Spec declares the snapshot read and no actions.
    spec = AP / "widget_contract" / "specs" / "session-pulse-0.1.yaml"
    widget = load_widget_file(spec)
    check("spec declares session-pulse read with no actions",
          widget.id == "session-pulse" and widget.actions == ())
    (read,) = widget.reads
    check("read is a store snapshot read",
          (read.source, read.operation, read.output_type) ==
          ("store", "sessions.snapshot.v2", "sessions.snapshot.v2"))

    # 2. Render tree shape for a populated snapshot.
    data = snapshot(
        orchestrator={"status": "attention", "active_agent_sessions": 1,
                      "abandoned_agent_sessions": 0, "blocked_agent_sessions": 1,
                      "failed_agent_sessions": 0, "attention_items": 1, "message": "1 active"},
        workstreams=[{"workstream_id": "ws-1", "status": "running", "updated_at": "2026-01-01T00:00:01Z"}],
        activity=[{"timestamp": "2026-01-01T00:00:01Z", "event_type": "session.created",
                   "workstream_id": "ws-1", "actor": "agent"}],
    )
    tree = render(widget, {"snapshot": data}, {"snapshot": "fresh"})
    children = tree["render"]["children"]
    check("orchestrator renders as key-value",
          children[0]["primitive"] == "key-value"
          and children[0]["props"]["value"]["status"] == "attention")
    check("active sessions renders as metric",
          children[1]["primitive"] == "metric" and children[1]["props"]["value"] == 1)
    check("workstreams table renders rows",
          children[2]["props"]["label"] == "Workstreams"
          and children[2]["props"]["rows"][0]["workstream_id"] == "ws-1")
    check("activity table renders rows",
          children[3]["props"]["label"] == "Activity"
          and children[3]["props"]["rows"][0]["event_type"] == "session.created")

    # 3. Safe projection excludes non-declared fields; malformed input fails closed.
    projection = read_snapshot_v2({**snapshot(), "credentials": [{"value": "x"}], "profiles": []})
    check("safe projection excludes undeclared fields",
          "credentials" not in projection and "profiles" not in projection)
    malformed = False
    try:
        read_snapshot_v2({"workstreams": "wrong"})
    except ReadAdapterError:
        malformed = True
    check("malformed snapshot fails closed", malformed)

    # 4. CLI artifact path + error-state artifact for a missing snapshot.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "snapshot.json"
        source.write_text(json.dumps(snapshot(workstreams=[
            {"workstream_id": "ws-9", "status": "blocked", "updated_at": "2026-01-01T00:00:00Z"}])),
            encoding="utf-8")
        target = tmp_path / "session-pulse.json"
        result = _run_widget(Namespace(widget_command=None, view="session-pulse", repo=None,
                                       snapshot=target, snapshot_input=source))
        check("CLI session-pulse view succeeds", result.status == "succeeded")
        artifact = json.loads(target.read_text(encoding="utf-8"))
        check("artifact has widget identity and no error",
              artifact["widget"] == {"id": "session-pulse", "version": "0.1"} and artifact["error"] is None)
        check("artifact renders workstreams table",
              any(c["primitive"] == "table" and c["props"]["label"] == "Workstreams"
                  for c in artifact["render"]["children"]))

        missing = tmp_path / "missing.json"
        target2 = tmp_path / "session-pulse2.json"
        result2 = _run_widget(Namespace(widget_command=None, view="session-pulse", repo=None,
                                        snapshot=target2, snapshot_input=missing))
        check("missing snapshot yields error-state artifact",
              result2.status == "succeeded"
              and json.loads(target2.read_text(encoding="utf-8"))["render"]["primitive"] == "error-state")

    # 5. Manifest row + read-only default.
    manifest = json.loads((AP / "widget" / "widgets.json").read_text(encoding="utf-8"))
    check("manifest has the pulse row with artifact",
          any(w["id"] == "pulse" and w["artifact"] == "session-pulse.json" for w in manifest["widgets"]))
    serve = (AP / "widget" / "serve.py").read_text(encoding="utf-8")
    check("default serve.py stays read-only (no POST handler)", "do_POST" not in serve)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
