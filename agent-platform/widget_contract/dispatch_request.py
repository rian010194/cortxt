"""Versioned dispatch-request projection (``dispatch.request.v1``) for S7b (#471).

The dispatch request is the server-side, authoritative rendering of exactly what
a confirmed ``workflow.claim-run.v1`` action will dispatch: immutable scope and
acceptance criteria, approval reference, worker role/workflow, engine and
routing reason, limits, artifact policy, and the approved engine policy. It is
derived from the approved GitHub Issue and the routing manifest only -- the
browser supplies nothing that can widen scope or limits.

``request_id`` is a server-derived digest of the immutable request snapshot
(scope, acceptance criteria, approval reference, role/workflow, engine and
routing, limits, artifact policy, engine policy). A confirmation view binds to
this id: if the Issue changes between preview and confirmation, the digest
changes and the confirmed action is rejected as stale instead of silently
launching a different mandate.

Eligibility is fail-closed: a Workstream is launchable only when it is
authoritatively ``workflow:ready``, carries a routable task-shape label, has a
complete mandate (scope, positive approval reference, worker role, versioned
workflow id, every dispatch limit, artifact policy, and an explicit Engine
policy approving the routed engine/reliability class), and its routed engine is
registered.

Issue format contract (authoritative):

- ``## Deterministic acceptance criteria`` -- ordered (``1.``) or unordered
  (``-``) Markdown list items.
- ``## Approval status`` -- the section must record *positive* operator
  approval of this exact scope/route/limits; an explicit negation
  (``... is not approved``) is treated as no approval.
- ``## Worker role and limits`` -- bulleted or plain lines declaring
  ``Workflow:``, ``Worker role:``, ``Max runtime:``, ``Max cost:``,
  ``Max parallel workers:``, and ``Delegation depth:``.
- ``## Engine policy`` (or ``## Routing policy``) -- explicit approval of the
  routed engine and/or its minimum reliability class, e.g.
  ``Reliability: verified`` and/or ``Engine: <engine-id>``.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .detail import _bullets, _section, _workflow_state, parse_dispatch_limits

# Every dispatch-contract field the request must carry and the launcher must
# enforce. `workflow` here is the versioned workflow *identifier* (e.g.
# work-launcher/v1) declared in the issue's limits, distinct from the
# `workflow_ready` *state* requirement.
MANDATORY_LIMITS = ("workflow", "worker_role", "max_runtime_seconds",
                    "max_cost_usd", "max_parallel_workers", "delegation_depth")
DEFAULT_ARTIFACT_POLICY = (
    "Commit only English project artifacts on a feature branch. Do not push, merge, "
    "close issues, expose secrets, copy full prompts, or record model reasoning."
)

ISOLATION_WORKTREE = "worktree"
ISOLATION_SHARED = "shared-checkout"

# An approved artifact policy waives the run's own isolated worktree only when
# it says so explicitly and affirmatively. Everything else -- including a policy
# that demands isolation, the default policy, and an issue with no artifact
# policy section at all -- gets an isolated worktree.
#
# S7d (#473), closing the #472 dogfood findings 6 and 8: the UI launch path
# (workflow.claim-run.v1 -> gh_claim_run_resume -> WorkLauncher.resume) created
# no worktree at all, so a mandate requiring the change to stay "inside the
# run's isolated worktree" was unenforceable rather than merely unenforced.
# Making this a field of the immutable dispatch request means the decision is
# derived on the server from the approved mandate, is covered by `request_id`
# (a browser cannot choose it -- a tampered value changes the digest and the
# confirmation is rejected as stale), and is rendered in the confirmation view
# before the operator confirms.
_ISOLATION_WAIVED = re.compile(
    r"\bshared\s+checkout\b"
    r"|\bno\s+isolated\s+worktree\b"
    r"|\bwithout\s+(?:an\s+)?isolated\s+worktree\b",
    re.I)

# Phrase presence is not permission. A *tightening* mandate contains the very
# same phrases as a waiver -- "the worker must not use a shared checkout",
# "never work without an isolated worktree" -- so matching on presence alone
# read the strictest mandates an operator can write as permission to drop
# isolation entirely, the exact inversion of the boundary this field exists to
# carry. A clause waives isolation only when nothing negates it first.
# Deliberately only unambiguous negation: a bare modal ("the run must use the
# shared checkout") is an affirmative waiver, and treating it as negation would
# override an explicit operator mandate in the other direction.
_NEGATION_BEFORE_WAIVER = re.compile(
    r"\b(?:not|never|cannot|can't|don't|doesn't|without|outside|avoid|"
    r"forbidden|prohibited|disallowed)\b",
    re.I)

# Sentence/clause boundaries. A long policy states many things; the negation
# that governs a waiver phrase is the one in its own clause, not one three
# sentences earlier.
_CLAUSE_SPLIT = re.compile(r"[.;\n]")


def isolation_for_artifact_policy(policy: str | None) -> str:
    """The isolation the approved artifact policy requires (fails closed).

    Returns ``shared-checkout`` only for a clause that affirmatively waives the
    run's own worktree. A negated clause -- a mandate *requiring* isolation --
    is not a waiver, and neither is a policy that never mentions the subject.
    """
    if not isinstance(policy, str):
        return ISOLATION_WORKTREE
    for clause in _CLAUSE_SPLIT.split(policy):
        match = _ISOLATION_WAIVED.search(clause)
        if match is None:
            continue
        if _NEGATION_BEFORE_WAIVER.search(clause[:match.start()]):
            continue
        return ISOLATION_SHARED
    return ISOLATION_WORKTREE


# Approval resolution lives in `widget_contract.approval`, the single durable
# home every reader shares (S7d #473, from the #472 dogfood finding 3 -- the
# dispatch request and the Workstream projection used to disagree about the
# same issue's approval).
from .approval import resolve_approval

ENGINE_POLICY_SECTIONS = ("Engine policy", "Routing policy")

# Fields that constitute the immutable dispatch-request snapshot. Anything
# environment-derived (eligibility, missing, engine registration availability)
# is deliberately excluded so a runtime change does not invalidate an approved
# mandate -- but a changed Issue always does.
REQUEST_DIGEST_FIELDS = (
    "issue_id", "workflow", "scope", "acceptance_criteria", "approval_reference",
    "isolation",
    "worker_role", "workflow_id", "engine", "routing_reason", "routable_task_tags",
    "engine_policy", "max_runtime_seconds", "max_cost_usd", "max_parallel_workers",
    "delegation_depth", "artifact_policy",
)

# Stable failure taxonomy: missing-code -> (category, recovery guidance) per
# AC5 (missing limits, unavailable engine, routing, mandate policy).
FAILURE_RECOVERY: dict[str, tuple[str, str]] = {
    "workflow_ready": ("eligibility",
                       "Move the issue to workflow:ready after operator approval before launching."),
    "scope": ("eligibility",
              "Add an explicit ## Scope section to the approved issue."),
    "acceptance_criteria": ("eligibility",
                            "Add explicit deterministic acceptance criteria (ordered or bulleted list) to the issue."),
    "approval_reference": ("eligibility",
                           "Record positive operator approval of this exact scope, route, and limits in the issue "
                           "Approval status section (negated approval is not approval)."),
    "workflow": ("eligibility",
                 "Declare the versioned workflow id (e.g. Workflow: work-launcher/v1) in the issue "
                 "Worker role and limits section."),
    "worker_role": ("eligibility",
                    "Declare the worker role in the issue Worker role and limits section."),
    "max_runtime_seconds": ("eligibility",
                            "Declare the max runtime in the issue Worker role and limits section."),
    "max_cost_usd": ("eligibility",
                     "Declare the max cost ceiling in the issue Worker role and limits section."),
    "max_parallel_workers": ("eligibility",
                             "Declare max parallel workers in the issue Worker role and limits section."),
    "delegation_depth": ("eligibility",
                         "Declare delegation depth in the issue Worker role and limits section."),
    "routable_task_tag": ("routing",
                          "Add a routable task-shape label (e.g. background-task) matching a registered engine manifest."),
    "engine_routed": ("routing",
                      "Add a routable task-shape label so routing can select an engine."),
    "engine_registered": ("engine",
                          "Register the routed engine's provider, or approve an issue Engine policy that routes to "
                          "a registered engine."),
    # #500: distinct from `engine_registered`, which means "nothing here can
    # run this engine". This one means the engine IS registered and would have
    # been dispatched, but its executable or carrier is absent on this host --
    # the failure that burned two approved dispatches at the adapter boundary
    # before any provider was reached. The reason names what is missing; see
    # `runtime_launch_preflight`.
    "engine_carrier_unavailable": ("engine",
                                   "The routed engine has no runnable carrier on this host. Install or select one, "
                                   "or approve an Engine policy routing to an engine this host can launch."),
    "engine_policy": ("routing",
                      "Add an explicit ## Engine policy section approving the engine and/or its reliability class."),
    "engine_policy_unapproved": ("routing",
                                 "Amend the issue Engine policy to approve the routed engine and its reliability "
                                 "class, or add a routable task-shape label matching the approved engine."),
}


def task_tags_for_issue(issue: Mapping[str, Any], manifests: Sequence[Any]) -> list[str]:
    """The issue's labels intersected with the routing manifest's task shapes."""
    labels = {str(item.get("name", "") if isinstance(item, Mapping) else item)
              for item in issue.get("labels") or []}
    shapes: set[str] = set()
    for manifest in manifests:
        shapes.update(getattr(manifest, "task_shapes", ()))
    return sorted(labels & shapes)


def parse_engine_policy(body: str) -> dict[str, str | None] | None:
    """Parse the explicit approved engine/policy constraint, or None.

    The section declares the minimum approved reliability class and/or the
    exact approved engine id, e.g.::

        ## Engine policy

        Reliability: verified
        Engine: dsh

    A missing section means the mandate does not authorize any engine routing,
    so the request is not eligible (fail closed).
    """
    value = _section(body, ENGINE_POLICY_SECTIONS)
    if value is None:
        return None
    approved_reliability: str | None = None
    approved_engine: str | None = None
    for line in value.splitlines():
        stripped = line.strip().rstrip(".")
        lowered = stripped.casefold()
        if lowered.startswith("reliability:"):
            candidate = stripped.split(":", 1)[1].strip().casefold()
            if candidate in ("verified", "unverified"):
                approved_reliability = candidate
        elif lowered.startswith("engine:"):
            candidate = stripped.split(":", 1)[1].strip()
            if candidate:
                approved_engine = candidate
    return {"approved_reliability": approved_reliability, "approved_engine": approved_engine}


def _approval_reference(body: str, comments: Sequence[Any] | None = None) -> str | None:
    """The issue's current approval reference, only when it is positively approved.

    Delegates to `widget_contract.approval.resolve_approval` so this reader and
    the Workstream projections cannot drift apart again.
    """
    return resolve_approval(body, comments)["reference"]


def route_for_issue(issue: Mapping[str, Any], manifests: Sequence[Any],
                    fallback: str) -> tuple[Any | None, list[str]]:
    """Route the issue by its task-shape labels, or (None, []) when not routable.

    The mandate's approved Engine policy constrains routing: an exact approved
    engine is selected when declared, and a declared minimum reliability class
    filters candidates before the cost sort -- a cheap engine is never selected
    unless the approved request permits its reliability class.
    """
    tags = task_tags_for_issue(issue, manifests)
    if not tags:
        return None, tags
    from routing.engine_manifest import EngineChoice, route

    policy = parse_engine_policy(str(issue.get("body") or ""))
    if policy and policy.get("approved_engine"):
        approved = policy["approved_engine"]
        matched = None
        for manifest in manifests:
            if manifest.engine_id == approved:
                intersection = set(tags) & set(getattr(manifest, "task_shapes", ()))
                if intersection:
                    matched = sorted(intersection)[0]
                    break
        reason = ("mandate-approved engine" if matched
                  else "mandate-approved engine (no manifest match)")
        return EngineChoice(engine_id=approved, reason=reason, matched_tag=matched,
                            checkpoint_required=True), tags

    return route(tags, list(manifests), fallback=fallback,
                 min_reliability=policy["approved_reliability"] if policy else None), tags


def _request_id(payload: Mapping[str, Any]) -> str:
    """Server-derived digest of the immutable request snapshot.

    Deterministic across identical Issue reads; any change to the mandate,
    routing, or limits changes the digest, so a confirmation bound to a stale
    snapshot is rejected rather than silently launching a different mandate.
    """
    canonical = json.dumps({key: payload.get(key) for key in REQUEST_DIGEST_FIELDS},
                           sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _failures(missing: Sequence[str],
              detail: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    """Stable, recoverable failure entries for every missing-code (AC5).

    `detail` carries a host-specific reason for codes that have one (#500:
    which carrier is missing), appended to the stable recovery text rather
    than replacing it -- the taxonomy stays fixed while the message can say
    what actually went wrong here.
    """
    errors = []
    for code in missing:
        category, recovery = FAILURE_RECOVERY.get(code, ("eligibility", "Complete the approved issue mandate."))
        reason = (detail or {}).get(code)
        if reason:
            recovery = f"{recovery} On this host: {reason}."
        errors.append({"code": code, "category": category, "recovery": recovery})
    return errors


def build_dispatch_request_v1(
    issue: Mapping[str, Any],
    choice: Any | None,
    *,
    repo: str,
    engine_registered: bool = True,
    engine_unavailable_reason: str | None = None,
    routable_tags: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Render the authoritative dispatch request and its fail-closed eligibility."""
    number = issue["number"]
    body = str(issue.get("body") or "")
    workflow, workflow_labels = _workflow_state(issue)
    limits = parse_dispatch_limits(body)
    tags = list(routable_tags) if routable_tags is not None else []

    scope = _section(body, ("Scope",))
    acceptance = _bullets(body, ("Acceptance criteria", "Acceptance Criteria",
                                 "Deterministic acceptance criteria"))
    approval = _approval_reference(body, issue.get("comments"))
    artifact_policy = _section(body, ("Artifact policy",)) or DEFAULT_ARTIFACT_POLICY
    engine_policy = parse_engine_policy(body)

    missing: list[str] = []
    if workflow != "ready":
        missing.append("workflow_ready")
    if not scope:
        missing.append("scope")
    if not acceptance:
        missing.append("acceptance_criteria")
    if not approval:
        missing.append("approval_reference")
    for key in MANDATORY_LIMITS:
        if key not in limits:
            missing.append(key)
    if not tags:
        missing.append("routable_task_tag")
    if choice is None:
        missing.append("engine_routed")
    elif not engine_registered:
        # #500: distinguish "no host can run this" from "this host cannot".
        # A reason means the engine is registered and would have dispatched,
        # but its carrier is absent here -- refused now, before a claim, with
        # the cause named, instead of dying at the adapter boundary after an
        # approved dispatch was already spent.
        missing.append("engine_carrier_unavailable" if engine_unavailable_reason
                       else "engine_registered")
    if engine_policy is None:
        missing.append("engine_policy")
    elif engine_policy.get("approved_engine") and getattr(choice, "engine_id", None) != engine_policy["approved_engine"]:
        missing.append("engine_policy_unapproved")

    payload = {
        "schema_version": 1,
        "issue_id": f"{repo}#{number}",
        "eligible": not missing,
        "workflow": workflow,
        "workflow_labels": workflow_labels,
        "scope": scope,
        "acceptance_criteria": acceptance,
        "approval_reference": approval,
        "worker_role": limits.get("worker_role"),
        "workflow_id": limits.get("workflow"),
        "engine": getattr(choice, "engine_id", None) if choice is not None else None,
        "routing_reason": getattr(choice, "reason", None) if choice is not None else None,
        "routable_task_tags": tags,
        "engine_policy": engine_policy,
        "max_runtime_seconds": limits.get("max_runtime_seconds"),
        "max_cost_usd": limits.get("max_cost_usd"),
        "max_parallel_workers": limits.get("max_parallel_workers"),
        "delegation_depth": limits.get("delegation_depth"),
        "artifact_policy": artifact_policy,
        "isolation": isolation_for_artifact_policy(artifact_policy),
        "missing": missing,
        "errors": _failures(missing, {"engine_carrier_unavailable": engine_unavailable_reason}
                            if engine_unavailable_reason else None),
    }
    payload["request_id"] = _request_id(payload)
    return payload


# ---------------------------------------------------------------------------
# dispatch.request.v2 (S#520, design §2): approval bound to the execution
# configuration, not identifiers alone.
# ---------------------------------------------------------------------------

# Canonical bound field set for the v2 request digest, grouped by the six
# dimensions design §2 names. Field ORDER here is the fixed canonical order the
# digest serialises in (see `canonicalisation rule` below); do not reorder.
#
#   semantic content -> scope, acceptance_criteria
#   route            -> engine, routing_reason, routable_task_tags, engine_policy
#   model            -> execution_profile_revision  (binds provider + model)
#   profile          -> worker_role, workflow_id
#   limits           -> max_runtime_seconds, max_cost_usd, max_parallel_workers,
#                       delegation_depth, artifact_policy
#   report channel   -> report_channel
#   charging         -> charge_policy_revision, charge_policy_route  (W11 / #542)
#
# `isolation` is bound through `execution_profile_revision` (it is a field of
# the execution profile) rather than separately; `issue_id` and
# `approval_reference` stay in the digest so the approval cannot be replayed
# against a different issue or a changed mandate.
#
# W11 (design §2, §3.4): `charge_policy_revision` is an immutable digest over
# the declared charging record's semantic content (verdict, source, dates, and
# the route it binds); `charge_policy_route` is the confirmed regime
# (`zero_charge` | `metered`). Binding both means an approval recorded under
# `zero_charge` cannot silently ride a re-bound or revised charge policy -- the
# request digest changes and the confirmation is stale. Both are `None` when no
# charge policy was resolved at projection time, and `None` is bound distinctly
# from an absent field.
REQUEST_V2_BOUND_FIELDS = (
    "issue_id",
    "approval_reference",
    "scope",
    "acceptance_criteria",
    "engine",
    "routing_reason",
    "routable_task_tags",
    "engine_policy",
    "execution_profile_revision",
    "worker_role",
    "workflow_id",
    "max_runtime_seconds",
    "max_cost_usd",
    "max_parallel_workers",
    "delegation_depth",
    "artifact_policy",
    "report_channel",
    "charge_policy_revision",
    "charge_policy_route",
)

# Canonicalisation rule (documented, shared with the execution-profile revision
# in `routing/execution_profile`): select exactly `REQUEST_V2_BOUND_FIELDS`,
# serialise with `json.dumps(sort_keys=True, separators=(",", ":"), default=str)`
# so nested maps sort deterministically, `None` stays distinct from an absent
# value, and non-JSON values fall back to `str`; digest =
# "sha256:" + sha256(utf8(canonical)).hexdigest(). Two requests with the same
# meaning over every bound field produce the same digest; any change to a bound
# field produces a different one.
DEFAULT_REPORT_CHANNEL = "issue-comment"


def report_channel(body: str) -> str:
    """The channel the worker's result is reported on (bound field).

    Defaults to ``issue-comment`` (the dispatch contract's result channel: a
    result envelope is posted to the issue). An explicit ``## Report channel``
    section may override it deterministically; a missing section keeps the
    default so an unstated channel cannot silently widen the approved report.
    """
    section = _section(body, ("Report channel", "Report Channel", "Result channel"))
    if section:
        value = section.splitlines()[0].strip().rstrip(".")
        if value:
            return value
    return DEFAULT_REPORT_CHANNEL


def build_dispatch_request_v2(
    issue: Mapping[str, Any],
    choice: Any | None,
    *,
    repo: str,
    engine_registered: bool = True,
    engine_unavailable_reason: str | None = None,
    routable_tags: Sequence[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    charge_policy: Any | None = None,
) -> dict[str, Any]:
    """Render the v2 dispatch request: approval bound to the execution profile.

    ``dispatch.request.v2`` (design §2) extends v1 by binding an immutable
    ``execution_profile_revision`` -- a digest of the resolved execution
    configuration (route engine, worker profile, provider, model, isolation) --
    and a ``report_channel`` into the request digest. The digest therefore
    covers the semantic content plus the actual execution configuration, not
    identifiers alone: an approved request cannot be re-launched against a
    different model, provider, or profile without invalidating the approval.

    ``provider`` and ``model`` are the resolved, non-secret execution
    identifiers (the same class the routing manifest and launcher preflight
    treat as routing configuration). ``None`` means "not resolved at projection
    time" and is itself bound.
    """
    from routing.execution_profile import (
        execution_profile,
        execution_profile_revision,
    )

    base = build_dispatch_request_v1(
        issue, choice, repo=repo,
        engine_registered=engine_registered,
        engine_unavailable_reason=engine_unavailable_reason,
        routable_tags=routable_tags,
    )
    body = str(issue.get("body") or "")

    isolation = base["isolation"]
    profile = execution_profile(
        engine_id=base["engine"] or "",
        worker_role=base["worker_role"],
        provider=provider,
        model=model,
        isolation=isolation,
    )
    revision = execution_profile_revision(profile)

    payload = dict(base)
    payload["schema_version"] = 2
    payload["execution_profile_revision"] = revision
    payload["report_channel"] = report_channel(body)

    # W11 (#542): the charging regime and the versioned policy it rests on.
    # `None` when no charge policy was resolved -- bound distinctly from absent.
    if charge_policy is not None:
        from routing.charge_policy import charge_policy_revision
        payload["charge_policy_id"] = charge_policy.charge_policy_id
        payload["charge_policy_revision"] = charge_policy_revision(charge_policy)
        payload["charge_policy_route"] = charge_policy.route
    else:
        payload["charge_policy_id"] = None
        payload["charge_policy_revision"] = None
        payload["charge_policy_route"] = None

    # The request digest now covers the bound field set (semantic content,
    # route, model/profile via the revision, limits, report channel, and the
    # charge-policy revision + route).
    payload["request_id"] = request_digest_v2(payload)
    return payload


def request_digest_v2(payload: Mapping[str, Any]) -> str:
    """The v2 request digest over the canonical bound field set.

    Deterministic across semantically identical requests; any change to a bound
    field -- including a change to the resolved execution profile (model,
    provider, profile, isolation) or the report channel -- changes the digest.
    """
    from routing.execution_profile import canonical_json, sha256_digest

    return sha256_digest(canonical_json(payload, REQUEST_V2_BOUND_FIELDS))


def approval_binds_digest(approved_request_id: str | None, payload: Mapping[str, Any]) -> bool:
    """True only when ``approved_request_id`` equals the request's own digest.

    Design §2: the operator's approval is *recorded against the digest*. A
    request whose digest differs from the approved digest is not treated as
    approved -- regardless of whether its approval_reference text still reads
    as positive. This is the fail-closed test the confirmation and launch paths
    use: an approved id that does not match the current digest is stale.
    """
    if not approved_request_id:
        return False
    return approved_request_id == request_digest_v2(payload)
