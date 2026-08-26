#!/usr/bin/env python3
"""Deterministic regression tests for scripts/atlas_sync.py (#210).

Exercises the Atlas relation contract, idempotence, and safety rules from
issue #210 / docs/agents/atlas.md against a fake gh runner, so no real
gh/network calls happen. Run directly: python scripts/test_atlas_sync.py
(0 = pass)
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "atlas_sync.py"
spec = importlib.util.spec_from_file_location("atlas_sync", MOD)
a = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = a  # atlas_sync.py uses `from __future__ import annotations`;
# register the module so dataclass processing can resolve cls.__module__.
spec.loader.exec_module(a)

fail = []


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fail.append(name)


REPO_ID = "o/r"


class FakeGh:
    """Pure in-memory stand-in for the injectable gh runner. No subprocess,
    no network -- list_issues() just returns whatever dicts the test built."""

    def __init__(self, issues):
        self.issues = issues
        self.updated_bodies = {}
        self.comments = []

    def list_issues(self, repo):
        return self.issues

    def update_issue_body(self, repo, number, body):
        self.updated_bodies[number] = body
        for iss in self.issues:
            if iss["number"] == number:
                iss["body"] = body

    def comment(self, repo, number, body):
        self.comments.append((number, body))


def work_issue(number, title, state="open", labels=None, body="", milestone=None,
                native_parent=None, native_sub_issues=None, native_blocked_by=None):
    return {
        "number": number,
        "title": title,
        "state": state,
        "body": body,
        "labels": list(labels or []),
        "milestone": {"title": milestone} if milestone else None,
        "native_parent": native_parent,
        "native_sub_issues": list(native_sub_issues or []),
        "native_blocked_by": list(native_blocked_by or []),
    }


def map_body(area, milestone=None, destination="Destination TBD.", decisions="No decisions yet.",
             questions="No open questions yet."):
    ms_line = f"Milestone: {milestone}\n" if milestone else ""
    return (
        f"Area: {area}\n"
        f"{ms_line}"
        "Planning stage: Exploring\n"
        "\n"
        "## Destination\n"
        "\n"
        f"{destination}\n"
        "\n"
        f"{a.AUTO_START}\n(will be regenerated)\n{a.AUTO_END}\n"
        "\n"
        "## Decisions so far\n"
        "\n"
        f"{decisions}\n"
        "\n"
        "## Open questions\n"
        "\n"
        f"{questions}\n"
    )


def map_issue(number, area, milestone=None, **kw):
    return work_issue(number, f"Atlas map: {area}", labels=["atlas:map"],
                       body=map_body(area, milestone=milestone, **kw), milestone=None)


# ---------------------------------------------------------------------------

def run_all_checks():
    print("== auto-section regeneration + coordinator-section preservation ==")
    gh = FakeGh([
        map_issue(100, "Global", destination="Ship Atlas.", decisions="ADR-018 accepted.",
                  questions="How many areas at launch?"),
        work_issue(1, "Wire dispatch loop", state="open", labels=["workflow:ready"], milestone="M1"),
        work_issue(2, "Old prep work", state="closed", labels=["workflow:done"], milestone="M1"),
    ])
    report = a.sync_repo(gh, REPO_ID, "2026-01-01T00:00:00Z")
    check("global map regenerated on first run", 100 in report.changed)
    new_body = gh.updated_bodies[100]
    check("coordinator Destination text preserved", "Ship Atlas." in new_body)
    check("coordinator Decisions text preserved", "ADR-018 accepted." in new_body)
    check("coordinator Open questions text preserved", "How many areas at launch?" in new_body)
    check("auto markers still present", a.AUTO_START in new_body and a.AUTO_END in new_body)
    check("auto content mentions the open work issue", "Wire dispatch loop" in a.extract_auto(new_body))
    check("a sync summary comment was posted", any(c[0] == 100 for c in gh.comments))

    # ---------------------------------------------------------------------------
    print("== idempotence (AC3): second run with unchanged issue data writes nothing ==")
    report2 = a.sync_repo(gh, REPO_ID, "2026-01-02T00:00:00Z")
    check("no map reported as changed on the second run", report2.changed == [])
    check("global map reported unchanged", 100 in report2.unchanged)
    check("no second comment posted", len([c for c in gh.comments if c[0] == 100]) == 1)

    # ---------------------------------------------------------------------------
    print("== idempotence: a real data change DOES trigger a rewrite ==")
    gh.issues.append(work_issue(3, "New work", state="open", labels=["workflow:ready"], milestone="M1"))
    report3 = a.sync_repo(gh, REPO_ID, "2026-01-03T00:00:00Z")
    check("global map changed once new work exists", 100 in report3.changed)

    # ---------------------------------------------------------------------------
    print("== one-workflow-label discipline (AC4) ==")
    gh4 = FakeGh([
        map_issue(200, "Global"),
        work_issue(10, "No workflow label", state="open", labels=[], milestone="M1"),
        work_issue(11, "Two workflow labels", state="open", labels=["workflow:ready", "workflow:blocked"], milestone="M1"),
        work_issue(12, "Fine", state="open", labels=["workflow:ready"], milestone="M1"),
    ])
    a.sync_repo(gh4, REPO_ID, "2026-01-01T00:00:00Z")
    auto4 = a.extract_auto(gh4.updated_bodies[200])
    check("zero-label issue reported as a discipline violation", "#10 No workflow label" in auto4)
    check("multi-label issue reported as a discipline violation", "#11 Two workflow labels" in auto4)
    check("compliant issue not reported as a violation", "#12 Fine: labels" not in auto4)
    check("violations were never silently corrected (labels untouched)",
          any(i["labels"] == [] for i in gh4.issues if i["number"] == 10))

    # ---------------------------------------------------------------------------
    print("== milestone progress (AC5) ==")
    gh5 = FakeGh([
        map_issue(300, "MCP lifecycle and dispatch stack", milestone="Open-source product packaging"),
        work_issue(20, "A", state="open", labels=["workflow:ready"], milestone="Open-source product packaging"),
        work_issue(21, "B", state="open", labels=["workflow:in-progress"], milestone="Open-source product packaging"),
        work_issue(22, "C", state="closed", labels=["workflow:done"], milestone="Open-source product packaging"),
        work_issue(23, "Unrelated milestone", state="open", labels=["workflow:ready"], milestone="Other"),
    ])
    a.sync_repo(gh5, REPO_ID, "2026-01-01T00:00:00Z")
    auto5 = a.extract_auto(gh5.updated_bodies[300])
    check("milestone progress shows open=2, closed=1", "Open: 2  Closed: 1" in auto5)
    check("issue from a different milestone is excluded from the area", "Unrelated milestone" not in auto5)

    # ---------------------------------------------------------------------------
    print("== relationship rendering + validation (AC8) ==")
    gh8 = FakeGh([
        map_issue(400, "Global"),
        # native and text agree -> dedupe to a single Part of edge
        work_issue(30, "Parent", state="open", labels=["workflow:ready"], milestone="M"),
        work_issue(31, "Child agree", state="open", labels=["workflow:ready"], milestone="M",
                   body="Part of: #30", native_parent=30),
        # native/text conflict -> drift, both sides reported, no parent resolved
        work_issue(32, "Other parent", state="open", labels=["workflow:ready"], milestone="M"),
        work_issue(33, "Child conflict", state="open", labels=["workflow:ready"], milestone="M",
                   body="Part of: #30", native_parent=32),
        # multiple text parents -> drift
        work_issue(34, "Child multi-parent", state="open", labels=["workflow:ready"], milestone="M",
                   body="Part of: #30\nPart of: #32"),
        # self-edge -> drift, rejected
        work_issue(35, "Self parent", state="open", labels=["workflow:ready"], milestone="M", body="Part of: #35"),
        # missing target -> drift
        work_issue(36, "Missing parent", state="open", labels=["workflow:ready"], milestone="M", body="Part of: #999"),
        # cross-repo -> rejected
        work_issue(37, "Cross repo parent", state="open", labels=["workflow:ready"], milestone="M",
                   body="Part of: other/repo#30"),
        # Depends on legacy alias == Blocked by, same edge, dedupe
        work_issue(38, "Blocker", state="open", labels=["workflow:ready"], milestone="M"),
        work_issue(39, "Legacy alias", state="open", labels=["workflow:ready"], milestone="M",
                   body="Blocked by: #38\nDepends on: #38"),
        # closed blocker retained as history, not an active blocker
        work_issue(40, "Closed blocker", state="closed", labels=["workflow:done"], milestone="M"),
        work_issue(41, "Blocked by closed", state="open", labels=["workflow:ready"], milestone="M",
                   body="Blocked by: #40"),
        # mutual blocked_by cycle -> drift on both
        work_issue(42, "Cycle A", state="open", labels=["workflow:ready"], milestone="M", body="Blocked by: #43"),
        work_issue(43, "Cycle B", state="open", labels=["workflow:ready"], milestone="M", body="Blocked by: #42"),
    ])
    nodes8, drift8 = a.build_graph({i["number"]: a.issue_from_dict(i) for i in gh8.issues}, REPO_ID)

    check("native/text agreement resolves to a single parent", nodes8[31].parent == 30)
    check("native/text agreement produces no drift", nodes8[31].drift == [])

    check("native/text conflict leaves parent unresolved", nodes8[33].parent is None)
    check("native/text conflict is reported as drift", any("mismatch" in d for d in nodes8[33].drift))

    check("multiple text Part of targets -> drift, no parent", nodes8[34].parent is None)
    check("multiple parents drift mentions both targets", any("multiple immediate Part of" in d for d in nodes8[34].drift))

    check("self-edge Part of rejected", nodes8[35].parent is None)
    check("self-edge reported as drift", any("self-edge" in d for d in nodes8[35].drift))

    check("missing Part of target rejected", nodes8[36].parent is None)
    check("missing target reported as drift", any("does not exist" in d for d in nodes8[36].drift))

    check("cross-repo Part of target rejected", nodes8[37].parent is None)
    check("cross-repo rejection reported as drift", any("cross-repo" in d for d in nodes8[37].drift))

    check("Depends on legacy alias dedupes with Blocked by into one edge", nodes8[39].blocked_by == {38})

    check("closed blocker retained as an edge (history)", 40 in nodes8[41].blocked_by)

    check("mutual blocked_by cycle flagged on both members",
          any("cycle" in d for d in nodes8[42].drift) and any("cycle" in d for d in nodes8[43].drift))

    issues8_dict = {i.number: i for i in (a.issue_from_dict(x) for x in gh8.issues)}
    area_issues8 = [i for i in issues8_dict.values() if not i.is_map]
    auto8 = a.render_area_auto("Test area", "M", area_issues8, issues8_dict, nodes8, 0, "2026-01-01T00:00:00Z")
    check("named references render as title + #number", "Parent (#30)" in auto8)
    check("closed blocker rendered with a history tag, not as an active blocker",
          "Blocked by: Closed blocker (#40) [closed, history]" in auto8)

    # ---------------------------------------------------------------------------
    print("== actionable frontier (AC10) ==")
    gh10 = FakeGh([
        map_issue(500, "Global"),
        work_issue(50, "Ready, unblocked", state="open", labels=["workflow:ready"], milestone="M"),
        work_issue(51, "Ready but blocked", state="open", labels=["workflow:ready"], milestone="M",
                   body="Blocked by: #50"),
        work_issue(52, "Claimed", state="open", labels=["workflow:in-progress"], milestone="M"),
    ])
    a.sync_repo(gh10, REPO_ID, "2026-01-01T00:00:00Z")
    auto10 = a.extract_auto(gh10.updated_bodies[500])
    frontier_section = auto10.split("### Actionable frontier")[1].split("### Milestone overview")[0]
    check("unblocked ready issue is in the frontier", "Ready, unblocked (#50)" in frontier_section)
    check("blocked ready issue is excluded from the frontier", "Ready but blocked (#51)" not in frontier_section)
    check("in-progress issue listed separately as claimed work", "Claimed (#52)" in frontier_section)

    # ---------------------------------------------------------------------------
    print("== review evidence presence/absence (AC11) ==")
    gh11 = FakeGh([
        map_issue(600, "Global"),
        work_issue(60, "Reviewed with evidence", state="open", labels=["workflow:review"], milestone="M",
                   body="Contract fit: AC1-14 verified, see PR #601\nRepository fit: matches AGENTS.md conventions"),
        work_issue(61, "Done without evidence", state="closed", labels=["workflow:done"], milestone="M"),
    ])
    a.sync_repo(gh11, REPO_ID, "2026-01-01T00:00:00Z")
    auto11 = a.extract_auto(gh11.updated_bodies[600])
    check("present evidence rendered, not MISSING",
          "Reviewed with evidence (#60): contract fit = AC1-14 verified, see PR #601; repository fit = matches AGENTS.md conventions" in auto11)
    check("absent evidence rendered as MISSING",
          "Done without evidence (#61): contract fit = MISSING; repository fit = MISSING" in auto11)

    # ---------------------------------------------------------------------------
    print("== safe-content scan for known-bad markers (AC12) ==")
    check("scan_unsafe finds an AWS-style key marker", a.scan_unsafe("key=AKIAABCDEFGHIJKLMNOP") == ["AKIA"])
    check("scan_unsafe finds a private key marker", "PRIVATE KEY" in a.scan_unsafe("-----BEGIN RSA PRIVATE KEY-----"))
    check("scan_unsafe returns nothing for clean text", a.scan_unsafe("Area: Global, all clear.") == [])

    gh12 = FakeGh([
        map_issue(700, "Global"),
        work_issue(70, "Leaked key AKIAABCDEFGHIJKLMNOP", state="open", labels=["workflow:ready"], milestone="M"),
    ])
    report12 = a.sync_repo(gh12, REPO_ID, "2026-01-01T00:00:00Z")
    check("map with unsafe generated content is not written", 700 not in gh12.updated_bodies)
    check("unsafe content reported on the sync report", any(n == 700 for n, _ in report12.unsafe))
    check("map with unsafe content also reported as failed (not silently dropped)",
          any(n == 700 for n, _ in report12.failed))
    check("no comment posted for the unsafe map", not any(c[0] == 700 for c in gh12.comments))

    # ---------------------------------------------------------------------------
    print("== completion/archive where automatable (AC13) ==")
    issues13 = {
        i["number"]: a.issue_from_dict(i)
        for i in [
            work_issue(80, "Done with evidence", state="closed", labels=["workflow:done"], milestone="M",
                       body="Contract fit: verified\nRepository fit: verified"),
        ]
    }
    complete13 = a.compute_completion(list(issues13.values()), map_issue_number=800)
    check("area with only closed, fully-evidenced work is complete", complete13["complete"] is True)

    issues13b = dict(issues13)
    issues13b[81] = a.issue_from_dict(work_issue(81, "Still open", state="open", labels=["workflow:ready"], milestone="M"))
    complete13b = a.compute_completion(list(issues13b.values()), map_issue_number=800)
    check("an open required issue blocks completion", complete13b["complete"] is False)
    check("open issue is listed as the blocking reason", complete13b["open_required"] == [81])

    issues13c = {
        82: a.issue_from_dict(work_issue(82, "Reviewed, missing repo-fit", state="closed",
                                          labels=["workflow:done"], milestone="M", body="Contract fit: verified")),
    }
    complete13c = a.compute_completion(list(issues13c.values()), map_issue_number=800)
    check("missing review evidence blocks completion even when closed", complete13c["complete"] is False)
    check("review gap reported by issue number", complete13c["review_gaps"] == [82])

    check("Atlas sync never closes issues itself (no close/label-mutation call exists on the fake gh)",
          not hasattr(FakeGh, "close_issue"))

    # ---------------------------------------------------------------------------
    print("== failure isolation: one map's exception does not abort the whole sync ==")
    gh_fail = FakeGh([
        map_issue(900, "Global"),
        map_issue(901, "Area B", milestone="M"),
    ])
    orig_render_map_body = a.render_map_body


    def flaky_render_map_body(map_issue_rec, all_issues, nodes, global_drift, self_repo, sync_time_iso):
        if map_issue_rec.number == 901:
            raise RuntimeError("simulated rendering failure for #901")
        return orig_render_map_body(map_issue_rec, all_issues, nodes, global_drift, self_repo, sync_time_iso)


    a.render_map_body = flaky_render_map_body
    try:
        report_fail = a.sync_repo(gh_fail, REPO_ID, "2026-01-01T00:00:00Z")
    finally:
        a.render_map_body = orig_render_map_body

    check("the failing map is recorded in the failed list, not silently dropped",
          any(n == 901 for n, _ in report_fail.failed))
    check("the healthy global map still synced despite the other map's failure", 900 in report_fail.changed)
    check("no update was written for the failing map", 901 not in gh_fail.updated_bodies)

    # ---------------------------------------------------------------------------
    print("== site page emission (issue #285) ==")
    import tempfile
    import json as _json
    from pathlib import Path as _Path

    gh_site = FakeGh([
        map_issue(214, "Global", destination="Global destination.", decisions="ADR-018 accepted.",
                  questions="No open questions."),
        map_issue(215, "MCP lifecycle and dispatch stack", milestone="Open-source product packaging"),
        work_issue(1, "Wire dispatch loop", state="open", labels=["workflow:ready"], milestone="Open-source product packaging"),
        work_issue(2, "Done work", state="closed", labels=["workflow:done"], milestone="Open-source product packaging"),
        work_issue(3, "Blocked issue", state="open", labels=["workflow:blocked"], milestone="M2",
                   body="Blocked by: #1"),
    ])
    site_issues = {i["number"]: a.issue_from_dict(i) for i in gh_site.issues}
    site_nodes, site_drift = a.build_graph(site_issues, REPO_ID)
    site_page = a.render_site_page(site_issues, site_nodes, site_drift, REPO_ID, "2026-01-01T00:00:00Z")
    check("site page has frontmatter title", "title: Status and roadmap (Atlas)" in site_page)
    check("site page lists roadmap areas", "MCP lifecycle and dispatch stack" in site_page)
    check("site page lists the actionable frontier", "Wire dispatch loop (#1)" in site_page)
    check("site page lists milestone overview", "Open-source product packaging: open 1, closed 1" in site_page)
    check("site page renders blockers", "Blocked issue (#3) blocked by Wire dispatch loop (#1)" in site_page)
    check("site page has last-sync timestamp", "Last successful sync" in site_page and "2026-01-01T00:00:00Z" in site_page)

    with tempfile.TemporaryDirectory() as td:
        # out_dir is the repo checkout root (emit writes under site/...).
        out = _Path(td)
        path1, wrote1 = a.emit_site_page(
            out_dir=out, issues=site_issues, nodes=site_nodes,
            global_drift=site_drift, self_repo=REPO_ID, sync_time_iso="2026-01-01T00:00:00Z",
        )
        check("emit writes the page on first run", wrote1 is True)
        check("emit writes to the reserved docs path", path1.as_posix().endswith(a.SITE_PAGE_PATH))
        path2, wrote2 = a.emit_site_page(
            out_dir=out, issues=site_issues, nodes=site_nodes,
            global_drift=site_drift, self_repo=REPO_ID, sync_time_iso="2026-01-01T00:00:00Z",
        )
        check("emit is idempotent at the same timestamp: writes nothing", wrote2 is False)

        # Regression (semantic idempotence): identical issue data at a
        # DIFFERENT timestamp must be a no-op that preserves the artifact
        # already on disk. Before this fix, the sync timestamp was compared
        # verbatim, so every run rewrote (and the workflow re-committed) the
        # page even though nothing about the roadmap had changed.
        before = path1.read_text(encoding="utf-8")
        path3, wrote3 = a.emit_site_page(
            out_dir=out, issues=site_issues, nodes=site_nodes,
            global_drift=site_drift, self_repo=REPO_ID, sync_time_iso="2026-01-02T00:00:00Z",
        )
        check("emit is a no-op when only the sync timestamp advances (identical issue data)", wrote3 is False)
        check("prior page artifact is preserved byte-for-byte (old timestamp retained)",
              path3.read_text(encoding="utf-8") == before)

        # ISO timestamps in issue-owned data remain semantically significant;
        # only the two generated freshness fields may be normalized.
        timestamp_title_issues = dict(site_issues)
        timestamp_title_issues[2] = a.issue_from_dict(
            work_issue(2, "Incident at 2026-01-01T00:00:00Z", state="open",
                       labels=["workflow:ready"], milestone="Open-source product packaging")
        )
        timestamp_title_nodes, timestamp_title_drift = a.build_graph(timestamp_title_issues, REPO_ID)
        _, title_wrote1 = a.emit_site_page(
            out_dir=out, issues=timestamp_title_issues, nodes=timestamp_title_nodes,
            global_drift=timestamp_title_drift, self_repo=REPO_ID,
            sync_time_iso="2026-01-02T00:00:00Z",
        )
        timestamp_title_issues[2] = a.issue_from_dict(
            work_issue(2, "Incident at 2026-01-02T00:00:00Z", state="open",
                       labels=["workflow:ready"], milestone="Open-source product packaging")
        )
        timestamp_title_nodes, timestamp_title_drift = a.build_graph(timestamp_title_issues, REPO_ID)
        _, title_wrote2 = a.emit_site_page(
            out_dir=out, issues=timestamp_title_issues, nodes=timestamp_title_nodes,
            global_drift=timestamp_title_drift, self_repo=REPO_ID,
            sync_time_iso="2026-01-03T00:00:00Z",
        )
        check("site rewrite is not suppressed when an ISO timestamp in an issue title changes",
              title_wrote1 is True and title_wrote2 is True)

        # A real content change (new work issue) DOES trigger a rewrite,
        # even though the timestamp also advances in the same call.
        changed_issues = dict(site_issues)
        changed_issues[9] = a.issue_from_dict(
            work_issue(9, "Newly filed work", state="open", labels=["workflow:ready"],
                       milestone="Open-source product packaging")
        )
        changed_nodes, changed_drift = a.build_graph(changed_issues, REPO_ID)
        path4, wrote4 = a.emit_site_page(
            out_dir=out, issues=changed_issues, nodes=changed_nodes,
            global_drift=changed_drift, self_repo=REPO_ID, sync_time_iso="2026-01-03T00:00:00Z",
        )
        check("emit still rewrites when the underlying issue data actually changes", wrote4 is True)
        check("rewritten page reflects the new timestamp",
              "2026-01-03T00:00:00Z" in path4.read_text(encoding="utf-8"))

        # Safe-content scan: a leak in an issue title must never reach the page.
        gh_leak = FakeGh([
            map_issue(214, "Global"),
            work_issue(71, "Leaked key AKIAABCDEFGHIJKLMNOP", state="open",
                       labels=["workflow:ready"], milestone="M"),
        ])
        leak_issues = {i["number"]: a.issue_from_dict(i) for i in gh_leak.issues}
        leak_nodes, leak_drift = a.build_graph(leak_issues, REPO_ID)
        try:
            a.emit_site_page(out_dir=out, issues=leak_issues, nodes=leak_nodes,
                             global_drift=leak_drift, self_repo=REPO_ID,
                             sync_time_iso="2026-01-01T00:00:00Z")
            check("emit rejects a page containing known-bad markers", False)
        except ValueError:
            check("emit rejects a page containing known-bad markers", True)

    # -----------------------------------------------------------------------
    print("== visual graph emission (issue #300) ==")

    gh_graph = FakeGh([
        map_issue(214, "Global"),
        map_issue(215, "MCP lifecycle and dispatch stack", milestone="Open-source product packaging"),
        work_issue(1, "Wire dispatch loop", state="open", labels=["workflow:ready"],
                   milestone="Open-source product packaging"),
        work_issue(2, "Done work", state="closed", labels=["workflow:done"],
                   milestone="Open-source product packaging"),
        work_issue(3, "Blocked issue", state="open", labels=["workflow:blocked"], milestone="M2",
                   body="Blocked by: #1"),
        work_issue(4, "Child of blocked", state="open", labels=["workflow:in-progress"],
                   milestone="Open-source product packaging", body="Part of: #3"),
    ])
    graph_issues = {i["number"]: a.issue_from_dict(i) for i in gh_graph.issues}
    graph_nodes, graph_drift = a.build_graph(graph_issues, REPO_ID)

    graph_doc = _json.loads(a.render_site_graph(graph_issues, graph_nodes, graph_drift,
                                                REPO_ID, "2026-01-01T00:00:00Z"))
    check("graph doc has schema_version", graph_doc.get("schema_version") == 1)
    check("graph doc has repo + sync_time", graph_doc["repo"] == REPO_ID and "2026-01-01" in graph_doc["sync_time"])
    check("graph nodes carry number/title/state", all(k in graph_doc["nodes"][0] for k in ("number", "title", "state")))
    check("graph node workflow style mapped", {n["number"]: n["workflow"] for n in graph_doc["nodes"]} ==
          {1: "ready", 2: "done", 3: "blocked", 4: "in-progress"})
    check("graph node frontier flag true for ready issue", next(n["frontier"] for n in graph_doc["nodes"] if n["number"] == 1) is True)
    check("graph node in_progress flag true for in-progress issue", next(n["in_progress"] for n in graph_doc["nodes"] if n["number"] == 4) is True)
    check("graph node milestone + area populated", next(n for n in graph_doc["nodes"] if n["number"] == 1)["milestone"] == "Open-source product packaging")
    check("graph node area derived from milestone", next(n for n in graph_doc["nodes"] if n["number"] == 1)["area"] == "MCP lifecycle and dispatch stack")
    check("graph edges include blocked_by", {"from": 1, "to": 3, "kind": "blocked_by"} in graph_doc["edges"])
    check("graph edges include part_of", {"from": 3, "to": 4, "kind": "part_of"} in graph_doc["edges"])
    check("graph lists milestones", "Open-source product packaging" in graph_doc["milestones"])
    check("graph reports frontier count", graph_doc["frontier_count"] == 1)

    with tempfile.TemporaryDirectory() as td:
        out = _Path(td)
        p1, w1 = a.emit_site_graph(out_dir=out, issues=graph_issues, nodes=graph_nodes,
                                   global_drift=graph_drift, self_repo=REPO_ID,
                                   sync_time_iso="2026-01-01T00:00:00Z")
        check("emit graph writes on first run", w1 is True)
        check("emit graph writes to reserved path", p1.as_posix().endswith(a.SITE_GRAPH_PATH))
        p2, w2 = a.emit_site_graph(out_dir=out, issues=graph_issues, nodes=graph_nodes,
                                   global_drift=graph_drift, self_repo=REPO_ID,
                                   sync_time_iso="2026-01-01T00:00:00Z")
        check("emit graph idempotent at same timestamp", w2 is False)

        # Regression (semantic idempotence): identical issue data at a
        # DIFFERENT timestamp must be a no-op that preserves the artifact
        # already on disk (mirrors the site-page regression above).
        before_graph = p1.read_text(encoding="utf-8")
        p3, w3 = a.emit_site_graph(out_dir=out, issues=graph_issues, nodes=graph_nodes,
                                   global_drift=graph_drift, self_repo=REPO_ID,
                                   sync_time_iso="2026-01-02T00:00:00Z")
        check("emit graph is a no-op when only the sync timestamp advances (identical issue data)", w3 is False)
        check("prior graph artifact is preserved byte-for-byte (old sync_time retained)",
              p3.read_text(encoding="utf-8") == before_graph)

        timestamp_graph_issues = dict(graph_issues)
        timestamp_graph_issues[2] = a.issue_from_dict(
            work_issue(2, "Incident at 2026-01-01T00:00:00Z", state="open",
                       labels=["workflow:ready"], milestone="M1")
        )
        timestamp_graph_nodes, timestamp_graph_drift = a.build_graph(timestamp_graph_issues, REPO_ID)
        _, graph_title_wrote1 = a.emit_site_graph(
            out_dir=out, issues=timestamp_graph_issues, nodes=timestamp_graph_nodes,
            global_drift=timestamp_graph_drift, self_repo=REPO_ID,
            sync_time_iso="2026-01-02T00:00:00Z",
        )
        timestamp_graph_issues[2] = a.issue_from_dict(
            work_issue(2, "Incident at 2026-01-02T00:00:00Z", state="open",
                       labels=["workflow:ready"], milestone="M1")
        )
        timestamp_graph_nodes, timestamp_graph_drift = a.build_graph(timestamp_graph_issues, REPO_ID)
        _, graph_title_wrote2 = a.emit_site_graph(
            out_dir=out, issues=timestamp_graph_issues, nodes=timestamp_graph_nodes,
            global_drift=timestamp_graph_drift, self_repo=REPO_ID,
            sync_time_iso="2026-01-03T00:00:00Z",
        )
        check("graph rewrite is not suppressed when an ISO timestamp in an issue title changes",
              graph_title_wrote1 is True and graph_title_wrote2 is True)
        written = _json.loads((out / a.SITE_GRAPH_PATH).read_text(encoding="utf-8"))
        check("emitted graph JSON round-trips", written["schema_version"] == 1)

        # A real content change DOES trigger a rewrite, even though the
        # timestamp also advances in the same call.
        changed_graph_issues = dict(graph_issues)
        changed_graph_issues[9] = a.issue_from_dict(
            work_issue(9, "Newly filed work", state="open", labels=["workflow:ready"],
                       milestone="Open-source product packaging")
        )
        changed_graph_nodes, changed_graph_drift = a.build_graph(changed_graph_issues, REPO_ID)
        p4, w4 = a.emit_site_graph(out_dir=out, issues=changed_graph_issues, nodes=changed_graph_nodes,
                                   global_drift=changed_graph_drift, self_repo=REPO_ID,
                                   sync_time_iso="2026-01-03T00:00:00Z")
        check("emit graph still rewrites when the underlying issue data actually changes", w4 is True)
        rewritten_graph = _json.loads(p4.read_text(encoding="utf-8"))
        check("rewritten graph reflects the new sync_time", rewritten_graph["sync_time"] == "2026-01-03T00:00:00Z")

        # Safe-content scan: a leak in an issue title must never reach the graph.
        try:
            a.emit_site_graph(out_dir=out, issues=leak_issues, nodes=leak_nodes,
                              global_drift=leak_drift, self_repo=REPO_ID,
                              sync_time_iso="2026-01-01T00:00:00Z")
            check("emit graph rejects a leak in an issue title", False)
        except ValueError:
            check("emit graph rejects a leak in an issue title", True)


def test_all_checks_pass():
    """Pytest entry point: run the same checks as the standalone script."""
    run_all_checks()
    assert not fail, f"{len(fail)} check(s) failed: {fail}"


if __name__ == "__main__":
    run_all_checks()
    if fail:
        print(f"\n{len(fail)} check(s) failed: {fail}")
        sys.exit(1)
    print("\nall checks passed")
    sys.exit(0)
