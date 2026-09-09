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
- recoverable requires ``workflow.recover-to-ready.v1``'s own precondition
  (``adapters.github_ports.return_to_ready_transition``: exactly
  ``workflow:in-progress``) *plus* positive evidence from the run authority
  (``run_authority.compute_run_freshness``) that a Run existed and no longer
  holds the Issue. The label alone is not enough in either direction: an Issue
  whose worker is still alive must not be offered a recovery that would
  re-open the dispatch gate underneath a running claim, and an Issue with no
  Run at all has no stranded Run to recover -- see ``run_holds_issue``;
- decidable mirrors the projection's existing ``attention``/``decision`` rule:
  ``workflow:review`` with recorded evidence;
- unblockable is ``workflow:blocked`` plus the same positive run-liveness
  evidence recovery requires (``workflow.unblock-to-ready.v1``, #519). The
  port's other two requirements -- re-reading the label at write time and a
  stated justification -- are its own and are not re-implemented here.

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

# The dispatcher owns the claim, so its record is the only authority for
# whether ownership was released (#507).
from .run_authority import STORE_DISPATCHER

KIND_LAUNCH = "launch"
KIND_RECOVER = "recover"
KIND_DECISION = "decision"
KIND_UNBLOCK = "unblock"

VIEW_LAUNCH = "view:launch"
VIEW_RECOVERY = "view:recovery"
VIEW_DECISION = "view:decision"
VIEW_UNBLOCK = "view:unblock"

_LABELS = {
    KIND_LAUNCH: "Start the approved Run",
    KIND_RECOVER: "Return this Issue to ready",
    KIND_DECISION: "Record the operator decision",
    KIND_UNBLOCK: "Lift the block and return to ready",
}
_VIEWS = {
    KIND_LAUNCH: VIEW_LAUNCH,
    KIND_RECOVER: VIEW_RECOVERY,
    KIND_DECISION: VIEW_DECISION,
    KIND_UNBLOCK: VIEW_UNBLOCK,
}


def run_holds_issue(summaries: Sequence[Mapping[str, Any]] | None,
                    freshness_status: str | None) -> bool | None:
    """Whether a Run still holds this Issue: ``True``/``False``, or ``None``.

    ``None`` means *not established*, and the caller must fail closed. That is
    the important case, and the reason this is tri-state rather than a bool:

    - **No correlated Run at all** is not evidence of a stranded Run. An
      ``workflow:in-progress`` Issue with no Run record is the normal shape of
      an epic, or of work a human is doing right now by hand -- including this
      very Issue while it is being implemented. Offering to "return it to
      ready" there would re-open the dispatch gate
      (``scripts/dispatcher.py`` claims only ``workflow:ready``) underneath
      live human work, so a worker could claim an Issue somebody is already
      working in. Absence of a Run yields ``None``, never ``False``.
    - **``unavailable`` freshness** means ``now`` could not be resolved;
      ``compute_run_freshness`` documents that its caller fails closed. So does
      this, and so does any status this function does not recognise.

    A Run holds the Issue while the run authority still considers it alive:
    ``fresh`` and ``stale`` both count.

    ``stranded_running`` no longer yields ``False`` (#507). A heartbeat that
    stopped arriving is not the dispatcher saying the claim was released --
    it is only the absence of a signal, and the dispatcher may still consider
    the claim valid for the rest of its lease. Recomputing lease expiry here
    would not help either: a locally derived expiry is this projection's
    opinion, not the write side's record. So a stranded claim is ``None`` --
    not established -- and the caller fails closed. The remedy for a genuinely
    abandoned Run is the dispatcher releasing or timing out the claim, which
    then shows up as ``terminal``.

    ``terminal`` yields ``False`` only when the **dispatcher** is among the
    sources that reported it. The dispatcher owns the claim, so only its record
    is evidence that ownership was released; a session store reporting a
    finished Run is a worker's own account of itself. Note the remaining, real
    limit: a released claim means the dispatcher no longer holds the Issue, not
    that the worker's process has ended. Recovery re-opens the dispatch gate,
    which is safe against a released claim; it is not a promise that nothing is
    still running somewhere.

    Any other status -- ``indeterminate`` provenance, ``unavailable`` clock, or
    one this function does not recognise -- is ``None``.
    """
    items = [s for s in (summaries or []) if isinstance(s, Mapping)]
    if not items:
        return None
    status = str(freshness_status)
    if status in ("fresh", "stale"):
        return True
    if status == "terminal":
        if all(STORE_DISPATCHER in (s.get("sources") or ()) for s in items):
            return False
        return None
    return None


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
        # authority must then supply positive evidence that a Run existed and
        # released the Issue. `None` -- no Run at all, an unresolvable clock,
        # or an unreadable store -- fails closed, because recovery re-opens
        # the dispatch gate and must never do so on absence of evidence.
        if run_active is False:
            kind = KIND_RECOVER
    elif state == "blocked":
        # #519 registered `workflow.unblock-to-ready.v1` but nothing ever
        # derived an affordance for it, so a blocked Issue had no way back
        # through the OS at all. The gate is the SAME run-liveness evidence
        # the recovery branch requires, and for the same reason: both end at
        # `workflow:ready`, which re-opens the dispatch gate, and doing that
        # while a claim is still held risks a second Run.
        #
        # It is deliberately not the recovery branch widened. The port keeps
        # its own capability (`act:unblock-to-ready`), re-reads the label, and
        # requires a stated justification, because lifting a block sets aside
        # a recorded refusal -- something run liveness knows nothing about.
        # Holding recovery grants nothing here, and holding this grants
        # nothing about recovery.
        #
        # The `None` case is the documented, deliberate limit: an Issue
        # blocked by triage rather than by a Run has no correlated Run, so
        # `run_holds_issue` yields `None` and this offers nothing. Widening
        # that would re-open the dispatch gate on absence of evidence.
        if run_active is False:
            kind = KIND_UNBLOCK
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
