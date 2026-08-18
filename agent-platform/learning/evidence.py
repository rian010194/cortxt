"""EvidenceClassifier — typed evidence for the controlled learning loop (Fas 8, Beslut 10c).

Architecture borrowed as DESIGN INSPIRATION from Cloudflare Agent Memory (operator directive 2026-08-18):
a ``verifier`` runs checks before a memory is classified into one of four types, and retrieval is
multi-channel. Fas 8 uses the idea, NOT the Cloudflare service (no SLA, unknown pricing).

Two phases (Kimi P2.6):
- ``phase_a`` (at submit): initial classification of a candidate's payload/provenance into the four types
  (facts, events, instructions, tasks) — what the candidate IS.
- ``phase_b`` (before PromotionGate.evaluate, Task 5): verifier-checks over the EvidenceMatrix — whether the
  candidate's evaluation EVIDENCE is trustworthy enough to carry promotion weight (fail-closed).
"""
from __future__ import annotations

from typing import Any, Mapping


class EvidenceClassifier:
    """Typifies candidate evidence into the four Agent-Memory-inspired groups."""

    # minimum fraction of the fixture set that must be covered for evidence to carry weight (Kimi P2.6)
    _MIN_FIXTURE_COVERAGE = 0.5

    def phase_a(self, payload: Mapping[str, Any], provenance: str | None) -> dict[str, Any]:
        """Initial classification of a candidate's payload at submit (Kimi P2.6 phase a).

        Conservative v1 mapping (explicit key sets — deterministic, no substring surprises):
        - facts:        numeric/quality metrics (success_rate, baseline_delta, cost, latency, ...)
        - events:       timestamps + provenance (eval_run_at, proposed_at, provenance)
        - instructions: references to active candidate/config (active_candidate, baseline, config)
        - tasks:        lifecycle/next-step state (fixture_set, rollback_plan, next)
        Everything else falls through to ``facts`` so nothing is silently dropped.
        """
        facts: dict[str, Any] = {}
        events: dict[str, Any] = {}
        instructions: dict[str, Any] = {}
        tasks: dict[str, Any] = {}
        for k, v in (payload or {}).items():
            if k in {"provenance", "eval_run_at", "proposed_at", "created_at", "updated_at"}:
                events[k] = v
            elif k in {"active_candidate", "active_version", "baseline", "config"}:
                instructions[k] = v
            elif k in {"fixture_set", "rollback_plan", "next", "queue", "status"}:
                tasks[k] = v
            else:
                facts[k] = v
        if provenance:
            events["provenance"] = provenance
        return {"facts": facts, "events": events, "instructions": instructions, "tasks": tasks}

    def verify(self, candidate, matrix: Mapping[str, Any]) -> bool:
        """Phase (b) — verifier-checks over the EvidenceMatrix (Kimi P2.6).

        Evidence may NOT carry promotion weight unless the matrix is complete, has no regression, and
        covers a sufficient fraction of the fixture set. Fail-closed: any doubt returns False.
        """
        if not matrix.get("complete", True):
            return False
        if matrix.get("no_regression") is not True:
            return False
        coverage = matrix.get("fixture_coverage", 1.0)
        if coverage is None or coverage < self._MIN_FIXTURE_COVERAGE:
            return False
        return True
