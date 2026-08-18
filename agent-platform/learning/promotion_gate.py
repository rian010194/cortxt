"""PromotionGate — rule-driven executor (Fas 8, Beslut 3 / 9.3; P0.2, P0.3, P1.7).

Design (from the approved spec, refined by Kimi re-review):
- ``PromotionRule`` is frozen data carrying enough semantics (candidate_type/kind/metric/threshold/comparator)
  to be evaluated WITHOUT hardcoded per-type if-statements (P0.3).
- ``PromotionGate.evaluate(matrix, candidate_id)`` takes NO ``rules`` argument from the caller (P0.2):
  rules are resolved internally from the gate's own ``rules_registry`` (type -> rules) and ALWAYS unioned
  with the unbreakable ``MANDATORY_OPERATOR_GATES`` (= {"tool"}, external-effect class per §32.2/§31). So a
  tool candidate is ALWAYS ``AWAIT_OPERATOR`` regardless of its eval result — self-approval is structurally
  impossible.
- Promotion is conservatively strict (P1.7): PROMOTE only when the candidate is STRICTLY better than baseline
  (metric passes threshold with the given comparator) AND no regression AND the matrix is complete. A tie is
  NOT promoted (AWAIT_OPERATOR). An incomplete matrix never promotes (fail-closed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# candidate types whose effect class mandates a human gate (§31/§32.2) — never bypassable.
# "addon" added for Fas 5 (v.02 wayfinder): a community addon can install
# executable logic (vision doc §6), same self-approval-impossible guarantee
# as "tool". See learning/addon_review.py for the Codex-security precondition
# gate this alone does not express (MANDATORY_OPERATOR_GATES short-circuits
# to AWAIT_OPERATOR before any other rule is evaluated, by design).
MANDATORY_OPERATOR_GATES = {"tool", "addon"}

VERDICTS = ("PROMOTE", "AWAIT_OPERATOR", "REJECT")


@dataclass(frozen=True)
class PromotionRule:
    candidate_type: str
    kind: str  # "eval" | "safety" | "operator_gate"
    metric: str | None = None
    threshold: float | None = None
    comparator: str = "gt"  # default "gt" = strictly-better required (Kimi Task4 P1: "gte" auto-promoted ties)
    operator_scope: str | None = None


def _compare(value: Any, threshold: float, op: str) -> bool:
    if op == "gte":
        return value >= threshold
    if op == "gt":
        return value > threshold
    if op == "lte":
        return value <= threshold
    if op == "eq":
        return value == threshold
    raise ValueError(f"unknown comparator: {op}")


class PromotionGate:
    """Pure, deterministic rule executor. Rules come from the registry, never from the caller."""

    def __init__(self, rules_registry: Mapping[str, list[PromotionRule]] | None = None) -> None:
        self._rules = dict(rules_registry or {})

    def evaluate(self, matrix: Mapping[str, Any], candidate_id: str) -> str:
        """Return PROMOTE | AWAIT_OPERATOR | REJECT. Fail-closed on any doubt (P0.2/P0.3/P1.7)."""
        # Kimi Task4 P2.1: normalize type prefix (strip/lower) so "Tool@..." can't bypass the gate.
        candidate_type = candidate_id.split("@", 1)[0].strip().lower()
        rules = list(self._rules.get(candidate_type, []))
        # union the unbreakable operator gates for this type (P0.2) — cannot be removed.
        if candidate_type in MANDATORY_OPERATOR_GATES:
            rules.append(PromotionRule(candidate_type, kind="operator_gate",
                                       operator_scope=candidate_type))

        if not matrix.get("complete", True):
            # incomplete evidence must never promote (plan-review P1.2 / spec Error handling: CannotDecide)
            return "REJECT"

        if not rules:
            return "AWAIT_OPERATOR"  # no rules registered -> no verified basis to auto-promote
        if any(r.kind == "operator_gate" for r in rules):
            return "AWAIT_OPERATOR"  # human gate required, regardless of eval (P0.2)

        for rule in rules:
            if rule.kind == "eval":
                v = matrix.get(rule.metric)
                if v is None:
                    return "REJECT"  # missing metric -> cannot decide -> fail-closed
                try:
                    passes = _compare(v, rule.threshold or 0.0, rule.comparator)
                except ValueError:
                    return "REJECT"  # Kimi Task4 P2.3: unknown comparator -> fail-closed, not an exception
                if passes:
                    continue  # this rule passes (strictly better / threshold met)
                if v == (rule.threshold or 0.0):
                    return "AWAIT_OPERATOR"  # tie: not worse, not strictly better (P1.7)
                return "REJECT"  # worse on this metric
            elif rule.kind == "safety":
                if rule.metric:
                    if matrix.get(rule.metric) is False:
                        return "REJECT"  # safety constraint violated
                elif matrix.get("no_regression") is not True:
                    return "REJECT"
            else:
                # Kimi Task4 P3: unknown rule kind is fail-OPEN-prone — treat as fail-closed (REJECT).
                return "REJECT"
        # All configured rules passed for a registered type with an auto-promotable rule.
        return "PROMOTE"
