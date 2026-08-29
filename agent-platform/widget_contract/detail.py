"""Versioned Workstream detail projection (``workstream.detail.v1``) for S7a (#470).

The detail is the authoritative read model one Workstream's full mandate and
Run history is rendered from. Every field is derived from an explicit source:

- issue identity/state/labels/milestone from the GitHub Issue record,
- scope, outcome, acceptance criteria, approval reference, and dispatch limits
  from explicit body sections/fields (a missing value stays missing),
- relations from explicit ``Part of:`` / ``Blocked by:`` / ``Depends on:`` lines,
- Run summaries from the provenance-preserving adapter in ``run_authority``.

Nothing is inferred from title, branch name, browser state, or free text.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

WORKFLOW = re.compile(r"^workflow:(inbox|ready|in-progress|review|blocked|done)$", re.I)
SECTION = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.M)
BULLET = re.compile(r"^[-*]\s+(.+?)\s*$", re.M)

RELATION_PART_OF = "part-of"
RELATION_BLOCKED_BY = "blocked-by"


def _labels(issue: Mapping[str, Any]) -> list[str]:
    return [str(item.get("name", "") if isinstance(item, Mapping) else item)
            for item in issue.get("labels") or []]


def _workflow_state(issue: Mapping[str, Any]) -> tuple[str, list[str]]:
    labels = _labels(issue)
    workflow_labels = [label.lower() for label in labels if WORKFLOW.fullmatch(label)]
    workflow = workflow_labels[0].split(":", 1)[1] if len(workflow_labels) == 1 else "unknown"
    return workflow, workflow_labels


def _section(body: str, names: Sequence[str]) -> str | None:
    """Return the text of the first matching explicit section, or None."""
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


def _bullets(body: str, names: Sequence[str]) -> list[str]:
    section = _section(body, names)
    if not section:
        return []
    return [match.group(1).strip() for match in BULLET.finditer(section) if match.group(1).strip()]


def parse_relations(body: str) -> list[dict[str, Any]]:
    """Parse explicit ``Part of: #N`` / ``Blocked by: #N`` / ``Depends on: #N`` lines."""
    relations: list[dict[str, Any]] = []
    for line in (body or "").splitlines():
        stripped = line.strip()
        match = re.match(r"^(?:Part of|Blocked by|Depends on):\s*#(\d+)", stripped, re.I)
        if not match:
            continue
        lowered = stripped.casefold()
        if lowered.startswith("part of"):
            relation = RELATION_PART_OF
        else:
            relation = RELATION_BLOCKED_BY
        relations.append({"relation": relation, "target": int(match.group(1))})
    return relations


_INT = re.compile(r"\d+")


def _first_int(value: str) -> int | None:
    match = _INT.search(value)
    return int(match.group(0)) if match else None


def _first_usd(value: str) -> float | None:
    match = re.search(r"USD\s*(\d+(?:\.\d+)?)", value, re.I)
    if not match:
        return None
    return float(match.group(1))


def parse_dispatch_limits(body: str) -> dict[str, Any]:
    """Parse explicit dispatch-limit fields; a missing field is simply absent."""
    limits: dict[str, Any] = {}
    worker_role = None
    workflow = None
    for line in (body or "").splitlines():
        stripped = line.strip()
        lowered = stripped.casefold()
        if lowered.startswith("worker role:"):
            worker_role = stripped.split(":", 1)[1].strip().rstrip(".")
            worker_role = re.split(r"[,;]", worker_role)[0].strip() or None
        elif lowered.startswith("workflow:"):
            workflow = stripped.split(":", 1)[1].strip().rstrip(".")
        elif lowered.startswith("max runtime:"):
            value = _first_int(stripped)
            if value is not None:
                limits["max_runtime_seconds"] = value
        elif lowered.startswith("max cost:"):
            value = _first_usd(stripped)
            if value is not None:
                limits["max_cost_usd"] = value
        elif lowered.startswith("max parallel workers:"):
            value = _first_int(stripped)
            if value is not None:
                limits["max_parallel_workers"] = value
        elif lowered.startswith("delegation depth:"):
            value = _first_int(stripped)
            if value is not None:
                limits["delegation_depth"] = value
    if worker_role:
        limits["worker_role"] = worker_role
    if workflow:
        limits["workflow"] = workflow
    return limits


def _milestone(issue: Mapping[str, Any]) -> str | None:
    value = issue.get("milestone")
    if isinstance(value, Mapping):
        title = value.get("title")
        return title if isinstance(title, str) and title else None
    return value if isinstance(value, str) and value else None


def build_workstream_detail_v1(
    issue: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    *,
    repo: str,
    status: str = "fresh",
    error: Mapping[str, Any] | None = None,
    age_seconds: int = 0,
    synthetic: bool = False,
) -> dict[str, Any]:
    """Map one GitHub Issue plus correlated Run summaries onto ``workstream.detail.v1``."""
    number = issue["number"]
    body = str(issue.get("body") or "")
    workflow, workflow_labels = _workflow_state(issue)

    evidence = _section(body, ("Evidence", "Verification", "Validation"))
    acceptance = _bullets(body, ("Acceptance criteria", "Acceptance Criteria",
                                 "Deterministic acceptance criteria"))
    approval = _section(body, ("Approval status", "Approval", "Human approval", "Operator approval"))
    outcome = _section(body, ("Outcome", "Objective", "Destination"))
    scope = _section(body, ("Scope",))

    return {
        "schema_version": 1,
        "mode": "synthetic" if synthetic else "local",
        "synthetic": synthetic,
        "issue": {
            "issue_id": f"{repo}#{number}",
            "number": number,
            "title": str(issue.get("title") or "Untitled work"),
            "state": str(issue.get("state") or "open"),
            "workflow": workflow,
            "workflow_labels": workflow_labels,
            "url": issue.get("url"),
            "milestone": _milestone(issue),
        },
        "mandate": {
            "outcome": outcome,
            "scope": scope,
            "acceptance_criteria": acceptance,
            "approval_reference": approval,
            "dispatch_limits": parse_dispatch_limits(body),
        },
        "relations": parse_relations(body),
        "runs": [dict(run) for run in runs],
        "evidence": {
            "present": bool(evidence),
            "summary": (evidence[:1200] if evidence else None),
            "review_state": "review" if workflow == "review" else None,
        },
        "source": {
            "status": status,
            "age_seconds": int(age_seconds),
            "complete": status == "fresh",
            "error": dict(error) if error else None,
        },
    }


def build_synthetic_workstream_detail_v1(repo: str, number: int = 470) -> dict[str, Any]:
    """Deterministic synthetic detail using the exact same schema (no mutation)."""
    issue = {
        "number": number,
        "title": "Build: S7a — Real Workstream detail projection and Run authority",
        "body": (
            "## Scope\n\nBuild the versioned fail-closed read-model foundation.\n\n"
            "## Deterministic acceptance criteria\n\n"
            "- A real GitHub Issue fixture plus real-format local Run records produce a schema-valid detail projection.\n"
            "- Synthetic and local projections validate against the same versioned schema.\n\n"
            "## Approval status\n\nOperator approved issue creation on 2026-08-29.\n\n"
            "## Worker role and limits\n\n"
            "Worker role: builder\nMax runtime: 5400 seconds\nMax cost: USD 7.00 hard ceiling\n"
            "Max parallel workers: 2\nDelegation depth: 1\n\n"
            "Part of: #469\n"
        ),
        "state": "open",
        "labels": [{"name": "workflow:in-progress"}],
        "url": f"https://github.com/{repo}/issues/{number}",
        "milestone": None,
    }
    runs = [
        {
            "run_id": "20260829T120000Z_aaaaaaaa",
            "issue_ref": f"{repo}#{number}",
            "status": "in_progress",
            "engine": "dsh",
            "worker_role": "builder",
            "started_at": "2026-08-29T12:00:00+00:00",
            "finished_at": None,
            "sources": ["dispatcher.runs"],
            "conflict": None,
        }
    ]
    return build_workstream_detail_v1(issue, runs, repo=repo, status="fresh", age_seconds=0, synthetic=True)