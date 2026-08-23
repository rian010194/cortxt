#!/usr/bin/env python3
"""Offline checks for ADR-040 label-invariant enforcement (issue #325).

Run: python scripts/test_label_invariant.py
Prints ok/FAIL lines and exits non-zero on any failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from label_invariant import (  # noqa: E402
    LabelInvariantError,
    check_label_invariant,
    collect_and_check,
    extract_referenced_issues,
    inbox_violation,
    main as label_invariant_main,
    normalize_labels,
)

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def raises(exc_type: type[BaseException], fn: Any) -> bool:
    try:
        fn()
    except exc_type:
        return True
    except Exception:
        return False
    return False


def run_checks() -> None:
    # 1. extract_referenced_issues helper
    check(
        "extract: empty or None body yields empty list",
        extract_referenced_issues("") == [] and extract_referenced_issues(None) == [],
    )
    check(
        "extract: matches Closes, Fixes, Resolves, issue, and Part of case-insensitively",
        extract_referenced_issues(
            "Closes #10\nfixes #11\nRESOLVES #12\nPart of: #13\nPart of #14\nissue #15\nIssue: #16"
        ) == [10, 11, 12, 13, 14, 15, 16],
    )
    check(
        "extract: matches repo-qualified issue reference",
        extract_referenced_issues("Part of: rian010194/cortxt#325") == [325],
    )
    check(
        "extract: deduplicates repeated references in single body",
        extract_referenced_issues("Closes #10, also issue #10 and Part of: #10") == [10],
    )
    check(
        "extract: malformed non-string raises LabelInvariantError",
        raises(LabelInvariantError, lambda: extract_referenced_issues(123)),  # type: ignore[arg-type]
    )

    # 2. normalize_labels helper
    check(
        "normalize_labels: handles strings and dicts with name",
        normalize_labels(["workflow:ready", {"name": "workflow:inbox"}])
        == ["workflow:ready", "workflow:inbox"],
    )
    check(
        "normalize_labels: malformed non-list raises LabelInvariantError",
        raises(LabelInvariantError, lambda: normalize_labels(123)),
    )
    check(
        "normalize_labels: malformed element raises LabelInvariantError",
        raises(LabelInvariantError, lambda: normalize_labels([123])),
    )

    # 3. inbox_violation helper
    check(
        "inbox_violation: open issue with workflow:inbox is True",
        inbox_violation({"state": "open", "labels": ["workflow:inbox"]}) is True,
    )
    check(
        "inbox_violation: uppercase OPEN with workflow:inbox is True",
        inbox_violation({"state": "OPEN", "labels": [{"name": "workflow:inbox"}]}) is True,
    )
    check(
        "inbox_violation: closed issue with workflow:inbox is False",
        inbox_violation({"state": "closed", "labels": ["workflow:inbox"]}) is False,
    )
    check(
        "inbox_violation: open issue with workflow:done is False",
        inbox_violation({"state": "open", "labels": ["workflow:done"]}) is False,
    )
    check(
        "inbox_violation: malformed issue missing state raises LabelInvariantError",
        raises(LabelInvariantError, lambda: inbox_violation({"labels": []})),
    )
    check(
        "inbox_violation: malformed issue missing labels raises LabelInvariantError",
        raises(LabelInvariantError, lambda: inbox_violation({"state": "open"})),
    )

    # 4. Scenario: no violation (issues at ready, done, review, or closed)
    prs_clean = [
        {"number": 101, "body": "Closes #10"},
        {"number": 102, "body": "Part of: #20\nissue #30"},
    ]
    issues_clean = {
        10: {"state": "open", "labels": ["workflow:done"]},
        20: {"state": "open", "labels": ["workflow:ready"]},
        30: {"state": "open", "labels": ["workflow:review"]},
    }
    check(
        "scenario: no violation returns empty list",
        check_label_invariant(prs_clean, issues_clean) == [],
    )

    # 5. Scenario: one violation
    prs_one = [{"number": 201, "body": "Closes #10"}]
    issues_one = {
        10: {"state": "open", "labels": ["workflow:inbox", "area:dispatch"]},
    }
    expected_one = [
        {"issue_number": 10, "pr_number": 201, "workflow": "workflow:inbox"},
    ]
    check(
        "scenario: one violation detected with correct shape",
        check_label_invariant(prs_one, issues_one) == expected_one,
    )

    # 6. Scenario: multiple violations sorted by issue_number
    prs_multi = [
        {"number": 302, "body": "Closes #50"},
        {"number": 301, "body": "Part of: #25\nissue #12"},
    ]
    issues_multi = {
        50: {"state": "open", "labels": ["workflow:inbox"]},
        25: {"state": "open", "labels": ["workflow:inbox"]},
        12: {"state": "open", "labels": ["workflow:inbox"]},
    }
    got_multi = check_label_invariant(prs_multi, issues_multi)
    check(
        "scenario: multiple violations returned sorted by issue_number",
        got_multi == [
            {"issue_number": 12, "pr_number": 301, "workflow": "workflow:inbox"},
            {"issue_number": 25, "pr_number": 301, "workflow": "workflow:inbox"},
            {"issue_number": 50, "pr_number": 302, "workflow": "workflow:inbox"},
        ],
    )

    # 7. Scenario: closed-issue skip
    prs_closed = [{"number": 401, "body": "Closes #40"}]
    issues_closed = {
        40: {"state": "closed", "labels": ["workflow:inbox"]},
    }
    check(
        "scenario: closed issue with workflow:inbox is skipped",
        check_label_invariant(prs_closed, issues_closed) == [],
    )

    # 8. Scenario: no-linked-issue skip
    prs_nolink = [
        {"number": 501, "body": "Pure refactoring with no issue reference."},
        {"number": 502, "body": None},
    ]
    issues_nolink = {
        60: {"state": "open", "labels": ["workflow:inbox"]},
    }
    check(
        "scenario: PR with no linked issue is skipped",
        check_label_invariant(prs_nolink, issues_nolink) == [],
    )

    # 9. Scenario: PR body referencing several issues where only one is inbox
    prs_mixed = [
        {"number": 601, "body": "Closes #71\nPart of: #72\nissue #73"},
    ]
    issues_mixed = {
        71: {"state": "open", "labels": ["workflow:done"]},
        72: {"state": "open", "labels": ["workflow:inbox"]},
        73: {"state": "closed", "labels": ["workflow:inbox"]},
    }
    check(
        "scenario: PR referencing multiple issues reports only the open inbox issue",
        check_label_invariant(prs_mixed, issues_mixed) == [
            {"issue_number": 72, "pr_number": 601, "workflow": "workflow:inbox"},
        ],
    )

    # 10. Scenario: string-keyed issues dict compatibility
    prs_strkeys = [{"number": 701, "body": "Closes #80"}]
    issues_strkeys = {
        "80": {"state": "open", "labels": ["workflow:inbox"]},
    }
    check(
        "scenario: string-keyed issues dict resolves issue number",
        check_label_invariant(prs_strkeys, issues_strkeys) == [
            {"issue_number": 80, "pr_number": 701, "workflow": "workflow:inbox"},
        ],
    )

    # 11. Malformed input fails closed (raises LabelInvariantError)
    check(
        "malformed: non-list merged_prs raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant("not_a_list", {})),  # type: ignore[arg-type]
    )
    check(
        "malformed: non-dict PR item raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant(["not_a_dict"], {})),  # type: ignore[list-item]
    )
    check(
        "malformed: PR missing number raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([{"body": "Closes #1"}], {})),
    )
    check(
        "malformed: PR invalid number type raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([{"number": "one", "body": "Closes #1"}], {})),  # type: ignore[list-item]
    )
    check(
        "malformed: PR boolean number raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([{"number": True, "body": "Closes #1"}], {})),  # type: ignore[list-item]
    )
    check(
        "malformed: PR non-string body raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([{"number": 1, "body": 123}], {})),  # type: ignore[list-item]
    )
    check(
        "malformed: non-dict issues raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([], "not_a_dict")),  # type: ignore[arg-type]
    )
    check(
        "malformed: issue item not a dict raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([], {1: "not_a_dict"})),  # type: ignore[dict-item]
    )
    check(
        "malformed: issue missing state raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([], {1: {"labels": []}})),
    )
    check(
        "malformed: issue state wrong type raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([], {1: {"state": 123, "labels": []}})),  # type: ignore[dict-item]
    )
    check(
        "malformed: issue missing labels raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([], {1: {"state": "open"}})),
    )
    check(
        "malformed: issue labels wrong type raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([], {1: {"state": "open", "labels": 123}})),  # type: ignore[dict-item]
    )
    check(
        "malformed: issue label element wrong type raises LabelInvariantError",
        raises(LabelInvariantError, lambda: check_label_invariant([], {1: {"state": "open", "labels": [123]}})),  # type: ignore[dict-item]
    )

    # 12. Output payload invariant: never includes issue or PR bodies
    violations = check_label_invariant(
        [{"number": 801, "body": "Sensitive PR body with Closes #90"}],
        {90: {"state": "open", "labels": ["workflow:inbox"], "body": "Sensitive issue body"}},
    )
    check(
        "output invariant: violation record contains only issue_number, pr_number, and workflow keys",
        violations == [{"issue_number": 90, "pr_number": 801, "workflow": "workflow:inbox"}],
    )

    # 13. collect_and_check with fake gh runner (network-free)
    fake_prs = json.dumps([
        {"number": 901, "body": "Closes #91"},
        {"number": 902, "body": "Part of: #92"},
    ])
    fake_issue_91 = json.dumps({"state": "open", "labels": ["workflow:inbox"]})
    fake_issue_92 = json.dumps({"state": "open", "labels": ["workflow:ready"]})

    def fake_gh(args: list[str]) -> str:
        if args[0] == "pr" and args[1] == "list":
            return fake_prs
        if args[0] == "api" and "issues/91" in args[1]:
            return fake_issue_91
        if args[0] == "api" and "issues/92" in args[1]:
            return fake_issue_92
        raise RuntimeError(f"unexpected fake_gh command: {args}")

    cli_violations, cli_prs = collect_and_check("test/repo", limit=10, gh_runner=fake_gh)
    check(
        "collect_and_check: correctly fetches and detects violation with fake runner",
        cli_violations == [{"issue_number": 91, "pr_number": 901, "workflow": "workflow:inbox"}]
        and len(cli_prs) == 2,
    )


def test_all_checks_pass() -> None:
    assert main() == 0


def main() -> int:
    run_checks()
    if FAILS:
        print(f"test_label_invariant: FAIL ({len(FAILS)}): {FAILS}")
        return 1
    print("test_label_invariant: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
