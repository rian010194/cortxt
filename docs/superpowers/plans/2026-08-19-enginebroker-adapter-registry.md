# EngineBroker Adapter Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `unified_cli.py`'s and `daemon/loop.py`'s hardcoded `if choice.engine_id == "hermes"` branches with a small `EngineAdapter`/`EngineBroker`/`EngineContext` registry, so adding a future engine is a manifest row + one adapter file instead of a new `if/elif` branch in two places.

**Architecture:** A new `agent-platform/runtime/` module trio — `engine_adapter.py` (a `Protocol` every engine adapter implements), `engine_registry.py` (`EngineBroker`, one per `engine_id`, v1 holds exactly one provider and is pure passthrough; `EngineContext`, a `dict`-like `engine_id -> EngineBroker` lookup that always returns a broker, never `None`) — plus `runtime/adapters/hermes_adapter.py` (`HermesAdapter`, a thin wrapper around the existing, untouched `routing/hermes_invoker.invoke_hermes`). `route()`/`engine_manifest.py` is not touched; this only replaces the *invocation* step after `route()` has already picked an `engine_id`.

**Tech Stack:** Python 3.11+, pytest, dataclasses, `typing.Protocol`.

**Spec:** `docs/adr/026-engine-adapter-registry-separate-from-route-selection.md` and `docs/adr/027-engine-context-adopts-service-broker-not-exclusive-binding.md` (both Accepted — these ADRs are the design; no separate spec document exists). Operator-approved scope additions beyond the ADRs' literal text, agreed in the brainstorming session that produced this plan: (1) `daemon/loop.py`'s own direct `invoke_hermes()` call site is migrated too, not just `unified_cli.py`'s (ADR-026's validation checklist only lists `unified_cli.py`, but leaving `daemon/loop.py` on the old path would defeat the ADR's stated benefit — "add an engine = one manifest row + one adapter file" — for the daemon specifically).

## Global Constraints

- `route()` / `agent-platform/routing/engine_manifest.py` (the `route()` function, `EngineManifest`, `EngineChoice`, `DEFAULT_MANIFESTS`) must show **zero diff** at the end of this plan. If any task touches this file, that task is wrong.
- `agent-platform/routing/hermes_invoker.py`'s `invoke_hermes()` function body is not rewritten — `HermesAdapter` wraps it, it does not reimplement it.
- No routing policy (round-robin, weighting, load balancing) is implemented in `EngineBroker`. v1 is exactly-one-provider passthrough. A broker with more than one provider is out of scope for this plan.
- No `DeepseekAdapter`, `ClaudeAdapter`, or any adapter beyond `HermesAdapter` is built in this plan.
- No cross-process/RPC broker. `hermes_invoker.py`'s subprocess model is the only invocation mechanism.
- Every task that changes an existing file's observable behavior must be covered by a test that would fail on the old code path — these are regression-safety tasks, not just new-code tasks.
- Full suite (`agent-platform/`, run from that directory: `python -m pytest tests/ -q`) must end at 558+ passed, 14 skipped, 0 failed after the last task (baseline confirmed 2026-08-19 immediately before this plan was written).

---

## File Structure

New files:
- `agent-platform/runtime/engine_adapter.py` — `EngineAdapter` Protocol. One responsibility: define the shape every adapter must implement.
- `agent-platform/runtime/engine_registry.py` — `NoProviderRegisteredError`, `EngineBroker`, `EngineContext`. One responsibility: the registry/broker mechanics, no knowledge of any specific engine.
- `agent-platform/runtime/adapters/__init__.py` — empty, makes `adapters` a package.
- `agent-platform/runtime/adapters/hermes_adapter.py` — `HermesAdapter`. One responsibility: adapt `routing.hermes_invoker.invoke_hermes` to the `EngineAdapter` shape.
- `agent-platform/runtime/default_engine_context.py` — `build_default_engine_context()`. One responsibility: wire today's one known adapter (`HermesAdapter`) into a fresh `EngineContext`. Kept separate from `engine_registry.py` so the registry module itself never has to import a specific adapter (mirrors `engine_manifest.py`'s own `DEFAULT_MANIFESTS` pattern of "generic mechanism in one file, default instance in the same file" — but here the default wiring pulls in an adapter import the registry module shouldn't need, hence the split).

Modified files:
- `agent-platform/cli/unified_cli.py` — `_run_dispatch()` (currently lines 294–371): the `if choice.engine_id == "hermes": ... else: ...` block (currently lines 338–363) is replaced with a broker lookup. Gains an optional `engine_context` keyword parameter for test injection.
- `agent-platform/daemon/loop.py` — `DaemonLoop` dataclass: the `invoke_hermes: Callable` field is replaced with `engine_context: EngineContext`. `run_once()`'s `if choice.engine_id != "hermes": continue` guard (currently lines 147–154) becomes a `broker.has_provider` check; the `self.invoke_hermes(...)` call (currently line 167) becomes `broker.invoke(...)`.
- `agent-platform/tests/daemon/test_loop.py` — `_make_loop()` helper and every test that currently passes `invoke_hermes=...` switches to `engine_context=...`.

New test files:
- `agent-platform/tests/runtime/test_engine_adapter.py`
- `agent-platform/tests/runtime/test_engine_registry.py`
- `agent-platform/tests/runtime/adapters/test_hermes_adapter.py`
- `agent-platform/tests/runtime/test_default_engine_context.py`
- `agent-platform/tests/cli/test_unified_cli_dispatch.py`

---

### Task 1: `EngineAdapter` protocol

**Files:**
- Create: `agent-platform/runtime/engine_adapter.py`
- Test: `agent-platform/tests/runtime/test_engine_adapter.py`

**Interfaces:**
- Produces: `EngineAdapter` — a `typing.Protocol` (decorated `@runtime_checkable`) with one method: `invoke(self, profile: str, prompt: str, *, timeout_seconds: int, model: str | None = None, provider: str | None = None) -> dict`. This signature is deliberately identical to `routing.hermes_invoker.invoke_hermes`'s signature (minus the `run_subprocess` test-injection parameter, which is `HermesAdapter`'s own internal concern, not part of the adapter contract).

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/runtime/test_engine_adapter.py
from __future__ import annotations

from runtime.engine_adapter import EngineAdapter


class _ConformingAdapter:
    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None):
        return {"status": "succeeded", "profile": profile}


class _NonConformingAdapter:
    def frobnicate(self):
        return None


def test_conforming_object_is_an_engine_adapter_instance():
    assert isinstance(_ConformingAdapter(), EngineAdapter)


def test_non_conforming_object_is_not_an_engine_adapter_instance():
    assert not isinstance(_NonConformingAdapter(), EngineAdapter)
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `agent-platform/`): `python -m pytest tests/runtime/test_engine_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'runtime.engine_adapter'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/runtime/engine_adapter.py
"""The invocation contract every engine adapter implements (ADR-026).

route() (routing/engine_manifest.py) decides *which* engine_id wins for a
task -- picking isn't invoking, per hermes_invoker.py's own docstring. This
Protocol is the "invoking" half: whatever object a broker holds for a given
engine_id, it can call .invoke(...) on it without knowing which concrete
engine it's talking to.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EngineAdapter(Protocol):
    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/runtime/test_engine_adapter.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/engine_adapter.py agent-platform/tests/runtime/test_engine_adapter.py
git commit -m "feat(runtime): add EngineAdapter protocol (ADR-026)"
```

---

### Task 2: `EngineBroker` and `EngineContext`

**Files:**
- Create: `agent-platform/runtime/engine_registry.py`
- Test: `agent-platform/tests/runtime/test_engine_registry.py`

**Interfaces:**
- Consumes: `EngineAdapter` from Task 1 (`runtime.engine_adapter`).
- Produces:
  - `NoProviderRegisteredError(RuntimeError)`.
  - `EngineBroker` — `.has_provider -> bool`, `.register(adapter: EngineAdapter) -> None`, `.invoke(profile, prompt, *, timeout_seconds, model=None, provider=None) -> dict` (raises `NoProviderRegisteredError` if `has_provider` is `False`; otherwise delegates to the sole registered provider — v1 is exactly-one-provider passthrough per ADR-027).
  - `EngineContext` — `.get(engine_id: str) -> EngineBroker` (always returns a broker; auto-creates and caches an empty one on first access for an unknown `engine_id`, per ADR-027 point 1: "`EngineContext.get(engine_id)` returnerar alltid en broker-referens... aldrig en adapter direkt"), `.register(engine_id: str, adapter: EngineAdapter) -> None` (shorthand for `.get(engine_id).register(adapter)`).

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/runtime/test_engine_registry.py
from __future__ import annotations

import pytest

from runtime.engine_registry import EngineBroker, EngineContext, NoProviderRegisteredError


class _FakeAdapter:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None):
        self.calls.append((profile, prompt, timeout_seconds, model, provider))
        return self._response


def test_empty_broker_has_no_provider():
    broker = EngineBroker()
    assert broker.has_provider is False


def test_empty_broker_invoke_raises_no_provider_registered():
    broker = EngineBroker()
    with pytest.raises(NoProviderRegisteredError):
        broker.invoke("builder", "do it", timeout_seconds=60)


def test_broker_with_one_provider_passes_through():
    adapter = _FakeAdapter({"status": "succeeded"})
    broker = EngineBroker()
    broker.register(adapter)
    result = broker.invoke("builder", "do it", timeout_seconds=60, model="m", provider="p")
    assert result == {"status": "succeeded"}
    assert adapter.calls == [("builder", "do it", 60, "m", "p")]
    assert broker.has_provider is True


def test_context_get_returns_broker_for_unknown_engine_id():
    context = EngineContext()
    broker = context.get("nobody-registered-this")
    assert isinstance(broker, EngineBroker)
    assert broker.has_provider is False


def test_context_get_is_stable_across_calls():
    context = EngineContext()
    first = context.get("hermes")
    second = context.get("hermes")
    assert first is second


def test_context_register_makes_broker_have_provider():
    adapter = _FakeAdapter({"status": "succeeded"})
    context = EngineContext()
    context.register("hermes", adapter)
    assert context.get("hermes").has_provider is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/runtime/test_engine_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'runtime.engine_registry'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/runtime/engine_registry.py
"""EngineBroker/EngineContext (ADR-026, ADR-027).

Service-broker pattern, not exclusive binding (ADR-027): engine_id is a
broker key, never a directly-bound adapter slot. v1 policy is exactly one
provider per broker, pure passthrough -- no routing policy (round-robin,
weighting) is built until a second provider is actually registered under
the same engine_id (ADR-027 non-goal, explicit).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from runtime.engine_adapter import EngineAdapter


class NoProviderRegisteredError(RuntimeError):
    """No adapter is registered for this engine_id yet."""


@dataclass
class EngineBroker:
    _providers: list[EngineAdapter] = field(default_factory=list)

    @property
    def has_provider(self) -> bool:
        return bool(self._providers)

    def register(self, adapter: EngineAdapter) -> None:
        self._providers.append(adapter)

    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict:
        if not self._providers:
            raise NoProviderRegisteredError(
                "no adapter registered for this broker's engine_id"
            )
        # v1: exactly one provider, pure passthrough (ADR-027 point 2).
        return self._providers[0].invoke(
            profile, prompt, timeout_seconds=timeout_seconds, model=model, provider=provider
        )


@dataclass
class EngineContext:
    _brokers: dict[str, EngineBroker] = field(default_factory=dict)

    def get(self, engine_id: str) -> EngineBroker:
        if engine_id not in self._brokers:
            self._brokers[engine_id] = EngineBroker()
        return self._brokers[engine_id]

    def register(self, engine_id: str, adapter: EngineAdapter) -> None:
        self.get(engine_id).register(adapter)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/runtime/test_engine_registry.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/engine_registry.py agent-platform/tests/runtime/test_engine_registry.py
git commit -m "feat(runtime): add EngineBroker/EngineContext service-broker registry (ADR-027)"
```

---

### Task 3: `HermesAdapter`

**Files:**
- Create: `agent-platform/runtime/adapters/__init__.py`
- Create: `agent-platform/runtime/adapters/hermes_adapter.py`
- Test: `agent-platform/tests/runtime/adapters/__init__.py`
- Test: `agent-platform/tests/runtime/adapters/test_hermes_adapter.py`

**Interfaces:**
- Consumes: `routing.hermes_invoker.invoke_hermes` (untouched, existing function) and `routing.hermes_invoker.HermesInvocationError` (untouched, existing exception — `HermesAdapter` does not catch or translate it; it propagates to the caller exactly as `invoke_hermes` itself raises it).
- Produces: `HermesAdapter` — a class satisfying `EngineAdapter` (Task 1). `__init__(self, invoke_hermes: Callable = <routing.hermes_invoker.invoke_hermes>) -> None` (the default parameter is the real function, injectable for tests exactly like `hermes_invoker.invoke_hermes`'s own `run_subprocess` parameter is). `.invoke(...)` delegates directly, no added logic.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/runtime/adapters/__init__.py
```

```python
# agent-platform/tests/runtime/adapters/test_hermes_adapter.py
from __future__ import annotations

import pytest

from runtime.adapters.hermes_adapter import HermesAdapter
from runtime.engine_adapter import EngineAdapter
from routing.hermes_invoker import HermesInvocationError


def test_hermes_adapter_is_an_engine_adapter():
    assert isinstance(HermesAdapter(), EngineAdapter)


def test_invoke_delegates_to_injected_invoke_hermes_unchanged():
    calls = []

    def fake_invoke_hermes(profile, prompt, *, timeout_seconds, model=None, provider=None):
        calls.append((profile, prompt, timeout_seconds, model, provider))
        return {"status": "succeeded", "profile": profile}

    adapter = HermesAdapter(invoke_hermes=fake_invoke_hermes)
    result = adapter.invoke("researcher", "do research", timeout_seconds=300, model="m", provider="p")

    assert result == {"status": "succeeded", "profile": "researcher"}
    assert calls == [("researcher", "do research", 300, "m", "p")]


def test_invoke_propagates_hermes_invocation_error_unwrapped():
    def raising_invoke_hermes(profile, prompt, *, timeout_seconds, model=None, provider=None):
        raise HermesInvocationError("could not start hermes")

    adapter = HermesAdapter(invoke_hermes=raising_invoke_hermes)
    with pytest.raises(HermesInvocationError):
        adapter.invoke("builder", "do it", timeout_seconds=60)


def test_default_constructor_uses_real_invoke_hermes():
    import runtime.adapters.hermes_adapter as module
    from routing.hermes_invoker import invoke_hermes as real_invoke_hermes

    adapter = module.HermesAdapter()
    assert adapter._invoke_hermes is real_invoke_hermes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/runtime/adapters/test_hermes_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'runtime.adapters'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/runtime/adapters/__init__.py
```

```python
# agent-platform/runtime/adapters/hermes_adapter.py
"""Wraps routing.hermes_invoker.invoke_hermes as an EngineAdapter (ADR-026
point 3: "befintlig invocation-kod paketeras om, skrivs inte om" -- existing
invocation code is repackaged, not rewritten. This class adds no logic
beyond the delegation itself; invoke_hermes's tested subprocess behavior,
including HermesInvocationError, passes through unchanged."""
from __future__ import annotations

from typing import Callable

from routing.hermes_invoker import invoke_hermes as _default_invoke_hermes


class HermesAdapter:
    def __init__(self, invoke_hermes: Callable = _default_invoke_hermes) -> None:
        self._invoke_hermes = invoke_hermes

    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict:
        return self._invoke_hermes(
            profile, prompt, timeout_seconds=timeout_seconds, model=model, provider=provider
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/runtime/adapters/test_hermes_adapter.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/adapters/ agent-platform/tests/runtime/adapters/
git commit -m "feat(runtime): add HermesAdapter wrapping invoke_hermes (ADR-026)"
```

---

### Task 4: `build_default_engine_context()`

**Files:**
- Create: `agent-platform/runtime/default_engine_context.py`
- Test: `agent-platform/tests/runtime/test_default_engine_context.py`

**Interfaces:**
- Consumes: `EngineContext` (Task 2, `runtime.engine_registry`), `HermesAdapter` (Task 3, `runtime.adapters.hermes_adapter`).
- Produces: `build_default_engine_context() -> EngineContext` — returns a fresh `EngineContext` with a fresh `HermesAdapter()` registered under `"hermes"`. Nothing registered under `"claude-direct"` (matches today's reality: no invoker exists for it — ADR-026 explicitly defers building a `ClaudeAdapter`).

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/runtime/test_default_engine_context.py
from __future__ import annotations

from runtime.default_engine_context import build_default_engine_context


def test_hermes_has_a_provider():
    context = build_default_engine_context()
    assert context.get("hermes").has_provider is True


def test_claude_direct_has_no_provider():
    context = build_default_engine_context()
    assert context.get("claude-direct").has_provider is False


def test_each_call_returns_an_independent_context():
    first = build_default_engine_context()
    second = build_default_engine_context()
    assert first is not second
    assert first.get("hermes") is not second.get("hermes")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/runtime/test_default_engine_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'runtime.default_engine_context'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent-platform/runtime/default_engine_context.py
"""Today's one known-good engine wiring (ADR-026/027 v1: exactly one
provider per engine_id, HermesAdapter is the only adapter that exists).
Kept separate from engine_registry.py so that module never has to import a
specific adapter -- adding a second adapter later means editing this file
plus adding the adapter file, not touching the registry mechanics."""
from __future__ import annotations

from runtime.adapters.hermes_adapter import HermesAdapter
from runtime.engine_registry import EngineContext


def build_default_engine_context() -> EngineContext:
    context = EngineContext()
    context.register("hermes", HermesAdapter())
    return context
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/runtime/test_default_engine_context.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/default_engine_context.py agent-platform/tests/runtime/test_default_engine_context.py
git commit -m "feat(runtime): add build_default_engine_context() default wiring"
```

---

### Task 5: Migrate `unified_cli.py`'s `_run_dispatch` to the broker

**Files:**
- Modify: `agent-platform/cli/unified_cli.py` (the `_run_dispatch` function, currently lines 294–371)
- Test: `agent-platform/tests/cli/test_unified_cli_dispatch.py`
- Existing test (must still pass unmodified): `agent-platform/tests/cli/test_unified_cli_script_invocation.py`

**Interfaces:**
- Consumes: `EngineContext` (Task 2), `build_default_engine_context` (Task 4).
- Produces: `_run_dispatch(args: argparse.Namespace, *, engine_context: "EngineContext | None" = None) -> ResultEnvelope` — the `engine_context` keyword parameter is new, defaults to `None` (production/CLI callers never pass it, so `build_default_engine_context()` is used, identical to today's real-`invoke_hermes` behavior); tests pass a fake `EngineContext` directly. No other part of `_run_dispatch`'s public behavior (argparse wiring, `ResultEnvelope` shape, evidence dict keys, session-state calls) changes.

There is currently no unit test of `_run_dispatch`'s hermes/claude-direct branch logic — only the bare-subprocess smoke test in `test_unified_cli_script_invocation.py`, which exercises the `claude-direct` path (tag `widget-ui`) end-to-end but does not mock anything. This task adds the first real branch-level regression test, using the new `engine_context` injection seam.

- [ ] **Step 1: Write the failing test**

```python
# agent-platform/tests/cli/test_unified_cli_dispatch.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))

from cli.unified_cli import _run_dispatch
from runtime.engine_registry import EngineContext


class _FakeHermesAdapter:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None):
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
    adapter = _FakeHermesAdapter({"status": "succeeded", "profile": "researcher"})
    context = EngineContext()
    context.register("hermes", adapter)

    args = _make_args(tmp_path, tags="research")
    result = _run_dispatch(args, engine_context=context)

    assert result.status == "succeeded"
    assert adapter.calls == [("researcher", "do the thing", 60, None, None)]
    assert result.evidence[0]["engine"] == "hermes"
    assert result.evidence[0]["hermes_result"]["status"] == "succeeded"


def test_hermes_adapter_failed_status_yields_failed_result(tmp_path):
    adapter = _FakeHermesAdapter({"status": "failed", "profile": "builder"})
    context = EngineContext()
    context.register("hermes", adapter)

    args = _make_args(tmp_path, tags="parallel-dispatch")
    result = _run_dispatch(args, engine_context=context)

    assert result.status == "failed"


def test_claude_direct_routed_task_is_recorded_blocked_without_invoking_anything(tmp_path):
    context = EngineContext()  # nothing registered for "claude-direct"

    args = _make_args(tmp_path, tags="widget-ui")
    result = _run_dispatch(args, engine_context=context)

    assert result.status == "succeeded"  # dispatch itself succeeded: routing + recording worked
    assert result.evidence[0]["engine"] == "claude-direct"


def test_explicit_hermes_profile_overrides_tag_based_default(tmp_path):
    adapter = _FakeHermesAdapter({"status": "succeeded", "profile": "custom-profile"})
    context = EngineContext()
    context.register("hermes", adapter)

    args = _make_args(tmp_path, tags="research", hermes_profile="custom-profile")
    _run_dispatch(args, engine_context=context)

    assert adapter.calls[0][0] == "custom-profile"


def test_no_engine_context_argument_uses_real_default_wiring(tmp_path):
    # No hermes CLI available in CI -- claude-direct path never invokes
    # anything, so this exercises the default-wiring branch safely.
    args = _make_args(tmp_path, tags="widget-ui")
    result = _run_dispatch(args)
    assert result.status == "succeeded"
    assert result.evidence[0]["engine"] == "claude-direct"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_unified_cli_dispatch.py -v`
Expected: FAIL — `_run_dispatch() got an unexpected keyword argument 'engine_context'`

- [ ] **Step 3: Modify `_run_dispatch`**

In `agent-platform/cli/unified_cli.py`, add near the top of the file (inside the existing `from __future__ import annotations` / stdlib import block, after `from typing import Any`):

```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.engine_registry import EngineContext
```

(This replaces the existing `from typing import Any` line — `TYPE_CHECKING` is added to the same import.)

Replace the function signature and body (currently lines 294–371) with:

```python
def _run_dispatch(
    args: argparse.Namespace, *, engine_context: "EngineContext | None" = None
) -> ResultEnvelope:
    """Orchestrator Dispatch v0.1: route a tagged task to an engine, invoke
    it, and record the outcome in the same session_state Fas 2 already
    tracks. See .hermes/plans/2026-08-19-orchestrator-dispatch-v01.md.

    Invocation goes through an EngineContext broker (ADR-026/027) instead of
    a hardcoded if/elif on engine_id -- "claude-direct" has no adapter
    registered (no confirmed one-shot Claude Code CLI entry point exists;
    guessing one would repeat the exact mistake ADR-022 was written to
    avoid), so its broker has no provider and the task is recorded as
    "blocked" -- picked up by a human/Claude Code session, not auto-executed.
    Any other engine_id with no registered adapter gets the same treatment,
    not a silent fallback to whatever IS registered.

    `engine_context` is None in every real CLI invocation (build_default_
    engine_context() is used); tests inject a fake one directly.
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from routing.engine_manifest import DEFAULT_MANIFESTS, route
        from runtime import session_state as state
        from runtime.default_engine_context import build_default_engine_context

        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        choice = route(tags, DEFAULT_MANIFESTS)
        context = engine_context if engine_context is not None else build_default_engine_context()

        store = args.store or (_get_agent_platform_path() / ".sessions")
        session = state.create(store, task_id=args.task_id)
        session_id = session["session_id"]
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})

    # From here on, a session exists on disk. Any exception below must
    # still leave it with a terminal event -- otherwise it's stuck showing
    # "running" forever even though the CLI already reported failure
    # (caught by review: a whitespace-only --prompt or a missing hermes
    # binary raised between session creation and the terminal append,
    # orphaning the session).
    try:
        evidence = {
            "engine": choice.engine_id,
            "routing_reason": choice.reason,
            "matched_tag": choice.matched_tag,
            "excluded": list(choice.excluded),
            "checkpoint_required": choice.checkpoint_required,
        }

        broker = context.get(choice.engine_id)
        if broker.has_provider:
            # Check the full supplied tag set, not choice.matched_tag: route()
            # picks matched_tag as the alphabetically-first tag in the
            # intersection with the winning engine's task_shapes, which isn't
            # necessarily "research" even when "research" was among --tags
            # (e.g. --tags research,parallel-dispatch matches "parallel-dispatch"
            # alphabetically first, silently defeating this default -- caught
            # by review before merge).
            hermes_profile = args.hermes_profile if args.hermes_profile is not None else next(
                (profile for tag, profile in _HERMES_PROFILE_BY_TAG.items() if tag in tags),
                "builder",
            )
            result = broker.invoke(
                hermes_profile, args.prompt, timeout_seconds=args.timeout,
                model=args.model, provider=args.provider,
            )
            state.append(store, session_id, 0, "session.terminal", {"status": result["status"]})
            # Kept as "hermes_result" even though the broker is generic:
            # hermes is the only engine with a registered adapter today, so
            # renaming this key would be a real (if currently invisible)
            # evidence-shape change with no engine that would exercise the
            # difference -- not something this plan does speculatively.
            evidence["hermes_result"] = {k: v for k, v in result.items() if k != "stdout"}
            status = "succeeded" if result["status"] == "succeeded" else "failed"
        else:
            if choice.engine_id == "claude-direct":
                reason = "routed to claude-direct: pick this up in a Claude Code session"
            else:
                reason = f"routed to {choice.engine_id}: no invoker wired for this engine yet"
            state.append(store, session_id, 0, "session.terminal", {"status": "blocked", "reason": reason})
            status = "succeeded"  # dispatch itself succeeded: routing + recording worked

        return ResultEnvelope(
            status=status,
            artifacts=[f"session:{session_id}", f"engine:{choice.engine_id}"],
            evidence=[evidence],
        )
    except Exception as e:
        state.append(store, session_id, 0, "session.terminal", {"status": "failed", "reason": str(e)})
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})
    finally:
        # Best-effort: the widget polls this same file (cli/status.py's
        # write_snapshot), so a dispatch result should show up there without
        # the operator having to run `cortxt sessions` afterward. Runs
        # whichever branch above returned, success or failure, via `finally`
        # -- a snapshot write failure must never mask the dispatch's own
        # result, but per review it must not vanish silently either
        # (status.py's own load_sessions() logs exactly this class of gap
        # for the same reason).
        #
        # Scope note (review): this only refreshes the snapshot for
        # `dispatch`. Other session.terminal producers (agent_loop.py,
        # coding_loop.py, rlm_child_cli.py, supervisor/coordinator.py) don't
        # -- extending to all of them is a real, larger change, not covered
        # by this fix. Also note load_sessions() rescans the whole store, so
        # this is O(n) in total session history per dispatch call; fine at
        # v0.1 scale, a candidate to revisit if the store grows large.
        try:
            cli_dir = Path(__file__).parent
            if str(cli_dir) not in sys.path:
                sys.path.insert(0, str(cli_dir))
            import status as status_cli

            snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
            status_cli.write_snapshot(status_cli.load_sessions(store), snapshot_path)
        except Exception as snapshot_error:
            logger.warning("dispatch: could not refresh widget snapshot: %s", snapshot_error)
```

This `finally` block is reproduced verbatim from the current file (lines 373–399) — it is unrelated to the broker migration and must not be altered by this task. It is included here only so the replacement is complete; do not modify its logic.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/cli/test_unified_cli_dispatch.py tests/cli/test_unified_cli_script_invocation.py -v`
Expected: 5 + 2 passed, 0 failed. The `test_unified_cli_script_invocation.py` tests must pass unmodified — they prove the bare-script `sys.path` bootstrap still works with the new `runtime.default_engine_context` import inside `_run_dispatch`'s deferred-import block.

- [ ] **Step 5: Commit**

```bash
git add agent-platform/cli/unified_cli.py agent-platform/tests/cli/test_unified_cli_dispatch.py
git commit -m "refactor(cli): route _run_dispatch invocation through EngineContext broker"
```

---

### Task 6: Migrate `daemon/loop.py` to the broker

**Files:**
- Modify: `agent-platform/daemon/loop.py`
- Modify: `agent-platform/tests/daemon/test_loop.py`

**Interfaces:**
- Consumes: `EngineContext` (Task 2), `build_default_engine_context` (Task 4).
- Produces: `DaemonLoop.engine_context: EngineContext` (dataclass field, replaces the removed `invoke_hermes: Callable` field, default factory `build_default_engine_context`). `run_once()`'s observable behavior (which issues get claimed, which get skipped, what `gate_outcome` results) is unchanged for every existing test scenario — this task's test changes are pure DI-seam renames, not new assertions.

- [ ] **Step 1: Update the test helper and all call sites in `test_loop.py`**

At the top of `agent-platform/tests/daemon/test_loop.py`, add:

```python
from types import SimpleNamespace

from runtime.engine_registry import EngineContext
```

Add this helper near `_fake_invoke_hermes` (keep `_fake_invoke_hermes` itself unchanged — it's still a valid `(profile, prompt, *, timeout_seconds, model=None, provider=None) -> dict` shaped function, just now wrapped instead of injected directly):

```python
def _context_with_hermes(invoke_fn):
    context = EngineContext()
    context.register("hermes", SimpleNamespace(invoke=invoke_fn))
    return context
```

In `_make_loop()`, replace the `invoke_hermes=_fake_invoke_hermes` parameter and its use with:

```python
def _make_loop(tmp_path: Path, *, list_ready_issues, route=_fake_route,
                engine_context=None, supervised=True,
                git_head=None):
    return DaemonLoop(
        repo="owner/repo",
        state_dir=tmp_path / "state",
        snapshot_path=tmp_path / "snapshot.json",
        budget=SessionBudget(max_cost_usd=100.0, max_wall_clock_seconds=3600.0),
        autonomy=AutonomyTracker(),
        supervised=supervised,
        manifests=DEFAULT_MANIFESTS,
        workdir=tmp_path,
        list_ready_issues=list_ready_issues,
        engine_context=engine_context or _context_with_hermes(_fake_invoke_hermes),
        route=route,
        git_head=git_head or _make_progressing_git_head(),
    )
```

Then update every test that currently passes `invoke_hermes=...` to `_make_loop`:
- `test_crash_then_restart_does_not_redispatch`: change `invoke_hermes=_counting_invoke` to `engine_context=_context_with_hermes(_counting_invoke)` (both call sites — `first` and `second`, using the **same** context instance is not required and not correct here: build a fresh `_context_with_hermes(_counting_invoke)` for each of `first`/`second`, matching how `list_ready_issues`/`_counting_invoke` are already shared closures across both).
- `test_route_choosing_non_hermes_engine_is_skipped_not_dispatched`: change `invoke_hermes=_counting_invoke` to `engine_context=_context_with_hermes(_counting_invoke)`. This test's `route` fake returns `engine_id="claude-direct"`, and the context only has `"hermes"` registered — `context.get("claude-direct").has_provider` is `False`, so the assertions (`dispatch_count["n"] == 0`, issue not claimed) hold for the same reason as before, now via the broker's provider check instead of a hardcoded string comparison.
- `test_hermes_invocation_error_freezes_that_issue`: change `invoke_hermes=_raising_invoke` to `engine_context=_context_with_hermes(_raising_invoke)`.

All other tests in the file use the default `engine_context=None` (which now defaults to `_context_with_hermes(_fake_invoke_hermes)`) and need no change beyond what `_make_loop`'s signature change already gives them.

- [ ] **Step 2: Run the test file to verify it fails against the still-unmodified `loop.py`**

Run: `python -m pytest tests/daemon/test_loop.py -v`
Expected: FAIL — `DaemonLoop.__init__() got an unexpected keyword argument 'engine_context'`

- [ ] **Step 3: Modify `daemon/loop.py`**

Change the imports (remove the `invoke_hermes` import, add the registry imports):

```python
from daemon.autonomy import AutonomyTracker
from daemon.budget import SessionBudget
from daemon.stop_flag import is_stop_requested
from daemon.evidence_gate import GateOutcome, evaluate_gate
from daemon.github_scanner import list_ready_issues as _default_list_ready_issues
from routing.engine_manifest import DEFAULT_MANIFESTS, EngineManifest, route as _default_route
from routing.hermes_invoker import HermesInvocationError
from runtime.default_engine_context import build_default_engine_context
from runtime.engine_registry import EngineContext
from cli.status import write_snapshot
```

In the `DaemonLoop` dataclass, replace:

```python
    invoke_hermes: Callable = _default_invoke_hermes
```

with:

```python
    engine_context: EngineContext = field(default_factory=build_default_engine_context)
```

In `run_once()`, replace:

```python
            choice = self.route(task_tags, self.manifests)

            if choice.engine_id != "hermes":
                # This v1 daemon only has a Hermes invoker wired (routing.
                # hermes_invoker.invoke_hermes -- see its own docstring:
                # "claude-direct has no headless invocation here"). Silently
                # dispatching a claude-direct (or any non-hermes) routing
                # decision to Hermes anyway is exactly the "wrong surface"
                # failure mode behind #165/#166 -- refuse instead of guessing.
                continue
```

with:

```python
            choice = self.route(task_tags, self.manifests)

            broker = self.engine_context.get(choice.engine_id)
            if not broker.has_provider:
                # No adapter registered for this engine_id (ADR-026/027) --
                # e.g. route() chose "claude-direct", which this v1 daemon
                # has no invoker for (routing.hermes_invoker's own docstring:
                # "claude-direct has no headless invocation here"). Silently
                # dispatching to whatever IS registered instead is exactly
                # the "wrong surface" failure mode behind #165/#166 -- refuse
                # instead of guessing.
                continue
```

And replace:

```python
            head_before = self.git_head(self.workdir)
            try:
                invoke_result = self.invoke_hermes(
                    "researcher" if "research" in task_tags else "builder",
                    issue["title"], timeout_seconds=300,
                )
            except HermesInvocationError as error:
```

with:

```python
            head_before = self.git_head(self.workdir)
            try:
                invoke_result = broker.invoke(
                    "researcher" if "research" in task_tags else "builder",
                    issue["title"], timeout_seconds=300,
                )
            except HermesInvocationError as error:
```

Everything else in `run_once()` and `run_forever()` is unchanged.

- [ ] **Step 4: Run the full daemon test suite to verify it passes**

Run: `python -m pytest tests/daemon/ -v`
Expected: all passed, 0 failed (same test count as before this task — no tests added or removed, only the DI seam changed).

- [ ] **Step 5: Commit**

```bash
git add agent-platform/daemon/loop.py agent-platform/tests/daemon/test_loop.py
git commit -m "refactor(daemon): route DaemonLoop invocation through EngineContext broker"
```

---

### Task 7: Full-suite verification and ADR validation checklist cross-check

**Files:** none created or modified — verification only.

- [ ] **Step 1: Run the full test suite**

Run (from `agent-platform/`): `python -m pytest tests/ -q`
Expected: 558 + (new tests from Tasks 1–6: 2+6+4+3+5 = 20) = 578 passed, 14 skipped, 0 failed. (`test_loop.py`'s test count is unchanged from baseline — Task 6 only renamed a DI seam, added no new test cases.)

- [ ] **Step 2: Confirm `route()`/`engine_manifest.py` has zero diff**

Run: `git diff main -- agent-platform/routing/engine_manifest.py`
Expected: empty output. If non-empty, stop and find which task touched it — that task is wrong per this plan's Global Constraints.

- [ ] **Step 3: Confirm `hermes_invoker.py`'s function body is unmodified**

Run: `git diff main -- agent-platform/routing/hermes_invoker.py`
Expected: empty output.

- [ ] **Step 4: Walk ADR-026's Validation checklist against the actual diff**

Open `docs/adr/026-engine-adapter-registry-separate-from-route-selection.md`'s `## Validation` section and confirm each line against the real code (not against this plan's description of it):
- `EngineAdapter` protocol and `EngineContext` registry implemented and tested — Tasks 1, 2.
- `HermesAdapter` repackages `invoke_hermes()` without changing its tested behavior — Task 3's `test_invoke_delegates_to_injected_invoke_hermes_unchanged` and `test_invoke_propagates_hermes_invocation_error_unwrapped`.
- `unified_cli.py:338–359`'s if/elif chain removed, replaced by `engine_context.get(...).invoke(...)` — Task 5 (grep the file to confirm the literal string `choice.engine_id == "hermes"` no longer appears).
- `route()`/`engine_manifest.py` unchanged (diff shows zero changes) — Step 2 above.

- [ ] **Step 5: Walk ADR-027's Validation checklist against the actual diff**

Open `docs/adr/027-engine-context-adopts-service-broker-not-exclusive-binding.md`'s `## Validation` section:
- `EngineContext.get(engine_id)` returns an `EngineBroker`, not an adapter directly — Task 2's `test_context_get_returns_broker_for_unknown_engine_id`.
- Broker with one registered provider behaves identically to a direct call (no extra side effects, no measurable overhead beyond a method hop) — Task 2's `test_broker_with_one_provider_passes_through`.
- `unified_cli.py`'s call surface (`engine_context.get(...).invoke(...)`) matches ADR-026's sketch — Task 5.
- No routing policy (round-robin/weighting) implemented until a second provider is actually registered under the same key — confirmed by inspection of `EngineBroker.invoke()` (Task 2): it unconditionally uses `self._providers[0]`.

- [ ] **Step 6: Grep for any remaining hardcoded engine_id string comparisons outside route()/engine_manifest.py**

Run: `grep -rn 'engine_id == "hermes"\|engine_id != "hermes"\|engine_id == "claude-direct"' agent-platform/cli/ agent-platform/daemon/`
Expected: no matches (the only remaining `engine_id == "claude-direct"` string comparison is the one inside `_run_dispatch`'s `else` branch that picks the human-readable blocked-reason message — that one is fine, it's choosing a message, not deciding whether to invoke).

No commit for this task — it is a verification pass. If any step surfaces a discrepancy, fix it as a follow-up commit referencing the specific ADR validation line it satisfies.

---

### Task 8 (added during Task 7's full-suite run — regression fix): `HermesAdapter` must resolve its default `invoke_hermes` lazily, not freeze it at import time

**Discovered:** Task 7 Step 1's full-suite run (`python -m pytest tests/ -q`) returned 566 passed, 14 skipped, **11 failed** — all 11 failures confined to `agent-platform/tests/cli/test_dispatch.py`, a pre-existing 324-line, ~17-test file this plan's own file-structure survey missed (the grep used while writing this plan, `grep -rln "_run_dispatch\|run_dispatch" tests/`, does not match this file's content — it calls `cli.unified_cli.main([...])` end-to-end, never the literal string `_run_dispatch`).

**Root cause:** every test in that file uses `unittest.mock.patch("routing.hermes_invoker.invoke_hermes", ...)` around a call to `main([...])`, expecting that patch to intercept the real Hermes call. Before Task 3, `unified_cli.py` called `hermes_invoker.invoke_hermes(...)` directly by attribute lookup on the `routing.hermes_invoker` module at call time, so the patch worked. After Task 3/5, the call goes through `HermesAdapter.invoke()`, whose `__init__` signature is `def __init__(self, invoke_hermes: Callable = _default_invoke_hermes)` — `_default_invoke_hermes` is a name bound via `from routing.hermes_invoker import invoke_hermes as _default_invoke_hermes` at the top of `runtime/adapters/hermes_adapter.py`. Python evaluates a default-argument expression exactly once, when the `def` statement executes (i.e. when `hermes_adapter.py` is first imported) — the resulting function *object* is frozen into `HermesAdapter.__init__.__defaults__`. `unittest.mock.patch("routing.hermes_invoker.invoke_hermes", ...)` replaces the attribute on the `routing.hermes_invoker` *module object* after that point; it cannot reach back and change a default value some other module already captured by reference. No `patch(...)` target existed that could affect `HermesAdapter()`'s bare-default behavior — a real, load-bearing regression against an existing test suite, not a false positive.

**Fix:** make `HermesAdapter`'s bare-default path resolve `routing.hermes_invoker.invoke_hermes` by *live module-attribute lookup at call time* instead of by frozen constructor default. Explicit injection (`HermesAdapter(invoke_hermes=fake_fn)`, used by Task 3's own tests) is unaffected — it still takes priority. This is the smallest change that fixes the regression without touching `test_dispatch.py` at all (its `patch("routing.hermes_invoker.invoke_hermes", ...)` calls become valid again unmodified, because the lookup now genuinely reads that module attribute at call time).

**Files:**
- Modify: `agent-platform/runtime/adapters/hermes_adapter.py` (all of it — full rewrite, still ~25 lines)
- Modify: `agent-platform/tests/runtime/adapters/test_hermes_adapter.py` — one test (`test_default_constructor_uses_real_invoke_hermes`) must change; the other three are unaffected.
- No other file changes. `tests/cli/test_dispatch.py` is NOT modified by this task — it passing unmodified is this task's actual acceptance criterion.

**Interfaces:**
- Consumes: `routing.hermes_invoker` (the module itself, not just its `invoke_hermes` name).
- Produces: `HermesAdapter` — same public shape as Task 3 (`__init__(self, invoke_hermes: Callable | None = None)`, `.invoke(...)`), but the constructor's default is now `None`, and `.invoke()` resolves the real function at call time when no explicit one was injected. Callers from Task 4/5/6 (`build_default_engine_context()`, `_run_dispatch`, `DaemonLoop`) are unaffected — none of them pass `invoke_hermes=` explicitly, so they all get the live-lookup path, which behaves identically to before except that it is now interceptable by `unittest.mock.patch`.

- [ ] **Step 1: Write the failing test — replace `test_default_constructor_uses_real_invoke_hermes`**

In `agent-platform/tests/runtime/adapters/test_hermes_adapter.py`, replace this existing test:

```python
def test_default_constructor_uses_real_invoke_hermes():
    import runtime.adapters.hermes_adapter as module
    from routing.hermes_invoker import invoke_hermes as real_invoke_hermes

    adapter = module.HermesAdapter()
    assert adapter._invoke_hermes is real_invoke_hermes
```

with:

```python
def test_default_constructor_delegates_to_live_hermes_invoker_module_lookup():
    from unittest.mock import patch

    fake_result = {"status": "succeeded", "profile": "builder"}
    adapter = HermesAdapter()
    with patch("routing.hermes_invoker.invoke_hermes", return_value=fake_result) as fake:
        result = adapter.invoke("builder", "do it", timeout_seconds=60)
    fake.assert_called_once_with("builder", "do it", timeout_seconds=60, model=None, provider=None)
    assert result == fake_result


def test_explicit_invoke_hermes_still_takes_priority_over_live_lookup():
    from unittest.mock import patch

    calls = []

    def explicit_fn(profile, prompt, *, timeout_seconds, model=None, provider=None):
        calls.append((profile, prompt, timeout_seconds, model, provider))
        return {"status": "succeeded", "profile": profile}

    adapter = HermesAdapter(invoke_hermes=explicit_fn)
    with patch("routing.hermes_invoker.invoke_hermes") as unused_patch:
        adapter.invoke("builder", "do it", timeout_seconds=60)
    unused_patch.assert_not_called()
    assert calls == [("builder", "do it", 60, None, None)]
```

(Both new tests replace the one old test — the file goes from 4 tests to 5.)

- [ ] **Step 2: Run the test file to verify the first new test fails**

Run: `python -m pytest tests/runtime/adapters/test_hermes_adapter.py -v`
Expected: `test_default_constructor_delegates_to_live_hermes_invoker_module_lookup` FAILS (the current `HermesAdapter()` binds the real, unpatched function at construction time, so `fake.assert_called_once_with(...)` fails because the mock was never called). `test_explicit_invoke_hermes_still_takes_priority_over_live_lookup` PASSES already (explicit injection already worked). The other 3 pre-existing tests still pass.

- [ ] **Step 3: Rewrite `runtime/adapters/hermes_adapter.py`**

Replace the entire file with:

```python
"""Wraps routing.hermes_invoker.invoke_hermes as an EngineAdapter (ADR-026
point 3: "befintlig invocation-kod paketeras om, skrivs inte om" -- existing
invocation code is repackaged, not rewritten. This class adds no logic
beyond the delegation itself; invoke_hermes's tested subprocess behavior,
including HermesInvocationError, passes through unchanged.

The default path resolves routing.hermes_invoker.invoke_hermes by live
module-attribute lookup at call time, not by binding the function object as
a constructor default -- a default-argument expression is evaluated once,
at class-definition time, and freezing it here would make
unittest.mock.patch("routing.hermes_invoker.invoke_hermes", ...) unable to
intercept calls made through HermesAdapter's bare default (a real
regression found in agent-platform/tests/cli/test_dispatch.py, a
pre-existing suite that patches exactly that target around real
cli.unified_cli.main([...]) calls). Explicit injection
(HermesAdapter(invoke_hermes=fake_fn)) is unaffected by this and still
takes priority -- it is only the "no argument given" path that now does a
live lookup instead of a frozen one.
"""
from __future__ import annotations

from typing import Callable

import routing.hermes_invoker as _hermes_invoker_module


class HermesAdapter:
    def __init__(self, invoke_hermes: Callable | None = None) -> None:
        self._invoke_hermes = invoke_hermes

    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict:
        invoke_fn = self._invoke_hermes or _hermes_invoker_module.invoke_hermes
        return invoke_fn(
            profile, prompt, timeout_seconds=timeout_seconds, model=model, provider=provider
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/runtime/adapters/test_hermes_adapter.py -v`
Expected: 5 passed (the 2 new + `test_hermes_adapter_is_an_engine_adapter` + `test_invoke_delegates_to_injected_invoke_hermes_unchanged` + `test_invoke_propagates_hermes_invocation_error_unwrapped`, all still green).

- [ ] **Step 5: Run the full suite to confirm the regression is gone**

Run (from `agent-platform/`): `python -m pytest tests/ -q`
Expected: 0 failed. Total passed count is 578 (Task 7's expected count) − 1 (old `test_default_constructor_uses_real_invoke_hermes` removed) + 2 (two new tests added) = 579, plus the 11 `test_dispatch.py` tests that were failing now pass again (they were already counted in the "passed" bucket of earlier runs when Tasks 1-6 were reviewed in isolation — they only started failing once Task 5 wired the real `build_default_engine_context()` into `unified_cli.py`'s production path, which is why Task 7's full run was the first point they could fail). Report the exact final `passed`/`skipped`/`failed` line from this run — do not assume the arithmetic above is exact; the real pytest summary line is the source of truth.

- [ ] **Step 6: Commit**

```bash
git add agent-platform/runtime/adapters/hermes_adapter.py agent-platform/tests/runtime/adapters/test_hermes_adapter.py
git commit -m "fix(runtime): resolve HermesAdapter's default invoke_hermes lazily, not at import time

Fixes a regression against agent-platform/tests/cli/test_dispatch.py,
discovered by Task 7's full-suite run: patch(\"routing.hermes_invoker.invoke_hermes\")
could not intercept calls made through HermesAdapter's frozen constructor
default. Explicit injection is unaffected."
```

No `tests/cli/test_dispatch.py` changes in this commit — that file passing unmodified is how this task is verified.
