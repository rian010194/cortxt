#!/usr/bin/env python3
"""Deterministic, report-only repository governance checks.

The checker never deletes files or mutates GitHub. It intentionally reports
external checks as unavailable when `gh` cannot provide live data.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = (".hermes/", ".trace/", ".kanban/")
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def run(*args: str) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8",
                          errors="replace", capture_output=True, check=False)
    return proc.returncode, proc.stdout.strip()


def tracked() -> list[str]:
    code, out = run("git", "ls-files")
    return out.splitlines() if code == 0 else []


def check_links(files: list[str]) -> list[str]:
    findings: list[str] = []
    for path in files:
        if not path.endswith(".md"):
            continue
        doc = ROOT / path
        text = doc.read_text(encoding="utf-8", errors="replace")
        for target in LINK.findall(text):
            target = target.split("#", 1)[0].strip()
            if not target or re.match(r"(?:https?|mailto):", target):
                continue
            if not (doc.parent / target).resolve().exists():
                findings.append(f"broken-link: {doc.relative_to(ROOT)} -> {target}")
    return findings


def local_findings() -> list[str]:
    files = tracked()
    findings = check_links(files)
    for path in files:
        if path.startswith(RUNTIME_DIRS):
            findings.append(f"tracked-runtime-file: {path}")
        if (path.startswith("schemas/") or path.startswith("contracts/")) and path.endswith((".py", ".ps1", ".sh", ".bat")):
            findings.append(f"executable-under-contracts: {path}")
    code, out = run("git", "ls-files", "--others", "--exclude-standard")
    if code == 0:
        for path in out.splitlines():
            if "/" not in path and "\\" not in path:
                findings.append(f"untracked-root-file: {path}")
    for rel in files:
        if not rel.startswith("docs/") or not rel.endswith(".md"):
            continue
        if rel.startswith("docs/archive/"):
            continue
        doc = ROOT / rel
        head = doc.read_text(encoding="utf-8", errors="replace")[:1200].lower()
        if "status:" not in head or "authority:" not in head:
            findings.append(f"active-doc-metadata: {rel}")
    return findings


def github_findings() -> list[str]:
    findings: list[str] = []
    code, raw = run("gh", "issue", "list", "--repo",
                    "rian010194/ai-workspace-control-plane", "--state", "open",
                    "--limit", "200", "--json", "number,body,projectItems")
    if code:
        return ["github-checks-unavailable: gh issue list failed"]
    for issue in json.loads(raw):
        if not issue["projectItems"]:
            findings.append(f"issue-without-project-item: #{issue['number']}")
        body = (issue.get("body") or "").lower()
        states = [item.get("status", {}).get("name") for item in issue["projectItems"]]
        if "Ready" in states:
            required = ("scope", "acceptance", "worker", "runtime", "cost", "approval")
            missing = [key for key in required if key not in body]
            if missing:
                findings.append(f"ready-incomplete: #{issue['number']} missing {','.join(missing)}")
    return findings


def main() -> int:
    findings = local_findings() + github_findings()
    print(json.dumps({"status": "report-only", "finding_count": len(findings),
                      "findings": findings}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
