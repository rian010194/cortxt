# Track 0: Orchestrator Mechanism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Confirm Pi's and the operator's own coding agent's invocation contracts, confirm what actually drives autonomous Kanban dispatch in this repo, and add a queryable checkpoint-policy field to the engine manifest — the three pieces Track 0 owns per the swarm design, without guessing any of them.

**Architecture:** Two investigative tasks (spikes, not code) establish ground truth before anything is built on top of them. One code task extends `agent-platform/routing/engine_manifest.py`'s existing, tested `EngineManifest`/`route()` pair with a `checkpoint_required` field — data the escalation step of the swarm design can consult, independent of what Task 2 finds.

**Tech Stack:** Python 3.11+, pytest, existing `agent-platform/routing/` package conventions (frozen dataclasses, `from __future__ import annotations`).

**Spec:** `docs/superpowers/specs/2026-08-19-v02-swarm-orchestration-model-design.md`

## Global Constraints

- No CLI invocation contract (Pi, the own coding agent, or any future engine) is written into code until confirmed by direct inspection — per the spec's explicit callout against guessing an invocation shape (the headless-Claude-Code-CLI precedent).
- `reliability_class` on any new `EngineManifest` entry starts at `"unverified"` and stays there until that engine has its own cleared proof step (spec, Engine Expansion section).
- Every code task's tests run via `pytest agent-platform/tests/ -v` from the repo root's `agent-platform/` directory (existing project convention — see `tests/routing/test_engine_manifest.py`).

---

### Task 1: Pi and own-coding-agent invocation spike

**Files:**
- Create: `.hermes/plans/2026-08-19-track0-engine-spike-findings.md` (gitignored, matches the existing `.hermes/plans/` convention used for the prior session's running logs)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: a findings note that Task 3 of Track 0's *next* plan (not this one — see Task 3 below) will read before writing `pi_invoker.py`/`own_agent_invoker.py`. This task does not itself write those invoker modules.

- [ ] **Step 1: Locate Pi's CLI entry point**

Run: `where pi` (or `Get-Command pi` if `where` isn't on PATH) to confirm Pi is installed and find its executable path. If not found, check the operator's shell profile / installed packages for how Pi is normally invoked (it may be a different command name — do not assume `pi`).

- [ ] **Step 2: Read Pi's own `--help` output**

Run: `pi --help` (substitute the actual command found in Step 1). Record the full output in the findings note. Look specifically for a non-interactive / one-shot / scriptable mode analogous to Hermes's `-z` flag — this is the detail Task 3 of the next plan needs most.

- [ ] **Step 3: Locate the own coding agent's CLI entry point**

Ask the operator directly what command invokes "the own coding agent" mentioned in the brainstorming session, if it is not obvious from `PATH` or the repo's `scripts/` directory. Do not guess a binary name.

- [ ] **Step 4: Read the own coding agent's `--help` output (or equivalent)**

Same as Step 2, for the own agent. Record in the findings note.

- [ ] **Step 5: Write the findings note's verdict section**

For each engine (Pi, own agent), write one paragraph answering: (a) is there a confirmed one-shot/non-interactive invocation, (b) what is its exact command shape (flags, stdin/stdout contract), (c) is it ready for a `*_invoker.py` module now, or does it need a follow-up spike (e.g. if it requires an API key/config not yet present). This verdict is what unblocks or freezes the next plan's invoker-module task.

- [ ] **Step 6: Commit the findings note**

```bash
git add .hermes/plans/2026-08-19-track0-engine-spike-findings.md
git commit -m "spike: confirm Pi and own-agent CLI invocation contracts"
```

(Note: `.hermes/` is gitignored repo-wide per existing convention — confirm with `git check-ignore .hermes/plans/2026-08-19-track0-engine-spike-findings.md` before this step. If ignored, skip the commit; the file still exists locally and its contents get folded into the end-of-session handoff instead.)

---

### Task 2: Confirm the Kanban dispatch trigger mechanism

**Files:**
- Create: `.hermes/plans/2026-08-19-track0-kanban-mechanism-findings.md` (same gitignore caveat as Task 1)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: a findings note establishing whether the failed #165/#166/#174/#175 dispatches ran through `scripts/dispatcher.py` + `scripts/worker_adapters.py` (this repo's `Run`/claim/lease primitive) or through separate tooling outside this repo's version control (e.g. Hermes's own worktree/task automation). This determines whether "mid-task checkpoint support" is even buildable as a code change in this repo, or is a personal-discipline practice until a future track builds a repo-owned Kanban wrapper.

- [ ] **Step 1: Rule in or out `scripts/dispatcher.py`**

Read `scripts/dispatcher.py` in full (405 lines). Confirm whether it has any code path that creates a GitHub issue, opens a PR, or otherwise matches the "autonomous Kanban dispatch" behavior described in the prior handoff (issues #165, #166, #174, #175 — self-reported "completed" with an uncommitted worktree). If `dispatcher.py`'s `Run`/`claim`/`complete` lifecycle has no GitHub-issue or PR-opening code at all, that's decisive: it is not the mechanism that failed.

- [ ] **Step 2: Search for what does open PRs from a GitHub issue**

Run: `grep -rn "gh pr create\|gh issue\|github" .hermes/plans/2026-08-19-orchestrator-dispatch-v01.md scripts/ agent-platform/ 2>/dev/null` (adjust to whatever the environment supports) to find any script or config in this repo that ties a GitHub issue to an autonomous agent run. Also check `.github/ISSUE_TEMPLATE/agent-task.yml` (confirmed to exist) for clues about what tooling consumes that template.

- [ ] **Step 3: Ask the operator directly if repo-internal search is inconclusive**

If no repo-internal mechanism is found (this is the likely outcome — `.github/workflows/` currently has only `ci.yml`, no Hermes/Kanban automation), do not guess further. Ask the operator: "Where does the actual Kanban-dispatch trigger live — is it a Hermes-side worktree/task feature outside this repo, or something I haven't found yet?" Record the answer.

- [ ] **Step 4: Write the verdict**

State plainly in the findings note: is mid-task-checkpoint enforcement buildable as a code change in this repo today (name the file/mechanism if yes), or does it require either (a) a future track that builds a repo-owned Kanban-invocation wrapper, or (b) staying a personal-discipline practice (I manually withhold "done" acceptance until I've reviewed an actual diff, regardless of what the dispatched agent self-reports) until such a wrapper exists.

- [ ] **Step 5: Commit the findings note** (same gitignore caveat as Task 1 Step 6)

```bash
git add .hermes/plans/2026-08-19-track0-kanban-mechanism-findings.md
git commit -m "spike: confirm what actually triggers Kanban-style autonomous dispatch"
```

---

### Task 3: Add `checkpoint_required` to `EngineManifest`

**Files:**
- Modify: `agent-platform/routing/engine_manifest.py`
- Test: `agent-platform/tests/routing/test_engine_manifest.py`

**Interfaces:**
- Consumes: nothing from Task 1/2 — this is buildable regardless of their findings, since it only declares policy data, not an enforcement mechanism.
- Produces: `EngineManifest.checkpoint_required: bool` (default `True`), consulted by `EngineChoice` — later dispatch logic (a future task, not this plan) can read `EngineChoice.checkpoint_required` to decide whether an escalated run needs the mid-task gate before it's trusted to continue unattended.

- [ ] **Step 1: Write the failing test — manifest defaults to checkpoint-required**

Add to `agent-platform/tests/routing/test_engine_manifest.py`:

```python
def test_manifest_defaults_to_checkpoint_required():
    manifest = EngineManifest(
        engine_id="test-engine",
        task_shapes=("general",),
        cost_class="cheap",
        reliability_class="unverified",
    )
    assert manifest.checkpoint_required is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/routing/test_engine_manifest.py::test_manifest_defaults_to_checkpoint_required -v`
Expected: FAIL with `TypeError: EngineManifest.__init__() got an unexpected keyword argument` or an `AttributeError` on `checkpoint_required` (the field doesn't exist yet).

- [ ] **Step 3: Add the field to `EngineManifest`**

In `agent-platform/routing/engine_manifest.py`, inside the `EngineManifest` dataclass (after the existing `notes: str = ""` field):

```python
    checkpoint_required: bool = True
```

Update the class docstring's last paragraph to add one sentence: `checkpoint_required` defaults to `True` — an engine is only exempted once a proof step or track-specific evidence justifies unattended multi-step runs (none does yet, so nothing sets it to `False` today).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest agent-platform/tests/routing/test_engine_manifest.py::test_manifest_defaults_to_checkpoint_required -v`
Expected: PASS

- [ ] **Step 5: Write the failing test — `claude-direct` and `hermes` defaults are unchanged (still `True`)**

```python
def test_default_manifests_require_checkpoint():
    for manifest in DEFAULT_MANIFESTS:
        assert manifest.checkpoint_required is True, (
            f"{manifest.engine_id} should default to checkpoint_required=True; "
            "no engine has cleared evidence to be exempted yet"
        )
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest agent-platform/tests/routing/test_engine_manifest.py::test_default_manifests_require_checkpoint -v`
Expected: PASS already, actually — since Step 3's default is `True` and `DEFAULT_MANIFESTS` doesn't override it. If it unexpectedly fails, that means one of the two existing `EngineManifest(...)` literals in `DEFAULT_MANIFESTS` passed `checkpoint_required=False` explicitly, which Step 3 didn't add — re-check Step 3 was applied only to the dataclass field default, not the `DEFAULT_MANIFESTS` literals.

- [ ] **Step 7: Write the failing test — `EngineChoice` exposes the winning manifest's checkpoint policy**

```python
def test_route_result_carries_checkpoint_policy():
    manifests = (
        EngineManifest(
            engine_id="engine-a",
            task_shapes=("research",),
            cost_class="cheap",
            reliability_class="unverified",
            checkpoint_required=False,
        ),
    )
    choice = route(["research"], manifests)
    assert choice.checkpoint_required is False
```

- [ ] **Step 8: Run test to verify it fails**

Run: `pytest agent-platform/tests/routing/test_engine_manifest.py::test_route_result_carries_checkpoint_policy -v`
Expected: FAIL — `EngineChoice` has no `checkpoint_required` field yet.

- [ ] **Step 9: Add `checkpoint_required` to `EngineChoice` and set it in `route()`**

In `agent-platform/routing/engine_manifest.py`, add a field to the `EngineChoice` dataclass (after `excluded`):

```python
    checkpoint_required: bool = True
```

In `route()`, both `return` statements need updating. The fallback-path return (no candidate matched):

```python
    if not candidates:
        return EngineChoice(
            engine_id=fallback,
            reason=f"no engine matched task_tags={sorted(tag_set)}; falling back to default",
            matched_tag=None,
            excluded=tuple(excluded),
            checkpoint_required=True,
        )
```

(The fallback engine's own manifest isn't looked up here — `route()` only receives the candidate `manifests` list, and a fallback by definition wasn't in it as a match. Default to `True`, the conservative choice, rather than looking up `fallback` in `manifests` speculatively.)

The winning-candidate return:

```python
    candidates.sort(key=lambda pair: (COST_ORDER[pair[0].cost_class], pair[0].engine_id))
    winner, matched_tag = candidates[0]
    return EngineChoice(
        engine_id=winner.engine_id,
        reason=f"matched tag {matched_tag!r}, cheapest of {len(candidates)} candidate(s)",
        matched_tag=matched_tag,
        excluded=tuple(excluded),
        checkpoint_required=winner.checkpoint_required,
    )
```

- [ ] **Step 10: Run test to verify it passes**

Run: `pytest agent-platform/tests/routing/test_engine_manifest.py::test_route_result_carries_checkpoint_policy -v`
Expected: PASS

- [ ] **Step 11: Run the full existing test_engine_manifest.py suite to confirm no regression**

Run: `pytest agent-platform/tests/routing/test_engine_manifest.py -v`
Expected: all tests PASS, including the pre-existing ones (`route()`'s tag-matching, cost-ordering, and fallback tests written in Fas 3).

- [ ] **Step 12: Run the full project test suite**

Run: `pytest agent-platform/tests/ -v`
Expected: all tests PASS (493+ from the prior session, plus the 3 new ones here — no regressions elsewhere, since this task only added a defaulted field).

- [ ] **Step 13: Commit**

```bash
git add agent-platform/routing/engine_manifest.py agent-platform/tests/routing/test_engine_manifest.py
git commit -m "routing: add checkpoint_required policy field to EngineManifest/EngineChoice"
```

---

## Self-review notes

- Spec coverage: Track 0's three deliverables (Pi/own-agent spike, `*_invoker.py` modules, mid-task-checkpoint support) map to Task 1 (spike), Task 2 (a second, necessary spike the spec's wording assumed was already known — the Kanban trigger location), and Task 3 (the one grounded code piece). The `*_invoker.py` modules themselves are deliberately **not** in this plan — they depend on Task 1's findings, which don't exist yet. Once Task 1 lands, a short follow-up plan (one task per confirmed engine) covers them; writing their TDD steps now would mean guessing the CLI contract, which the spec explicitly forbids.
- No placeholders: every step has literal commands/code, no "TBD" or "add appropriate X."
- Type consistency: `checkpoint_required: bool` used identically across `EngineManifest`, `EngineChoice`, and the test file.
