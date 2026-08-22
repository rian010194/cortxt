"""Canonical, versioned candidates projection shared by every renderer."""
from __future__ import annotations

import re
from typing import Any, Iterable

EDGE = re.compile(r"^(Blocked by|Depends on):\s*#(\d+)\s*$", re.MULTILINE | re.IGNORECASE)
AREA = re.compile(r"^Area:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)


def dependency_targets(issues: Iterable[dict[str, Any]]) -> list[int]:
    open_numbers = {x["number"] for x in issues}
    return sorted({int(raw) for issue in issues for _, raw in EDGE.findall(issue.get("body") or "")
                   if int(raw) not in open_numbers})


def _labels(issue: dict[str, Any]) -> list[str]:
    return [x.get("name", "") if isinstance(x, dict) else str(x) for x in issue.get("labels") or []]


def _area(issue: dict[str, Any], labels: list[str]) -> tuple[str | None, list[str]]:
    body = AREA.findall(issue.get("body") or "")
    label_areas = [x[6:].strip() for x in labels if x.lower().startswith("area:")]
    values = list(dict.fromkeys(body + label_areas))
    drift = ["ambiguous area"] if len(values) > 1 or len(body) > 1 or len(label_areas) > 1 else []
    return (body[0] if body else label_areas[0] if label_areas else None), drift


def build_candidates_view(issues: Iterable[dict[str, Any]], *, complete: bool = True,
                          status: str = "fresh", age_seconds: int = 0,
                          error: dict[str, Any] | None = None,
                          blocker_statuses: dict[int, dict[str, Any]] | None = None,
                          actions: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    source = sorted((dict(x) for x in issues if str(x.get("state", "")).upper() == "OPEN"), key=lambda x: x["number"])
    by_number = {x["number"]: x for x in source}
    parsed: dict[int, list[dict[str, Any]]] = {}
    duplicate_numbers: set[int] = set()
    graph: dict[int, set[int]] = {x["number"]: set() for x in source}
    for issue in source:
        seen: set[int] = set(); edges = []
        for relation, raw in EDGE.findall(issue.get("body") or ""):
            target = int(raw)
            if target in seen: duplicate_numbers.add(issue["number"])
            seen.add(target); graph[issue["number"]].add(target)
            if not any(e["target"] == target for e in edges):
                edges.append({"relation": relation.title(), "target": target})
        parsed[issue["number"]] = edges

    def cyclic(start: int, node: int, visited: set[int]) -> bool:
        if node in visited: return False
        visited.add(node)
        return any(target == start or (target in graph and cyclic(start, target, visited)) for target in graph[node])

    groups = {name: [] for name in ("frontier", "in_progress", "blocked", "other", "violations", "atlas_maps")}
    for issue in source:
        labels = _labels(issue); workflow = [x for x in labels if x.lower().startswith("workflow:")]
        area, violations = _area(issue, labels)
        if len(workflow) != 1: violations.append("workflow label cardinality")
        if issue["number"] in duplicate_numbers: violations.append("duplicate dependency edge")
        details = []; open_count = 0
        for edge in parsed[issue["number"]]:
            target = by_number.get(edge["target"]) or (blocker_statuses or {}).get(edge["target"])
            if edge["target"] == issue["number"]: violations.append("self dependency edge")
            if target is None:
                target_status = "missing"; violations.append(f"missing dependency target #{edge['target']}")
                open_count += 1
            else:
                target_labels = _labels(target)
                done = "workflow:done" in [x.lower() for x in target_labels]
                closed = str(target.get("state", "")).upper() == "CLOSED"
                target_status = "closed-history" if closed else "done" if done else "open"
                if not (done or closed): open_count += 1
            details.append({**edge, "target_status": target_status,
                            "target_title": target.get("title") if target else None})
        if cyclic(issue["number"], issue["number"], set()): violations.append("dependency cycle")
        milestone = issue.get("milestone")
        row = {"number": issue["number"], "title": issue.get("title", ""),
               "workflow": workflow[0] if len(workflow) == 1 else f"VIOLATION ({len(workflow)} workflow labels)",
               "area": area, "milestone": milestone.get("title") if isinstance(milestone, dict) else None,
               "url": issue.get("url"), "open_blocker_count": open_count,
               "dependencies": details, "violations": sorted(set(violations))}
        lower = [x.lower() for x in labels]
        workflow_key = [x.lower() for x in workflow]
        if "atlas:map" in lower: group = "atlas_maps"
        elif violations: group = "violations"
        elif workflow_key == ["workflow:ready"] and open_count == 0: group = "frontier"
        elif workflow_key == ["workflow:in-progress"]: group = "in_progress"
        elif open_count: group = "blocked"
        else: group = "other"
        groups[group].append(row)
    result_groups = [{"id": name, "count": len(rows), "rows": rows} for name, rows in groups.items()]
    if actions:
        handoffs = [{"id": action["id"], "operation": action["operation"], "enabled": True,
                     "port": action["port"], "effect_class": action["effect_class"],
                     "authorization": dict(action["authorization"]), "confirm": dict(action["confirm"]),
                     "reason": "Operator-authorized action: approval reference + confirm required"}
                    for action in actions]
    else:
        handoffs = [{"id": "mark-ready", "enabled": False, "reason": "Read-only: no label writes"},
                    {"id": "claim-run", "enabled": False, "reason": "Read-only: no dispatch callback"}]
    return {"schema_version": 1, "source": {"complete": complete, "status": status,
            "age_seconds": age_seconds, "error": error}, "total": len(source), "groups": result_groups,
            "handoffs": handoffs}


def render_candidates_tree(model: dict[str, Any]) -> dict[str, Any]:
    """Browser-friendly data-only tree consuming the exact normalized model."""
    return {"primitive": "stack", "state": model["source"]["status"], "props": {"label": "Candidates"},
            "children": [{"primitive": "table", "state": "ready", "props": {"label": g["id"], "rows": g["rows"],
                "columns": ["number", "title", "workflow", "area", "milestone", "open_blocker_count"]}} for g in model["groups"]]}
