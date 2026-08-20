# Plan-task-ref correlation metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `plan_task_ref` optional session field (Part 1 of the
plan-vs-actual divergence design) so a session can record which sidecar-YAML
plan task it's executing, threaded through session creation and the
status/snapshot pipeline. This is the correlation-metadata increment only —
no sidecar loading, no reconciliation logic, no widget rendering (that's
Part 2, a separate later plan, per the spec's explicit increment ordering).

**Architecture:** `session_state.create()` gains one new optional keyword
parameter, `plan_task_ref: str | None`, stored verbatim in the
`session.created` event payload using the exact same "include a key only if
supplied" pattern the existing optional fields (`workstream_id`, `run_id`,
etc.) already use. `cli/status.py:load_sessions()` reads it off
`created_payload` into the per-session dict it builds, mirroring the
existing `runtime`/`branch` lines. `write_snapshot()` requires no code
change — it already carries whatever `load_sessions()` produced through to
the snapshot JSON by inheritance — but gets a regression test proving that
inheritance actually holds for this new field, since that claim is asserted
by this plan and should not go unverified.

**Tech Stack:** Python 3.11+, pytest, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-plan-vs-actual-divergence-v1-design.md`
(Part 1, "The new session field this requires" section)

## Revision note (2026-08-20, Codex review)

Codex reviewed this plan against the pasted full contents of
`session_state.py`, `cli/status.py`, and both test files (its Windows
sandbox cannot spawn any subprocess in this environment — `CreateProcessAsUserW
failed: 5` — so file contents were pasted into the review prompt directly,
per the established workaround; no tool calls were made). One real bug was
found and fixed inline: Task 3's original test guessed `write_snapshot()`'s
signature and the snapshot's JSON shape (`write_snapshot(out_path,
workstreams, sessions=sessions)`, workstream→lane→session traversal) —
both wrong against the real function (`write_snapshot(sessions,
snapshot_path, ...)`, flat `{"sessions": [...]}` output). Fixed in Task 3
below to call the real signature and read `doc["sessions"]` directly.

Three further findings (no sidecar YAML implementation, no drift-check
lint, no call site threading a real `plan_task_ref` at dispatch time) are
correct observations but not gaps in this plan — the spec (Part 1,
"its own implementation increment") and this plan's own Self-review notes
both scope those out deliberately: the sidecar format and lint are
explicitly Non-goals of the spec itself, and populating `plan_task_ref` at
a real call site is Open Question #5 in the spec, left for a later
increment. Not actioned here.

A minor note (`plan_task_ref=""` is accepted, "non-empty string" claim is
untested) is accepted as a known, harmless permissiveness — every other
optional identity field on `create()` (`workstream_id`, `branch`, etc.)
has the identical property and none of them are validated either; adding
validation to only the new field would be inconsistent with the function's
existing contract, not a fix.

## Global Constraints

- `plan_task_ref` is optional everywhere; omitting it must not change any
  existing behavior or serialized output (spec: "additive... no new event
  type, no schema-version bump").
- No validation of the string's shape (`<plan_id>#<task_id>`) happens in
  this increment — that parsing/resolution is Part 2's correlation logic,
  explicitly out of scope here. `session_state.create()` accepts any
  non-empty string or `None`, same permissiveness as the other optional
  identity fields.
- Do not touch sidecar YAML format, widget rendering, or daemon dispatch
  logic — all explicitly out of scope per the spec's Non-goals section.

---

### Task 1: `session_state.create()` accepts `plan_task_ref`

**Files:**
- Modify: `agent-platform/runtime/session_state.py:80-112` (the `create()` function)
- Test: `agent-platform/tests/runtime/test_session_state.py`

**Interfaces:**
- Produces: `session_state.create(store, task_id, *, ..., plan_task_ref: str | None = None) -> dict`. The returned `doc["events"][0]["payload"]` includes key `"plan_task_ref"` only when a non-`None` value was supplied — same as `workstream_id`, `run_id`, `issue_id`, `branch`, `worktree`, `worker_role`, `runtime` already behave.

- [ ] **Step 1: Write the failing test**

Add to `agent-platform/tests/runtime/test_session_state.py`:

```python
def test_create_includes_plan_task_ref_when_given():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1", plan_task_ref="2026-08-20-example-plan#T3")
    assert doc["events"][0]["payload"]["plan_task_ref"] == "2026-08-20-example-plan#T3"


def test_create_omits_plan_task_ref_when_not_given():
    store = _store(Path(tempfile.mkdtemp()))
    doc = s.create(store, task_id="t1")
    assert "plan_task_ref" not in doc["events"][0]["payload"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-platform && python -m pytest tests/runtime/test_session_state.py -k plan_task_ref -v`
Expected: FAIL — `create() got an unexpected keyword argument 'plan_task_ref'`

- [ ] **Step 3: Add the parameter**

In `agent-platform/runtime/session_state.py`, modify `create()`:

```python
def create(
    store: Path,
    task_id: str,
    *,
    workstream_id: str | None = None,
    run_id: str | None = None,
    issue_id: str | None = None,
    branch: str | None = None,
    worktree: str | None = None,
    worker_role: str | None = None,
    runtime: str | None = None,
    plan_task_ref: str | None = None,
) -> dict:
    if not isinstance(task_id, str) or not task_id.strip():
        raise SessionError("invalid_input", "task_id must be a non-empty string")
    session_id = "session_" + uuid.uuid4().hex
    payload = {"task_id": task_id}
    optional = {
        "workstream_id": workstream_id,
        "run_id": run_id,
        "issue_id": issue_id,
        "branch": branch,
        "worktree": worktree,
        "worker_role": worker_role,
        "runtime": runtime,
        "plan_task_ref": plan_task_ref,
    }
    payload.update({key: value for key, value in optional.items() if value is not None})
    doc = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "events": [_event(0, "session.created", payload, ZERO_HASH)],
    }
    _atomic_write(_session_path(store, session_id), doc)
    return doc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/runtime/test_session_state.py -v`
Expected: PASS, all tests including the two new ones and the pre-existing `test_create_returns_session_with_one_event` (which asserts the exact payload dict for a call with no optional args — must still equal `{"task_id": "synth-classify-001"}`, confirming the new field stays absent when omitted).

- [ ] **Step 5: Commit**

```bash
git add agent-platform/runtime/session_state.py agent-platform/tests/runtime/test_session_state.py
git commit -m "feat(session-state): add optional plan_task_ref field to session.created"
```

---

### Task 2: `load_sessions()` surfaces `plan_task_ref`

**Files:**
- Modify: `agent-platform/cli/status.py:160-185` (the dict `load_sessions()` appends per session)
- Test: `agent-platform/tests/cli/test_status.py`

**Interfaces:**
- Consumes: `session_state.create(..., plan_task_ref=...)` from Task 1.
- Produces: each dict in `load_sessions()`'s return list gains key
  `"plan_task_ref"`, value `created_payload.get("plan_task_ref")` (i.e.
  `None` when the session was created without one — same style as the
  existing `"runtime": created_payload.get("runtime")` line, no `or`
  fallback since there is no legacy field to fall back to).

- [ ] **Step 1: Write the failing test**

Add to `agent-platform/tests/cli/test_status.py` (near the other
`load_sessions` metadata tests, e.g. after
`test_workstream_groups_agent_sessions_and_keeps_workspace_metadata`):

```python
def test_load_sessions_surfaces_plan_task_ref(tmp_path):
    store = tmp_path / "sessions"
    store.mkdir()
    state.create(
        store,
        task_id="t1",
        workstream_id="issue-180",
        plan_task_ref="2026-08-20-example-plan#T3",
    )
    state.create(store, task_id="t2", workstream_id="issue-180")

    sessions = status.load_sessions(store)
    by_task = {s["task_id"]: s for s in sessions}
    assert by_task["t1"]["plan_task_ref"] == "2026-08-20-example-plan#T3"
    assert by_task["t2"]["plan_task_ref"] is None
```

Confirm `state` (the `runtime.session_state` module) and `status` are
already imported under those names at the top of the test file — if the
existing import is `from runtime import session_state as state` and
`from cli import status`, reuse those; do not add a second alias.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-platform && python -m pytest tests/cli/test_status.py -k plan_task_ref -v`
Expected: FAIL — `KeyError: 'plan_task_ref'`

- [ ] **Step 3: Add the field**

In `agent-platform/cli/status.py`, inside `load_sessions()`'s
`sessions.append({...})` block, add one line alongside the existing
`"runtime": created_payload.get("runtime"),` line:

```python
                "runtime": created_payload.get("runtime"),
                "plan_task_ref": created_payload.get("plan_task_ref"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent-platform && python -m pytest tests/cli/test_status.py -v`
Expected: PASS, all tests including the new one.

- [ ] **Step 5: Commit**

```bash
git add agent-platform/cli/status.py agent-platform/tests/cli/test_status.py
git commit -m "feat(status): surface plan_task_ref from session.created payload"
```

---

### Task 3: `write_snapshot()` regression test for `plan_task_ref` inheritance

**Files:**
- Test: `agent-platform/tests/cli/test_status.py`
- No production code change expected — `write_snapshot()` carries whatever
  `load_sessions()` produces through to the snapshot JSON without
  per-field special-casing (confirmed by reading `write_snapshot()` in
  full this session). This task exists to prove that claim holds for
  `plan_task_ref` specifically, not to assume it.

**Interfaces:**
- Consumes: `load_sessions()` output from Task 2, `write_snapshot()`
  (existing function, signature unchanged).

- [ ] **Step 1: Write the test**

Add to `agent-platform/tests/cli/test_status.py`, placed near the existing
`test_write_snapshot_includes_runtimes_and_credentials_when_given`:

```python
def test_write_snapshot_carries_plan_task_ref_through(tmp_path):
    store = tmp_path / "sessions"
    store.mkdir()
    state.create(
        store,
        task_id="t1",
        workstream_id="issue-180",
        plan_task_ref="2026-08-20-example-plan#T3",
    )

    sessions = status.load_sessions(store)
    out_path = tmp_path / "snapshot.json"
    status.write_snapshot(sessions, out_path)

    doc = json.loads(out_path.read_text(encoding="utf-8"))
    matching = [s for s in doc["sessions"] if s.get("task_id") == "t1"]
    assert matching, "expected session t1 to appear in doc['sessions']"
    assert matching[0]["plan_task_ref"] == "2026-08-20-example-plan#T3"
```

`write_snapshot()`'s real signature is
`write_snapshot(sessions, snapshot_path, *, runtimes=None, credentials=None,
daemon=None, engines=None, skills=None, profiles=None) -> None` — positional
`sessions` first, then the output path; the snapshot document is a flat
`{"sessions": [...]}` shape (`doc["sessions"] == sessions`, confirmed by
the existing `test_write_snapshot_includes_runtimes_and_credentials_when_given`
test), not a workstream/lane traversal. Do not call `build_workstreams()`
for this test — `write_snapshot()` takes the flat session list directly.

- [ ] **Step 2: Run test to verify current behavior**

Run: `cd agent-platform && python -m pytest tests/cli/test_status.py -k plan_task_ref_through -v`
Expected: PASS if Task 2 landed first (inheritance already works with no
code change) — if it fails, `write_snapshot()` does special-case fields
somewhere and needs a one-line fix mirroring how `runtime` is carried
through; do not add speculative code before seeing a real failure.

- [ ] **Step 3: Commit**

```bash
git add agent-platform/tests/cli/test_status.py
git commit -m "test(status): lock in plan_task_ref inheritance through write_snapshot"
```

---

## Self-review notes

- **Spec coverage:** This plan implements exactly the "new session field
  this requires" subsection of Part 1. It deliberately does NOT implement
  the sidecar YAML format itself (no loader/parser task) — the spec states
  the sidecar is "not required to exist at plan-authoring time" and its
  drift-check lint is explicitly out of scope (Non-goals); there is no
  code artifact to build for the sidecar format alone, only the schema
  documentation already in the spec. Part 2 (correlation/reconciliation/
  rendering) is a separate, later plan per the spec's own increment
  ordering — not duplicated here.
- **Open question #5** ("who writes `plan_task_ref` at session-creation
  time... a new `--plan-task` CLI flag, or the interactive picker per the
  operator's decision #5") is Part 2/daemon-dispatch territory, not this
  increment — this plan only makes the field exist and flow through; wiring
  a CLI flag or picker to populate it is future work, named but not built
  here.
