"""Versioned dispatch-request projection (``dispatch.request.v1``) for S7b (#471).

The dispatch request is the server-side, authoritative rendering of exactly what
a confirmed ``workflow.claim-run.v1`` action will dispatch: immutable scope and
acceptance criteria, approval reference, worker role/workflow, engine and
routing reason, limits, and artifact policy. It is derived from the approved
GitHub Issue and the routing manifest only -- the browser supplies nothing that
can widen scope or limits.

Eligibility is fail-closed: a Workstream is launchable only when it is
authoritatively ``workflow:ready``, carries a routable task-shape label, has a
complete mandate (scope, acceptance criteria, approval reference, worker role,
runtime and cost limits), and its routed engine is registered.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .detail import _bullets, _section, _workflow_state, parse_dispatch_limits

MANDATORY_LIMITS = ("worker_role", "max_runtime_seconds", "max_cost_usd")
DEFAULT_ARTIFACT_POLICY = (
    "Commit only English project artifacts on a feature branch. Do not push, merge, "
    "close issues, expose secrets, copy full prompts, or record model reasoning."
)


def task_tags_for_issue(issue: Mapping[str, Any], manifests: Sequence[Any]) -> list[str]:
    """The issue's labels intersected with the routing manifest's task shapes."""
    labels = {str(item.get("name", "") if isinstance(item, Mapping) else item)
              for item in issue.get("labels") or []}
    shapes: set[str] = set()
    for manifest in manifests:
        shapes.update(getattr(manifest, "task_shapes", ()))
    return sorted(labels & shapes)


def route_for_issue(issue: Mapping[str, Any], manifests: Sequence[Any],
                    fallback: str) -> tuple[Any | None, list[str]]:
    """Route the issue by its task-shape labels, or (None, []) when not routable."""
    tags = task_tags_for_issue(issue, manifests)
    if not tags:
        return None, tags
    from routing.engine_manifest import route

    return route(tags, list(manifests), fallback=fallback), tags


def build_dispatch_request_v1(
    issue: Mapping[str, Any],
    choice: Any | None,
    *,
    repo: str,
    engine_registered: bool = True,
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
    approval = _section(body, ("Approval status", "Approval", "Human approval", "Operator approval"))
    artifact_policy = _section(body, ("Artifact policy",)) or DEFAULT_ARTIFACT_POLICY

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
        missing.append("engine_registered")

    return {
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
        "max_runtime_seconds": limits.get("max_runtime_seconds"),
        "max_cost_usd": limits.get("max_cost_usd"),
        "max_parallel_workers": limits.get("max_parallel_workers"),
        "delegation_depth": limits.get("delegation_depth"),
        "artifact_policy": artifact_policy,
        "missing": missing,
    }