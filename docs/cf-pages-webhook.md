# Cloudflare Pages auto-deploy webhook (C.1, issue #310)

Runbook for restoring Cloudflare Pages auto-deploy for the `cortxt` docs
site by registering the GitHub repository webhook that Cloudflare Pages
uses to trigger builds. Root cause recorded in #305: the repo had no
GitHub webhook, so `deployments_enabled: true` on the Pages project never
fired and every production deploy was a manual Pages API POST.

## When to use this

- Verify whether the Pages webhook is registered (read-only, safe to run
  any time).
- Register the webhook so pushes/merges to `main` auto-deploy (a
  production-affecting action; operator authorization required).
- Update the webhook after a secret rotation.

## Prerequisites

- `gh` CLI authenticated with `repo` scope.
- `cortxt` CLI with the `cloudflare` credential injected (the token is
  pulled at runtime via `cortxt credentials inject --id cloudflare`, never
  stored or printed by the script).
- The Cloudflare Pages **webhook URL** and **webhook secret** for the
  `cortxt` project. These are only visible in the Cloudflare dashboard:
  Pages project `cortxt` -> Settings -> Builds & deployments -> Git
  integration (the webhook endpoint and its secret are shown when the
  project is connected to GitHub). They are NOT available through the
  public API, so the operator copies them once and passes them in.

## Read-only check

```bash
python scripts/pages_webhook.py --check
```

Prints the Pages project git-source state (source type, repo,
production_branch, deployments_enabled) and the repo's registered GitHub
hooks, then reports whether a Cloudflare Pages hook is present and active.
Exit 0 when present; exit 1 when missing (no mutation).

## Register (operator-authorized, one-time)

```bash
python scripts/pages_webhook.py --register \
  --webhook-url "https://<pages-webhook-url>" \
  --secret "<pages-webhook-secret>"
```

- Always preview first: add `--dry-run` to print the exact request with the
  secret redacted and perform no mutation.
- The hook is created with events `push` + `pull_request`, content type
  `application/json`, active, pointing at the Pages webhook URL.
- If a Pages hook already exists, add `--replace` to update it.
- The script fails closed on missing credential/URL/secret, a project
  git-source mismatch, or any API error, with no side effect.

## Verify

1. `python scripts/pages_webhook.py --check` reports the hook present and
   active.
2. Push (or merge) to `main`; within a minute Cloudflare Pages should start
   a production deployment of the `cortxt` project automatically. Watch
   https://dash.cloudflare.com -> Pages -> cortxt -> Deployments, or verify
   the site after deploy: `curl -s -o /dev/null -w "%{http_code}" https://docs.cortxt.io/atlas/`.

## Secret rotation

1. Generate a new secret in the Cloudflare dashboard (or reuse a stored one).
2. Re-run `--register --replace` with the new secret.
3. `--check` to confirm the hook is still active.

## Manual-deploy fallback (unchanged)

If the webhook is ever unavailable, the manual path remains:

```bash
cortxt credentials inject --id cloudflare --store-dir "%USERPROFILE%\.cortxt\credentials" \
  --runtime coordinator --purpose cf-pages-deploy-trigger
# POST https://api.cloudflare.com/client/v4/accounts/<ACCOUNT>/pages/projects/cortxt/deployments  body={}
```

Account id for this project: `c7c04f119f81234dc3d851bf6ff2adfe`.

## Boundaries

- The script never prints or persists secrets; the webhook secret is
  redacted in every output.
- Registration is a production-affecting action and is executed by the
  operator after review, per the operator decision in #305 (C.1 = script +
  docs; registration run by the operator).
