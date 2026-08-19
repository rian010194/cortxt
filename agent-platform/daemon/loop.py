# agent-platform/daemon/loop.py
"""The daemon's core dispatch cycle (spec: "Daemon loop" + "Data flow").
Wires the Evidence Gate, GitHub scanner, budget, and autonomy tracker
around the existing, proven dispatch v0.1 primitives -- routing.
engine_manifest.route() and routing.hermes_invoker.invoke_hermes() -- not
supervisor.coordinator.Coordinator, which is RLM child-recursion machinery
for a different concern (see spec's Architecture section and this plan's
course-correction note).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from daemon.autonomy import AutonomyTracker
from daemon.budget import SessionBudget
from daemon.evidence_gate import evaluate_gate
from daemon.github_scanner import list_ready_issues as _default_list_ready_issues
from routing.engine_manifest import DEFAULT_MANIFESTS, EngineManifest, route as _default_route
from routing.hermes_invoker import invoke_hermes as _default_invoke_hermes
from cli.status import write_snapshot


def _known_task_shapes(manifests: tuple[EngineManifest, ...]) -> set[str]:
    shapes: set[str] = set()
    for m in manifests:
        shapes.update(m.task_shapes)
    return shapes


@dataclass
class DaemonLoop:
    repo: str
    state_dir: Path
    snapshot_path: Path
    budget: SessionBudget
    autonomy: AutonomyTracker
    supervised: bool = True
    manifests: tuple[EngineManifest, ...] = DEFAULT_MANIFESTS
    list_ready_issues: Callable = _default_list_ready_issues
    invoke_hermes: Callable = _default_invoke_hermes
    route: Callable = _default_route
    claimed_issue_ids: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        claimed_path = self.state_dir / "claimed.json"
        if claimed_path.is_file():
            self.claimed_issue_ids = set(json.loads(claimed_path.read_text(encoding="utf-8")))

    def _persist_claimed(self) -> None:
        (self.state_dir / "claimed.json").write_text(
            json.dumps(sorted(self.claimed_issue_ids)), encoding="utf-8"
        )

    def _write_status(self) -> None:
        write_snapshot([], self.snapshot_path, daemon={
            "status": "running",
            "claimed": sorted(self.claimed_issue_ids),
            "budget_spent_usd": self.budget.spent_usd,
        })

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

            # Persist the claim BEFORE dispatching (finding #2, review round 1):
            # a crash between a successful invoke_hermes() and persistence would
            # otherwise cause a real duplicate dispatch on restart. Persisting
            # first means the crash-window failure mode is a stuck claim
            # (visible in claimed.json, requires manual clear) instead of a
            # duplicate real-world side effect -- the safer trade for this
            # project's verified-progress-over-unverified-completion stance.
            self.claimed_issue_ids.add(issue_id)
            self._persist_claimed()

            invoke_result = self.invoke_hermes(
                "researcher" if "research" in task_tags else "builder",
                issue["title"], timeout_seconds=300,
            )
            result_envelope = {
                "status": "succeeded" if invoke_result["status"] == "succeeded" else "failed",
                "evidence": [{"kind": "hermes_result", "detail": invoke_result["status"]}],
                "artifacts": [f"issue:{issue_id}", f"engine:{choice.engine_id}"],
            }
            # Keyed on choice.matched_tag (finding #1, review round 1), not
            # task_tags[0] -- matched_tag is the tag route() actually used to
            # pick the engine, so the autonomy streak reflects the real
            # routing decision even when an issue carries multiple labels.
            gate_outcome = evaluate_gate(result_envelope, checkpoint_required=(
                self.supervised or choice.checkpoint_required
                or not self.autonomy.is_unlocked(choice.engine_id, choice.matched_tag)
            ))
            self.autonomy.record_pass(choice.engine_id, choice.matched_tag,
                                       clean=gate_outcome.decision in ("proceed", "pause"))

            self._write_status()

            return [{"issue_id": issue_id, "engine_id": choice.engine_id,
                      "gate_outcome": {"decision": gate_outcome.decision, "reason": gate_outcome.reason}}]
        return []
