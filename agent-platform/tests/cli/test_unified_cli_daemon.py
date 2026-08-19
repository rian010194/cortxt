from __future__ import annotations

import json
from pathlib import Path

from cli.unified_cli import main


def test_daemon_stop_touches_stop_flag(tmp_path):
    state_dir = tmp_path / "daemon-state"
    exit_code = main(["daemon", "stop", "--state-dir", str(state_dir)])
    assert exit_code == 0
    assert (state_dir / "STOP").exists()


def test_daemon_status_reports_no_snapshot(tmp_path, capsys):
    snapshot_path = tmp_path / "snapshot.json"  # does not exist yet
    exit_code = main(["daemon", "status", "--snapshot", str(snapshot_path)])
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "succeeded"  # a missing snapshot is not an error -- daemon just hasn't run yet
    assert out["evidence"][0]["daemon"] is None


def test_daemon_status_reads_existing_snapshot(tmp_path, capsys):
    from cli.status import write_snapshot

    snapshot_path = tmp_path / "snapshot.json"
    write_snapshot([], snapshot_path, daemon={"status": "running", "claimed": ["owner/repo#1"]})

    exit_code = main(["daemon", "status", "--snapshot", str(snapshot_path)])
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "succeeded"
    assert out["evidence"][0]["daemon"]["claimed"] == ["owner/repo#1"]
