"""ToolCandidateAdapter — §32.3 Tool-platform candidate (Fas 8, Beslut 5 / P1.6).

Mechanism-hooked: a tool candidate is registered and gated by effect class. Because every tool effect class
that touches the outside (external_mutation / irreversible / credential, §32.2) mandates a human operator
gate, the adapter's gate semantics ALWAYS route such tools to AWAIT_OPERATOR — and MANDATORY_OPERATOR_GATES
in the PromotionGate guarantees this even if no rules reach the gate. Full §32.3 security checklist
(credential/network isolation, dependency scanning) is an explicitly deferred v1.x deliverable (P1.6).
"""
from __future__ import annotations

from .candidate import Candidate
from .promotion_gate import PromotionRule

# effect classes that always require an operator gate (§32.2)
_EXTERNAL_EFFECTS = {"external_mutation", "irreversible", "credential"}


class ToolCandidateAdapter:
    def to_candidate(self, name: str, version: str, effect_class: str) -> Candidate:
        assert effect_class in _EXTERNAL_EFFECTS | {"observe", "local_mutation", "bounded_execution"}, \
            f"unknown tool effect class: {effect_class}"
        return Candidate(
            type="tool", name=name, version=version,
            payload={"effect_class": effect_class},
        )

    def rules(self, candidate: Candidate) -> list[PromotionRule]:
        # Honest fail-closed (Kimi Task8-11 P1): MANDATORY_OPERATOR_GATES = {"tool"} makes EVERY tool
        # candidate AWAIT_OPERATOR regardless of effect class, so the adapter's rule set is always the
        # operator gate — an [eval,safety] branch here would be dead code the gate permanently overrules.
        effect = (candidate.payload or {}).get("effect_class", "")
        return [PromotionRule("tool", kind="operator_gate", operator_scope=effect or "tool")]
