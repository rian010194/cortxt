from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from cli.unified_cli import _run_dispatch
from runtime.engine_registry import EngineContext


class _FakeHermesAdapter:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
        self.calls.append((profile, prompt, timeout_seconds, model, provider))
        return self._response


class _FakeDshAdapter:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
        self.calls.append((profile, prompt, timeout_seconds, model, provider))
        return self._response


class _FakeClaudeAdapter:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None, session_id=None):
        self.calls.append((profile, prompt, timeout_seconds, model, provider))
        return self._response


def _make_args(tmp_path, *, tags, hermes_profile=None):
    return argparse.Namespace(
        tags=tags,
        task_id="dispatch-test",
        prompt="do the thing",
        store=tmp_path / "sessions",
        timeout=60,
        model=None,
        provider=None,
        hermes_profile=hermes_profile,
        snapshot=tmp_path / "snapshot.json",
    )


def test_hermes_routed_task_invokes_the_registered_adapter(tmp_path):
    # hermes keeps parallel-dispatch; research/background-task now go to dsh
    # (cheap tie-break on engine_id, deliberate operator decision 2026-08-21).
    # parallel-dispatch has no _HERMES_PROFILE_BY_TAG entry, so the profile
    # default is "builder".
    adapter = _FakeHermesAdapter({"status": "succeeded", "profile": "builder"})
    context = EngineContext()
    context.register("hermes", adapter)

    args = _make_args(tmp_path, tags="parallel-dispatch")
    result = _run_dispatch(args, engine_context=context)

    assert result.status == "succeeded"
    assert adapter.calls == [("builder", "do the thing", 60, None, None)]
    assert result.evidence[0]["engine"] == "hermes"
    assert result.evidence[0]["hermes_result"]["status"] == "succeeded"


def test_hermes_free_routed_task_invokes_the_registered_adapter(tmp_path):
    # research/background-task now route to hermes-free (free < cheap,
    # deliberate operator decision 2026-08-22, issue #243); hermes keeps
    # parallel-dispatch. parallel-dispatch has no _HERMES_PROFILE_BY_TAG
    # entry, so the profile default is "builder" for hermes.
    adapter = _FakeHermesAdapter({"status": "succeeded", "profile": "builder"})
    context = EngineContext()
    context.register("hermes-free", adapter)

    args = _make_args(tmp_path, tags="research")
    result = _run_dispatch(args, engine_context=context)

    assert result.status == "succeeded"
    assert adapter.calls == [("researcher", "do the thing", 60, None, None)]
    assert result.evidence[0]["engine"] == "hermes-free"
    assert result.evidence[0]["hermes_result"]["status"] == "succeeded"


def test_hermes_adapter_failed_status_yields_failed_result(tmp_path):
    adapter = _FakeHermesAdapter({"status": "failed", "profile": "builder"})
    context = EngineContext()
    context.register("hermes", adapter)

    args = _make_args(tmp_path, tags="parallel-dispatch")
    result = _run_dispatch(args, engine_context=context)

    assert result.status == "failed"


def test_claude_routed_task_with_no_registered_adapter_is_recorded_blocked(tmp_path):
    context = EngineContext()  # nothing registered for "claude"

    args = _make_args(tmp_path, tags="widget-ui")
    result = _run_dispatch(args, engine_context=context)

    assert result.status == "succeeded"  # dispatch itself succeeded: routing + recording worked
    assert result.evidence[0]["engine"] == "claude"


def test_explicit_hermes_profile_overrides_tag_based_default(tmp_path):
    adapter = _FakeHermesAdapter({"status": "succeeded", "profile": "custom-profile"})
    context = EngineContext()
    context.register("hermes", adapter)

    args = _make_args(tmp_path, tags="parallel-dispatch", hermes_profile="custom-profile")
    _run_dispatch(args, engine_context=context)

    assert adapter.calls[0][0] == "custom-profile"


def test_no_engine_context_argument_uses_real_default_wiring(tmp_path):
    # The default wiring now routes widget-ui to the verified headless claude
    # adapter. Patch the adapter class so the test never spawns a real CLI.
    fake = _FakeClaudeAdapter({"status": "succeeded", "profile": "builder"})
    with patch("runtime.default_engine_context.ClaudeAdapter", return_value=fake):
        args = _make_args(tmp_path, tags="widget-ui")
        result = _run_dispatch(args)
    assert result.status == "succeeded"
    assert result.evidence[0]["engine"] == "claude"
    assert len(fake.calls) == 1
