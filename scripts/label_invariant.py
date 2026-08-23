#!/usr/bin/env python3
"""ADR-040 label-invariant enforcement (issue #325).

Enforces the invariant that an open issue whose delivery PR has merged
must never remain at `workflow:inbox`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence

# Pattern to extract referenced issue numbers from PR bodies.
# Matches "Closes #123", "Closes: #123", "issue #123", "Part of: #123", "Fixes #123", etc.
ISSUE_REF_PATTERN = re.compile(
    r"(?i)\b(?:closes?|closed|fixes?|fixed|resolves?|resolved|issues?|part\s+of):?\s*(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#\s*([0-9]+)"
)


class LabelInvariantError(ValueError):
    """Raised when input data to label invariant checks is malformed."""


def extract_referenced_issues(body: str | None) -> list[int]:
    """Extract referenced issue numbers from PR body text deterministically.

    Returns a deduplicated list of issue numbers in order of appearance.
    """
    if body is None:
        return []
    if not isinstance(body, str):
        raise LabelInvariantError("PR body must be a string or None")

    matches = ISSUE_REF_PATTERN.findall(body)
    seen: set[int] = set()
    result: list[int] = []
    for match in matches:
        num = int(match)
        if num not in seen:
            seen.add(num)
            result.append(num)
    return result


def normalize_labels(labels: Any) -> list[str]:
    """Normalize labels into a list of label name strings."""
    if not isinstance(labels, (list, tuple, set)):
        raise LabelInvariantError("labels must be a list, tuple, or set")
    normalized: list[str] = []
    for label in labels:
        if isinstance(label, str):
            normalized.append(label)
        elif isinstance(label, Mapping) and "name" in label and isinstance(label["name"], str):
            normalized.append(label["name"])
        else:
            raise LabelInvariantError(f"invalid label item: {label!r}")
    return normalized


def inbox_violation(issue: Mapping[str, Any]) -> bool:
    """Return True if an issue is open and still at workflow:inbox."""
    if not isinstance(issue, Mapping):
        raise LabelInvariantError("issue must be a dict or mapping")
    if "state" not in issue:
        raise LabelInvariantError("issue missing 'state'")
    if not isinstance(issue["state"], str):
        raise LabelInvariantError("issue 'state' must be a string")
    if "labels" not in issue:
        raise LabelInvariantError("issue missing 'labels'")

    state = issue["state"].strip().lower()
    labels = normalize_labels(issue["labels"])
    return state == "open" and "workflow:inbox" in labels


def check_label_invariant(
    merged_prs: Sequence[Mapping[str, Any]],
    issues: Mapping[Any, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Check merged PRs and referenced issues for ADR-040 label invariant violations.

    An invariant violation occurs when an open issue referenced by a merged PR
    remains labeled with `workflow:inbox`.

    Returns a list of violations sorted by issue_number:
    [{"issue_number": int, "pr_number": int, "workflow": "workflow:inbox"}]

    Never includes issue bodies or PR bodies in the output.
    Closed issues and PRs with no referenced issues are skipped.
    """
    if not isinstance(merged_prs, (list, tuple)):
        raise LabelInvariantError("merged_prs must be a list or tuple")
    if not isinstance(issues, Mapping):
        raise LabelInvariantError("issues must be a dict or mapping")

    # Pre-validate issues dictionary entries
    for k, v in issues.items():
        if not isinstance(v, Mapping):
            raise LabelInvariantError(f"issue {k!r} data must be a dict or mapping")
        if "state" not in v or not isinstance(v["state"], str):
            raise LabelInvariantError(f"issue {k!r} must contain string 'state'")
        if "labels" not in v:
            raise LabelInvariantError(f"issue {k!r} must contain 'labels'")
        normalize_labels(v["labels"])

    violations: list[dict[str, Any]] = []

    for pr in merged_prs:
        if not isinstance(pr, Mapping):
            raise LabelInvariantError("each PR must be a dict or mapping")
        if "number" not in pr or "body" not in pr:
            raise LabelInvariantError("PR dict must contain 'number' and 'body'")
        pr_number = pr["number"]
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            raise LabelInvariantError("PR 'number' must be a positive integer")

        pr_body = pr["body"]
        if pr_body is not None and not isinstance(pr_body, str):
            raise LabelInvariantError("PR 'body' must be a string or None")

        referenced_issues = extract_referenced_issues(pr_body)
        if not referenced_issues:
            continue

        for issue_num in referenced_issues:
            issue_data = issues.get(issue_num)
            if issue_data is None:
                issue_data = issues.get(str(issue_num))
            if issue_data is None:
                continue

            if inbox_violation(issue_data):
                violations.append({
                    "issue_number": int(issue_num),
                    "pr_number": int(pr_number),
                    "workflow": "workflow:inbox",
                })

    violations.sort(key=lambda item: (item["issue_number"], item["pr_number"]))
    return violations


def default_gh_runner(args: list[str]) -> str:
    """Execute a gh CLI command and return its stdout."""
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"gh command failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def collect_and_check(
    repo: str,
    limit: int = 50,
    gh_runner: Callable[[list[str]], str] = default_gh_runner,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch merged PRs and referenced issues via gh runner, then check label invariant.

    Returns (violations, merged_prs).
    """
    prs_raw = gh_runner([
        "pr", "list", "--repo", repo, "--state", "merged",
        "--limit", str(limit), "--json", "number,body",
    ])
    merged_prs = json.loads(prs_raw)
    if not isinstance(merged_prs, list):
        raise LabelInvariantError("gh pr list did not return a list")

    referenced: set[int] = set()
    for pr in merged_prs:
        if isinstance(pr, Mapping):
            referenced.update(extract_referenced_issues(pr.get("body")))

    issues: dict[int, dict[str, Any]] = {}
    for issue_num in sorted(referenced):
        try:
            issue_raw = gh_runner([
                "api", f"repos/{repo}/issues/{issue_num}",
                "--jq", "{state: .state, labels: [.labels[].name]}",
            ])
            issues[issue_num] = json.loads(issue_raw)
        except Exception as exc:
            sys.stderr.write(f"warning: failed to fetch issue #{issue_num}: {exc}\n")

    violations = check_label_invariant(merged_prs, issues)
    return violations, merged_prs


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for label invariant check."""
    parser = argparse.ArgumentParser(description="Enforce ADR-040 label invariant on merged PRs.")
    parser.add_argument(
        "--repo",
        default="",
        help="GitHub repository (owner/repo). Defaults to GITHUB_REPOSITORY env var.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of merged PRs to check (default: 50).",
    )
    args = parser.parse_args(argv)

    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        sys.stderr.write("error: --repo or GITHUB_REPOSITORY environment variable is required\n")
        return 2

    try:
        violations, _ = collect_and_check(repo, limit=args.limit)
    except Exception as exc:
        sys.stderr.write(f"error: failed to check label invariant: {exc}\n")
        return 1

    if violations:
        sys.stderr.write(f"FAIL: {len(violations)} label invariant violation(s) found:\n")
        for v in violations:
            sys.stderr.write(
                f"  - Issue #{v['issue_number']} is open with label '{v['workflow']}' but referenced by merged PR #{v['pr_number']}\n"
            )
        return 1

    print("label invariant OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
