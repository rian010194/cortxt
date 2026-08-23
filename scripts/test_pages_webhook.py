#!/usr/bin/env python3
"""Offline checks for the Cloudflare Pages webhook helper (#310, C.1).

Run: python scripts/test_pages_webhook.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers: dry-run request construction (correct events/content-type, secret
never printed), fail-closed input/credential handling, check-mode hook
detection and redaction, and the no-secret-in-output invariant.
"""
from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pages_webhook as pw  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def proc(stdout="[]", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def make_runner(calls, hooks_response="[]", hook_create=None, token="cfat_testtoken"):
    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "cortxt":
            return proc(stdout=f"{token}\n")
        if argv[0] == "gh" and any("hooks" in part for part in argv) and "--paginate" in argv:
            return proc(stdout=hooks_response)
        if argv[0] == "gh" and hook_create is not None and any("hooks" in part for part in argv):
            return proc(stdout=json.dumps(hook_create))
        return proc(returncode=1, stderr="unexpected")
    return runner


def main() -> int:
    # 1. Dry-run builds the correct request and never prints the secret.
    calls = []
    webhook_url = "https://api.cloudflare.com/client/v4/accounts/a1/pages/webhooks/deploy_hook"
    secret = "super-secret-value"
    created = {"id": 42, "active": True, "events": ["push", "pull_request"],
               "config": {"url": webhook_url, "content_type": "json", "secret": secret}}
    runner = make_runner(calls, hooks_response="[]", hook_create=created)
    project_reader = lambda account, path, token: {"success": True, "result": {
        "source": {"type": "github", "config": {"owner": "o", "repo_name": "r"}}}}
    rc = pw.register("acc", "o/r", webhook_url, secret, dry_run=True, replace=False,
                     run_subprocess=runner, project_reader=project_reader)
    check("dry-run register exits 0", rc == 0)
    out = "\n".join(calls and [str(c) for c in calls] or [])
    check("secret never appears in output", secret not in out)

    # 2. Real (non-dry-run) register calls gh with events push+pull_request.
    calls = []
    runner = make_runner(calls, hooks_response="[]", hook_create=created)
    project_reader = lambda account, path, token: {"success": True, "result": {
        "source": {"type": "github", "config": {"owner": "o", "repo_name": "r"}}}}
    rc = pw.register("acc", "o/r", webhook_url, secret, dry_run=False, replace=False,
                     run_subprocess=runner, project_reader=project_reader)
    check("register succeeds", rc == 0)
    gh_call = next(a for a in calls if a[0] == "gh" and "POST" in a)
    joined = " ".join(gh_call)
    check("register uses events push and pull_request",
          "events[]=push" in joined and "events[]=pull_request" in joined)
    check("register uses content type json", "config[content_type]=json" in joined)

    # 3. Fail-closed: missing secret.
    try:
        pw.build_register_request("o/r", webhook_url, "")
        check("missing secret fails closed", False)
    except pw.InputError:
        check("missing secret fails closed", True)

    # 4. Check mode detects an existing Pages hook and redacts its secret.
    calls = []
    hooks = json.dumps([{"id": 7, "active": True, "events": ["push", "pull_request"],
                         "config": {"url": "https://api.cloudflare.com/client/v4/accounts/a1/pages/webhooks/deploy_hook",
                                    "secret": "hook-secret-xyz"}}])
    runner = make_runner(calls, hooks_response=hooks)
    project_reader = lambda account, path, token: {"success": True, "result": {
        "source": {"type": "github", "config": {"owner": "o", "repo_name": "r",
                                                "production_branch": "main",
                                                "deployments_enabled": True}}}}
    rc = pw.check("acc", "o/r", run_subprocess=runner, project_reader=project_reader)
    check("check exits 0 when Pages hook present", rc == 0)
    out = "\n".join(str(c) for c in calls)
    check("hook secret never appears in check output", "hook-secret-xyz" not in out)

    # 5. Redaction invariant.
    redacted = pw.redact({"config": {"secret": "abc", "url": "https://x"}})
    check("redact masks the secret value", redacted["config"]["secret"] == "<redacted>")
    check("redact keeps the url", redacted["config"]["url"] == "https://x")

    # 6. Credential unavailable fails closed.
    def no_token(argv, **kwargs):
        return proc(stdout="no token here\n")
    try:
        pw.inject_cloudflare_token(no_token)
        check("missing credential fails closed", False)
    except pw.CredentialUnavailable:
        check("missing credential fails closed", True)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
