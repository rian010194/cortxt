"""SkillCandidateAdapter — §31 Skill-platform candidate (Fas 8, Beslut 5 / P1.6).

Mechanism-hooked: a SkillManifest-based candidate is registered and gated by the §31 promotion table. In v1
the adapter is mechanism-functional (register + structural/regression eval + rule gate) but NOT deep-verified
for live skill-instruction eval (that is a budget-gated v1.x step, per P1.6 honesty).
"""
from __future__ import annotations

from .candidate import Candidate
from .promotion_gate import PromotionRule

# §31 table: 'instruction/example/source' -> eval+safety (auto-promotable); executable-helper -> operator gate.
_EXEC_HELPER_TYPES = {"executable_helper", "executable-helper", "helper"}
_AUTO_TYPES = {"instruction", "example", "source", "reference"}


class SkillCandidateAdapter:
    def to_candidate(self, name: str, version: str, change_type: str, content_md: str) -> Candidate:
        assert change_type in _EXEC_HELPER_TYPES | _AUTO_TYPES, f"unknown skill change_type: {change_type}"
        return Candidate(
            type="skill", name=name, version=version,
            payload={"change_type": change_type, "content_md": content_md},
        )

    def rules(self, candidate: Candidate) -> list[PromotionRule]:
        change_type = (candidate.payload or {}).get("change_type", "")
        if change_type in _EXEC_HELPER_TYPES:
            # §31: executable helper -> named human operator gate; never auto.
            return [PromotionRule("skill", kind="operator_gate", operator_scope="executable_helper")]
        # instruction/example/source -> eval against fixtures + regression (auto-promotable).
        return [
            PromotionRule("skill", kind="eval", metric="baseline_delta", threshold=0.0, comparator="gt"),
            PromotionRule("skill", kind="safety", metric="no_regression"),
        ]
