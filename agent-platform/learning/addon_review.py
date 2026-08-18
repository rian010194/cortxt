"""Addon review gate — Fas 5, extending PromotionGate rather than building a
fourth candidate-review system (v.02 vision doc §6, operator's own framing).

Operator decision (2026-08-18): community addons go through two steps —
a mandatory Codex security review, then the operator's own final approval.
`PromotionGate` already gives "tool" candidates a structural
never-self-approve guarantee via `MANDATORY_OPERATOR_GATES`, but that
guarantee short-circuits straight to AWAIT_OPERATOR before any other rule
(including a safety rule) is evaluated — so it cannot express "must clear
Codex's security check before even reaching the operator's queue." This
module is that missing precondition, applied in front of the unmodified,
already-tested PromotionGate.
"""
from __future__ import annotations

from typing import Any, Mapping

from learning.promotion_gate import PromotionGate

ADDON_TYPE = "addon"


def _candidate_type(candidate_id: str) -> str:
    # Same normalization PromotionGate.evaluate() applies internally, so
    # this precondition can't be bypassed by a case/whitespace variant
    # that PromotionGate would still resolve to "addon" (e.g. "Addon@x",
    # " addon@x") -- the two must agree on what counts as an addon.
    return candidate_id.split("@", 1)[0].strip().lower()


class AddonReviewGate:
    """Wraps a PromotionGate with the Codex-security precondition for addon candidates."""

    def __init__(self, promotion_gate: PromotionGate) -> None:
        self._promotion_gate = promotion_gate

    def submit(self, matrix: Mapping[str, Any], candidate_id: str) -> str:
        if _candidate_type(candidate_id) == ADDON_TYPE and matrix.get("codex_security_passed") is not True:
            # Fail closed: missing, False, or any non-True value all reject.
            # The operator never sees an addon Codex hasn't cleared.
            return "REJECT"
        return self._promotion_gate.evaluate(matrix, candidate_id)
