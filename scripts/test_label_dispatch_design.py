#!/usr/bin/env python3
"""Offline checks for the label to dispatch design and notice scaffold (#330).

Run: python scripts/test_label_dispatch_design.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. The design doc exists at docs/architecture/label-dispatch.md and contains
   the required markers (purpose, trigger, gate sequence, execution-map gate,
   operator approval, no auto-claim, execution path, idempotency, "what this does
   NOT do" section, cortxt work resume, cortxt work plan).
2. The scaffold workflow YAML parses, declares the labeled trigger with the
   workflow:ready label condition, includes the actor guard, verifies the
   dedupe marker before commenting, posts a comment only (no label/claim/dispatch
   mutation), and preserves the concurrency group.
3. Zero a/o/u-with-diacritics in tracked doc, workflow, and test files; no secret
   or prompt markers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "architecture" / "label-dispatch.md"
WORKFLOW = REPO / ".github" / "workflows" / "label-dispatch-notice.yml"

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
    # --- 1. Design doc verification ---
    check("design doc exists at docs/architecture/label-dispatch.md", DOC.is_file())
    doc_text = DOC.read_text(encoding="utf-8") if DOC.is_file() else ""

    required_markers = [
        "## Purpose",
        "## Trigger",
        "workflow:ready",
        "## Gate sequence",
        "Execution-Map Pre-flight Gate",
        "ADR-039",
        "cortxt work plan",
        "Mandatory Operator Approval Gate",
        "NO auto-claim",
        "NO auto-run",
        "## Execution path",
        "cortxt work resume",
        "## Idempotency and replay handling",
        "#328",
        "## What this does NOT do",
        "<!-- cortxt-dispatch-notice -->",
    ]
    for marker in required_markers:
        check(f"doc contains {marker!r}", marker in doc_text)

    normalized_doc = " ".join(doc_text.split())
    check("doc specifies design record status",
          "design record" in doc_text.lower() and "proposed" in doc_text.lower())
    check("doc states operator approval is mandatory",
          "operator approval remains mandatory" in doc_text.lower()
          or "operator approval is always required" in doc_text.lower())
    check("doc states graph/label state alone never grants dispatch authority",
          "never grant dispatch authority" in normalized_doc.lower()
          or "never grants dispatch authority" in normalized_doc.lower())

    # --- 2. Workflow verification ---
    check("scaffold workflow exists at .github/workflows/label-dispatch-notice.yml",
          WORKFLOW.is_file())
    wf_text = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""

    try:
        doc = yaml.safe_load(wf_text)
    except Exception as exc:
        check(f"workflow YAML parses cleanly: {exc}", False)
        doc = None

    if doc is not None:
        check("workflow YAML parsed successfully", True)
        triggers = doc.get("on") or doc.get(True) or {}
        check("issues trigger declared", "issues" in triggers)
        issues_cfg = triggers.get("issues", {})
        check("issues trigger covers labeled action",
              isinstance(issues_cfg, dict) and "labeled" in issues_cfg.get("types", []))

        concurrency = doc.get("concurrency", {})
        check("concurrency group label-dispatch-notice",
              concurrency.get("group") == "label-dispatch-notice")
        check("cancel-in-progress is false",
              concurrency.get("cancel-in-progress") is False)

        permissions = doc.get("permissions", {})
        check("permissions declare contents read and issues write",
              permissions.get("contents") == "read" and permissions.get("issues") == "write")

        jobs = doc.get("jobs", {})
        notice_job = jobs.get("notice", {})
        if_cond = str(notice_job.get("if", ""))
        check("job condition filters for workflow:ready label",
              "workflow:ready" in if_cond)
        check("actor guard excludes github-actions[bot]",
              "github-actions[bot]" in if_cond)
        check("actor guard excludes cortxt-atlas[bot]",
              "cortxt-atlas[bot]" in if_cond)

        check("workflow checks dedupe marker before commenting",
              "<!-- cortxt-dispatch-notice -->" in wf_text and "COMMENTS" in wf_text)
        check("workflow posts notice comment via gh api",
              "gh api -X POST" in wf_text and "/comments" in wf_text)

        # Non-mutating assertions: workflow should not execute mutations
        forbidden_mutations = [
            "gh issue edit",
            "issue edit",
            "git push",
            "git commit",
            "gh pr merge",
            "gh pr close",
            "gh issue close",
            "python scripts/dispatcher.py",
        ]
        for forbidden in forbidden_mutations:
            check(f"workflow contains no mutation command: {forbidden!r}",
                  forbidden not in wf_text)

    # --- 3. Diacritics and secret hygiene ---
    test_path = Path(__file__).resolve()
    test_text = test_path.read_text(encoding="utf-8") if test_path.is_file() else ""
    secret_patterns = ["-----" + "BEGIN", "s" + "k-", "cfa" + "t_", "pro" + "mpt:"]

    for name, content in [
        ("docs/architecture/label-dispatch.md", doc_text),
        (".github/workflows/label-dispatch-notice.yml", wf_text),
        ("scripts/test_label_dispatch_design.py", test_text),
    ]:
        diacritics = re.findall(r"[\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]", content)
        check(f"zero a/o/u-with-diacritics in {name}", not diacritics)
        for secret_marker in secret_patterns:
            check(f"no secret/prompt marker {secret_marker!r} in {name}",
                  secret_marker not in content)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
