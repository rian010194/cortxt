import json
import random
import subprocess
from types import SimpleNamespace

import pytest

from widget_contract.adapters.github_ports import (
    FIELDS, MAX_ISSUES, BlockerLookupError, GitHubExitError, GitHubJSONError,
    GitHubTimeoutError, GitHubTruncationError, LastGoodCandidates, LastGoodIssues,
    list_all_open_issues, resolve_blocker_status,
)
from widget_contract.candidates import build_candidates_view, render_candidates_tree
from widget_contract.loader import load_widget_file
from widget_contract.registry import READ_OPERATIONS, TYPES
from widget_contract.renderer import render
from widget_contract.validation import ValidationError, validate


def completed(stdout="[]", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def issue(number, workflow="workflow:ready", body="", *, title=None, labels=(), state="OPEN", area=None):
    names = ([workflow] if workflow else []) + list(labels)
    if area:
        names.append(f"Area: {area}")
    return {"number": number, "title": title or f"Issue {number}", "body": body,
            "labels": [{"name": x} for x in names], "state": state,
            "milestone": {"title": "M1"} if number % 2 else None,
            "url": f"https://example.invalid/issues/{number}"}


def group(model, name):
    return next(x for x in model["groups"] if x["id"] == name)


def test_all_open_read_has_required_fields_timeout_and_completeness_bound():
    calls = []
    result = list_all_open_issues("o/r", run_subprocess=lambda *a, **kw: calls.append((a, kw)) or completed())
    command, options = calls[0][0][0], calls[0][1]
    assert result == {"schema_version": 1, "complete": True, "issues": []}
    assert command == ["gh", "issue", "list", "--repo", "o/r", "--state", "open", "--limit", str(MAX_ISSUES), "--json", FIELDS]
    assert options == {"capture_output": True, "text": True, "timeout": 30}
    many = json.dumps([{}] * MAX_ISSUES)
    with pytest.raises(GitHubTruncationError):
        list_all_open_issues("o/r", run_subprocess=lambda *a, **k: completed(many))


@pytest.mark.parametrize(("runner", "error"), [
    (lambda *a, **k: completed(returncode=2, stderr="bad"), GitHubExitError),
    (lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("gh", 1)), GitHubTimeoutError),
    (lambda *a, **k: completed("{"), GitHubJSONError),
])
def test_typed_source_failures(runner, error):
    with pytest.raises(error):
        list_all_open_issues("o/r", run_subprocess=runner)


def test_blocker_lookup_failure_is_typed_and_last_good_remains_visible_with_age():
    with pytest.raises(BlockerLookupError):
        resolve_blocker_status("o/r", 4, run_subprocess=lambda *a, **k: completed(returncode=1, stderr="gone"))
    times = iter([100, 112])
    cache = LastGoodIssues(clock=lambda: next(times))
    assert cache.read("o/r", run_subprocess=lambda *a, **k: completed())["status"] == "fresh"
    stale = cache.read("o/r", run_subprocess=lambda *a, **k: completed(returncode=1, stderr="offline"))
    assert stale["status"] == "stale" and stale["complete"] is False
    assert stale["age_seconds"] == 12 and stale["error"]["kind"] == "nonzero_exit"


def test_candidates_adapter_uses_injected_runner_and_last_good_staleness():
    times = iter([100, 109])
    cache = LastGoodCandidates(clock=lambda: next(times))
    fresh = cache.read("o/r", run_subprocess=lambda *a, **k: completed())
    assert fresh["source"] == {"complete": True, "status": "fresh", "age_seconds": 0, "error": None}
    stale = cache.read("o/r", run_subprocess=lambda *a, **k: completed(returncode=1, stderr="offline"))
    assert stale["source"]["status"] == "stale"
    assert stale["source"]["age_seconds"] == 9
    assert stale["source"]["error"]["kind"] == "nonzero_exit"


def test_frontier_exact_rules_and_closed_or_done_blockers_do_not_block():
    items = [
        issue(1, body="Blocked by: #10\nDepends on: #11"),
        issue(2, labels=("atlas:map",)), issue(3, workflow=None),
        issue(4, labels=("workflow:blocked",)), issue(5, workflow="workflow:in-progress"),
        issue(6, body="Blocked by: #12"),
    ]
    blockers = {10: issue(10, "workflow:blocked", state="CLOSED"),
                11: issue(11, "workflow:done", state="OPEN"),
                12: issue(12, "workflow:blocked", state="OPEN")}
    model = build_candidates_view(items, blocker_statuses=blockers)
    assert [x["number"] for x in group(model, "frontier")["rows"]] == [1]
    row = group(model, "frontier")["rows"][0]
    assert [x["target_status"] for x in row["dependencies"]] == ["closed-history", "done"]
    assert [x["number"] for x in group(model, "blocked")["rows"]] == [6]


def test_relation_aliases_deduplicate_but_report_duplicate_and_name_source():
    model = build_candidates_view([issue(1, body="Blocked by: #2\nDepends on: #2"), issue(2, "workflow:done")])
    row = group(model, "violations")["rows"][0]
    assert row["violations"] == ["duplicate dependency edge"]
    assert row["dependencies"] == [{"relation": "Blocked By", "target": 2, "target_status": "done", "target_title": "Issue 2"}]


def test_drift_is_visible_and_never_repaired():
    items = [
        issue(1, body="Blocked by: #1\nBlocked by: #99", area="A"),
        issue(2, body="Area: B", area="A"),
        issue(3, labels=("workflow:blocked",)),
        issue(4, body="Blocked by: #5"), issue(5, body="Depends on: #4"),
    ]
    model = build_candidates_view(items)
    violations = {r["number"]: r["violations"] for r in group(model, "violations")["rows"]}
    assert "self dependency edge" in violations[1]
    assert "missing dependency target #99" in violations[1]
    assert "ambiguous area" in violations[2]
    assert "workflow label cardinality" in violations[3]
    assert "dependency cycle" in violations[4] and "dependency cycle" in violations[5]


def test_exactly_once_counts_and_order_are_stable_under_shuffle():
    items = [issue(8), issue(2, "workflow:in-progress"), issue(5, labels=("atlas:map",)),
             issue(1, body="Blocked by: #8"), issue(3, workflow="workflow:inbox")]
    golden = build_candidates_view(items)
    random.Random(42).shuffle(items)
    shuffled = build_candidates_view(items)
    assert shuffled == golden
    numbers = [r["number"] for g in golden["groups"] for r in g["rows"]]
    assert len(numbers) == len(set(numbers)) == golden["total"] == sum(g["count"] for g in golden["groups"])


def test_rows_browser_cli_equivalence_frontier_first_and_zero_golden():
    model = build_candidates_view([issue(2, "workflow:inbox"), issue(1)])
    assert [g["id"] for g in model["groups"]][:2] == ["frontier", "in_progress"]
    tree = render_candidates_tree(model)
    assert [(c["props"]["label"], len(c["props"]["rows"])) for c in tree["children"]] == [(g["id"], g["count"]) for g in model["groups"]]
    assert json.loads(json.dumps(model)) == model
    zero = build_candidates_view([])
    assert zero["total"] == 0 and all(g["count"] == 0 for g in zero["groups"])


def test_spec_loads_and_handoffs_are_disabled_without_callbacks():
    from pathlib import Path
    spec = Path(__file__).parents[2] / "widget_contract" / "specs" / "candidates-0.1.yaml"
    widget = load_widget_file(spec)
    assert widget.id == "candidates" and len(widget.actions) == 2
    assert {a.id for a in widget.actions} == {"mark-ready", "claim-run"}
    model = build_candidates_view([])
    assert all(x == {**x, "enabled": False} and "callback" not in x for x in model["handoffs"])


def test_candidates_type_and_read_are_registered_and_strict():
    model = build_candidates_view([issue(1)])
    validate(model, TYPES["candidates.view.v1"].schema)
    operation = READ_OPERATIONS["candidates.view.v1"]
    assert (operation.source, operation.output_type, operation.capability) == (
        "github", "candidates.view.v1", "read:issues")
    malformed = {**model, "total": "one"}
    with pytest.raises(ValidationError, match="expected integer"):
        validate(malformed, TYPES["candidates.view.v1"].schema)


@pytest.mark.parametrize(("status", "expected"), [("fresh", "ready"), ("stale", "stale"), ("error", "error")])
def test_contract_renderer_frontier_first_and_source_states(status, expected):
    from pathlib import Path
    widget = load_widget_file(Path(__file__).parents[2] / "widget_contract" / "specs" / "candidates-0.1.yaml")
    error = {"kind": "offline", "message": "unavailable"} if status != "fresh" else None
    model = build_candidates_view([issue(1)], complete=status == "fresh", status=status, error=error)
    tree = render(widget, {"candidates": model}, {"candidates": status})
    assert tree["render"]["children"][0]["props"]["value"] == model["source"]
    tables = [node for node in tree["render"]["children"] if node["primitive"] == "table"]
    assert tables[0]["props"]["label"] == "frontier"
    assert tables[0]["props"]["rows"][0]["number"] == 1
    assert tables[0]["state"] == expected


def test_cli_visual_path_atomically_writes_contract_artifact(monkeypatch, capsys, tmp_path):
    from argparse import Namespace
    from cli.unified_cli import _run_widget
    from widget_contract.adapters import github_ports
    monkeypatch.setattr(github_ports, "list_all_open_issues", lambda repo: {
        "schema_version": 1, "complete": True, "issues": [issue(1)]})
    monkeypatch.setattr(github_ports, "resolve_blocker_status", lambda repo, number: pytest.fail("unexpected lookup"))
    target = tmp_path / "candidates.json"
    result = _run_widget(Namespace(widget_command=None, view="candidates", repo="o/r", snapshot=target))
    capsys.readouterr()
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert result.status == "succeeded"
    assert artifact["widget"] == {"id": "candidates", "version": "0.1"}
    assert artifact["render"]["primitive"] == "stack"
    assert artifact["repo"] == "o/r"
    assert artifact["handoffs"] == [
        {"id": "mark-ready", "operation": "workflow.mark-ready.v1", "port": "github-transition",
         "effect_class": "workflow-transition", "authorization": {"mode": "operator", "reference": "operator-approval"},
         "confirm": {"summary": "Move the issue from workflow:inbox to workflow:ready",
                     "effect_class": "workflow-transition", "required": True},
         "enabled": True, "reason": "Operator-authorized action: approval reference + confirm required"},
        {"id": "claim-run", "operation": "workflow.claim-run.v1", "port": "cli",
         "effect_class": "run-dispatch", "authorization": {"mode": "operator", "reference": "operator-approval"},
         "confirm": {"summary": "Claim and run the issue through the execution map",
                     "effect_class": "run-dispatch", "required": True},
         "enabled": True, "reason": "Operator-authorized action: approval reference + confirm required"},
    ]


def test_widget_renders_open_in_cli_handoff_controls_without_post():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[2] / "widget" / "index.html").read_text(encoding="utf-8")
    assert "Open in CLI" in html
    assert "copyCommand" in html
    assert "candidate-chain" in html
    assert "cortxt widget action" in html
    assert "do_POST" not in html


def test_cli_json_and_visual_paths_use_the_same_model(monkeypatch, capsys):
    from argparse import Namespace
    from cli.unified_cli import _run_widget
    from widget_contract.adapters import github_ports
    items = [issue(1), issue(2, "workflow:inbox")]
    monkeypatch.setattr(github_ports, "list_all_open_issues", lambda repo: {"schema_version": 1, "complete": True, "issues": items})
    monkeypatch.setattr(github_ports, "resolve_blocker_status", lambda repo, number: pytest.fail("unexpected lookup"))
    result = _run_widget(Namespace(widget_command="candidates", view=None, repo="o/r", format="json"))
    cli_model = json.loads(capsys.readouterr().out)
    assert result.status == "succeeded" and cli_model == result.evidence[0]["candidates"]
    result = _run_widget(Namespace(widget_command=None, view="candidates", repo="o/r"))
    visual = json.loads(capsys.readouterr().out)
    assert result.evidence[0]["candidates"] == cli_model
    assert [len(x["props"]["rows"]) for x in visual["children"]] == [g["count"] for g in cli_model["groups"]]
