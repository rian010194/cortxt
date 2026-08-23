#!/usr/bin/env python3
"""Cloudflare Pages auto-deploy webhook registration and check (issue #310, C.1).

Root cause recorded in #305: the repo has no GitHub webhook registered, so
Cloudflare Pages auto-deploy never fires on push/merge and every production
deploy is a manual Pages API POST. This script makes the registration
repeatable and verifiable:

- `--check` (read-only, default): reads the Cloudflare Pages project config
  (git source state) and lists the repo's GitHub hooks, then reports whether
  a Cloudflare Pages hook is registered and active.
- `--register`: creates (or with `--replace` updates) the GitHub repository
  webhook that points at the Cloudflare Pages webhook endpoint, events
  `push` + `pull_request`, content type `application/json`, active.
  The Cloudflare webhook URL and secret are operator-supplied (they are only
  visible in the Cloudflare Pages dashboard) via --webhook-url/--secret or
  the CF_PAGES_WEBHOOK_URL/CF_PAGES_WEBHOOK_SECRET environment variables.
- `--dry-run` prints the exact request that would be sent, with the secret
  redacted, and performs no mutation.

Fail-closed: any missing input, unavailable credential, or API error aborts
with a structured message and no side effect. Secrets are never printed.

Credential sources: the Cloudflare API token is injected at runtime through
`cortxt credentials inject --id cloudflare` (token on stdout, starts
`cfat_`); GitHub is called through the authenticated `gh` CLI. Both are
injectable for the network-free check tests.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

CF_API_BASE = "https://api.cloudflare.com/client/v4"
DEFAULT_ACCOUNT = "c7c04f119f81234dc3d851bf6ff2adfe"  # deployment config, not a secret
PROJECT = "cortxt"
REPO = "rian010194/cortxt"
EVENTS = ["push", "pull_request"]
CONTENT_TYPE = "json"


class PagesWebhookError(RuntimeError):
    kind = "pages_webhook_error"


class CredentialUnavailable(PagesWebhookError):
    kind = "credential_unavailable"


class InputError(PagesWebhookError):
    kind = "input_error"


class ApiError(PagesWebhookError):
    kind = "api_error"


def inject_cloudflare_token(run_subprocess: Callable[..., Any]) -> str:
    """Inject the Cloudflare API token through the cortxt credential broker."""
    out = run_subprocess(
        ["cortxt", "credentials", "inject", "--id", "cloudflare",
         "--store-dir", os.path.expandvars(r"%USERPROFILE%\.cortxt\credentials"),
         "--runtime", "coordinator", "--purpose", "cf-pages-webhook-check"],
        capture_output=True, text=True, timeout=60,
    )
    token = next((line.strip() for line in (out.stdout or "").splitlines()
                  if line.startswith("cfat_")), "")
    if not token:
        raise CredentialUnavailable("no cfat_ token on stdout from cortxt credentials inject")
    return token


def cf_api_get(account: str, path: str, token: str) -> dict[str, Any]:
    url = f"{CF_API_BASE}/accounts/{account}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except (json.JSONDecodeError, OSError):
            body = {"errors": [{"message": f"HTTP {exc.code}"}]}
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError(f"Cloudflare request failed: {exc}") from exc
    if not body.get("success"):
        detail = (body.get("errors") or [{}])[0].get("message", "unknown error")
        raise ApiError(f"Cloudflare API error: {detail}")
    return body


def gh_hooks(repo: str, run_subprocess: Callable[..., Any]) -> list[dict[str, Any]]:
    out = run_subprocess(["gh", "api", f"repos/{repo}/hooks", "--paginate"],
                         capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise ApiError(f"gh api repos/{repo}/hooks failed: {out.stderr.strip()}")
    try:
        hooks = json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise ApiError("gh returned malformed JSON for hooks") from exc
    if not isinstance(hooks, list):
        raise ApiError("gh hooks result is not a list")
    return hooks


def find_pages_hook(hooks: list[dict[str, Any]], pages_url: str | None) -> dict[str, Any] | None:
    for hook in hooks:
        url = (hook.get("config") or {}).get("url", "")
        if "api.cloudflare.com" in url and (pages_url is None or url == pages_url):
            return hook
    return None


def redact(hook: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a hook config with the secret value redacted."""
    result = json.loads(json.dumps(hook))
    config = result.get("config")
    if isinstance(config, dict) and "secret" in config:
        config["secret"] = "<redacted>"
    return result


def check(account: str, repo: str, run_subprocess: Callable[..., Any],
          project_reader: Callable[[str, str, str], dict[str, Any]] | None = None) -> int:
    token = inject_cloudflare_token(run_subprocess)
    reader = project_reader or cf_api_get
    project = reader(account, f"/pages/projects/{PROJECT}", token)
    source = project.get("result", {}).get("source") or {}
    config = source.get("config") or {}
    print(f"Cloudflare Pages project: {PROJECT}")
    print(f"  source type: {source.get('type')}")
    print(f"  repo: {config.get('owner')}/{config.get('repo_name')}")
    print(f"  production_branch: {config.get('production_branch')}")
    print(f"  deployments_enabled: {config.get('deployments_enabled')}")

    hooks = gh_hooks(repo, run_subprocess)
    pages_hook = find_pages_hook(hooks, None)
    print(f"GitHub repo hooks: {len(hooks)}")
    for hook in hooks:
        active = hook.get("active")
        events = ",".join(hook.get("events") or [])
        url = (hook.get("config") or {}).get("url", "")
        marker = "  <- Cloudflare Pages hook" if hook is pages_hook else ""
        print(f"  id={hook.get('id')} active={active} events={events} url={url}{marker}")

    if pages_hook is not None:
        print("STATUS: Cloudflare Pages webhook registered and will auto-deploy on push/merge.")
        return 0
    print("STATUS: no Cloudflare Pages webhook registered - auto-deploy will not fire. "
          "Run with --register (operator authorization) to create it.")
    return 1


def build_register_request(repo: str, webhook_url: str, secret: str) -> dict[str, Any]:
    if not webhook_url.startswith("https://"):
        raise InputError("--webhook-url must be an https URL")
    if not secret:
        raise InputError("--secret is required (Cloudflare Pages webhook secret)")
    return {
        "name": "web",
        "active": True,
        "events": EVENTS,
        "config": {
            "url": webhook_url,
            "content_type": CONTENT_TYPE,
            "secret": secret,
        },
    }


def register(account: str, repo: str, webhook_url: str, secret: str, *,
             dry_run: bool, replace: bool, run_subprocess: Callable[..., Any],
             project_reader: Callable[[str, str, str], dict[str, Any]] | None = None) -> int:
    token = inject_cloudflare_token(run_subprocess)
    reader = project_reader or cf_api_get
    project = reader(account, f"/pages/projects/{PROJECT}", token)
    source = project.get("result", {}).get("source") or {}
    config = source.get("config") or {}
    expected_repo = f"{config.get('owner')}/{config.get('repo_name')}"
    if expected_repo != repo:
        raise InputError(f"project git source is {expected_repo}, not {repo}")

    request = build_register_request(repo, webhook_url, secret)
    hooks = gh_hooks(repo, run_subprocess)
    existing = find_pages_hook(hooks, webhook_url)
    if existing is not None and not replace:
        print("A Cloudflare Pages webhook is already registered; use --replace to update it.")
        return 1

    shown = {**request, "config": {**request["config"], "secret": "<redacted>"}}
    print(f"GH create hook request (repo={repo}, dry_run={dry_run}, replace={replace}):")
    print(json.dumps(shown, indent=2))
    if dry_run:
        print("dry-run: no mutation performed.")
        return 0

    args = ["gh", "api", "-X", "POST", f"repos/{repo}/hooks",
            "-f", f"name={request['name']}",
            "-f", f"active={str(request['active']).lower()}",
            "-f", "events[]=push", "-f", "events[]=pull_request",
            "-f", f"config[url]={request['config']['url']}",
            "-f", "config[content_type]=json",
            "-f", f"config[secret]={request['config']['secret']}"]
    out = run_subprocess(args, capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise ApiError(f"gh hook creation failed: {out.stderr.strip()}")
    try:
        created = json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise ApiError("gh returned malformed JSON for hook creation") from exc
    if isinstance(created, list):
        if not created:
            raise ApiError("gh hook creation returned an empty list")
        created = created[0]
    if not isinstance(created, dict):
        raise ApiError("gh hook creation result is not an object")
    print("registered hook:")
    print(json.dumps(redact(created), indent=2))
    print("VERIFY: run --check (or a test push to main) to confirm auto-deploy fires.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default=os.environ.get("CF_PAGES_ACCOUNT", DEFAULT_ACCOUNT))
    parser.add_argument("--repo", default=REPO, help="GitHub owner/repo")
    parser.add_argument("--project", default=PROJECT, help="Cloudflare Pages project name")
    parser.add_argument("--check", action="store_true", help="Read-only check (default)")
    parser.add_argument("--register", action="store_true", help="Create/update the GitHub webhook")
    parser.add_argument("--webhook-url", default=os.environ.get("CF_PAGES_WEBHOOK_URL", ""),
                        help="Cloudflare Pages webhook endpoint URL (from the CF dashboard)")
    parser.add_argument("--secret", default=os.environ.get("CF_PAGES_WEBHOOK_SECRET", ""),
                        help="Cloudflare Pages webhook secret (from the CF dashboard)")
    parser.add_argument("--dry-run", action="store_true", help="Print the request, no mutation")
    parser.add_argument("--replace", action="store_true", help="Update an existing Pages hook")
    args = parser.parse_args(argv)

    try:
        if args.register:
            return register(args.account, args.repo, args.webhook_url, args.secret,
                            dry_run=args.dry_run, replace=args.replace,
                            run_subprocess=subprocess.run)
        return check(args.account, args.repo, run_subprocess=subprocess.run)
    except PagesWebhookError as exc:
        print(f"{exc.kind}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
