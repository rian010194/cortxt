#!/usr/bin/env python3
"""Atlas sync (#210): deterministic reader/generator for roadmap maps.

Reads open+closed issues, milestones, and relations (native sub-issues/
dependencies where available, plus the body conventions `Depends on:`,
`Blocked by:`, `Part of:`) via an injectable gh runner, then regenerates the
auto-generated section of each `atlas:map` issue between the
`<!-- atlas:auto:start -->` / `<!-- atlas:auto:end -->` markers. Everything
outside the markers (Destination, Decisions so far, Open questions, and any
other coordinator-owned text) is preserved byte-for-byte.

Design notes:
- GitHub Issues remain the single source of truth (ADR-018); Atlas maps are
  derived views, never a second backlog.
- Relation contract: containment (native sub-issue or `Part of: #N`, max one
  immediate parent) and prerequisite (`Blocked by: #N`, with `Depends on: #N`
  accepted as a legacy read alias for the same edge). Native and text sources
  are reconciled: agreement is deduplicated; conflicts are rendered as drift
  with source attribution, never silently resolved.
- Idempotence (AC3): the sync only rewrites a map body when the rendered
  auto-content (ignoring the sync timestamp line) actually differs from the
  current one. A second run against unchanged issue data writes nothing and
  posts no comment.
- Safety (AC12): generated content is scanned for a fixed list of known-bad
  markers (credential/prompt-leak patterns) before it is ever written.
- No network calls happen from pure logic in this module; GhRunner is the
  only place `gh` is invoked, and it is always injectable (see
  scripts/test_atlas_sync.py for the fake used in tests).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]

AUTO_START = "<!-- atlas:auto:start -->"
AUTO_END = "<!-- atlas:auto:end -->"

ATLAS_MAP_LABEL = "atlas:map"

WORKFLOW_LABELS = {
    "workflow:inbox",
    "workflow:ready",
    "workflow:in-progress",
    "workflow:review",
    "workflow:blocked",
    "workflow:done",
}

GH_CLI_TIMEOUT_SECONDS = 30

# Known-bad content markers (AC12): generated bodies/comments must never
# contain secrets, full prompts, private documents, raw sensitive logs, or
# model reasoning. This is a defensive net over deterministic output, not a
# substitute for keeping the generator itself free of such content.
KNOWN_BAD_MARKERS = [
    "-----BEGIN",
    "PRIVATE KEY",
    "api_key=",
    "apikey=",
    "Authorization: Bearer",
    "password:",
    "AKIA",
    "ghp_",
    "sk-ant-",
    "sk-proj-",
    "<system-prompt>",
    "chain-of-thought",
    "reasoning trace",
]

AREA_RE = re.compile(r"(?im)^\s*Area:\s*(.+?)\s*$")
MILESTONE_FIELD_RE = re.compile(r"(?im)^\s*Milestone:\s*(.+?)\s*$")
WORK_KIND_RE = re.compile(r"(?im)^\s*Work kind:\s*([a-z]+)\s*$")

REL_REPO = r"(?:([\w.\-]+/[\w.\-]+)#|#)"
PART_OF_RE = re.compile(rf"(?im)^\s*Part of:\s*{REL_REPO}(\d+)\s*$")
BLOCKED_BY_RE = re.compile(rf"(?im)^\s*Blocked by:\s*{REL_REPO}(\d+)\s*$")
DEPENDS_ON_RE = re.compile(rf"(?im)^\s*Depends on:\s*{REL_REPO}(\d+)\s*$")

CONTRACT_FIT_RE = re.compile(r"(?im)^\s*Contract fit(?: evidence)?:\s*(.+)$")
REPOSITORY_FIT_RE = re.compile(r"(?im)^\s*Repository fit(?: evidence)?:\s*(.+)$")

EMPTY_EVIDENCE_VALUES = {"", "tbd", "(none)", "none", "n/a", "-"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class IssueRecord:
    number: int
    title: str
    state: str  # "open" | "closed"
    body: str
    labels: list = field(default_factory=list)
    milestone: Optional[str] = None
    native_parent: Optional[int] = None
    native_sub_issues: list = field(default_factory=list)
    native_blocked_by: list = field(default_factory=list)

    @property
    def is_map(self) -> bool:
        return ATLAS_MAP_LABEL in self.labels

    @property
    def workflow_labels(self) -> list:
        return [l for l in self.labels if l in WORKFLOW_LABELS]


@dataclass
class Relation:
    kind: str  # "part_of" | "blocked_by"
    target_repo: str
    target: int
    source: str  # "text" | "native"
    legacy_alias: bool = False


@dataclass
class IssueNode:
    number: int
    parent: Optional[int] = None
    blocked_by: set = field(default_factory=set)
    drift: list = field(default_factory=list)


def issue_from_dict(d: dict) -> IssueRecord:
    milestone = d.get("milestone")
    if isinstance(milestone, dict):
        milestone = milestone.get("title")
    labels = d.get("labels") or []
    if labels and isinstance(labels[0], dict):
        labels = [l["name"] for l in labels]
    return IssueRecord(
        number=int(d["number"]),
        title=d.get("title", ""),
        state=d.get("state", "open").lower(),
        body=d.get("body") or "",
        labels=list(labels),
        milestone=milestone,
        native_parent=d.get("native_parent"),
        native_sub_issues=list(d.get("native_sub_issues") or []),
        native_blocked_by=list(d.get("native_blocked_by") or []),
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_area(body: str) -> Optional[str]:
    m = AREA_RE.search(body)
    return m.group(1) if m else None


def parse_milestone_field(body: str) -> Optional[str]:
    m = MILESTONE_FIELD_RE.search(body)
    return m.group(1) if m else None


def parse_work_kind(body: str) -> str:
    m = WORK_KIND_RE.search(body)
    return m.group(1) if m else "delivery"


def parse_text_relations(body: str, self_repo: str) -> list:
    relations = []
    for m in PART_OF_RE.finditer(body):
        repo = m.group(1) or self_repo
        relations.append(Relation("part_of", repo, int(m.group(2)), "text"))
    for m in BLOCKED_BY_RE.finditer(body):
        repo = m.group(1) or self_repo
        relations.append(Relation("blocked_by", repo, int(m.group(2)), "text"))
    for m in DEPENDS_ON_RE.finditer(body):
        repo = m.group(1) or self_repo
        relations.append(Relation("blocked_by", repo, int(m.group(2)), "text", legacy_alias=True))
    return relations


def extract_review_evidence(body: str) -> dict:
    def clean(m):
        if not m:
            return None
        val = m.group(1).strip()
        return None if val.lower() in EMPTY_EVIDENCE_VALUES else val

    return {
        "contract_fit": clean(CONTRACT_FIT_RE.search(body)),
        "repository_fit": clean(REPOSITORY_FIT_RE.search(body)),
    }


def scan_unsafe(text: str) -> list:
    """Return the known-bad markers (AC12) found in text, if any."""
    return [marker for marker in KNOWN_BAD_MARKERS if marker.lower() in text.lower()]


# ---------------------------------------------------------------------------
# Relation graph + validation
# ---------------------------------------------------------------------------


def resolve_containment(issue: IssueRecord, issues: dict, self_repo: str):
    drift = []
    text_targets = set()
    for r in parse_text_relations(issue.body, self_repo):
        if r.kind != "part_of":
            continue
        if r.target_repo != self_repo:
            drift.append(f"cross-repo Part of target rejected: {r.target_repo}#{r.target}")
            continue
        text_targets.add(r.target)

    if len(text_targets) > 1:
        drift.append(f"multiple immediate Part of targets in text: {sorted(text_targets)}")

    text_target = next(iter(text_targets)) if len(text_targets) == 1 else None
    native = issue.native_parent

    if native is not None and text_target is not None:
        if native == text_target:
            parent = native
        else:
            drift.append(f"native/text Part of mismatch: native=#{native} text=#{text_target}")
            parent = None
    elif native is not None:
        parent = native
    else:
        parent = text_target

    if parent is not None:
        if parent == issue.number:
            drift.append(f"self-edge rejected: Part of #{issue.number}")
            parent = None
        elif parent not in issues:
            drift.append(f"Part of target #{parent} does not exist")
            parent = None

    return parent, drift


def resolve_blocked_by(issue: IssueRecord, issues: dict, self_repo: str):
    targets = set()
    drift = []
    for r in parse_text_relations(issue.body, self_repo):
        if r.kind != "blocked_by":
            continue
        if r.target_repo != self_repo:
            drift.append(f"cross-repo Blocked by target rejected: {r.target_repo}#{r.target}")
            continue
        if r.target == issue.number:
            drift.append(f"self-edge rejected: Blocked by #{issue.number}")
            continue
        if r.target not in issues:
            drift.append(f"Blocked by target #{r.target} does not exist")
            continue
        targets.add(r.target)
    for t in issue.native_blocked_by:
        if t == issue.number:
            drift.append(f"self-edge rejected: native Blocked by #{issue.number}")
            continue
        if t not in issues:
            drift.append(f"native Blocked by target #{t} does not exist")
            continue
        targets.add(t)
    return targets, drift


def find_containment_cycle_members(parents: dict) -> set:
    cyclic = set()
    for start in list(parents.keys()):
        path = []
        seen = set()
        cur = start
        while cur is not None and cur in parents:
            if cur in seen:
                idx = path.index(cur)
                cyclic.update(path[idx:])
                break
            seen.add(cur)
            path.append(cur)
            cur = parents.get(cur)
    return cyclic


def find_prereq_cycle_members(edges: dict) -> set:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = defaultdict(int)
    cyclic = set()

    def dfs(u, stack):
        color[u] = GRAY
        stack.append(u)
        for v in edges.get(u, ()):
            if color[v] == GRAY:
                idx = stack.index(v)
                cyclic.update(stack[idx:])
            elif color[v] == WHITE:
                dfs(v, stack)
        stack.pop()
        color[u] = BLACK

    for n in list(edges.keys()):
        if color[n] == WHITE:
            dfs(n, [])
    return cyclic


def build_graph(issues: dict, self_repo: str):
    """Build the containment/prerequisite graph over non-map work issues.

    Returns (nodes: dict[int, IssueNode], global_drift: list[str]).
    """
    work_issues = {n: i for n, i in issues.items() if not i.is_map}
    nodes = {}
    parents = {}
    edges = {}
    global_drift = []

    for num, issue in work_issues.items():
        parent, p_drift = resolve_containment(issue, issues, self_repo)
        blocked_by, b_drift = resolve_blocked_by(issue, issues, self_repo)
        node = IssueNode(number=num, parent=parent, blocked_by=blocked_by, drift=p_drift + b_drift)
        nodes[num] = node
        if parent is not None:
            parents[num] = parent
        edges[num] = blocked_by

    for num in find_containment_cycle_members(parents):
        nodes[num].drift.append(f"containment cycle detected involving #{num}")
        nodes[num].parent = None

    cyclic_prereq = find_prereq_cycle_members(edges)
    for num in cyclic_prereq:
        nodes[num].drift.append(f"prerequisite cycle detected involving #{num}")

    for num, node in nodes.items():
        for d in node.drift:
            global_drift.append(f"#{num} {work_issues[num].title}: {d}")

    return nodes, global_drift


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------


def compute_discipline_violations(issues: dict) -> list:
    violations = []
    for num, issue in sorted(issues.items()):
        if issue.is_map or issue.state != "open":
            continue
        wf = issue.workflow_labels
        if len(wf) != 1:
            violations.append((num, issue.title, wf))
    return violations


def compute_frontier(issue_numbers, issues: dict, nodes: dict):
    frontier = []
    in_progress = []
    for num in sorted(issue_numbers):
        issue = issues[num]
        if issue.state != "open" or issue.is_map:
            continue
        wf = issue.workflow_labels
        if wf == ["workflow:in-progress"]:
            in_progress.append(issue)
            continue
        if wf != ["workflow:ready"]:
            continue
        node = nodes.get(num)
        blockers_open = [
            b
            for b in (node.blocked_by if node else set())
            if b in issues and issues[b].state == "open" and "workflow:done" not in issues[b].labels
        ]
        if blockers_open:
            continue
        frontier.append(issue)
    return frontier, in_progress


def compute_milestone_progress(issues: dict, milestone_name: Optional[str]):
    relevant = [i for i in issues.values() if not i.is_map and i.milestone == milestone_name]
    open_count = sum(1 for i in relevant if i.state == "open")
    closed_count = sum(1 for i in relevant if i.state == "closed")
    return relevant, open_count, closed_count


def compute_review_evidence(issues) -> list:
    rows = []
    for i in sorted(issues, key=lambda x: x.number):
        if i.is_map or not ({"workflow:review", "workflow:done"} & set(i.labels)):
            continue
        ev = extract_review_evidence(i.body)
        rows.append((i, ev))
    return rows


def compute_completion(area_issues, map_issue_number: int) -> dict:
    relevant = [i for i in area_issues if i.number != map_issue_number and not i.is_map]
    open_required = [i for i in relevant if i.state == "open"]
    review_gaps = []
    for i in relevant:
        if {"workflow:review", "workflow:done"} & set(i.labels):
            ev = extract_review_evidence(i.body)
            if not ev["contract_fit"] or not ev["repository_fit"]:
                review_gaps.append(i.number)
    complete = not open_required and not review_gaps
    return {
        "complete": complete,
        "open_required": [i.number for i in open_required],
        "review_gaps": review_gaps,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def ref(issue: IssueRecord) -> str:
    return f"{issue.title} (#{issue.number})"


def _section(title: str, body_lines: list) -> list:
    out = [f"### {title}", ""]
    out.extend(body_lines if body_lines else ["(none)"])
    out.append("")
    return out


def render_relationship_lines(issue: IssueRecord, node: Optional[IssueNode], issues: dict) -> list:
    lines = []
    if node and node.parent is not None and node.parent in issues:
        lines.append(f"  - Part of: {ref(issues[node.parent])}")
    if node:
        for b in sorted(node.blocked_by):
            if b in issues:
                closed = issues[b].state == "closed" or "workflow:done" in issues[b].labels
                tag = "closed, history" if closed else "OPEN blocker"
                lines.append(f"  - Blocked by: {ref(issues[b])} [{tag}]")
    return lines


def render_area_auto(area_name: str, milestone_name: Optional[str], area_issues: list, issues: dict, nodes: dict,
                      map_issue_number: int, sync_time_iso: str) -> str:
    numbers = {i.number for i in area_issues}
    lines = [AUTO_START, ""]

    current_state = []
    for i in sorted(area_issues, key=lambda x: x.number):
        wf = ", ".join(i.workflow_labels) or "(no workflow label)"
        current_state.append(f"- {ref(i)} -- state: {i.state}, workflow: {wf}, work kind: {parse_work_kind(i.body)}")
    lines += _section("Current state", current_state)

    execution_path = []
    for i in sorted(area_issues, key=lambda x: x.number):
        rel = render_relationship_lines(i, nodes.get(i.number), issues)
        if rel:
            execution_path.append(f"- {ref(i)}")
            execution_path.extend(rel)
    lines += _section("Execution path", execution_path)

    blockers = []
    for i in sorted(area_issues, key=lambda x: x.number):
        node = nodes.get(i.number)
        if not node:
            continue
        for b in sorted(node.blocked_by):
            if b in issues and issues[b].state == "open" and "workflow:done" not in issues[b].labels:
                blockers.append(f"- {ref(i)} blocked by {ref(issues[b])}")
    lines += _section("Blockers", blockers)

    frontier, in_progress = compute_frontier(numbers, issues, nodes)
    frontier_lines = [f"- {ref(i)}" for i in frontier]
    frontier_lines.append("")
    frontier_lines.append("Claimed work in progress (workflow:in-progress):")
    frontier_lines.extend(f"- {ref(i)}" for i in in_progress)
    if not in_progress:
        frontier_lines.append("(none)")
    lines += _section("Actionable frontier", frontier_lines)

    relevant, open_count, closed_count = compute_milestone_progress(issues, milestone_name)
    ms_lines = [f"Milestone: {milestone_name or '(none)'}", f"Open: {open_count}  Closed: {closed_count}"]
    lines += _section("Milestone progress", ms_lines)

    drift_lines = []
    for i in sorted(area_issues, key=lambda x: x.number):
        node = nodes.get(i.number)
        if node and node.drift:
            for d in node.drift:
                drift_lines.append(f"- #{i.number} {i.title}: {d}")
    lines += _section("Relationship drift", drift_lines)

    violations = [v for v in compute_discipline_violations(issues) if v[0] in numbers]
    violation_lines = [f"- #{n} {t}: labels={labels or '[]'}" for n, t, labels in violations]
    lines += _section("Discipline violations (one workflow:* label required)", violation_lines)

    evidence_rows = compute_review_evidence(area_issues)
    evidence_lines = []
    for i, ev in evidence_rows:
        c = ev["contract_fit"] or "MISSING"
        r = ev["repository_fit"] or "MISSING"
        evidence_lines.append(f"- {ref(i)}: contract fit = {c}; repository fit = {r}")
    lines += _section("Review evidence", evidence_lines)

    completion = compute_completion(area_issues, map_issue_number)
    completion_lines = [f"Complete: {completion['complete']}"]
    if completion["open_required"]:
        completion_lines.append(f"Open required work: {completion['open_required']}")
    if completion["review_gaps"]:
        completion_lines.append(f"Missing review evidence: {completion['review_gaps']}")
    completion_lines.append("Archive is coordinator/operator action only; sync never closes issues.")
    lines += _section("Completion", completion_lines)

    lines += _section("Last successful sync", [f"{sync_time_iso}"])

    lines.append(AUTO_END)
    return "\n".join(lines)


def render_global_auto(all_issues: dict, nodes: dict, global_drift: list, sync_time_iso: str) -> str:
    work_issues = {n: i for n, i in all_issues.items() if not i.is_map}
    map_issues = [i for i in all_issues.values() if i.is_map]
    lines = [AUTO_START, ""]

    areas = sorted({parse_area(m.body) for m in map_issues if parse_area(m.body) and parse_area(m.body) != "Global"})
    current_state = []
    for area in areas:
        milestone_name = None
        for m in map_issues:
            if parse_area(m.body) == area:
                milestone_name = parse_milestone_field(m.body)
                break
        _, open_c, closed_c = compute_milestone_progress(all_issues, milestone_name)
        current_state.append(f"- Area: {area} -- milestone: {milestone_name or '(none)'}, open: {open_c}, closed: {closed_c}")
    lines += _section("Current state (roadmap areas)", current_state)

    cross_area = []
    milestone_of = {n: i.milestone for n, i in work_issues.items()}
    for num, node in nodes.items():
        for b in sorted(node.blocked_by):
            if b in work_issues and milestone_of.get(num) != milestone_of.get(b):
                cross_area.append(f"- {ref(work_issues[num])} blocked by {ref(work_issues[b])} (cross-area)")
    lines += _section("Execution path (cross-area blocker chain)", cross_area)

    blockers = []
    for num, node in nodes.items():
        for b in sorted(node.blocked_by):
            if b in work_issues and work_issues[b].state == "open" and "workflow:done" not in work_issues[b].labels:
                blockers.append(f"- {ref(work_issues[num])} blocked by {ref(work_issues[b])}")
    lines += _section("Blockers", blockers)

    frontier, in_progress = compute_frontier(work_issues.keys(), all_issues, nodes)
    frontier_lines = [f"- {ref(i)}" for i in frontier]
    frontier_lines.append("")
    frontier_lines.append("Claimed work in progress (workflow:in-progress):")
    frontier_lines.extend(f"- {ref(i)}" for i in in_progress)
    if not in_progress:
        frontier_lines.append("(none)")
    lines += _section("Actionable frontier", frontier_lines)

    milestones = sorted({i.milestone for i in work_issues.values() if i.milestone})
    ms_lines = []
    for ms in milestones:
        _, open_c, closed_c = compute_milestone_progress(all_issues, ms)
        ms_lines.append(f"- {ms}: open {open_c}, closed {closed_c}")
    lines += _section("Milestone overview", ms_lines)

    drift_lines = [f"- {d}" for d in global_drift]
    lines += _section("Relationship drift", drift_lines)

    violations = compute_discipline_violations(all_issues)
    violation_lines = [f"- #{n} {t}: labels={labels or '[]'}" for n, t, labels in violations]
    lines += _section("Discipline violations (one workflow:* label required)", violation_lines)

    evidence_rows = compute_review_evidence(list(work_issues.values()))
    evidence_lines = []
    for i, ev in evidence_rows:
        c = ev["contract_fit"] or "MISSING"
        r = ev["repository_fit"] or "MISSING"
        evidence_lines.append(f"- {ref(i)}: contract fit = {c}; repository fit = {r}")
    lines += _section("Review evidence", evidence_lines)

    lines += _section("Completion", ["Global map is preserved; it is never archived (per docs/agents/atlas.md)."])

    lines += _section("Last successful sync", [f"{sync_time_iso}"])

    lines.append(AUTO_END)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Site page emission (issue #285): render the global roadmap as a static
# docs page, reusing the same derived data the map bodies use.
# ---------------------------------------------------------------------------

SITE_PAGE_PATH = "site/src/content/docs/docs/atlas-status.md"


def render_site_page(all_issues: dict, nodes: dict, global_drift: list, self_repo: str,
                     sync_time_iso: str) -> str:
    """Render the public Atlas status page (markdown) from the same data
    pipeline the map bodies use. Purely derived and read-only: it never
    writes GitHub state and contains no interactive logic.

    The page is intentionally a *summary* mirror of the global map's
    coordinator-owned sections: the canonical roadmap remains the GitHub
    map issue (#214); this page is a derived publication for the docs
    site. It includes the sync timestamp so readers can see freshness,
    and the safe-content scan is applied before the page is ever written.
    """
    work_issues = {n: i for n, i in all_issues.items() if not i.is_map}
    map_issues = [i for i in all_issues.values() if i.is_map]
    lines = [
        "---",
        "title: Status and roadmap (Atlas)",
        "description: Live-derived status page for the Cortxt roadmap, generated from Atlas maps.",
        "---",
        "",
        "## Roadmap status",
        "",
        "This page is derived automatically from the [Atlas roadmap maps](",
        f"https://github.com/{self_repo}/issues/214) -- the GitHub issues "
        "remain the single source of truth. Last successful sync: "
        f"`{sync_time_iso}`.",
        "",
    ]

    # Current state (roadmap areas).
    areas = sorted({parse_area(m.body) for m in map_issues if parse_area(m.body) and parse_area(m.body) != "Global"})
    area_lines = []
    for area in areas:
        milestone_name = None
        for m in map_issues:
            if parse_area(m.body) == area:
                milestone_name = parse_milestone_field(m.body)
                break
        _, open_c, closed_c = compute_milestone_progress(all_issues, milestone_name)
        area_lines.append(f"- **{area}** -- milestone: {milestone_name or '(none)'}, open: {open_c}, closed: {closed_c}")
    lines += _section("Roadmap areas", area_lines)

    # Actionable frontier + claimed work.
    frontier, in_progress = compute_frontier(work_issues.keys(), all_issues, nodes)
    frontier_lines = [f"- {ref(i)}" for i in frontier]
    frontier_lines.append("")
    frontier_lines.append("Claimed work in progress (workflow:in-progress):")
    frontier_lines.extend(f"- {ref(i)}" for i in in_progress)
    if not in_progress:
        frontier_lines.append("(none)")
    lines += _section("Actionable frontier", frontier_lines)

    # Blockers (open prerequisites not yet done).
    blockers = []
    for num, node in nodes.items():
        for b in sorted(node.blocked_by):
            if b in work_issues and work_issues[b].state == "open" and "workflow:done" not in work_issues[b].labels:
                blockers.append(f"- {ref(work_issues[num])} blocked by {ref(work_issues[b])}")
    lines += _section("Blockers", blockers)

    # Milestone overview.
    milestones = sorted({i.milestone for i in work_issues.values() if i.milestone})
    ms_lines = []
    for ms in milestones:
        _, open_c, closed_c = compute_milestone_progress(all_issues, ms)
        ms_lines.append(f"- {ms}: open {open_c}, closed {closed_c}")
    lines += _section("Milestone overview", ms_lines)

    # Discipline violations.
    violations = compute_discipline_violations(all_issues)
    violation_lines = [f"- #{n} {t}: labels={labels or '[]'}" for n, t, labels in violations]
    lines += _section("Discipline violations (one workflow:* label required)", violation_lines)

    # Review evidence presence.
    evidence_rows = compute_review_evidence(list(work_issues.values()))
    evidence_lines = []
    for i, ev in evidence_rows:
        c = ev["contract_fit"] or "MISSING"
        r = ev["repository_fit"] or "MISSING"
        evidence_lines.append(f"- {ref(i)}: contract fit = {c}; repository fit = {r}")
    lines += _section("Review evidence", evidence_lines)

    # Relationship drift.
    drift_lines = [f"- {d}" for d in global_drift]
    lines += _section("Relationship drift", drift_lines)

    lines += _section("Last successful sync", [f"{sync_time_iso}"])
    return "\n".join(lines)


def emit_site_page(*, out_dir: Path, issues: dict, nodes: dict, global_drift: list,
                   self_repo: str, sync_time_iso: str) -> tuple[Path, bool]:
    """Render the site page and write it only when the content actually
    changed, ignoring the sync timestamp (AC3, same discipline as map-body
    idempotence): identical issue data at a new timestamp is a no-op that
    preserves the file already on disk. Returns (path, wrote).

    The safe-content scan (AC12) is applied before writing: a page
    containing known-bad markers is never written and raises instead, so
    the daily workflow fails loudly rather than publishing a leak.
    """
    page = render_site_page(issues, nodes, global_drift, self_repo, sync_time_iso)
    bad = scan_unsafe(page)
    if bad:
        raise ValueError(f"unsafe content markers detected in site page: {bad}")

    path = out_dir / SITE_PAGE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing is not None and _strip_timestamp_for_diff(existing) == _strip_timestamp_for_diff(page):
        return path, False
    path.write_text(page, encoding="utf-8")
    return path, True


# ---------------------------------------------------------------------------
# Visual graph emission (issue #300): render the roadmap graph as a
# content-free JSON document the docs-site visual page fetches. Reuses the
# same build_graph / compute_frontier data pipeline as the map bodies and
# the text site page; deliberately contains NO issue bodies, comments, drift
# prose, secrets, or reasoning -- only identifiers, states, and relations.
# ---------------------------------------------------------------------------

SITE_GRAPH_PATH = "site/public/atlas/graph.json"

# Stable color keys for the visual page. Map workflow labels to a palette
# so the page can render consistently without hardcoding business rules in
# client JS (the JSON carries the label; the page maps it to a color).
WORKFLOW_STYLE = {
    "workflow:inbox": "inbox",
    "workflow:ready": "ready",
    "workflow:in-progress": "in-progress",
    "workflow:review": "review",
    "workflow:blocked": "blocked",
    "workflow:done": "done",
    "": "none",
}


def _node_area(milestone_of: dict, area_map_issues: list, number: int) -> str:
    """Assign a work issue to the roadmap area whose milestone it belongs
    to (the same area/milestone link the maps use). Unmatched issues fall
    back to 'Other'."""
    ms = milestone_of.get(number)
    if not ms:
        return "Other"
    for m in area_map_issues:
        if parse_milestone_field(m.body) == ms:
            return parse_area(m.body) or "Other"
    return "Other"


def render_site_graph(all_issues: dict, nodes: dict, global_drift: list, self_repo: str,
                      sync_time_iso: str) -> str:
    """Render the Atlas roadmap graph as a compact, content-free JSON string.

    Node fields: number, title, state, workflow (style key), milestone, area,
    work_kind, frontier, in_progress, closed. Edge fields: from (the issue
    that depends on / is contained by), to, kind ('blocked_by' | 'part_of').
    Milestones and drift count are top-level. Titles are the only free-text;
    the safe-content scan is applied before writing so a leak in a title can
    never reach the committed file.
    """
    work_issues = {n: i for n, i in all_issues.items() if not i.is_map}
    map_issues = [i for i in all_issues.values() if i.is_map]
    milestone_of = {n: i.milestone for n, i in work_issues.items()}

    frontier, in_progress = compute_frontier(work_issues.keys(), all_issues, nodes)
    frontier_ids = {i.number for i in frontier}
    in_progress_ids = {i.number for i in in_progress}

    nodes_out = []
    for num in sorted(work_issues):
        issue = work_issues[num]
        node = nodes.get(num)
        wf = issue.workflow_labels
        wf_key = wf[0] if len(wf) == 1 else ""
        nodes_out.append({
            "number": num,
            "title": issue.title,
            "state": issue.state,
            "workflow": WORKFLOW_STYLE.get(wf_key, "none"),
            "milestone": milestone_of.get(num),
            "area": _node_area(milestone_of, map_issues, num),
            "work_kind": parse_work_kind(issue.body),
            "frontier": num in frontier_ids,
            "in_progress": num in in_progress_ids,
        })

    edges_out = []
    for num, node in nodes.items():
        if node is None:
            continue
        for b in sorted(node.blocked_by):
            edges_out.append({"from": b, "to": num, "kind": "blocked_by"})
        if node.parent is not None:
            edges_out.append({"from": node.parent, "to": num, "kind": "part_of"})

    milestones = sorted({i.milestone for i in work_issues.values() if i.milestone})

    doc = {
        "schema_version": 1,
        "repo": self_repo,
        "sync_time": sync_time_iso,
        "nodes": nodes_out,
        "edges": edges_out,
        "milestones": milestones,
        "drift_count": len(global_drift),
        "frontier_count": len(frontier),
    }
    return json.dumps(doc, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def emit_site_graph(*, out_dir: Path, issues: dict, nodes: dict, global_drift: list,
                    self_repo: str, sync_time_iso: str) -> tuple[Path, bool]:
    """Render the graph JSON and write it only when the content changed
    (same idempotence discipline as emit_site_page). Safe-content scan is
    applied before writing: a leak in an issue title must never reach the
    committed file."""
    graph = render_site_graph(issues, nodes, global_drift, self_repo, sync_time_iso)
    bad = scan_unsafe(graph)
    if bad:
        raise ValueError(f"unsafe content markers detected in site graph: {bad}")

    path = out_dir / SITE_GRAPH_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing is not None and _strip_timestamp_for_diff(existing) == _strip_timestamp_for_diff(graph):
        return path, False
    path.write_text(graph, encoding="utf-8")
    return path, True


# ---------------------------------------------------------------------------
# Body diffing / marker replacement
# ---------------------------------------------------------------------------

def _strip_sync_timestamp(auto_text: str) -> str:
    """Normalize the 'Last successful sync' subsection so idempotence checks
    (AC3) ignore the timestamp -- only real content changes should trigger a
    rewrite."""
    return re.sub(
        r"### Last successful sync\n\n.*?\n\n",
        "### Last successful sync\n\n<redacted-for-diff>\n\n",
        auto_text,
        flags=re.S,
    )


SYNC_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _strip_timestamp_for_diff(text: str) -> str:
    """Normalize every embedded sync timestamp so the site page/graph
    idempotence check (AC3, same discipline as _strip_sync_timestamp for map
    bodies) ignores freshness-only differences. Without this, a run against
    perfectly unchanged issue data still rewrites (and commits) the page and
    graph on every schedule tick, because the new timestamp always differs
    from the one already on disk -- a real bug, not intentional freshness."""
    return SYNC_TIMESTAMP_RE.sub("<redacted-for-diff>", text)


def extract_auto(body: str) -> Optional[str]:
    start = body.find(AUTO_START)
    end = body.find(AUTO_END)
    if start == -1 or end == -1 or end < start:
        return None
    return body[start : end + len(AUTO_END)]


def replace_auto(body: str, new_auto: str) -> str:
    start = body.find(AUTO_START)
    end = body.find(AUTO_END)
    if start == -1 or end == -1:
        # No markers present yet: append the auto block at the end.
        sep = "\n\n" if body and not body.endswith("\n\n") else ""
        return f"{body}{sep}{new_auto}\n"
    return body[:start] + new_auto + body[end + len(AUTO_END) :]


def render_map_body(map_issue: IssueRecord, all_issues: dict, nodes: dict, global_drift: list, self_repo: str,
                     sync_time_iso: str):
    """Return (new_body, changed: bool, new_auto: str)."""
    area = parse_area(map_issue.body)
    if area == "Global":
        new_auto = render_global_auto(all_issues, nodes, global_drift, sync_time_iso)
    else:
        milestone_name = parse_milestone_field(map_issue.body)
        area_issues, _, _ = compute_milestone_progress(all_issues, milestone_name)
        new_auto = render_area_auto(area, milestone_name, area_issues, all_issues, nodes, map_issue.number, sync_time_iso)

    old_auto = extract_auto(map_issue.body) or ""
    if _strip_sync_timestamp(new_auto) == _strip_sync_timestamp(old_auto):
        return map_issue.body, False, old_auto

    new_body = replace_auto(map_issue.body, new_auto)
    return new_body, True, new_auto


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class SyncReport:
    changed: list = field(default_factory=list)  # list of issue numbers
    unchanged: list = field(default_factory=list)
    failed: list = field(default_factory=list)  # list of (number, error)
    unsafe: list = field(default_factory=list)  # list of (number, markers)


def sync_repo(gh, repo: str, sync_time_iso: str) -> SyncReport:
    raw = gh.list_issues(repo)
    issues = {i.number: i for i in (issue_from_dict(d) for d in raw)}

    nodes, global_drift = build_graph(issues, repo)

    report = SyncReport()
    for num, issue in sorted(issues.items()):
        if not issue.is_map:
            continue
        try:
            new_body, changed, new_auto = render_map_body(issue, issues, nodes, global_drift, repo, sync_time_iso)
        except Exception as exc:  # noqa: BLE001 - one map's failure must not abort the run
            report.failed.append((num, str(exc)))
            continue

        if not changed:
            report.unchanged.append(num)
            continue

        bad = scan_unsafe(new_auto)
        if bad:
            report.unsafe.append((num, bad))
            report.failed.append((num, f"unsafe content markers detected: {bad}"))
            continue

        gh.update_issue_body(repo, num, new_body)
        gh.comment(repo, num, _sync_summary_comment(issue, new_auto, sync_time_iso))
        report.changed.append(num)

    return report


def _sync_summary_comment(issue: IssueRecord, new_auto: str, sync_time_iso: str) -> str:
    area = parse_area(issue.body) or "(unknown)"
    lines = [
        "## Atlas sync",
        "",
        f"Area: {area}",
        f"Synced at: {sync_time_iso}",
        "",
        "Auto-generated sections were regenerated. See the map body for full detail.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Real gh runner (not exercised by tests; tests inject a fake)
# ---------------------------------------------------------------------------


class GhRunner:
    """Thin wrapper around the gh CLI. Kept small so tests substitute a fake
    and no test exercises real subprocess/network calls."""

    def _gh(self, *args: str, input_text: Optional[str] = None) -> str:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GH_CLI_TIMEOUT_SECONDS,
            input=input_text,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return result.stdout

    def list_issues(self, repo: str) -> list:
        out = self._gh(
            "issue", "list", "-R", repo, "--state", "all", "--limit", "500",
            "--json", "number,title,state,body,labels,milestone",
        )
        issues = json.loads(out)
        for issue in issues:
            issue["state"] = issue["state"].lower()
            issue["native_parent"], issue["native_sub_issues"], issue["native_blocked_by"] = self._native_relations(
                repo, issue["number"]
            )
        return issues

    def _native_relations(self, repo: str, number: int):
        """Best-effort native sub-issue lookup. GitHub's sub-issues API is
        still rolling out; any failure degrades gracefully to text-only
        relations (native fields left empty), which is a fully supported
        path per the relation contract in docs/agents/atlas.md."""
        try:
            out = self._gh("api", f"repos/{repo}/issues/{number}/sub_issues")
            sub_issues = [s["number"] for s in json.loads(out)]
        except Exception:  # noqa: BLE001
            sub_issues = []
        return None, sub_issues, []

    def update_issue_body(self, repo: str, number: int, body: str) -> None:
        self._gh("issue", "edit", str(number), "-R", repo, "--body-file", "-", input_text=body)

    def comment(self, repo: str, number: int, body: str) -> None:
        self._gh("issue", "comment", str(number), "-R", repo, "--body-file", "-", input_text=body)


def main(argv=None) -> int:
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="Atlas sync: regenerate roadmap map auto sections and (optionally) emit the site page."
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument(
        "--emit-site", metavar="DIR", type=Path, default=None,
        help="Also render the public Atlas status page into DIR (the repo checkout root, "
             "e.g. '.' or the workflow checkout); writes the page at "
             "site/src/content/docs/docs/atlas-status.md only when its content changed",
    )
    parser.add_argument(
        "--emit-graph", metavar="DIR", type=Path, default=None,
        help="Also render the visual Atlas graph JSON into DIR (the repo checkout root); "
             "writes site/public/atlas/graph.json only when its content changed (issue #300)",
    )
    args = parser.parse_args(argv)

    gh = GhRunner()
    sync_time_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report = sync_repo(gh, args.repo, sync_time_iso)

    print(f"changed: {report.changed}")
    print(f"unchanged: {report.unchanged}")
    if report.failed:
        print(f"failed: {report.failed}", file=sys.stderr)
        return 1

    if args.emit_site is not None:
        raw = gh.list_issues(args.repo)
        issues = {i.number: i for i in (issue_from_dict(d) for d in raw)}
        nodes, global_drift = build_graph(issues, args.repo)
        path, wrote = emit_site_page(
            out_dir=args.emit_site, issues=issues, nodes=nodes,
            global_drift=global_drift, self_repo=args.repo,
            sync_time_iso=sync_time_iso,
        )
        print(f"site page: {'written' if wrote else 'unchanged'} -> {path}")

    if args.emit_graph is not None:
        raw = gh.list_issues(args.repo)
        issues = {i.number: i for i in (issue_from_dict(d) for d in raw)}
        nodes, global_drift = build_graph(issues, args.repo)
        path, wrote = emit_site_graph(
            out_dir=args.emit_graph, issues=issues, nodes=nodes,
            global_drift=global_drift, self_repo=args.repo,
            sync_time_iso=sync_time_iso,
        )
        print(f"site graph: {'written' if wrote else 'unchanged'} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
