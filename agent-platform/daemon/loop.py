"""The daemon's core dispatch cycle (spec: "Daemon loop" + "Data flow").
Wires the Evidence Gate, GitHub scanner, budget, and autonomy tracker
around the existing, proven dispatch v0.1 primitives -- routing.
engine_manifest.route() and the EngineContext broker (runtime/engine_registry.py) -- not
supervisor.coordinator.Coordinator, which is RLM child-recursion machinery
for a different concern (see spec's Architecture section and this plan's
course-correction note).

Final-review fixes (2026-08-19): route()'s decision is now enforced (an
engine_id with no registered EngineContext adapter is skipped, never silently dispatched to whatever IS registered -- see runtime/engine_registry.py, ADR-026/027);
Evidence Gate now checks a real signal (did a commit actually land) instead
of self-reported status alone; gate decisions have real effects (pause stops
run_forever, freeze is recorded distinctly); autonomy streaks persist across
restarts; HermesInvocationError and other run_once() failures no longer kill
the whole run_forever loop.

Prompt + worktree fix (2026-08-19, Task 11 Step 2 proof-step follow-up):
`run_once()` now sends Hermes the issue's full body, not just its title --
the earlier title-only prompt gave Hermes no actual task spec, which is why
the first real end-to-end proof dispatch produced no commit at all. Each
dispatch also gets its own git worktree + branch (`create_worktree`,
injectable like `git_head`), created from `workdir` before invoking and
never removed automatically (branch cleanup/merge stays an operator
decision). `commit_landed` is now checked against that worktree, not the
shared `workdir` -- this closes two of the three known limitations noted
below: the cwd Hermes's subprocess runs in is now explicitly the same path
`git_head` inspects (no more "coincidentally equal" caveat), and concurrent
dispatches can no longer false-positive off each other's commits since each
has its own worktree. A `workdir` that isn't a git repo now fails loudly at
worktree-creation time (`git worktree add` errors, caught and turned into a
distinct "could not create isolated worktree" freeze) instead of the old
silent every-dispatch-freezes-with-no-reason behavior.

Known limitations of the git-commit evidence check (re-review, 2026-08-19),
not fixed here -- ruled acceptable for v1, documented so a future reader
doesn't read "real signal" as airtight: `commit_landed` only proves *some*
commit landed in the dispatch's worktree during the call, not that its
content matches what the issue asked for -- a real code/doc review step is
still a separate, unbuilt gate (see the "granskare/dokumenterare/scout
roles in the loop" thread). `allowed_artifact_prefixes=("issue:", "engine:")`
passed to `evaluate_gate` below is also known-tautological: `artifacts` is
constructed from those exact two prefixes on every call, so that check can
never fail -- it is not real scope enforcement, only a placeholder for when
a real per-run artifact list exists. `SessionBudget.record_cost()` is still
never called anywhere in this package -- `budget_spent_usd` reports `None`
rather than a misleading `0.0`, but no real cost is ever measured.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from daemon.autonomy import AutonomyTracker
from daemon.budget import SessionBudget
from daemon.stop_flag import is_stop_requested
from daemon.evidence_gate import GateOutcome, evaluate_gate
from daemon.github_scanner import list_ready_issues as _default_list_ready_issues
from daemon.review_sync import sync_review_submissions as _default_review_sync
from routing.engine_manifest import DEFAULT_MANIFESTS, EngineManifest, route as _default_route
from routing.hermes_invoker import HermesInvocationError
from routing.dsh_invoker import DshInvocationError
from runtime.default_engine_context import build_default_engine_context
from runtime.engine_registry import EngineContext
from cli.status import write_snapshot
from subprocess_windows import no_window_kwargs


def _known_task_shapes(manifests: tuple[EngineManifest, ...]) -> set[str]:
    shapes: set[str] = set()
    for m in manifests:
        shapes.update(m.task_shapes)
    return shapes


def _default_git_head(workdir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, **no_window_kwargs(),
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _default_create_worktree(workdir: Path, issue_id: str) -> Path:
    """Give each dispatch its own branch + worktree, sibling to `workdir`, so
    Hermes never writes directly onto whatever branch happens to be checked
    out in the daemon's own working tree. Idempotent (a crash-then-restart on
    an already-claimed issue reuses the same worktree instead of erroring).
    Never removed here -- cleanup/merge of a dispatch's branch is an
    operator decision, not something this loop does silently.
    """
    safe_id = issue_id.replace("/", "-").replace("#", "-issue-")
    worktree_path = workdir.parent / f"{workdir.name}-worktrees" / safe_id
    if worktree_path.is_dir():
        return worktree_path
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    branch = f"daemon/{safe_id}"
    result = subprocess.run(
        ["git", "-C", str(workdir), "worktree", "add", "-b", branch, str(worktree_path)],
        capture_output=True, text=True, timeout=30, **no_window_kwargs(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")
    return worktree_path


@dataclass
class DaemonLoop:
    repo: str
    state_dir: Path
    snapshot_path: Path
    budget: SessionBudget
    autonomy: AutonomyTracker
    supervised: bool = True
    manifests: tuple[EngineManifest, ...] = DEFAULT_MANIFESTS
    workdir: Path = field(default_factory=Path.cwd)
    list_ready_issues: Callable = _default_list_ready_issues
    engine_context: EngineContext = field(default_factory=build_default_engine_context)
    route: Callable = _default_route
    git_head: Callable[[Path], "str | None"] = _default_git_head
    create_worktree: Callable[[Path, str], Path] = _default_create_worktree
    review_sync: Callable = _default_review_sync
    run_store: Path | None = None
    claimed_issue_ids: set[str] = field(default_factory=set, init=False)
    last_review_sync: dict = field(default_factory=lambda: {"synced": 0, "skipped": 0, "failed": 0}, init=False)

    def __post_init__(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        claimed_path = self.state_dir / "claimed.json"
        if claimed_path.is_file():
            self.claimed_issue_ids = set(json.loads(claimed_path.read_text(encoding="utf-8")))
        autonomy_path = self.state_dir / "autonomy.json"
        if autonomy_path.is_file():
            self.autonomy = AutonomyTracker.from_dict(
                json.loads(autonomy_path.read_text(encoding="utf-8"))
            )

    def _persist_claimed(self) -> None:
        tmp = self.state_dir / ".claimed.json.tmp"
        tmp.write_text(json.dumps(sorted(self.claimed_issue_ids)), encoding="utf-8")
        tmp.replace(self.state_dir / "claimed.json")

    def _persist_autonomy(self) -> None:
        tmp = self.state_dir / ".autonomy.json.tmp"
        tmp.write_text(json.dumps(self.autonomy.to_dict()), encoding="utf-8")
        tmp.replace(self.state_dir / "autonomy.json")

    def _write_status(
        self,
        *,
        last_gate_outcome: GateOutcome | None = None,
        last_error: str | None = None,
    ) -> None:
        lane_status = "running"
        if last_gate_outcome is not None:
            lane_status = {"pause": "review", "freeze": "blocked", "proceed": "done"}.get(
                last_gate_outcome.decision, last_gate_outcome.decision
            )
        daemon_workstreams = []
        for issue_id in sorted(self.claimed_issue_ids):
            safe_id = issue_id.replace("/", "-").replace("#", "-issue-")
            daemon_workstreams.append(
                {
                    "workstream_id": issue_id,
                    "issue_id": issue_id,
                    "workspace": {
                        "branch": f"daemon/{safe_id}",
                        "worktree": str(self.workdir.parent / f"{self.workdir.name}-worktrees" / safe_id),
                    },
                    "status": lane_status,
                    "updated_at": None,
                    "lanes": [
                        {
                            "lane_id": f"daemon:{issue_id}",
                            "label": "supervisor daemon",
                            "runtime": "cortxt",
                            "run_id": None,
                            "session_id": None,
                            "status": lane_status,
                            "severity": "warn" if lane_status in {"review", "blocked"} else "info",
                            "segments": [],
                        }
                    ],
                }
            )
        daemon_status: dict = {
            "status": "running",
            "claimed": sorted(self.claimed_issue_ids),
            "budget_spent_usd": self.budget.spent_usd if self.budget.spent_usd else None,
            "workstreams": daemon_workstreams,
            "review_sync": self.last_review_sync,
        }
        if last_gate_outcome is not None:
            daemon_status["last_gate_outcome"] = {
                "decision": last_gate_outcome.decision, "reason": last_gate_outcome.reason,
            }
        if last_error is not None:
            daemon_status["last_error"] = last_error
        write_snapshot(None, self.snapshot_path, daemon=daemon_status)

    def run_review_sync(self) -> dict:
        store = self.run_store or (Path(__file__).resolve().parents[1] / ".sessions")
        return self.review_sync(store=store, state_dir=self.state_dir)

    def run_once(self) -> list[dict]:
        try:
            review_report = self.run_review_sync()
            self.last_review_sync = {
                key: len(review_report[key]) for key in ("synced", "skipped", "failed")
            }
            self._write_status()
        except Exception as error:
            self.last_review_sync = {"synced": 0, "skipped": 0, "failed": 1,
                                     "error": str(error)}
            self._write_status(last_error=f"review sync failed: {error}")
        issues = self.list_ready_issues(self.repo)
        shapes = _known_task_shapes(self.manifests)
        for issue in issues:
            issue_id = f"{self.repo}#{issue['number']}"
            if issue_id in self.claimed_issue_ids:
                continue

            label_names = {lbl["name"] for lbl in issue.get("labels", [])}
            task_tags = sorted(label_names & shapes)
            if not task_tags:
                continue  # no routable tag on this issue -- skip, don't guess

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

            # Persist the claim BEFORE dispatching: a crash between a
            # successful invoke_hermes() and persistence would otherwise
            # cause a real duplicate dispatch on restart. Persisting first
            # means the crash-window failure mode is a stuck claim (visible
            # in claimed.json, requires manual clear) instead of a
            # duplicate real-world side effect.
            self.claimed_issue_ids.add(issue_id)
            self._persist_claimed()

            prompt = issue["title"]
            body = issue.get("body")
            if body:
                prompt = f"{issue['title']}\n\n{body}"

            try:
                worktree_path = self.create_worktree(self.workdir, issue_id)
            except Exception as error:
                gate_outcome = GateOutcome("freeze", f"could not create isolated worktree: {error}")
                self.autonomy.record_pass(choice.engine_id, choice.matched_tag, clean=False)
                self._persist_autonomy()
                self._write_status(last_gate_outcome=gate_outcome)
                return [{"issue_id": issue_id, "engine_id": choice.engine_id,
                          "gate_outcome": {"decision": gate_outcome.decision, "reason": gate_outcome.reason}}]

            head_before = self.git_head(worktree_path)
            try:
                invoke_result = broker.invoke(
                    "researcher" if "research" in task_tags else "builder",
                    prompt, timeout_seconds=300, cwd=worktree_path,
                )
            # ADR-026 Review Trigger: a second adapter (dsh) widened this
            # except from Hermes-specific to the two invocation errors that
            # exist today -- the "researcher"/"builder" profile strings above
            # are the EngineAdapter-protocol shape, not hermes-specific
            # (dsh_adapter ignores profile for its own routing).
            except (HermesInvocationError, DshInvocationError) as error:
                gate_outcome = GateOutcome("freeze", f"worker invocation failed to start: {error}")
                self.autonomy.record_pass(choice.engine_id, choice.matched_tag, clean=False)
                self._persist_autonomy()
                self._write_status(last_gate_outcome=gate_outcome)
                return [{"issue_id": issue_id, "engine_id": choice.engine_id,
                          "gate_outcome": {"decision": gate_outcome.decision, "reason": gate_outcome.reason}}]

            head_after = self.git_head(worktree_path)
            commit_landed = (
                head_before is not None and head_after is not None and head_before != head_after
            )
            reported_status = invoke_result["status"]
            # A "succeeded" report with no commit is the #165/#166/#174/#175
            # self-reported-completion signature -- treat it as a failure,
            # not a pass, regardless of what the engine claimed.
            effective_status = (
                "succeeded" if (reported_status == "succeeded" and commit_landed) else "failed"
            )

            result_envelope = {
                "status": effective_status,
                "evidence": [
                    {"kind": "hermes_result", "detail": reported_status},
                    {"kind": "git_commit_check", "before": head_before, "after": head_after,
                     "commit_landed": commit_landed},
                ],
                "artifacts": [f"issue:{issue_id}", f"engine:{choice.engine_id}"],
            }
            # Keyed on choice.matched_tag, not task_tags[0] -- matched_tag is
            # the tag route() actually used to pick the engine, so the
            # autonomy streak reflects the real routing decision even when
            # an issue carries multiple labels.
            gate_outcome = evaluate_gate(
                result_envelope,
                checkpoint_required=(
                    self.supervised or choice.checkpoint_required
                    or not self.autonomy.is_unlocked(choice.engine_id, choice.matched_tag)
                ),
                allowed_artifact_prefixes=("issue:", "engine:"),
            )
            self.autonomy.record_pass(choice.engine_id, choice.matched_tag,
                                       clean=gate_outcome.decision in ("proceed", "pause"))
            self._persist_autonomy()

            self._write_status(last_gate_outcome=gate_outcome)

            return [{"issue_id": issue_id, "engine_id": choice.engine_id,
                      "gate_outcome": {"decision": gate_outcome.decision, "reason": gate_outcome.reason}}]
        return []

    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        max_iterations: int | None = None,
    ) -> str:
        iterations = 0
        while True:
            if is_stop_requested(self.state_dir):
                return "stop_requested"
            if self.budget.exhausted():
                return "budget_exhausted"
            try:
                results = self.run_once()
            except Exception as error:
                self._write_status(last_error=str(error))
                results = []
            else:
                if results and results[0]["gate_outcome"]["decision"] == "pause":
                    return "paused_for_review"
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return "max_iterations"
            sleep(poll_interval_seconds)
