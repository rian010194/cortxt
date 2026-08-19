"""The daemon's core dispatch cycle (spec: "Daemon loop" + "Data flow").
Wires the Evidence Gate, GitHub scanner, budget, and autonomy tracker
around the existing, proven dispatch v0.1 primitives -- routing.
engine_manifest.route() and routing.hermes_invoker.invoke_hermes() -- not
supervisor.coordinator.Coordinator, which is RLM child-recursion machinery
for a different concern (see spec's Architecture section and this plan's
course-correction note).

Final-review fixes (2026-08-19): route()'s decision is now enforced (a
non-hermes choice is skipped, never silently dispatched to hermes anyway --
this v1 daemon has no invoker for any other engine, matching hermes_invoker
.py's own documented "claude-direct has no headless invocation here");
Evidence Gate now checks a real signal (did a commit actually land) instead
of self-reported status alone; gate decisions have real effects (pause stops
run_forever, freeze is recorded distinctly); autonomy streaks persist across
restarts; HermesInvocationError and other run_once() failures no longer kill
the whole run_forever loop.
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
from routing.engine_manifest import DEFAULT_MANIFESTS, EngineManifest, route as _default_route
from routing.hermes_invoker import HermesInvocationError, invoke_hermes as _default_invoke_hermes
from cli.status import write_snapshot


def _known_task_shapes(manifests: tuple[EngineManifest, ...]) -> set[str]:
    shapes: set[str] = set()
    for m in manifests:
        shapes.update(m.task_shapes)
    return shapes


def _default_git_head(workdir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


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
    invoke_hermes: Callable = _default_invoke_hermes
    route: Callable = _default_route
    git_head: Callable[[Path], "str | None"] = _default_git_head
    claimed_issue_ids: set[str] = field(default_factory=set, init=False)

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
        daemon_status: dict = {
            "status": "running",
            "claimed": sorted(self.claimed_issue_ids),
            "budget_spent_usd": self.budget.spent_usd if self.budget.spent_usd else None,
        }
        if last_gate_outcome is not None:
            daemon_status["last_gate_outcome"] = {
                "decision": last_gate_outcome.decision, "reason": last_gate_outcome.reason,
            }
        if last_error is not None:
            daemon_status["last_error"] = last_error
        write_snapshot([], self.snapshot_path, daemon=daemon_status)

    def run_once(self) -> list[dict]:
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

            if choice.engine_id != "hermes":
                # This v1 daemon only has a Hermes invoker wired (routing.
                # hermes_invoker.invoke_hermes -- see its own docstring:
                # "claude-direct has no headless invocation here"). Silently
                # dispatching a claude-direct (or any non-hermes) routing
                # decision to Hermes anyway is exactly the "wrong surface"
                # failure mode behind #165/#166 -- refuse instead of guessing.
                continue

            # Persist the claim BEFORE dispatching: a crash between a
            # successful invoke_hermes() and persistence would otherwise
            # cause a real duplicate dispatch on restart. Persisting first
            # means the crash-window failure mode is a stuck claim (visible
            # in claimed.json, requires manual clear) instead of a
            # duplicate real-world side effect.
            self.claimed_issue_ids.add(issue_id)
            self._persist_claimed()

            head_before = self.git_head(self.workdir)
            try:
                invoke_result = self.invoke_hermes(
                    "researcher" if "research" in task_tags else "builder",
                    issue["title"], timeout_seconds=300,
                )
            except HermesInvocationError as error:
                gate_outcome = GateOutcome("freeze", f"hermes invocation failed to start: {error}")
                self.autonomy.record_pass(choice.engine_id, choice.matched_tag, clean=False)
                self._persist_autonomy()
                self._write_status(last_gate_outcome=gate_outcome)
                return [{"issue_id": issue_id, "engine_id": choice.engine_id,
                          "gate_outcome": {"decision": gate_outcome.decision, "reason": gate_outcome.reason}}]

            head_after = self.git_head(self.workdir)
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
