# Orchestrator Engine Resume + CodexAdapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Cortxt orchestrator chat REPL a per-engine resumable session
(so a live conversation with Codex keeps its own accumulated context turn to
turn), a working `CodexAdapter`, and an operator-facing way to choose which
engine the chat REPL talks to.

**Architecture:** Extend the existing `EngineAdapter` protocol
(`runtime/engine_adapter.py`, ADR-026) with one additive, backward-compatible
`session_id` parameter. `invoke_hermes()`/`HermesAdapter` thread it through
to Hermes's verified `--resume <id>` flag and capture a fresh session's id via
`hermes sessions list`. A new `CodexAdapter` wraps `codex exec [resume <id>]
--json -o <file>`, reading the resumable id from the verified `thread.started`
JSONL event and the final answer from the `-o` file. `_run_orchestrator_chat`
gains an `--engine` flag and a local `/engine <id>` command, and tracks one
`session_id` per engine across the REPL's turns.

**Tech Stack:** Python 3.11+, pytest, subprocess (both adapters), no new
dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-orchestrator-engine-resume-and-codex-adapter-v1-design.md`

## Global Constraints

- `session_id=None` on every adapter's `invoke()` must behave identically to
  today's code (spec Architecture §1) — every existing call site and test
  that omits it must keep passing unmodified.
- `EngineContext`/`EngineBroker` (ADR-027) are unchanged: `codex` gets its
  own broker key with exactly one provider, same passthrough policy as
  `hermes`.
- `route()`/`engine_manifest.py` are unchanged (spec Non-goals) — no manifest
  row, no `route()` edit anywhere in this plan.
- No `ClaudeAdapter`, no daemon/dispatch-side resume, no streaming UI (spec
  Non-goals) — out of scope for every task below.
- Every real subprocess call this plan adds must spread
  `**subprocess_windows.no_window_kwargs()` into the call (see
  `agent-platform/subprocess_windows.py`, added 2026-08-20 to stop Windows
  flashing a console window for every captured subprocess call — already
  wired into `routing/hermes_invoker.py`'s existing call and several test
  files as a standalone fix; this plan's *new* calls, Task 3's
  `hermes sessions list` lookup and Task 5's `codex exec`, must use it too).
- Both adapters must decode subprocess output as `encoding="utf-8",
  errors="replace"` (the Hermes UTF-8 lesson, `routing/hermes_invoker.py`),
  and must pass `stdin=subprocess.DEVNULL` to the codex call specifically —
  verified live on 2026-08-20 that `codex exec` reads stdin as an appended
  `<stdin>` block when stdin isn't explicitly closed/redirected, even when a
  prompt argument is given, which would silently corrupt the prompt under a
  real subprocess call whose stdin is inherited from a parent process.
- **Verified facts this plan builds on** (real `codex`/`hermes` calls run
  2026-08-20 with the operator's prior go-ahead, resolving the spec's two
  open proof-step questions — do not re-verify, they're settled):
  - Codex: every `codex exec` (fresh or `resume`) JSONL stream's first line
    is `{"type":"thread.started","thread_id":"<uuid>"}`. That `thread_id` is
    the value `codex exec resume <thread_id> ...` accepts to continue the
    same conversation (confirmed: a second turn resumed with the captured
    id correctly recalled the first turn's content).
  - Hermes: `hermes -z <prompt> --resume <session_id>` (and `-r`) correctly
    resumes a session. A one-shot `-z` call's *newly created* session id is
    **not** printed to stdout (`--pass-session-id` only affects the model's
    own system prompt, not our captured output) — it must be read back via
    `hermes sessions list --limit 1 --workspace <cwd>` immediately after,
    whose plain-text table output looks like (real captured example):
    ```
    Preview                                Workspace          Last Active   Src    ID
    ────────────────────────────────────────────────────────────────────────────────────────────────────
    reply with exactly: ok                 agent-platform     just now      cli    20260820_112139_8c44cf
    ```
    Columns are separated by 2+ spaces; the session id is always the last
    column of the one data row `--limit 1` returns.

---

## Task 1: `EngineAdapter` protocol gains an additive `session_id` parameter

**Files:**
- Modify: `agent-platform/runtime/engine_adapter.py`
- Test: `agent-platform/tests/runtime/test_engine_adapter.py`

**Interfaces:**
- Produces: `EngineAdapter.invoke(profile, prompt, *, timeout_seconds,
  model=None, provider=None, cwd=None, session_id=None) -> dict` — the
  contract every later task's adapter implements.

- [ ] **Step 1: Write the failing test**

Add to `agent-platform/tests/runtime/test_engine_adapter.py`:

```python
class _OldStyleAdapter:
    """An adapter written before session_id existed -- must still conform."""

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None):
        return {"status": "succeeded", "profile": profile}


def test_pre_existing_adapter_without_session_id_still_conforms():
    assert isinstance(_OldStyleAdapter(), EngineAdapter)


def test_adapter_with_session_id_parameter_conforms():
    class _NewStyleAdapter:
        def invoke(self, profile, prompt, *, timeout_seconds, model=None,
                    provider=None, cwd=None, session_id=None):
            return {"status": "succeeded", "profile": profile, "session_id": session_id}

    assert isinstance(_NewStyleAdapter(), EngineAdapter)
```

- [ ] **Step 2: Run test to verify it currently passes trivially (protocol not yet documented) then proceed**

Run: `cd agent-platform && python -m pytest tests/runtime/test_engine_adapter.py -v`
Expected: PASS (runtime-checkable `Protocol` only checks method *names*
exist, not signatures, so both classes already satisfy `isinstance` before
any code change — this step is a baseline confirmation, not a red step).
This task's real deliverable is the protocol's documented signature udpate
in Step 3, exercised by Step 4's re-run.

- [ ] **Step 3: Update the protocol's declared signature**

In `agent-platform/runtime/engine_adapter.py`, change:

```python
    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
        cwd: Path | None = None,
    ) -> dict:
        ...
```

to:

```python
    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
        cwd: Path | None = None,
        session_id: str | None = None,
    ) -> dict:
        """session_id, when given, resumes an existing engine-native
        conversation instead of starting fresh -- opaque to every caller
        above the adapter (never parsed, compared, or assumed to mean the
        same thing across different engine_ids). The returned dict should
        include a `session_id` key: the engine-native id of the session
        that was just used (fresh or resumed), or None if the call failed
        before a session was established.
        """
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/runtime/test_engine_adapter.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/engine_adapter.py agent-platform/tests/runtime/test_engine_adapter.py
git commit -m "feat(runtime): add session_id to EngineAdapter protocol"
```

---

## Task 2: `invoke_hermes()` resumes via `--resume` when given a session id

**Files:**
- Modify: `agent-platform/routing/hermes_invoker.py`
- Test: `agent-platform/tests/routing/test_hermes_invoker.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `invoke_hermes(profile, prompt, *, timeout_seconds,
  run_subprocess=subprocess.run, model=None, provider=None, cwd=None,
  session_id=None) -> dict` where `argv` includes `["--resume",
  session_id]` when `session_id` is truthy. (Populating the *returned*
  `session_id` key is Task 3 — this task only adds the resume-request side.)

- [ ] **Step 1: Write the failing test**

Add to `agent-platform/tests/routing/test_hermes_invoker.py`:

```python
def test_invoke_hermes_passes_resume_flag_when_session_id_given():
    def fake_run(argv, **kwargs):
        assert argv == ["hermes", "-p", "builder", "-z", "do the thing", "--resume", "sess-123"]
        return _FakeCompletedProcess(0, stdout="ok")

    result = invoke_hermes(
        "builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run,
        session_id="sess-123",
    )
    assert result["status"] == "succeeded"


def test_invoke_hermes_omits_resume_flag_when_session_id_is_none():
    def fake_run(argv, **kwargs):
        assert "--resume" not in argv
        return _FakeCompletedProcess(0, stdout="ok")

    invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && python -m pytest tests/routing/test_hermes_invoker.py::test_invoke_hermes_passes_resume_flag_when_session_id_given -v`
Expected: FAIL with `TypeError: invoke_hermes() got an unexpected keyword argument 'session_id'`

- [ ] **Step 3: Implement**

In `agent-platform/routing/hermes_invoker.py`, change the signature and argv
construction:

```python
def invoke_hermes(
    profile: str,
    prompt: str,
    *,
    timeout_seconds: int,
    run_subprocess: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    model: str | None = None,
    provider: str | None = None,
    cwd: Path | None = None,
    session_id: str | None = None,
) -> dict:
    if not prompt.strip():
        raise ValueError("prompt must be a non-empty string")

    argv = ["hermes", "-p", profile, "-z", prompt]
    if session_id:
        argv += ["--resume", session_id]
    if model:
        argv += ["-m", model]
    if provider:
        argv += ["--provider", provider]
```

(Leave the rest of the function body as-is for this task — the
`started`/`try`/`except`/return block is untouched here; Task 3 edits the
final `return` to populate `session_id`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/routing/test_hermes_invoker.py -v`
Expected: PASS (all tests, including the two new ones and every pre-existing one)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/routing/hermes_invoker.py agent-platform/tests/routing/test_hermes_invoker.py
git commit -m "feat(routing): accept --resume session_id in invoke_hermes"
```

---

## Task 3: Capture a fresh Hermes session's id via `hermes sessions list`

**Files:**
- Modify: `agent-platform/routing/hermes_invoker.py`
- Test: `agent-platform/tests/routing/test_hermes_invoker.py`

**Interfaces:**
- Consumes: Task 2's `session_id` parameter on `invoke_hermes()`.
- Produces: `invoke_hermes(...)`'s returned dict always includes a
  `session_id` key. `_parse_latest_session_id(output: str) -> str | None`
  and `_capture_latest_hermes_session_id(cwd, run_subprocess) -> str | None`
  as module-level helpers (leading underscore: internal to this module,
  no other file imports them).

- [ ] **Step 1: Write the failing test**

Add to `agent-platform/tests/routing/test_hermes_invoker.py`:

```python
_SESSIONS_TABLE = (
    "Preview                                Workspace          Last Active   Src    ID\n"
    "─" * 104 + "\n"
    "reply with exactly: ok                 agent-platform     just now      cli    20260820_112139_8c44cf\n"
)


def test_invoke_hermes_captures_new_session_id_on_fresh_success(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ["hermes", "sessions", "list"]:
            return _FakeCompletedProcess(0, stdout=_SESSIONS_TABLE)
        return _FakeCompletedProcess(0, stdout="ok")

    result = invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)

    assert result["session_id"] == "20260820_112139_8c44cf"
    assert calls[0][:4] == ["hermes", "-p", "builder", "-z"]
    assert calls[1][:3] == ["hermes", "sessions", "list"]


def test_invoke_hermes_echoes_back_resumed_session_id_without_a_lookup_call(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _FakeCompletedProcess(0, stdout="ok")

    result = invoke_hermes(
        "builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run,
        session_id="20260820_112139_8c44cf",
    )

    assert result["session_id"] == "20260820_112139_8c44cf"
    assert len(calls) == 1  # no extra "sessions list" lookup needed on resume


def test_invoke_hermes_session_id_is_none_when_call_fails():
    def fake_run(argv, **kwargs):
        return _FakeCompletedProcess(1, stdout="", stderr="model refused")

    result = invoke_hermes("builder", "do the thing", timeout_seconds=60, run_subprocess=fake_run)
    assert result["session_id"] is None


def test_parse_latest_session_id_reads_last_column_of_one_data_row():
    from routing.hermes_invoker import _parse_latest_session_id

    assert _parse_latest_session_id(_SESSIONS_TABLE) == "20260820_112139_8c44cf"


def test_parse_latest_session_id_returns_none_when_table_has_no_data_rows():
    from routing.hermes_invoker import _parse_latest_session_id

    header_only = "Preview   Workspace   Last Active   Src    ID\n" + ("─" * 40) + "\n"
    assert _parse_latest_session_id(header_only) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && python -m pytest tests/routing/test_hermes_invoker.py::test_invoke_hermes_captures_new_session_id_on_fresh_success -v`
Expected: FAIL (`result["session_id"]` raises `KeyError` — key doesn't exist yet)

- [ ] **Step 3: Implement**

`agent-platform/routing/hermes_invoker.py` already imports `no_window_kwargs`
from `subprocess_windows` as part of the standalone terminal-flash fix
(2026-08-20) — reuse that same import, don't add a second one. Add these two
module-level helpers (near the top, after the imports and before
`invoke_hermes`):

```python
import re


def _parse_latest_session_id(output: str) -> str | None:
    """Parse `hermes sessions list --limit 1`'s plain-text table: columns
    are separated by 2+ spaces, the session id is always the last column
    of the single data row after the header/separator lines."""
    lines = output.splitlines()
    sep_index = next(
        (i for i, line in enumerate(lines) if line.strip() and set(line.strip()) <= {"─"}),
        None,
    )
    if sep_index is None:
        return None
    data_lines = [line for line in lines[sep_index + 1:] if line.strip()]
    if not data_lines:
        return None
    fields = re.split(r"\s{2,}", data_lines[0].strip())
    return fields[-1] if fields else None


def _capture_latest_hermes_session_id(
    cwd: Path | None,
    run_subprocess: Callable[..., "subprocess.CompletedProcess[str]"],
) -> str | None:
    argv = ["hermes", "sessions", "list", "--limit", "1"]
    if cwd is not None:
        argv += ["--workspace", str(cwd)]
    try:
        proc = run_subprocess(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            **no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return _parse_latest_session_id(proc.stdout or "")
```

Then change `invoke_hermes()`'s two `return` statements (the timeout branch
and the final branch) to populate `session_id`:

```python
    except subprocess.TimeoutExpired:
        return {
            "status": "timed_out",
            "profile": profile,
            "stdout": "",
            "stderr": f"hermes did not complete within {timeout_seconds}s",
            "elapsed_seconds": time.time() - started,
            "session_id": session_id,
        }
    except OSError as error:
        raise HermesInvocationError(f"could not start hermes: {error}") from error

    status = "succeeded" if proc.returncode == 0 else "failed"
    result_session_id = session_id
    if status == "succeeded" and session_id is None:
        result_session_id = _capture_latest_hermes_session_id(cwd, run_subprocess)

    return {
        "status": status,
        "profile": profile,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
        "elapsed_seconds": time.time() - started,
        "session_id": result_session_id,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/routing/test_hermes_invoker.py -v`
Expected: PASS (all tests, including every pre-existing one — `session_id`
being present now is additive to the returned dict, no prior test asserts
the dict's exact key set)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/routing/hermes_invoker.py agent-platform/tests/routing/test_hermes_invoker.py
git commit -m "feat(routing): capture a fresh Hermes session's id after invoke"
```

---

## Task 4: `HermesAdapter` passes `session_id` through unchanged

**Files:**
- Modify: `agent-platform/runtime/adapters/hermes_adapter.py`
- Test: `agent-platform/tests/runtime/adapters/test_hermes_adapter.py`

**Interfaces:**
- Consumes: Task 2/3's `invoke_hermes(..., session_id=...)`.
- Produces: `HermesAdapter().invoke(..., session_id=...)` — same delegation
  shape as every other parameter already on this class.

- [ ] **Step 1: Write the failing test**

Add to `agent-platform/tests/runtime/adapters/test_hermes_adapter.py`:

```python
def test_invoke_passes_session_id_through_to_invoke_hermes():
    calls = []

    def fake_invoke_hermes(profile, prompt, *, timeout_seconds, model=None,
                            provider=None, cwd=None, session_id=None):
        calls.append(session_id)
        return {"status": "succeeded", "profile": profile, "session_id": "new-id"}

    adapter = HermesAdapter(invoke_hermes=fake_invoke_hermes)
    result = adapter.invoke("builder", "do it", timeout_seconds=60, session_id="old-id")

    assert calls == ["old-id"]
    assert result["session_id"] == "new-id"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && python -m pytest tests/runtime/adapters/test_hermes_adapter.py::test_invoke_passes_session_id_through_to_invoke_hermes -v`
Expected: FAIL with `TypeError: invoke() got an unexpected keyword argument 'session_id'`

- [ ] **Step 3: Implement**

In `agent-platform/runtime/adapters/hermes_adapter.py`, change `invoke()`:

```python
    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
        cwd: Path | None = None,
        session_id: str | None = None,
    ) -> dict:
        invoke_fn = self._invoke_hermes if self._invoke_hermes is not None else _hermes_invoker_module.invoke_hermes
        return invoke_fn(
            profile, prompt, timeout_seconds=timeout_seconds, model=model,
            provider=provider, cwd=cwd, session_id=session_id,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/runtime/adapters/test_hermes_adapter.py -v`
Expected: PASS (all tests — the pre-existing ones that assert exact `calls`
tuples/`assert_called_once_with(...)` must still match since `session_id`
defaults to `None` and every existing test calls `invoke()` without it)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/adapters/hermes_adapter.py agent-platform/tests/runtime/adapters/test_hermes_adapter.py
git commit -m "feat(runtime): thread session_id through HermesAdapter"
```

---

## Task 5: `CodexAdapter`

**Files:**
- Create: `agent-platform/runtime/adapters/codex_adapter.py`
- Test: Create `agent-platform/tests/runtime/adapters/test_codex_adapter.py`

**Interfaces:**
- Consumes: `EngineAdapter` protocol shape from Task 1.
- Produces: `CodexAdapter(run_subprocess=None)` with `.invoke(profile,
  prompt, *, timeout_seconds, model=None, provider=None, cwd=None,
  session_id=None) -> dict`, returning `{status, profile, stdout, stderr,
  elapsed_seconds, session_id}`. Raises `CodexInvocationError` if the
  `codex` executable itself can't start (mirrors `HermesInvocationError`).
  Raises `NotImplementedError` if `provider` is given (Codex's CLI has no
  provider-override flag — spec Open question #3, resolved here: fail loud
  rather than silently ignore).

- [ ] **Step 1: Write the failing tests**

Create `agent-platform/tests/runtime/adapters/test_codex_adapter.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.adapters.codex_adapter import CodexAdapter, CodexInvocationError
from runtime.engine_adapter import EngineAdapter


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_THREAD_STARTED = '{"type":"thread.started","thread_id":"01a01e79-1e13-7643-b676-e02307b4b1be"}\n'


def _fake_run_writing_output_file(stdout=_THREAD_STARTED, returncode=0, message="ok"):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.write_text(message, encoding="utf-8")
        return _FakeCompletedProcess(returncode, stdout=stdout)

    return fake_run, calls


def test_codex_adapter_is_an_engine_adapter():
    assert isinstance(CodexAdapter(), EngineAdapter)


def test_fresh_call_builds_exec_argv_without_resume():
    fake_run, calls = _fake_run_writing_output_file()
    adapter = CodexAdapter(run_subprocess=fake_run)

    result = adapter.invoke("researcher", "do it", timeout_seconds=60)

    argv, kwargs = calls[0]
    assert argv[:2] == ["codex", "exec"]
    assert "resume" not in argv
    assert "-p" in argv and argv[argv.index("-p") + 1] == "researcher"
    assert argv[-1] == "do it"
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert result["status"] == "succeeded"
    assert result["session_id"] == "01a01e79-1e13-7643-b676-e02307b4b1be"
    assert result["stdout"] == "ok"


def test_resume_call_includes_resume_and_session_id_before_json_flag():
    fake_run, calls = _fake_run_writing_output_file()
    adapter = CodexAdapter(run_subprocess=fake_run)

    adapter.invoke("researcher", "continue", timeout_seconds=60, session_id="01a01e79-1e13-7643-b676-e02307b4b1be")

    argv, _ = calls[0]
    assert argv[:4] == ["codex", "exec", "resume", "01a01e79-1e13-7643-b676-e02307b4b1be"]


def test_model_and_cwd_are_forwarded():
    fake_run, calls = _fake_run_writing_output_file()
    adapter = CodexAdapter(run_subprocess=fake_run)

    adapter.invoke("researcher", "do it", timeout_seconds=60, model="o3", cwd=Path("/repo"))

    argv, kwargs = calls[0]
    assert "-m" in argv and argv[argv.index("-m") + 1] == "o3"
    assert "-C" in argv and argv[argv.index("-C") + 1] == str(Path("/repo"))
    assert kwargs["cwd"] == str(Path("/repo"))


def test_provider_argument_raises_not_implemented():
    fake_run, _ = _fake_run_writing_output_file()
    adapter = CodexAdapter(run_subprocess=fake_run)

    with pytest.raises(NotImplementedError):
        adapter.invoke("researcher", "do it", timeout_seconds=60, provider="anything")


def test_nonzero_exit_is_a_failed_status():
    fake_run, _ = _fake_run_writing_output_file(returncode=1, message="")
    adapter = CodexAdapter(run_subprocess=fake_run)

    result = adapter.invoke("researcher", "do it", timeout_seconds=60)

    assert result["status"] == "failed"


def test_timeout_returns_timed_out_status_and_echoes_session_id():
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 0))

    adapter = CodexAdapter(run_subprocess=fake_run)
    result = adapter.invoke("researcher", "do it", timeout_seconds=5, session_id="prior-id")

    assert result["status"] == "timed_out"
    assert result["session_id"] == "prior-id"


def test_missing_executable_raises_codex_invocation_error():
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("codex not found")

    adapter = CodexAdapter(run_subprocess=fake_run)
    with pytest.raises(CodexInvocationError):
        adapter.invoke("researcher", "do it", timeout_seconds=60)


def test_empty_prompt_is_rejected():
    adapter = CodexAdapter(run_subprocess=lambda *a, **k: None)
    with pytest.raises(ValueError):
        adapter.invoke("researcher", "", timeout_seconds=60)


def test_missing_thread_started_event_falls_back_to_prior_session_id():
    fake_run, _ = _fake_run_writing_output_file(stdout='{"type":"turn.completed"}\n')
    adapter = CodexAdapter(run_subprocess=fake_run)

    result = adapter.invoke("researcher", "do it", timeout_seconds=60, session_id="prior-id")

    assert result["session_id"] == "prior-id"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/runtime/adapters/test_codex_adapter.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'runtime.adapters.codex_adapter'`)

- [ ] **Step 3: Implement**

Create `agent-platform/runtime/adapters/codex_adapter.py`:

```python
"""Wraps the Codex CLI (`codex exec`) as an EngineAdapter (ADR-026).

Verified live against the installed `codex` CLI, 2026-08-20: every
`codex exec` (fresh or `resume`) JSONL stream's first line is
`{"type":"thread.started","thread_id":"<uuid>"}`, and that `thread_id` is
what `codex exec resume <thread_id> ...` accepts to continue the same
conversation -- confirmed a resumed call correctly recalled the prior
turn's content. `-o/--output-last-message <file>` writes the final
assistant message as plain text, avoiding parsing conversational prose out
of the JSONL/stdout stream.

`stdin=subprocess.DEVNULL` is required, not optional: `codex exec` reads
stdin as an appended `<stdin>` block whenever stdin isn't explicitly
closed/redirected, even when a prompt argument is also given -- observed
live as a "Reading additional input from stdin..." message that would
otherwise silently corrupt the prompt under a subprocess whose stdin is
inherited from a parent process.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from subprocess_windows import no_window_kwargs


class CodexInvocationError(RuntimeError):
    """Raised when the codex executable itself could not be started."""


def _parse_thread_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            return event.get("thread_id")
    return None


class CodexAdapter:
    def __init__(
        self, run_subprocess: Callable[..., "subprocess.CompletedProcess[str]"] | None = None
    ) -> None:
        self._run_subprocess = run_subprocess if run_subprocess is not None else subprocess.run

    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
        cwd: Path | None = None,
        session_id: str | None = None,
    ) -> dict:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if provider:
            raise NotImplementedError(
                "CodexAdapter has no provider-override flag on the codex CLI"
            )

        descriptor, tmp_path_str = tempfile.mkstemp(prefix=".codex-last-message-", suffix=".txt")
        os.close(descriptor)
        tmp_path = Path(tmp_path_str)
        try:
            argv = ["codex", "exec"]
            if session_id:
                argv += ["resume", session_id]
            argv += ["--json", "-o", str(tmp_path)]
            if profile:
                argv += ["-p", profile]
            if model:
                argv += ["-m", model]
            if cwd is not None:
                argv += ["-C", str(cwd)]
            argv.append(prompt)

            started = time.time()
            try:
                proc = self._run_subprocess(
                    argv,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                    stdin=subprocess.DEVNULL,
                    cwd=str(cwd) if cwd is not None else None,
                    **no_window_kwargs(),
                )
            except subprocess.TimeoutExpired:
                return {
                    "status": "timed_out",
                    "profile": profile,
                    "stdout": "",
                    "stderr": f"codex did not complete within {timeout_seconds}s",
                    "elapsed_seconds": time.time() - started,
                    "session_id": session_id,
                }
            except OSError as error:
                raise CodexInvocationError(f"could not start codex: {error}") from error

            new_session_id = _parse_thread_id(proc.stdout or "") or session_id
            message = tmp_path.read_text(encoding="utf-8", errors="replace") if tmp_path.exists() else ""
            return {
                "status": "succeeded" if proc.returncode == 0 else "failed",
                "profile": profile,
                "stdout": message.strip() if message.strip() else (proc.stdout or ""),
                "stderr": proc.stderr or "",
                "elapsed_seconds": time.time() - started,
                "session_id": new_session_id,
            }
        finally:
            tmp_path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/runtime/adapters/test_codex_adapter.py -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/adapters/codex_adapter.py agent-platform/tests/runtime/adapters/test_codex_adapter.py
git commit -m "feat(runtime): add CodexAdapter wrapping codex exec/resume"
```

---

## Task 6: Register `CodexAdapter` in the default engine context

**Files:**
- Modify: `agent-platform/runtime/default_engine_context.py`
- Test: `agent-platform/tests/runtime/test_default_engine_context.py`

**Interfaces:**
- Consumes: `CodexAdapter` from Task 5.
- Produces: `build_default_engine_context()` returns a context where
  `context.get("codex").has_provider is True`.

- [ ] **Step 1: Write the failing test**

Add to `agent-platform/tests/runtime/test_default_engine_context.py`:

```python
def test_codex_has_a_provider():
    context = build_default_engine_context()
    assert context.get("codex").has_provider is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && python -m pytest tests/runtime/test_default_engine_context.py::test_codex_has_a_provider -v`
Expected: FAIL (`assert False is True` — no adapter registered yet)

- [ ] **Step 3: Implement**

In `agent-platform/runtime/default_engine_context.py`:

```python
from runtime.adapters.codex_adapter import CodexAdapter
from runtime.adapters.hermes_adapter import HermesAdapter
from runtime.engine_registry import EngineContext


def build_default_engine_context() -> EngineContext:
    context = EngineContext()
    context.register("hermes", HermesAdapter())
    context.register("codex", CodexAdapter())
    return context
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/runtime/test_default_engine_context.py -v`
Expected: PASS (all tests, including the pre-existing `test_hermes_has_a_provider`, `test_claude_direct_has_no_provider`, `test_each_call_returns_an_independent_context`)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/default_engine_context.py agent-platform/tests/runtime/test_default_engine_context.py
git commit -m "feat(runtime): register CodexAdapter in the default engine context"
```

---

## Task 7: `transcript_record` carries an optional `engine_session_id`

**Files:**
- Modify: `agent-platform/cli/orchestrator.py`
- Test: `agent-platform/tests/cli/test_orchestrator_overview.py`

**Interfaces:**
- Consumes: nothing new from other tasks (pure data-shape change).
- Produces: `transcript_record(*, transcript_id, turn_index, role, content,
  engine, status, redactions=0, engine_session_id=None) -> dict` — always
  includes an `"engine_session_id"` key (possibly `None`), for Task 8's
  `_run_orchestrator_chat` to persist the adapter's returned `session_id`
  into `session_state` without inventing a second payload shape.

- [ ] **Step 1: Write the failing test**

Add to `agent-platform/tests/cli/test_orchestrator_overview.py`:

```python
def test_transcript_record_carries_optional_engine_session_id():
    record = orchestrator.transcript_record(
        transcript_id="t-1", turn_index=1, role="assistant", content="answer",
        engine="codex", status="succeeded", engine_session_id="thread-abc",
    )

    assert record["engine_session_id"] == "thread-abc"


def test_transcript_record_engine_session_id_defaults_to_none():
    record = orchestrator.transcript_record(
        transcript_id="t-1", turn_index=1, role="user", content="hi",
        engine="hermes", status="submitted",
    )

    assert record["engine_session_id"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/cli/test_orchestrator_overview.py::test_transcript_record_carries_optional_engine_session_id -v`
Expected: FAIL with `TypeError: transcript_record() got an unexpected keyword argument 'engine_session_id'`

- [ ] **Step 3: Implement**

In `agent-platform/cli/orchestrator.py`, change `transcript_record`:

```python
def transcript_record(
    *, transcript_id: str, turn_index: int, role: str, content: str,
    engine: str, status: str, redactions: int = 0,
    engine_session_id: str | None = None,
) -> dict[str, Any]:
    return {
        "transcript_id": transcript_id,
        "turn_index": turn_index,
        "role": role,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content_chars": len(content),
        "engine": engine,
        "status": status,
        "redactions": redactions,
        "engine_session_id": engine_session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/cli/test_orchestrator_overview.py -v`
Expected: PASS (all tests, including the pre-existing
`test_transcript_record_contains_hash_but_never_content`, which only checks
`"content" not in record` and the hash length — unaffected by the new key)

- [ ] **Step 5: Commit**

```bash
git add agent-platform/cli/orchestrator.py agent-platform/tests/cli/test_orchestrator_overview.py
git commit -m "feat(cli): carry optional engine_session_id on transcript records"
```

---

## Task 8: Engine choice + per-engine resume in `_run_orchestrator_chat`

**Files:**
- Modify: `agent-platform/cli/unified_cli.py`
- Test: `agent-platform/tests/cli/test_orchestrator_chat.py`

**Interfaces:**
- Consumes: Task 1's `session_id` parameter, Task 7's `engine_session_id`
  field, `EngineContext.get(engine_id)` (unchanged, ADR-027).
- Produces: `orchestrator chat --engine <id>` CLI flag (default `"hermes"`);
  a local `/engine <id>` REPL command; `_run_orchestrator_chat` tracks one
  `session_id` per engine across turns and threads it into
  `broker.invoke(..., session_id=...)`.

- [ ] **Step 1: Write the failing tests**

Replace `agent-platform/tests/cli/test_orchestrator_chat.py`'s `_args`,
`FakeBroker`, and `FakeContext` helpers, and add new tests. Full replacement
content for the file:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cli import unified_cli
from runtime import session_state


def _args(tmp_path: Path, ask: str, engine: str = "hermes") -> SimpleNamespace:
    return SimpleNamespace(
        ask=ask,
        engine=engine,
        hermes_profile="researcher",
        timeout=5,
        model=None,
        provider=None,
        store=tmp_path / "sessions",
        snapshot=tmp_path / "snapshot.json",
        stale_after=300,
        workstream_id="branch-main",
        branch="main",
    )


def _projection(tmp_path: Path) -> dict:
    return {
        "orchestrator": {"status": "idle", "message": "No verified work"},
        "workstreams": [],
        "runtimes": [{"runtime_id": "hermes", "installed": True, "running": False}],
        "engines": [],
        "skills": [],
        "profiles": [],
        "snapshot_path": tmp_path / "snapshot.json",
    }


class FakeBroker:
    def __init__(self, session_ids=None):
        self.calls = []
        self._session_ids = list(session_ids or [])

    def invoke(self, profile, prompt, **kwargs):
        self.calls.append((profile, prompt, kwargs))
        session_id = self._session_ids.pop(0) if self._session_ids else "sess-1"
        return {"status": "succeeded", "stdout": "Advisory answer", "stderr": "", "session_id": session_id}


class FakeContext:
    def __init__(self, brokers: dict):
        self.brokers = brokers

    def get(self, engine_id):
        return self.brokers[engine_id]


def test_slash_command_stays_local_and_never_invokes_engine(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "/status"), engine_context=FakeContext({"hermes": broker})
    )

    assert result.status == "succeeded"
    assert broker.calls == []
    assert "idle: No verified work" in capsys.readouterr().out


def test_greeting_is_conversational_local_and_does_not_disclose_state(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "Hello"), engine_context=FakeContext({"hermes": broker})
    )

    output = capsys.readouterr().out
    assert result.status == "succeeded"
    assert broker.calls == []
    assert "Hello! I’m the Cortxt orchestrator." in output
    assert "30 items" not in output
    assert "Attention required" not in output
    assert not (tmp_path / "sessions").exists()


def test_chat_invokes_hermes_broker_and_persists_metadata_only(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    result = unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?"), engine_context=FakeContext({"hermes": broker})
    )

    assert result.status == "succeeded"
    assert broker.calls[0][0] == "researcher"
    assert "SANITIZED LOCAL PROJECTION" in broker.calls[0][1]
    session_id = next((tmp_path / "sessions").iterdir()).name
    doc = session_state.load(tmp_path / "sessions", session_id)
    records = [event["payload"] for event in doc["events"] if event["event_type"].startswith("chat.")]
    assert [record["role"] for record in records] == ["user", "assistant"]
    assert all("content" not in record for record in records)
    assert doc["events"][-1]["event_type"] == "session.terminal"
    assert "Advisory answer" in capsys.readouterr().out


def test_default_engine_is_hermes_when_flag_omitted(tmp_path, monkeypatch, capsys):
    broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "hi there is anything running?"), engine_context=FakeContext({"hermes": broker})
    )

    assert broker.calls  # hermes broker was the one invoked


def test_engine_flag_selects_the_broker_for_every_turn(tmp_path, monkeypatch, capsys):
    hermes_broker = FakeBroker()
    codex_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?", engine="codex"),
        engine_context=FakeContext({"hermes": hermes_broker, "codex": codex_broker}),
    )

    assert hermes_broker.calls == []
    assert codex_broker.calls


def test_slash_engine_command_switches_broker_for_the_next_turn(tmp_path, monkeypatch, capsys):
    hermes_broker = FakeBroker()
    codex_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))
    inputs = iter(["/engine codex", "what is running?", "/quit"])

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, None),
        engine_context=FakeContext({"hermes": hermes_broker, "codex": codex_broker}),
        input_fn=lambda prompt: next(inputs),
    )

    assert hermes_broker.calls == []
    assert codex_broker.calls
    assert "Active engine: codex" in capsys.readouterr().out


def test_transcript_engine_field_follows_the_active_engine(tmp_path, monkeypatch, capsys):
    codex_broker = FakeBroker()
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?", engine="codex"),
        engine_context=FakeContext({"codex": codex_broker}),
    )

    session_id = next((tmp_path / "sessions").iterdir()).name
    doc = session_state.load(tmp_path / "sessions", session_id)
    records = [event["payload"] for event in doc["events"] if event["event_type"].startswith("chat.")]
    assert all(record["engine"] == "codex" for record in records)


def test_second_turn_to_the_same_engine_resumes_the_first_turns_session(tmp_path, monkeypatch, capsys):
    broker = FakeBroker(session_ids=["sess-first", "sess-second"])
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))
    inputs = iter(["what is running?", "and now?", "/quit"])

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, None),
        engine_context=FakeContext({"hermes": broker}),
        input_fn=lambda prompt: next(inputs),
    )

    assert broker.calls[0][2]["session_id"] is None
    assert broker.calls[1][2]["session_id"] == "sess-first"


def test_engine_session_id_is_persisted_on_the_assistant_record(tmp_path, monkeypatch, capsys):
    broker = FakeBroker(session_ids=["sess-first"])
    monkeypatch.setattr(unified_cli, "_collect_orchestrator_projection", lambda args: _projection(tmp_path))

    unified_cli._run_orchestrator_chat(
        _args(tmp_path, "what is running?"), engine_context=FakeContext({"hermes": broker})
    )

    session_id = next((tmp_path / "sessions").iterdir()).name
    doc = session_state.load(tmp_path / "sessions", session_id)
    assistant_record = next(
        event["payload"] for event in doc["events"]
        if event["event_type"] == "chat.assistant"
    )
    assert assistant_record["engine_session_id"] == "sess-first"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/cli/test_orchestrator_chat.py -v`
Expected: FAIL — `test_engine_flag_selects_the_broker_for_every_turn` and
the `/engine`/resume tests fail (`KeyError: 'hermes'` from the old
`FakeContext.get` always asserting `engine_id == "hermes"`, or the broker
never being invoked for `"codex"`); `test_second_turn...` and
`test_engine_session_id_is_persisted...` fail because `broker.calls[...][2]`
has no `"session_id"` key yet.

- [ ] **Step 3: Implement**

In `agent-platform/cli/unified_cli.py`, first add the `--engine` flag to the
`orchestrator` subcommand's chat-mode arguments (in `main()`, alongside the
existing `orchestrator_parser.add_argument("--hermes-profile", ...)` line):

```python
    orchestrator_parser.add_argument("--engine", default="hermes", help="Engine to talk to in chat mode (hermes, codex, ...)")
```

Then replace `_run_orchestrator_chat`'s body. The full new function:

```python
def _run_orchestrator_chat(
    args: argparse.Namespace, *, engine_context: "EngineContext | None" = None,
    input_fn=None,
) -> ResultEnvelope:
    """Talk to the advisory orchestrator while deterministic commands stay local."""
    from cli import orchestrator as orchestrator_cli
    from runtime import session_state as state
    from runtime.default_engine_context import build_default_engine_context

    projection = _collect_orchestrator_projection(args)
    context = engine_context or build_default_engine_context()
    active_engine_id = getattr(args, "engine", None) or "hermes"
    engine_sessions: dict[str, str] = {}
    transcript_id = orchestrator_cli.new_transcript_id()
    store = args.store or (_get_agent_platform_path() / ".sessions")
    session_id: str | None = None
    sequence = 0
    read_input = input_fn or input
    turn = 0
    failed = False

    print("Cortxt orchestrator chat — advisory, GitHub workflow state is authoritative.")
    print("Commands: /status /workstreams /runtimes /skills /engine <id> /quit")
    pending = [args.ask] if args.ask else None
    while True:
        try:
            value = pending.pop(0) if pending else read_input("cortxt> ")
        except (EOFError, KeyboardInterrupt):
            print("\nSession closed.")
            break
        value = value.strip()
        if not value:
            if pending is not None:
                break
            continue
        if value == "/quit":
            print("Session closed.")
            break
        if value.startswith("/engine"):
            parts = value.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                active_engine_id = parts[1].strip()
            print(f"Active engine: {active_engine_id}")
            if pending is not None and not pending:
                break
            continue
        if value.startswith("/"):
            print(orchestrator_cli.render_chat_command(value, projection))
        else:
            local_reply = orchestrator_cli.local_conversation_reply(value)
            if local_reply is not None:
                print(local_reply)
                if pending is not None and not pending:
                    break
                continue
            turn += 1
            if session_id is None:
                session_doc = state.create(
                    store,
                    task_id=f"orchestrator-chat:{transcript_id[:8]}",
                    workstream_id=args.workstream_id or args.branch or "orchestrator-chat",
                    run_id=transcript_id,
                    branch=args.branch,
                    worker_role="orchestrator",
                    runtime=active_engine_id,
                )
                session_id = session_doc["session_id"]
            prompt, redactions = orchestrator_cli.build_chat_prompt(value, projection)
            user_record = orchestrator_cli.transcript_record(
                transcript_id=transcript_id, turn_index=turn, role="user",
                content=value, engine=active_engine_id, status="submitted", redactions=redactions,
            )
            state.append(store, session_id, sequence, "chat.user", user_record)
            sequence += 1
            broker = context.get(active_engine_id)
            try:
                result = broker.invoke(
                    args.hermes_profile,
                    prompt,
                    timeout_seconds=args.timeout,
                    model=args.model,
                    provider=args.provider,
                    cwd=_get_agent_platform_path().parent,
                    session_id=engine_sessions.get(active_engine_id),
                )
            except Exception as error:
                result = {"status": "failed", "stdout": "", "stderr": str(error), "session_id": None}
            answer = result.get("stdout", "").strip()
            status = result.get("status", "failed")
            new_engine_session_id = result.get("session_id")
            if new_engine_session_id:
                engine_sessions[active_engine_id] = new_engine_session_id
            if answer:
                print(answer)
            else:
                print(f"{active_engine_id} {status}: {result.get('stderr') or 'no response'}")
            assistant_record = orchestrator_cli.transcript_record(
                transcript_id=transcript_id, turn_index=turn, role="assistant",
                content=answer or result.get("stderr", ""), engine=active_engine_id, status=status,
                engine_session_id=new_engine_session_id,
            )
            state.append(store, session_id, sequence, "chat.assistant", assistant_record)
            sequence += 1
            failed = failed or status != "succeeded"
        if pending is not None and not pending:
            break
    artifacts = [f"snapshot:{projection['snapshot_path']}"]
    if session_id is not None:
        state.append(
            store, session_id, sequence, "session.terminal",
            {"status": "failed" if failed else "succeeded"},
        )
        projection = _collect_orchestrator_projection(args)
        artifacts.append(f"session:{session_id}")
    return ResultEnvelope(
        status="failed" if failed else "succeeded",
        artifacts=artifacts,
        evidence=[{"transcript_id": transcript_id, "turns": turn, "content_persisted": False}],
    )
```

(Only the differences from today's version: `active_engine_id`/`engine_
sessions` replace the hardcoded `broker = context.get("hermes")` done once
up front; `/engine` is a new branch before the generic `/` dispatch; the
help line lists `/engine <id>`; `runtime=active_engine_id` replaces the
hardcoded `runtime="hermes"` in `state.create`; both `transcript_record`
calls use `engine=active_engine_id`; the assistant one adds
`engine_session_id=new_engine_session_id`; `broker.invoke(...)` moved inside
the loop and gained `session_id=engine_sessions.get(active_engine_id)`; the
result dict's `session_id` is captured into `engine_sessions` right after
the call.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/cli/test_orchestrator_chat.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 5: Run the full filtered suite to check for regressions**

Run: `cd agent-platform && python -m pytest -m "not real_inference and not docker_required" -q`
Expected: PASS, same or higher total than the 588 passed / 4 skipped
baseline recorded before this plan started (`.hermes/dispatch/handoff-20260820b.md`)

- [ ] **Step 6: Commit**

```bash
git add agent-platform/cli/unified_cli.py agent-platform/tests/cli/test_orchestrator_chat.py
git commit -m "feat(cli): add engine choice and per-engine resume to orchestrator chat"
```

---

## Self-review notes (for whoever executes this plan)

- Spec coverage: EngineAdapter protocol (Task 1), Hermes resume request +
  capture (Tasks 2–3), HermesAdapter passthrough (Task 4), CodexAdapter
  (Task 5), registration (Task 6), transcript persistence (Task 7), REPL
  engine choice + per-engine resume (Task 8) — every Architecture section
  of the spec has a task. The spec's Open questions #1–#2 (event shape,
  Hermes id capture) are resolved in Global Constraints, not left open.
  Open question #3 (provider handling) is resolved in Task 5 (raise).
  Open questions #4 (resuming a *past* Cortxt session across REPL
  restarts) and #5 (per-engine timeout defaults) remain genuinely open —
  correctly out of this plan's scope per the spec's own Decomposition note.
- No task references a type/function not defined by an earlier task in this
  plan or already present in the codebase.
