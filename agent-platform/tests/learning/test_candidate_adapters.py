"""Phase 8 Task 11 — skill/tool candidate adapters (mechanism-hooked, honest v1.x scope, P1.6)."""
from __future__ import annotations

from learning.candidate import Candidate
from learning.promotion_gate import PromotionGate, PromotionRule
from learning.skill_candidate import SkillCandidateAdapter
from learning.tool_candidate import ToolCandidateAdapter


# --- skill adapter: register + §31 rule gate ------------------------------------
def test_skill_instruction_candidate_builds_and_rule_allows_auto():
    """A skill 'instruction/example/source' change maps to [eval, safety] (auto-promotable rule per §31)."""
    adapter = SkillCandidateAdapter()
    cand = adapter.to_candidate(name="verify-fix", version="v2",
                                change_type="instruction", content_md="new guidance")
    assert isinstance(cand, Candidate)
    assert cand.type == "skill"
    assert cand.id == "skill@verify-fix@v2"
    # instruction-class change -> [eval, safety] rules (no operator_gate)
    rules = adapter.rules(cand)
    assert all(r.kind in ("eval", "safety") for r in rules)
    assert not any(r.kind == "operator_gate" for r in rules)


def test_skill_executable_helper_requires_operator():
    """§31: an executable-helper change requires a named human operator gate."""
    adapter = SkillCandidateAdapter()
    cand = adapter.to_candidate(name="verify-fix", version="v2",
                                change_type="executable_helper", content_md="script")
    rules = adapter.rules(cand)
    assert any(r.kind == "operator_gate" for r in rules)


# --- tool adapter: external-mutation always AWAIT_OPERATOR ---------------------
def test_tool_external_mutation_always_await_operator():
    """P0.2/Decision 5: a tool with external-mutation effect is ALWAYS AWAIT_OPERATOR regardless of eval."""
    adapter = ToolCandidateAdapter()
    cand = adapter.to_candidate(name="send-notice", version="v1",
                                effect_class="external_mutation")
    assert cand.type == "tool"
    gate = PromotionGate({"tool": []})  # no rules registered; MANDATORY_OPERATOR_GATES still applies
    assert gate.evaluate({"baseline_delta": 0.9, "no_regression": True, "complete": True},
                         cand.id) == "AWAIT_OPERATOR"


def test_tool_credential_always_await_operator():
    adapter = ToolCandidateAdapter()
    cand = adapter.to_candidate(name="rotate-secret", version="v1", effect_class="credential")
    assert cand.id == "tool@rotate-secret@v1"
    gate = PromotionGate({"tool": []})
    assert gate.evaluate({"baseline_delta": 0.9, "no_regression": True, "complete": True},
                         cand.id) == "AWAIT_OPERATOR"
