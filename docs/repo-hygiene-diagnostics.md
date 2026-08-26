# Repository hygiene diagnostic

`scripts/repo_hygiene_diagnostic.py` is a strictly read-only operator aid. It
does not clean, adopt, merge, push, label, archive, or otherwise mutate any
resource. ADR-039 remains authoritative: ambiguous and unresolved resources
require an operator decision.

The report inventories linked worktrees (including dirty, missing, detached,
and prunable state), local branches (upstream, gone-upstream, ahead/behind,
worktree binding, open PR, and reachability from `refs/remotes/origin/HEAD`),
and stash metadata without reading stash contents. The primary checkout is
derived from Git's common directory so linked-worktree invocation does not
change the reported canonical root.

Optional paths make non-Git inventory explicit:

```powershell
python scripts/repo_hygiene_diagnostic.py --repo <checkout> --json \
  --daemon-claims <state-dir>/claimed.json \
  --lifecycle-store <store.json> \
  --inbox-root <workspace>/lab/inbox
```

An omitted store is `not_configured`; a configured missing store is `absent`.
Malformed or unreadable Git, GitHub, or configured JSON inventory fails closed
with exit code 1. GitHub CLI authentication is therefore required: an unknown
PR inventory is never treated as an empty PR inventory.

Inbox diagnostics count `*/in/*.md`, validate the required frontmatter fields
(`from`, `to`, `type`, `created`, `artifact`, `affects`), validate the message
type, and report whether the referenced artifact exists. Messages are never
moved to `done` automatically.

Run the network-free focused checks with:

```powershell
python scripts/test_repo_hygiene_diagnostic.py
```
