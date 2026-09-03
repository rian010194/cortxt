"""Typed next action for a Workstream (``next_action`` / ``view_capabilities``).

S7d (#488) split *preview navigation* authority from *mutation* authority: the
browser derives Work's primary affordance from a typed ``next_action`` and a
read-only ``view_capabilities`` grant, while every mutation still requires the
registered action on a live host. Only the fixture side of that split was ever
implemented, so on a live host ``next_action`` was always ``null`` and neither
the launch nor the recovery affordance could appear (#498).

This module is the single derivation. It is deliberately a pure function over
answers the server has *already* computed from its own authorities:

- launchable comes from ``dispatch.request.v1``'s fail-closed ``eligible``
  (``widget_contract.dispatch_request.build_dispatch_request_v1``) -- the exact
  same verdict ``_bind_claim_run`` re-derives before a claim, so a projection
  can never offer a launch the claim gate would refuse;
- recoverable comes from ``workflow.recover-to-ready.v1``'s own precondition
  (``adapters.github_ports.return_to_ready_transition``: exactly
  ``workflow:in-progress``) *plus* the run authority in
  ``run_authority.compute_run_freshness`` -- the label alone is not enough,
  because an Issue whose worker is still alive must not be offered a recovery
  that would re-open the dispatch gate underneath a running claim;
- decidable mirrors the projection's existing ``attention``/``decision`` rule:
  ``workflow:review`` with recorded evidence.

Nothing here re-implements a policy. If a caller cannot supply an authority
answer it passes ``None`` and the result is no next action at all -- absence of
authority is never a permission.

``view_capabilities`` is read-only by construction: every value is prefixed
``view:`` and this module can never emit an ``act:`` capability. Navigating to a
preview is all a view grant authorizes; the mutation boundary is unchanged and
still lives in the registered action ports.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .run_authority import ACTIVE_RUN_STATUSES

KIND_LAUNCH = "launch"
KIND_RECOVER = "recover"
KIND_DECISION = "decision"

VIEW_LAUNCH = "view:launch"
VIEW_RECOVERY = "view:recovery"
VIEW_DECISION = "view:decision"

_LABELS = {
    KIND_LAUNCH: "Start the approved Run",
    KIND_RECOVER: "Return this Issue to ready",
    KIND_DECISION: "Record the operator decision",
}
_VIEWS = {
    KIND_LAUNCH: VIEW_LAUNCH,
    KIND_RECOVER: VIEW_RECOVERY,
    KIND_DECISION: VIEW_DECISION,
}


def has_active_run(summaries: Sequence[Mapping[str, Any]] | None,
                   freshness_status: str | None) -> bool:
    """True when a Run still holds this Issue, so recovery must not be offered.

    A claim counts as holding the Issue only while the run authority still
    considers it alive: an ``in_progress`` claim whose newest signal is past the
    stranded bound is exactly the abandoned Run
    ``workflow.recover-to-ready.v1`` exists to rescue, and must not block its
    own remedy. ``stranded_running`` therefore does not count as active, while
    ``fresh`` and ``stale`` do.
    """
    active = [s for s in (summaries or [])
              if isinstance(s, Mapping) and str(s.get("status")) in ACTIVE_RUN_STATUSES]
    if not active:
        return False
    return str(freshness_status) in ("fresh", "stale")


def resolve_next_action(workflow: str | None, *,
                        launch_eligible: bool | None = None,
                        run_active: bool | None = None,
                        has_evidence: bool = False) -> dict[str, Any]:
    """Derive the typed next action and its read-only view grant.

    Returns ``{"next_action": <object|None>, "view_capabilities": [...]}``.

    Fail-closed in every direction: an unknown workflow state, an authority
    answer the caller could not compute (``None``), or a state with no
    sanctioned next step all yield ``next_action: None`` and no view grant. The
    result is never a mutation-oriented default.
    """
    state = (workflow or "").strip().lower()
    kind: str | None = None

    if state == "ready":
        # Exactly the dispatch gate's verdict. `None` means the caller had no
        # authority to consult, which is not permission.
        if launch_eligible is True:
            kind = KIND_LAUNCH
    elif state == "in-progress":
        # The recovery transition's own precondition is the label; the run
        # authority decides whether the Issue is actually stranded. `None`
        # (unknown run state) fails closed.
        if run_active is False:
            kind = KIND_RECOVER
    elif state == "review":
        if has_evidence:
            kind = KIND_DECISION

    if kind is None:
        return {"next_action": None, "view_capabilities": []}

    capability = _VIEWS[kind]
    assert capability.startswith("view:")  # never an act: grant
    return {
        "next_action": {"kind": kind, "label": _LABELS[kind]},
        "view_capabilities": [capability],
    }
