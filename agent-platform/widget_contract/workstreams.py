"""Shared Work Console projection over GitHub Issue authority.

The browser consumes this deliberately small model in both local and public
mode.  Local values are derived from GitHub Issues; synthetic values live in
the static fixture and use the same schema.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .approval import resolve_approval
from .next_action import resolve_next_action

WORKFLOW = re.compile(r"^workflow:(inbox|ready|in-progress|review|blocked|done)$", re.I)
SECTION = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.M)


def _labels(issue: Mapping[str, Any]) -> list[str]:
    return [str(item.get("name", "") if isinstance(item, Mapping) else item)
            for item in issue.get("labels") or []]


def _section(body: str, names: Sequence[str]) -> str | None:
    matches = list(SECTION.finditer(body))
    wanted = {name.casefold() for name in names}
    for index, match in enumerate(matches):
        if match.group(1).strip().casefold() not in wanted:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = body[match.end():end].strip()
        value = re.sub(r"^[-*]\s+", "", value, flags=re.M).strip()
        return value or None
    return None


def build_workstream_projection(repo: str, issues: Sequence[Mapping[str, Any]], *,
                                status: str = "fresh", error: Mapping[str, Any] | None = None,
                                authority: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Map complete issue records to durable, non-invented Workstream views.

    ``authority`` carries the server-computed answers the typed ``next_action``
    is derived from, keyed by ``issue_id``: ``launch_eligible`` (the
    ``dispatch.request.v1`` verdict) and ``run_active`` (the run authority's
    view of whether a claim still holds the Issue). This projection is built
    from ``gh issue list`` records and cannot compute either itself, so a
    caller that omits them gets no next action at all rather than a guess
    (#498). Work reads its primary affordance from *this* projection, so it is
    the projection that must carry the field.
    """
    workstreams = []
    for issue in issues:
        labels = _labels(issue)
        workflow_labels = [label.lower() for label in labels if WORKFLOW.fullmatch(label)]
        workflow = workflow_labels[0].split(":", 1)[1] if len(workflow_labels) == 1 else "unknown"
        body = str(issue.get("body") or "")
        evidence = _section(body, ("Evidence", "Verification", "Validation"))
        acceptance = _section(body, ("Acceptance criteria", "Acceptance Criteria"))
        # The same approval authority the dispatch gate consults (S7d #473 /
        # #472 finding 3): this used to miss the `## Approval status` section
        # entirely and ignore explicit negations, so the gate reported an issue
        # eligible while this projection reported approval_recorded: false for
        # the very same issue. `gh issue list` carries no comments, so the
        # source label says this is the body-derived answer -- a later operator
        # retry authorization comment is only visible to the detail projection.
        approval = resolve_approval(body)
        outcome = _section(body, ("Outcome", "Objective", "Goal")) or str(issue.get("title") or "Untitled work")
        actionable = workflow == "review" and bool(evidence)
        issue_id = f"{repo}#{issue['number']}"
        grant = (authority or {}).get(issue_id) or {}
        derived = resolve_next_action(
            workflow,
            launch_eligible=grant.get("launch_eligible"),
            run_active=grant.get("run_active"),
            has_evidence=bool(evidence),
        )
        workstreams.append({
            "id": f"WS-{issue['number']}",
            "issue_id": issue_id,
            "number": issue["number"],
            "title": str(issue.get("title") or "Untitled work"),
            "outcome": outcome.splitlines()[0][:240],
            "workflow": workflow,
            "url": issue.get("url"),
            "attention": "decision" if actionable else ("blocked" if workflow == "blocked" else None),
            "decision": ({"summary": "Accept this reviewed evidence as the durable record?",
                          "actionable": True, "action_id": "record-decision"} if actionable else None),
            "authority": {"source": "GitHub Issue", "workflow_label": workflow_labels[0] if len(workflow_labels) == 1 else None,
                          "approval_recorded": approval["recorded"],
                          "approval_source": approval["source"]},
            "evidence": ([{"title": "Issue evidence", "detail": evidence[:1200], "status": "recorded"}]
                         if evidence else []),
            "acceptance_criteria": acceptance,
            # Typed navigation authority (#498). Read-only by construction:
            # `view_capabilities` can only ever carry `view:` grants, and the
            # mutation boundary remains the registered action ports.
            "next_action": derived["next_action"],
            "view_capabilities": derived["view_capabilities"],
        })
    order = {"review": 0, "blocked": 1, "in-progress": 2, "ready": 3, "inbox": 4, "done": 5, "unknown": 6}
    workstreams.sort(key=lambda item: (order.get(item["workflow"], 6), -item["number"]))
    return {"schema_version": 1, "mode": "local", "synthetic": False, "repo": repo,
            "status": status, "error": dict(error) if error else None, "workstreams": workstreams}
