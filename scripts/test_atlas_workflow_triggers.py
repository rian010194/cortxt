#!/usr/bin/env python3
"""Offline checks for the event-triggered Atlas sync workflow (#311 C.2, #329)
and its PR-governed publish path.

Run: python scripts/test_atlas_workflow_triggers.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: the atlas-sync workflow declares the issue/issue_comment/pull_request event
triggers in addition to the daily schedule and manual dispatch, the merged-only
guard on pull_request events, the anti-loop actor guard covering bot identities,
the preserved concurrency group, and PR governance for the site page/graph
publish step -- no credential persistence on checkout, a GitHub App
installation token (never GITHUB_TOKEN) used for the bot branch push and PR,
a fail-safe error when that token is unavailable, force-with-lease scoped to
the bot branch only, an unexpected-changed-path guard, and no auto merge/
approve/close of the publish PR.
"""
from __future__ import annotations

import re
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
    check("publish step remains idempotent (unchanged check before touching git)",
          "changed=false" in text and "git diff --quiet" in text)

    # --- PR governance: bot branch + GitHub App token, never GITHUB_TOKEN ---
    check("checkout does not persist credentials",
          "persist-credentials: false" in text)
    check("permissions no longer grant contents: write to the default token",
          "contents: read" in text and "contents: write" not in text)
    check("a GitHub App installation token is minted for the publish step",
          "create-github-app-token" in text)
    check("app token step reads dedicated App secrets (not GITHUB_TOKEN)",
          "secrets.ATLAS_BOT_APP_ID" in text and "secrets.ATLAS_BOT_APP_PRIVATE_KEY" in text)
    check("app-token minting failure does not fail the job outright (continue-on-error)",
          "continue-on-error: true" in text)
    check("job fails loudly with a clear error when the app token is unavailable",
          "app-token.outcome != 'success'" in text and "::error::Atlas publish refused" in text)
    check("app token is used for the bot push (never the default GITHUB_TOKEN)",
          "x-access-token:${ATLAS_BOT_TOKEN}" in text)
    check("app token is used for gh pr list/create (never the default GITHUB_TOKEN)",
          'GH_TOKEN="$ATLAS_BOT_TOKEN" gh pr' in text)

    check("push targets a stable, named bot branch",
          "BOT_BRANCH: atlas-sync/bot-updates" in text)
    code_lines = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    bare_force = re.search(r"--force(?!-with-lease)\b", code_lines)
    check("push uses force-with-lease, never a plain --force",
          "--force-with-lease" in text and bare_force is None)
    check("the PR flow reuses an existing open PR instead of always creating one",
          "gh pr list" in text and "gh pr create" in text)
    check("no auto-merge of the publish PR",
          "gh pr merge" not in text and "--auto-merge" not in text and "--admin" not in text)
    check("no auto-approve of the publish PR",
          "gh pr review" not in text and "--approve" not in text)
    check("no auto-close of the publish PR",
          "gh pr close" not in text)
    check("unexpected-changed-path allowlist guard is present before committing",
          "Unexpected changed paths outside the Atlas publish allowlist" in text)
    check("allowlist guard scopes exclusions to the two publish artifacts",
          ":!site/src/content/docs/docs/atlas-status.md" in text
          and ":!site/public/atlas/graph.json" in text)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
