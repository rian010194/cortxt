#!/usr/bin/env python3
"""Offline checks for the event-triggered Atlas sync workflow (#311 C.2, #329).

Run: python scripts/test_atlas_workflow_triggers.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: the atlas-sync workflow declares the issue/issue_comment/pull_request event
triggers in addition to the daily schedule and manual dispatch, the merged-only
guard on pull_request events, the anti-loop actor guard covering bot identities,
and the preserved concurrency group.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "atlas-sync.yml"

try:
    import yaml
except ImportError:
    print("FAIL: pyyaml is required to parse the workflow")
    sys.exit(1)

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)

    # PyYAML (YAML 1.1) parses the `on:` key as boolean True; GitHub Actions
    # (YAML 1.2) treats it as the string "on". Handle both.
    triggers = doc.get("on") or doc.get(True) or {}

    check("workflow file exists", WORKFLOW.is_file())
    check("workflow has a schedule trigger", "schedule" in triggers)
    check("workflow has workflow_dispatch", "workflow_dispatch" in triggers)
    issues = triggers.get("issues", {})
    check("issues trigger declared", isinstance(issues, dict) and "types" in issues)
    expected_types = {"opened", "edited", "labeled", "unlabeled", "closed", "reopened", "transferred"}
    check("issues trigger covers the expected event types",
          set(issues.get("types", [])) == expected_types)
    check("issue_comment trigger declared",
          isinstance(triggers.get("issue_comment"), dict))
    pull_request = triggers.get("pull_request", {})
    check("pull_request trigger declared",
          isinstance(pull_request, dict) and "types" in pull_request)
    check("pull_request trigger covers closed event",
          "closed" in pull_request.get("types", []))

    concurrency = doc.get("concurrency", {})
    check("concurrency group preserved",
          concurrency.get("group") == "atlas-sync")
    check("cancel-in-progress is false",
          concurrency.get("cancel-in-progress") is False)

    jobs = doc.get("jobs", {})
    sync = jobs.get("sync", {})
    if_cond = str(sync.get("if", ""))
    check("anti-loop actor guard covers cortxt-atlas[bot]",
          "cortxt-atlas[bot]" in if_cond)
    check("anti-loop actor guard covers github-actions[bot]",
          "github-actions[bot]" in if_cond)
    check("guard only applies to event triggers",
          "github.event_name" in if_cond)
    check("merged-only guard for pull_request events",
          "github.event.pull_request.merged" in if_cond)

    check("run step still emits site and graph",
          "--emit-site" in text and "--emit-graph" in text)
    check("commit step remains idempotent (unchanged check)",
          "unchanged; nothing to commit" in text)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
