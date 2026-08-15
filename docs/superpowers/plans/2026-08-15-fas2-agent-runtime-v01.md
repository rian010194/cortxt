# Fas 2 — Agent Runtime v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Fas 2's exit criterion from the target-architecture staircase — "a research fixture can be solved without Hermes" — by building a minimal Agent Runtime that runs one AI Act classification fixture end-to-end: claim → admit a real tool → call the reasoning kernel (extended with a model-assisted path) → validate the result against a JSON Schema → resumable session state → result envelope.

**Architecture:** New `agent-platform/runtime/` package with five focused modules (session state, a text-output inference port, a tool-admission gate, a static profile config, and the orchestrating loop), plus an additive (non-breaking) extension to the existing reasoning kernel adding a `MODEL_ASSISTED` strategy. Everything else (the AI Act vertical's schemas/instructions/fixtures, the existing `BudgetGate`/`provider_policy`) is reused unmodified.

**Tech Stack:** Python 3.12, pytest, stdlib only for session state (hashlib/json/tempfile/os), `jsonschema` for output validation (new dependency — see Task 3), the existing `agent-platform/inference/provider_policy.py` and `adapters/inference/budget_gate.py`.

## Global Constraints

- 0 real model calls in any test that runs in default CI (mirrors the whole repo's existing convention: `real_inference` pytest marker, excluded by default).
- No modification to any existing passing test or existing kernel solver (`_solve_direct`/`_solve_recursive`/`_solve_geometric`, `select_strategy`) — the kernel extension is purely additive.
- `reasoning/` must still pass `agent-platform/tests/reasoning/test_no_external_deps.py` after the extension — no new top-level imports beyond stdlib in `reasoning/kernel/*.py`.
- Every new dependency (`jsonschema`) must be declared in `agent-platform/pyproject.toml`'s `dependencies` AND added to `.github/workflows/ci.yml`'s install step in the same commit that starts using it — the PR #135 CI failure (undeclared PyYAML) must not repeat.
- Every file path below is relative to the repo root `C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane`.
- Run all tests from `agent-platform/` (matches its `pyproject.toml` `testpaths`/`pythonpath` config): `cd agent-platform && py -m pytest <path> -v`.
- Per [[feedback_dispatch_hermes]]: this build work should be dispatched to Hermes Builder per-task from a literal, pre-written spec (each task below is written to be handed to Hermes verbatim), with the plan owner (Claude) verifying every result independently before moving to the next task — not trusting Hermes's own summary.

---

### Task 1: Session state module

**Files:**
- Create: `agent-platform/runtime/__init__.py`
- Create: `agent-platform/runtime/session_state.py`
- Create: `agent-platform/tests/runtime/__init__.py`
- Test: `agent-platform/tests/runtime/test_session_state.py`

**Interfaces:**
- Produces: `SessionError(Exception)` with `.category: str`, `.message: str`; module functions `canonical_json(value: Any) -> bytes`, `utc_now() -> str`, `create(store: Path, task_id: str) -> dict` (returns the full session document), `append(store: Path, session_id: str, expected_sequence: int, event_type: str, payload: dict) -> dict` (returns the full updated session document), `load(store: Path, session_id: str) -> dict` (returns the full session document after hash-chain validation), `latest_sequence(session: dict) -> int`.
- A "session document" shape: `{"schema_version": 1, "session_id": str, "events": [event, ...]}`. Each event: `{"sequence": int, "event_type": str, "payload": dict, "previous_hash": str, "timestamp": str (UTC, microsecond ISO8601 with "Z"), "hash": str (sha256 hex of the other 6 fields as canonical JSON)}`. First event is always `event_type="session.created"`, `sequence=0`, `previous_hash="0"*64`.

- [ ] **Step 1: Write the failing test**

Create `agent-platform/tests/runtime/__init__.py` (empty file — matches the existing convention every other `agent-platform/tests/*/` subdir has one, per the PR #135 review finding that a missing `__init__.py` is a real gap).

Create `agent-platform/tests/runtime/test_session_state.py`:

```python
"""Session state: create/append/load/resume with a hash-chained, atomic-write log."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from runtime import session_state as s


def _store(tmp_path):
    d = tmp_path / "sessions"
    d.mkdir()
    return d


def test_create_returns_session_with_one_event():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="synth-classify-001")
    assert doc["schema_version"] == 1
    assert doc["session_id"].startswith("session_")
    assert len(doc["events"]) == 1
    ev = doc["events"][0]
    assert ev["sequence"] == 0
    assert ev["event_type"] == "session.created"
    assert ev["payload"] == {"task_id": "synth-classify-001"}
    assert ev["previous_hash"] == "0" * 64


def test_append_extends_chain_and_persists():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    doc2 = s.append(store, doc["session_id"], expected_sequence=0,
                     event_type="tool.admitted", payload={"tool": "read_fixture_file"})
    assert len(doc2["events"]) == 2
    assert doc2["events"][1]["sequence"] == 1
    assert doc2["events"][1]["previous_hash"] == doc2["events"][0]["hash"]


def test_append_rejects_wrong_expected_sequence():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    with pytest.raises(s.SessionError) as exc:
        s.append(store, doc["session_id"], expected_sequence=5,
                  event_type="tool.admitted", payload={})
    assert exc.value.category == "sequence_conflict"


def test_load_resumes_and_validates_chain():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    s.append(store, doc["session_id"], expected_sequence=0,
              event_type="tool.admitted", payload={"tool": "read_fixture_file"})
    reloaded = s.load(store, doc["session_id"])
    assert len(reloaded["events"]) == 2
    assert s.latest_sequence(reloaded) == 1


def test_load_detects_tampered_event():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    path = store / doc["session_id"] / "session.json"
    tampered = path.read_text(encoding="utf-8").replace("t1", "t1-TAMPERED")
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(s.SessionError) as exc:
        s.load(store, doc["session_id"])
    assert exc.value.category == "integrity_error"


def test_load_unknown_session_not_found():
    store = _store(Path(tempfile.mkdtemp()))
    with pytest.raises(s.SessionError) as exc:
        s.load(store, "session_doesnotexist")
    assert exc.value.category == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && py -m pytest tests/runtime/test_session_state.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'runtime'`.

- [ ] **Step 3: Write minimal implementation**

Create `agent-platform/runtime/__init__.py` (empty).

Create `agent-platform/runtime/session_state.py`:

```python
"""Append-only, hash-chained, resumable session state for Agent Runtime.

Ports the proven primitives from agent-platform/state/ledger.py (atomic
write via tempfile+os.replace, sha256 event-chain, optimistic-concurrency
append) as Agent Runtime's own code — session persistence and resume is
Agent Runtime's responsibility per the target architecture (§8.2), not a
delegated concern of a separate module. See
docs/superpowers/specs/2026-08-15-fas2-agent-runtime-v01-design.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64
SESSION_ID_RE = re.compile(r"^session_[0-9a-f]{32}$")
EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class SessionError(Exception):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _session_path(store: Path, session_id: str) -> Path:
    if not SESSION_ID_RE.fullmatch(session_id):
        raise SessionError("invalid_input", "invalid session_id")
    return store / session_id / "session.json"


def _event(sequence: int, event_type: str, payload: dict, previous_hash: str) -> dict:
    if not EVENT_TYPE_RE.fullmatch(event_type):
        raise SessionError("invalid_input", "invalid event_type")
    unsigned = {
        "sequence": sequence,
        "event_type": event_type,
        "payload": payload,
        "previous_hash": previous_hash,
        "timestamp": utc_now(),
    }
    digest = hashlib.sha256(canonical_json(unsigned)).hexdigest()
    return {**unsigned, "hash": digest}


def _atomic_write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json(doc) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as error:
        raise SessionError("io_error", "could not persist session") from error
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def create(store: Path, task_id: str) -> dict:
    if not isinstance(task_id, str) or not task_id.strip():
        raise SessionError("invalid_input", "task_id must be a non-empty string")
    session_id = "session_" + uuid.uuid4().hex
    doc = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "events": [_event(0, "session.created", {"task_id": task_id}, ZERO_HASH)],
    }
    _atomic_write(_session_path(store, session_id), doc)
    return doc


def _validate_chain(doc: dict, session_id: str) -> None:
    if not isinstance(doc, dict) or set(doc) != {"schema_version", "session_id", "events"}:
        raise SessionError("integrity_error", "session has an invalid shape")
    if doc["schema_version"] != SCHEMA_VERSION or doc["session_id"] != session_id:
        raise SessionError("integrity_error", "session identity is invalid")
    previous = ZERO_HASH
    fields = {"sequence", "event_type", "payload", "previous_hash", "timestamp", "hash"}
    for i, event in enumerate(doc["events"]):
        if not isinstance(event, dict) or set(event) != fields:
            raise SessionError("integrity_error", "event has an invalid shape")
        if event["sequence"] != i or event["previous_hash"] != previous:
            raise SessionError("integrity_error", "event sequence or chain is invalid")
        unsigned = {k: event[k] for k in fields if k != "hash"}
        expected = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        if event["hash"] != expected:
            raise SessionError("integrity_error", "event hash is invalid")
        previous = event["hash"]


def load(store: Path, session_id: str) -> dict:
    path = _session_path(store, session_id)
    if not path.is_file():
        raise SessionError("not_found", "session was not found")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise SessionError("integrity_error", "session is not valid JSON") from error
    _validate_chain(doc, session_id)
    return doc


def append(store: Path, session_id: str, expected_sequence: int, event_type: str, payload: dict) -> dict:
    doc = load(store, session_id)
    current = len(doc["events"]) - 1
    if current != expected_sequence:
        raise SessionError("sequence_conflict",
                            f"expected sequence {expected_sequence}, found {current}")
    doc["events"].append(_event(current + 1, event_type, payload, doc["events"][-1]["hash"]))
    _atomic_write(_session_path(store, session_id), doc)
    return doc


def latest_sequence(session: dict) -> int:
    return len(session["events"]) - 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-platform && py -m pytest tests/runtime/test_session_state.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/__init__.py agent-platform/runtime/session_state.py agent-platform/tests/runtime/__init__.py agent-platform/tests/runtime/test_session_state.py
git commit -m "feat(runtime): add hash-chained, resumable session state (Fas 2)"
```

---

### Task 2: Reasoning kernel extension — model-assisted strategy

**Files:**
- Modify: `agent-platform/reasoning/kernel/strategy.py`
- Modify: `agent-platform/reasoning/kernel/operators.py`
- Modify: `agent-platform/reasoning/kernel/engine.py`
- Test: `agent-platform/tests/reasoning/kernel/test_model_assisted.py`

**Interfaces:**
- Consumes: `ProblemState`, `new_problem` from `.problem_state` (unchanged).
- Produces: `Strategy.MODEL_ASSISTED` enum member; `operators.inspect_with_model(state: ProblemState, invoke: Callable[[Any], Any]) -> OperatorResult`; `operators.verify_against_schema(state: ProblemState, validate: Callable[[Any], bool]) -> OperatorResult`; `Engine.solve_model_assisted(self, content: Any, invoke: Callable[[Any], Any], validate: Callable[[Any], bool]) -> Result` (same `Result` dict shape as `Engine.solve`: `{"strategy", "value", "confidence", "steps"}`).

- [ ] **Step 1: Write the failing test**

Create `agent-platform/tests/reasoning/kernel/test_model_assisted.py`:

```python
"""Model-assisted strategy: additive extension, does not touch DM1's numeric solvers.

AC: inspect delegates to an injected callable (no arithmetic), verify delegates
to an injected validator (no fallback summation), and existing solve() behavior
for DIRECT/RECURSIVE/GEOMETRIC content is completely unaffected.
"""
from reasoning.kernel import Engine, Strategy
from reasoning.kernel.operators import inspect_with_model, verify_against_schema
from reasoning.kernel.problem_state import new_problem


def test_inspect_with_model_delegates_to_callable():
    state = new_problem({"case_id": "SYNTH-1"})
    result = inspect_with_model(state, invoke=lambda content: {"classification": "high_risk"})
    assert result.value == {"classification": "high_risk"}
    assert state._computed == {"classification": "high_risk"}
    assert "inspect_with_model" in state.transformation_log[-1]


def test_verify_against_schema_true():
    state = new_problem({"case_id": "SYNTH-1"})
    state._computed = {"classification": "high_risk"}
    result = verify_against_schema(state, validate=lambda v: v["classification"] == "high_risk")
    assert result.value == {"classification": "high_risk"}
    assert state.confidence == 1.0


def test_verify_against_schema_false_does_not_fall_back_to_arithmetic():
    state = new_problem({"case_id": "SYNTH-1"})
    state._computed = {"classification": "wrong"}
    result = verify_against_schema(state, validate=lambda v: v["classification"] == "high_risk")
    assert state.confidence == 0.0
    assert result.value == {"classification": "wrong"}  # unchanged, no summation attempted


def test_engine_solve_model_assisted_end_to_end():
    engine = Engine()
    result = engine.solve_model_assisted(
        content={"case_id": "SYNTH-1"},
        invoke=lambda content: {"classification": "high_risk"},
        validate=lambda v: v.get("classification") == "high_risk",
    )
    assert result["strategy"] == "model_assisted"
    assert result["value"] == {"classification": "high_risk"}
    assert result["confidence"] == 1.0
    assert len(result["steps"]) == 2  # inspect_with_model, verify_against_schema


def test_existing_direct_strategy_unaffected():
    # Regression guard: DM1's numeric solve() must still work exactly as before.
    engine = Engine()
    result = engine.solve([1, 2, 3])
    assert result["strategy"] == "direct"
    assert result["value"] == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && py -m pytest tests/reasoning/kernel/test_model_assisted.py -v`
Expected: FAIL — `ImportError: cannot import name 'inspect_with_model'` (and `solve_model_assisted` not found).

- [ ] **Step 3: Write minimal implementation**

In `agent-platform/reasoning/kernel/strategy.py`, add `MODEL_ASSISTED = "model_assisted"` to the `Strategy` enum, immediately after `GEOMETRIC = "geometric"`:

```python
class Strategy(str, Enum):
    DIRECT = "direct"
    RECURSIVE = "recursive"
    GEOMETRIC = "geometric"
    MODEL_ASSISTED = "model_assisted"
    HUMAN_ESCALATION = "human_escalation"
```

Do not modify `select_strategy()` — `MODEL_ASSISTED` is never auto-selected from content shape; it is only reached via the new explicit `Engine.solve_model_assisted` entry point added below.

In `agent-platform/reasoning/kernel/operators.py`, add these two functions at the end of the file (after `verify`):

```python
def inspect_with_model(state: ProblemState, invoke) -> OperatorResult:
    """Read content by delegating to an external callable instead of flattening scalars.

    ``invoke`` is ``Callable[[Any], Any]``: takes the state's content, returns
    the model's raw response. Unlike ``inspect()``, this never touches
    arithmetic — the model performs the "reading" this operator would
    otherwise flatten deterministically.
    """
    response = invoke(state.content)
    state._computed = response  # type: ignore[attr-defined]
    state.record("inspect_with_model", "inspected content via an external model call")
    return OperatorResult(response)


def verify_against_schema(state: ProblemState, validate) -> OperatorResult:
    """Confirm ``state._computed`` satisfies an external validator; confidence 1.0/0.0.

    ``validate`` is ``Callable[[Any], bool]`` (e.g. JSON Schema validation).
    Unlike ``verify()``, this never falls back to summing ``state.content``.
    """
    computed = getattr(state, "_computed", None)
    ok = bool(validate(computed))
    state.confidence = 1.0 if ok else 0.0
    state.record("verify_against_schema", f"validated with confidence {state.confidence:.2f}")
    return OperatorResult(computed)
```

In `agent-platform/reasoning/kernel/engine.py`:

1. Add to the import line `from .operators import OperatorResult, decompose, inspect, integrate, verify`, changing it to also import the two new operators:

```python
from .operators import (
    OperatorResult,
    decompose,
    inspect,
    inspect_with_model,
    integrate,
    verify,
    verify_against_schema,
)
```

2. Add a new solver function, placed after `_solve_geometric` and before the `_SOLVERS` dict:

```python
def _solve_model_assisted(state: ProblemState, invoke, validate) -> OperatorResult:
    inspect_with_model(state, invoke)
    return verify_against_schema(state, validate)
```

3. Add a new public method to the `Engine` class, after `solve`:

```python
    def solve_model_assisted(self, content, invoke, validate) -> Result:
        """Explicit entry point for MODEL_ASSISTED — never auto-selected by
        select_strategy(), always invoked directly by a caller that has a
        real inference callable and a real output validator (e.g. Agent
        Runtime's agent_loop)."""
        state = new_problem(content)
        result = _solve_model_assisted(state, invoke, validate)
        return {
            "strategy": Strategy.MODEL_ASSISTED.value,
            "value": result.value,
            "confidence": state.confidence,
            "steps": state.transformation_log,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-platform && py -m pytest tests/reasoning/kernel/test_model_assisted.py -v`
Expected: 5 passed.

Then run the full reasoning suite to confirm nothing existing broke:

Run: `cd agent-platform && py -m pytest tests/reasoning/ -v`
Expected: all previously-passing tests still pass (58+ tests), including `tests/reasoning/test_no_external_deps.py`.

- [ ] **Step 5: Commit**

```bash
git add agent-platform/reasoning/kernel/strategy.py agent-platform/reasoning/kernel/operators.py agent-platform/reasoning/kernel/engine.py agent-platform/tests/reasoning/kernel/test_model_assisted.py
git commit -m "feat(reasoning): additive MODEL_ASSISTED strategy for external inference callers (Fas 2)"
```

---

### Task 3: Text-output inference port

**Files:**
- Create: `agent-platform/runtime/text_inference_port.py`
- Test: `agent-platform/tests/runtime/test_text_inference_port.py`
- Modify: `agent-platform/pyproject.toml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `adapters.inference.budget_gate.BudgetGate`, `adapters.inference.budget_gate.BudgetExhausted` (existing, unmodified); `inference.provider_policy.evaluate_provider`, `ProviderEvidence` (existing, unmodified).
- Produces: `class TextInferenceError(RuntimeError)`; `class TextInferencePort` with `__init__(self, model: str, budget_gate: BudgetGate, provider_evidence: dict, data_class: str = "L0")` and `def invoke(self, prompt: str, output_schema: dict) -> dict` — raises `TextInferenceError` on policy denial or unavailable backend, raises `BudgetExhausted` (re-exported, not wrapped) when the gate blocks, otherwise returns the parsed JSON response as a `dict`. `output_schema` is passed to the provider as a best-effort hint only — this port does NOT validate the response against it; that is `verify_against_schema`'s job (Task 2), called by `agent_loop.py` (Task 5).

- [ ] **Step 1: Write the failing test**

Create `agent-platform/tests/runtime/test_text_inference_port.py`:

```python
"""TextInferencePort: real-inference gate + provider-policy check, no schema
validation here (that is verify_against_schema's job, called by agent_loop).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from adapters.inference.budget_gate import BudgetExhausted, BudgetGate
from runtime.text_inference_port import TextInferenceError, TextInferencePort


def _gate(tmp_path, max_calls):
    return BudgetGate(max_calls=max_calls, db_path=tmp_path / "spend.db")


def test_invoke_denied_by_provider_policy(tmp_path):
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": False, "provider_id": "untrusted"},
        data_class="L2",
    )
    with pytest.raises(TextInferenceError) as exc:
        port.invoke("classify this", output_schema={"type": "object"})
    assert "policy" in str(exc.value).lower()


def test_invoke_blocked_by_budget_before_any_backend_call(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        "runtime.text_inference_port.TextInferencePort._call_backend",
        lambda self, prompt, schema: called.append(1) or {"ok": True},
    )
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=0),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    with pytest.raises(BudgetExhausted):
        port.invoke("classify this", output_schema={"type": "object"})
    assert called == []  # backend never reached


def test_invoke_success_returns_parsed_backend_response(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "runtime.text_inference_port.TextInferencePort._call_backend",
        lambda self, prompt, schema: {"classification": "high_risk"},
    )
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    result = port.invoke("classify this", output_schema={"type": "object"})
    assert result == {"classification": "high_risk"}


def test_invoke_raises_when_backend_package_unavailable(tmp_path):
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    # No monkeypatch: real _call_backend runs, cortxt_resilient_inference is not
    # installed in the default dev/CI environment, so this must fail closed with
    # a clear TextInferenceError, never a silent fabricated response.
    with pytest.raises(TextInferenceError) as exc:
        port.invoke("classify this", output_schema={"type": "object"})
    assert "unavailable" in str(exc.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && py -m pytest tests/runtime/test_text_inference_port.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'runtime.text_inference_port'`.

- [ ] **Step 3: Write minimal implementation**

Add `jsonschema` to `agent-platform/pyproject.toml`'s dependencies line (this task doesn't call `jsonschema` directly yet — Task 5 does — but declaring it here, in the same PR that will use it, keeps the dependency declaration next to the first task that needs it; if Task 5 is done in the same PR this is fine, if split across PRs move this line to Task 5 instead). Change:

```toml
dependencies = ["pyyaml>=6"]
```
to:
```toml
dependencies = ["pyyaml>=6", "jsonschema>=4"]
```

In `.github/workflows/ci.yml`, change:
```yaml
      - run: pip install pytest pyyaml
```
to:
```yaml
      - run: pip install pytest pyyaml jsonschema
```

Create `agent-platform/runtime/text_inference_port.py`:

```python
"""TextInferencePort — text/structured-JSON model invocation for Agent Runtime.

Distinct from reasoning/recursive/rlm_engine.py's InferencePort
(invoke(content) -> int), which is scoped to the DM1-DM4 abstract reasoning
proof. This port returns a real parsed dict response and is what
agent_loop.py (Task 5) wires into the kernel's new MODEL_ASSISTED strategy
(Task 2) via inspect_with_model's `invoke` callable.

Fail-closed on two independent gates, both checked before any network call:
budget (BudgetGate, adapters/inference/budget_gate.py) and provider policy
(inference/provider_policy.py, ADR-016). Never fabricates a response when the
optional backend package is unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from adapters.inference.budget_gate import BudgetGate

_INFERENCE_DIR = Path(__file__).resolve().parent.parent / "inference"
if str(_INFERENCE_DIR) not in sys.path:
    sys.path.insert(0, str(_INFERENCE_DIR))
from provider_policy import AssuranceStatus, ProviderEvidence, evaluate_provider  # noqa: E402

try:
    from cortxt_resilient_inference import execute as _resilient_execute
    from cortxt_resilient_inference.http_adapter import OpenAICompatibleAdapter as _HttpAdapter

    _RI_AVAILABLE = True
except Exception:  # pragma: no cover - only when the optional dep is absent
    _RI_AVAILABLE = False


class TextInferenceError(RuntimeError):
    """Raised on provider-policy denial or an unavailable/failed backend (fail-closed)."""


class TextInferencePort:
    def __init__(self, model: str, budget_gate: BudgetGate, provider_evidence: dict,
                 data_class: str = "L0") -> None:
        self._model = model
        self._gate = budget_gate
        evidence = dict(provider_evidence)
        status = evidence.get("independent_assurance")
        if isinstance(status, str):
            try:
                evidence["independent_assurance"] = AssuranceStatus(status)
            except ValueError:
                pass
        try:
            decision = evaluate_provider(data_class, ProviderEvidence(**evidence))
        except (TypeError, ValueError) as error:
            raise TextInferenceError(f"provider evidence has an invalid schema: {error}") from error
        if decision.allowed is not True:
            raise TextInferenceError(f"provider policy denied this port: {decision.reasons}")

    def invoke(self, prompt: str, output_schema: dict) -> dict:
        return self._gate(self._call_backend, prompt, output_schema)

    def _call_backend(self, prompt: str, output_schema: dict) -> dict:
        if not _RI_AVAILABLE:
            raise TextInferenceError(
                "cortxt_resilient_inference is unavailable in this environment; "
                "install it and configure CORTXT_INFERENCE_URL/CORTXT_INFERENCE_API_KEY"
            )
        adapter = _HttpAdapter()
        result: Any = _resilient_execute(model=self._model, prompt=prompt,
                                          output_schema=output_schema, adapter=adapter)
        if not isinstance(result, dict):
            raise TextInferenceError("backend returned a non-object response")
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-platform && py -m pytest tests/runtime/test_text_inference_port.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/text_inference_port.py agent-platform/tests/runtime/test_text_inference_port.py agent-platform/pyproject.toml .github/workflows/ci.yml
git commit -m "feat(runtime): add TextInferencePort, fail-closed on budget/policy, declare jsonschema dep (Fas 2)"
```

---

### Task 4: Tool admission gate + read_fixture_file

**Files:**
- Create: `agent-platform/runtime/tools.py`
- Test: `agent-platform/tests/runtime/test_tools.py`

**Interfaces:**
- Produces: `class ToolAdmissionError(Exception)`; `class ToolGate` with `__init__(self, allowed_roots: list[Path])` and `def admit(self, tool_name: str, path: str) -> Path` (returns the resolved, validated path or raises `ToolAdmissionError`); `def read_fixture_file(gate: ToolGate, path: str) -> dict` (admits then reads+parses JSON, returns the parsed dict).

- [ ] **Step 1: Write the failing test**

Create `agent-platform/tests/runtime/test_tools.py`:

```python
"""Tool admission gate: sandboxed to allowed_roots, rejects traversal, real read tool."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tools import ToolAdmissionError, ToolGate, read_fixture_file


def _fixture_dir(tmp_path):
    d = tmp_path / "fixtures"
    d.mkdir()
    (d / "case.json").write_text(json.dumps({"case_id": "SYNTH-1"}), encoding="utf-8")
    return d


def test_admit_accepts_path_inside_allowed_root(tmp_path):
    fdir = _fixture_dir(tmp_path)
    gate = ToolGate(allowed_roots=[fdir])
    resolved = gate.admit("read_fixture_file", str(fdir / "case.json"))
    assert resolved == (fdir / "case.json").resolve()


def test_admit_rejects_path_outside_allowed_root(tmp_path):
    fdir = _fixture_dir(tmp_path)
    outside = tmp_path / "secret.json"
    outside.write_text("{}", encoding="utf-8")
    gate = ToolGate(allowed_roots=[fdir])
    with pytest.raises(ToolAdmissionError):
        gate.admit("read_fixture_file", str(outside))


def test_admit_rejects_traversal_attempt(tmp_path):
    fdir = _fixture_dir(tmp_path)
    gate = ToolGate(allowed_roots=[fdir])
    with pytest.raises(ToolAdmissionError):
        gate.admit("read_fixture_file", str(fdir / ".." / "secret.json"))


def test_read_fixture_file_returns_parsed_json(tmp_path):
    fdir = _fixture_dir(tmp_path)
    gate = ToolGate(allowed_roots=[fdir])
    data = read_fixture_file(gate, str(fdir / "case.json"))
    assert data == {"case_id": "SYNTH-1"}


def test_read_fixture_file_rejects_admission_before_reading(tmp_path):
    fdir = _fixture_dir(tmp_path)
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({"leak": True}), encoding="utf-8")
    gate = ToolGate(allowed_roots=[fdir])
    with pytest.raises(ToolAdmissionError):
        read_fixture_file(gate, str(outside))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && py -m pytest tests/runtime/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'runtime.tools'`.

- [ ] **Step 3: Write minimal implementation**

Create `agent-platform/runtime/tools.py`:

```python
"""Tool admission gate for Agent Runtime's read-only research profile.

Every tool call is admitted (path-sandboxed to explicitly allowed roots,
no traversal) before it runs — a denied admission never reaches disk I/O,
so no cost or side effect occurs for an invalid attempt.
"""
from __future__ import annotations

import json
from pathlib import Path


class ToolAdmissionError(Exception):
    pass


class ToolGate:
    def __init__(self, allowed_roots: list[Path]) -> None:
        self._roots = [Path(r).resolve() for r in allowed_roots]

    def admit(self, tool_name: str, path: str) -> Path:
        candidate = Path(path)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise ToolAdmissionError(f"{tool_name}: path does not exist: {path}") from error
        for root in self._roots:
            if resolved == root or root in resolved.parents:
                return resolved
        raise ToolAdmissionError(f"{tool_name}: path outside allowed roots: {resolved}")


def read_fixture_file(gate: ToolGate, path: str) -> dict:
    resolved = gate.admit("read_fixture_file", path)
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError, OSError) as error:
        raise ToolAdmissionError(f"read_fixture_file: could not read/parse {resolved}") from error
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-platform && py -m pytest tests/runtime/test_tools.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/tools.py agent-platform/tests/runtime/test_tools.py
git commit -m "feat(runtime): add sandboxed tool-admission gate + read_fixture_file (Fas 2)"
```

---

### Task 5: Research profile + agent loop (integration)

**Files:**
- Create: `agent-platform/runtime/research_profile.py`
- Create: `agent-platform/runtime/agent_loop.py`
- Test: `agent-platform/tests/runtime/test_agent_loop.py`

**Interfaces:**
- Consumes: `session_state.{create,append,load,latest_sequence,SessionError}` (Task 1); `reasoning.kernel.Engine`, `reasoning.kernel.strategy.Strategy` (Task 2); `runtime.text_inference_port.{TextInferencePort,TextInferenceError}` (Task 3); `runtime.tools.{ToolGate,ToolAdmissionError,read_fixture_file}` (Task 4); `adapters.inference.budget_gate.BudgetExhausted`.
- Produces: `research_profile.RESEARCH_PROFILE: dict` (static config: `{"profile_id": "research-v0.1", "allowed_tools": ["read_fixture_file"], "workflow": "vertical-01-ai-act/classify"}`); `agent_loop.AgentLoop` with `__init__(self, store: Path, tool_gate: ToolGate, port: TextInferencePort, output_schema: dict, system_prompt: str)` and `def run(self, task_id: str, fixture_path: str) -> dict` returning a result envelope `{"session_id": str, "status": "succeeded"|"blocked", "result": dict|None, "reason": str|None}`.

- [ ] **Step 1: Write the failing test**

Create `agent-platform/tests/runtime/test_agent_loop.py`:

```python
"""Full agent loop: claim -> admit tool -> read fixture -> kernel (model-assisted)
-> verify -> result envelope. TextInferencePort is faked (0 cost, deterministic).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.inference.budget_gate import BudgetExhausted
from runtime.agent_loop import AgentLoop
from runtime.session_state import load
from runtime.tools import ToolGate

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["classification"],
    "properties": {"classification": {"type": "string", "enum": ["high_risk", "minimal_risk"]}},
}


class FakePort:
    """Stands in for TextInferencePort — same .invoke(prompt, schema) -> dict shape."""

    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc
        self.calls = []

    def invoke(self, prompt, output_schema):
        self.calls.append((prompt, output_schema))
        if self._raise:
            raise self._raise
        return self._response


def _fixture(tmp_path, data):
    d = tmp_path / "fixtures"
    d.mkdir()
    path = d / "case.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return d, path


def test_run_succeeds_end_to_end(tmp_path):
    fdir, fpath = _fixture(tmp_path, {"case_id": "SYNTH-1"})
    gate = ToolGate(allowed_roots=[fdir])
    port = FakePort(response={"classification": "high_risk"})
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt="classify this system")
    envelope = loop.run(task_id="synth-classify-001", fixture_path=str(fpath))

    assert envelope["status"] == "succeeded"
    assert envelope["result"] == {"classification": "high_risk"}
    assert port.calls[0][1] == OUTPUT_SCHEMA

    session = load(tmp_path / "sessions", envelope["session_id"])
    event_types = [e["event_type"] for e in session["events"]]
    assert event_types == [
        "session.created", "tool.admitted", "tool.completed",
        "inference.requested", "inference.completed", "session.terminal",
    ]


def test_run_blocks_when_schema_validation_fails(tmp_path):
    fdir, fpath = _fixture(tmp_path, {"case_id": "SYNTH-1"})
    gate = ToolGate(allowed_roots=[fdir])
    port = FakePort(response={"classification": "not-a-valid-enum-value"})
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt="classify this system")
    envelope = loop.run(task_id="t1", fixture_path=str(fpath))

    assert envelope["status"] == "blocked"
    assert envelope["result"] is None
    assert "schema" in envelope["reason"].lower()


def test_run_blocks_on_budget_exhausted_without_leaving_partial_success(tmp_path):
    fdir, fpath = _fixture(tmp_path, {"case_id": "SYNTH-1"})
    gate = ToolGate(allowed_roots=[fdir])
    port = FakePort(raise_exc=BudgetExhausted("no budget"))
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt="classify this system")
    envelope = loop.run(task_id="t1", fixture_path=str(fpath))

    assert envelope["status"] == "blocked"
    assert "budget" in envelope["reason"].lower()
    session = load(tmp_path / "sessions", envelope["session_id"])
    assert session["events"][-1]["event_type"] == "session.terminal"
    assert session["events"][-1]["payload"]["status"] == "blocked"


def test_run_blocks_when_fixture_path_outside_allowed_root(tmp_path):
    fdir, fpath = _fixture(tmp_path, {"case_id": "SYNTH-1"})
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"case_id": "SYNTH-2"}), encoding="utf-8")
    gate = ToolGate(allowed_roots=[fdir])  # fpath's sibling dir only, not tmp_path itself
    port = FakePort(response={"classification": "high_risk"})
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt="classify this system")
    envelope = loop.run(task_id="t1", fixture_path=str(outside))

    assert envelope["status"] == "blocked"
    assert port.calls == []  # no model call for a denied tool admission
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && py -m pytest tests/runtime/test_agent_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'runtime.agent_loop'`.

- [ ] **Step 3: Write minimal implementation**

Create `agent-platform/runtime/research_profile.py`:

```python
"""Static config for Agent Runtime's read-only research profile (Fas 2 v0.1)."""

RESEARCH_PROFILE = {
    "profile_id": "research-v0.1",
    "allowed_tools": ["read_fixture_file"],
    "workflow": "vertical-01-ai-act/classify",
}
```

Create `agent-platform/runtime/agent_loop.py`:

```python
"""Agent Runtime's orchestrating loop (Fas 2 v0.1, read-only research profile).

claim -> admit+run one tool -> reasoning kernel (MODEL_ASSISTED strategy) ->
schema-validate -> result envelope. Every step is logged to session_state so
a crash mid-run can resume from the last completed event (not implemented as
an explicit resume() call in v0.1 -- the log itself is the resumability proof,
per the design spec's error-handling section).
"""
from __future__ import annotations

from pathlib import Path

import jsonschema

from adapters.inference.budget_gate import BudgetExhausted
from reasoning.kernel import Engine
from runtime import session_state as state
from runtime.tools import ToolAdmissionError, ToolGate, read_fixture_file


class AgentLoop:
    def __init__(self, store: Path, tool_gate: ToolGate, port, output_schema: dict,
                 system_prompt: str) -> None:
        self._store = Path(store)
        self._gate = tool_gate
        self._port = port
        self._schema = output_schema
        self._prompt = system_prompt

    def run(self, task_id: str, fixture_path: str) -> dict:
        session = state.create(self._store, task_id=task_id)
        session_id = session["session_id"]

        def _blocked(reason: str) -> dict:
            seq = state.latest_sequence(state.load(self._store, session_id))
            state.append(self._store, session_id, seq, "session.terminal",
                         {"status": "blocked", "reason": reason})
            return {"session_id": session_id, "status": "blocked", "result": None, "reason": reason}

        try:
            fixture = read_fixture_file(self._gate, fixture_path)
        except ToolAdmissionError as error:
            return _blocked(f"tool admission denied: {error}")

        seq = state.latest_sequence(state.load(self._store, session_id))
        session = state.append(self._store, session_id, seq, "tool.admitted",
                                {"tool": "read_fixture_file", "path": fixture_path})
        seq = state.latest_sequence(session)
        session = state.append(self._store, session_id, seq, "tool.completed",
                                {"tool": "read_fixture_file"})
        seq = state.latest_sequence(session)

        def _invoke(content):
            state.append(self._store, session_id, seq, "inference.requested", {"content": content})
            return self._port.invoke(self._prompt, self._schema)

        def _validate(response) -> bool:
            try:
                jsonschema.validate(instance=response, schema=self._schema)
                return True
            except jsonschema.ValidationError:
                return False

        engine = Engine()
        try:
            result = engine.solve_model_assisted(content=fixture, invoke=_invoke, validate=_validate)
        except BudgetExhausted as error:
            return _blocked(f"budget exhausted: {error}")

        seq = state.latest_sequence(state.load(self._store, session_id))
        state.append(self._store, session_id, seq, "inference.completed",
                     {"confidence": result["confidence"]})
        seq = state.latest_sequence(state.load(self._store, session_id))

        if result["confidence"] < 1.0:
            return _blocked("response failed schema validation")

        state.append(self._store, session_id, seq, "session.terminal",
                     {"status": "succeeded"})
        return {"session_id": session_id, "status": "succeeded", "result": result["value"], "reason": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-platform && py -m pytest tests/runtime/test_agent_loop.py -v`
Expected: 4 passed.

Then run the full agent-platform suite to confirm no regressions anywhere:

Run: `cd agent-platform && py -m pytest -m "not real_inference" -q`
Expected: all tests pass (previous count plus this task's new tests).

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/research_profile.py agent-platform/runtime/agent_loop.py agent-platform/tests/runtime/test_agent_loop.py
git commit -m "feat(runtime): wire agent_loop (claim, tool admission, kernel, verify, envelope) (Fas 2)"
```

---

### Task 6: Real-inference exit-criterion proof (opt-in, not default CI)

**Files:**
- Create: `agent-platform/tests/runtime/test_agent_loop_real_inference.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5, plus `verticals/vertical-01-ai-act/evals/synthetic/positive-cases/001-high-risk-medical-diagnostic.yaml` (read directly, not through `read_fixture_file` — this test converts one YAML eval fixture into the JSON shape `AgentLoop`/`read_fixture_file` expects, as a one-time setup step, not part of the runtime code itself).

- [ ] **Step 1: Write the test (this is the exit-criterion proof itself, not a red/green TDD step — it can only be run once credentials exist)**

Create `agent-platform/tests/runtime/test_agent_loop_real_inference.py`:

```python
"""Fas 2 exit-criterion proof: one real synthetic AI Act fixture, solved by
AgentLoop without Hermes, using a real model call. Excluded from default CI
(same convention as every other real_inference-marked test in this repo) --
run manually once CORTXT_INFERENCE_URL/CORTXT_INFERENCE_API_KEY are set and
cortxt_resilient_inference is installed. See
docs/superpowers/specs/2026-08-15-fas2-agent-runtime-v01-design.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from adapters.inference.budget_gate import BudgetGate
from runtime.agent_loop import AgentLoop
from runtime.text_inference_port import TextInferencePort
from runtime.tools import ToolGate

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-01-ai-act"
FIXTURE_YAML = VERTICAL / "evals" / "synthetic" / "positive-cases" / "001-high-risk-medical-diagnostic.yaml"
OUTPUT_SCHEMA = json.loads(
    (VERTICAL / "schemas" / "ai-act-assessment-output.schema.json").read_text(encoding="utf-8")
)
SYSTEM_PROMPT = (VERTICAL / "instructions" / "system-prompt-classify.md").read_text(encoding="utf-8")


@pytest.mark.real_inference
def test_ai_act_fixture_solved_without_hermes(tmp_path):
    fixture_case = yaml.safe_load(FIXTURE_YAML.read_text(encoding="utf-8"))["input"]
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    fixture_path = fixture_dir / "case.json"
    fixture_path.write_text(json.dumps(fixture_case), encoding="utf-8")

    gate = ToolGate(allowed_roots=[fixture_dir])
    budget_gate = BudgetGate(max_calls=1, db_path=tmp_path / "spend.db")
    port = TextInferencePort(
        model="synthetic-model",
        budget_gate=budget_gate,
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    loop = AgentLoop(store=tmp_path / "sessions", tool_gate=gate, port=port,
                      output_schema=OUTPUT_SCHEMA, system_prompt=SYSTEM_PROMPT)

    envelope = loop.run(task_id="fas2-exit-criterion", fixture_path=str(fixture_path))

    assert envelope["status"] == "succeeded", envelope.get("reason")
    assert envelope["result"]["case_id"] == fixture_case["case_id"]
```

Verified against the real file: `001-high-risk-medical-diagnostic.yaml` has top-level keys `fixture_id`, `fixture_type`, `input` (the object matching `ai-act-assessment-input.schema.json`), `expected_output`, `deterministic_assertions`, `model_assisted_assertions`, `human_review_required`. The test above reads `["input"]`, which is correct — no adjustment needed.

- [ ] **Step 2: Confirm it's excluded from default CI**

Run: `cd agent-platform && py -m pytest -m "not real_inference" -q`
Expected: this new test does not appear in the run (deselected count increases by 1).

- [ ] **Step 3: Commit**

```bash
git add agent-platform/tests/runtime/test_agent_loop_real_inference.py
git commit -m "test(runtime): add real_inference exit-criterion proof for Fas 2 (opt-in, not default CI)"
```

- [ ] **Step 4: Manual run once credentials exist (not part of this plan's automated steps)**

Once `CORTXT_INFERENCE_URL`/`CORTXT_INFERENCE_API_KEY` are set and `pip install cortxt_resilient_inference` (or equivalent) has been done separately:

Run: `cd agent-platform && py -m pytest tests/runtime/test_agent_loop_real_inference.py -v -m real_inference`

This run is the actual, literal proof of Fas 2's exit criterion. Report the result to Rikard; do not merge/close out Fas 2 as "done" until this has actually been run successfully at least once.

---

## Self-review notes (from the plan-writing process)

- **Spec coverage:** all 7 scope-decision items and all 5 spec components have a task. The design spec's "Out of scope" section (other strategies, strategy portability, non-`read_fixture_file` tools, Supervisor) has deliberately no task here — confirmed nothing in this plan builds them.
- **Type/interface consistency:** `session_state` functions all take `store: Path` first, matching across Tasks 1 and 5. `AgentLoop.run` returns the exact envelope shape used consistently in Tasks 5 and 6. `TextInferencePort.invoke(prompt, output_schema)` signature matches between Task 3's own tests, Task 5's `FakePort`, and Task 6's real usage.
- **Fixture shape verified during plan-writing, not left as an assumption:** Task 6's YAML fixture key (`input`) was checked against the real file `001-high-risk-medical-diagnostic.yaml` before this plan was finalized — no placeholder guess was left in the plan.
