from __future__ import annotations

import sys
import time

from supervisor.process_spawner import ProcessSpawner


def test_spawn_is_alive_and_terminate_gracefully_cycle(tmp_path):
    spawner = ProcessSpawner()
    script = tmp_path / "sleeper.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    child = spawner.spawn(session_id="session_test", args=[sys.executable, str(script)])
    try:
        assert spawner.is_alive(child)
        assert spawner.terminate_gracefully(child, timeout=5.0)
        assert not spawner.is_alive(child)
    finally:
        if spawner.is_alive(child):
            spawner.terminate_gracefully(child, timeout=1.0)


def test_is_alive_is_false_once_a_short_lived_process_exits(tmp_path):
    spawner = ProcessSpawner()
    script = tmp_path / "quick.py"
    script.write_text("pass\n", encoding="utf-8")

    child = spawner.spawn(session_id="session_test", args=[sys.executable, str(script)])
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and spawner.is_alive(child):
        time.sleep(0.1)
    assert not spawner.is_alive(child)


def test_start_time_mismatch_is_treated_as_not_alive(tmp_path):
    from dataclasses import replace

    spawner = ProcessSpawner()
    script = tmp_path / "sleeper2.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    child = spawner.spawn(session_id="session_test", args=[sys.executable, str(script)])
    try:
        stale = replace(child, start_time=child.start_time - 999999)
        assert not spawner.is_alive(stale)
    finally:
        spawner.terminate_gracefully(child, timeout=1.0)
