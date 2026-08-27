# Parallel work launcher

`cortxt work` is the local, automation, bootstrap, diagnostic, and
power-user surface for creating and observing multiple contract-backed
worker runs (ADR-015/021, ADR-042). GitHub Issues remain the scope and
workflow source of truth; the local run registry is only an execution
ledger.

Use `cortxt work new scope.md --repo owner/repo --approve --max-cost-usd N`.
The approval flag is an explicit operator gate. The command creates an inbox
issue, transitions it to ready, claims it through `Dispatcher`, creates an
isolated worktree, generates a bounded worker handoff, and starts the configured
adapter asynchronously. It prints the generated run id.

`cortxt work list` reads active runs. `cortxt work resume` creates a fresh run
identity for a ready issue; retry never overwrites an earlier attempt. `cortxt
work submit` records a terminal result and moves the issue to independent
review. No launcher command approves, merges, closes, or cleans a worktree.

The worker handoff contains only approved scope, acceptance criteria, dispatch
limits, and artifact policy. Inputs containing prohibited diacritics are
rejected. Secrets, raw runtime output, full prompts, and model reasoning must
not be placed in durable artifacts.

The MCP equivalents are `cortxt_run_create`, `cortxt_run_resume`, and
`cortxt_run_submit_for_review`. They are Tier 1 tools and inherit mandate
verification in `call_tool`; handlers receive binding fields only from the
verified envelope. The MCP server does not hold a private signing key and does
not write GitHub state.

## Parallel builder isolation (required for every parallel dispatch)

Parallel subagent builders must never write into the same working tree:
switching branches in one shared checkout does NOT isolate builds -- two
builders writing at the same time land in the same working tree regardless
of branch (2026-08-22 incident: issues #252 and #253 both wrote into main's
working tree). The mechanical fix is one **isolated linked git worktree**
per parallel build via `scripts/parallel_dispatch.py` (issue #257):

```bash
# 1. One isolated worktree per branch (from a clean repo checkout)
python scripts/parallel_dispatch.py prepare <repo> <branch> <base>
#    -> prints <repo-parent>/<repo-name>-worktrees/<branch-slug>

# 2. Dispatch each subagent with: "your working directory is <worktree>;
#    verify `git -C <worktree> branch --show-current` == <branch> and
#    `git -C <worktree> status --porcelain` is clean; write ONLY under
#    <worktree>; never run git-write commands."

# 3. After each build: verify, then commit in the worktree
python scripts/parallel_dispatch.py verify <worktree> <branch>
python scripts/parallel_dispatch.py commit <worktree> "feat: ..."

# 4. After merge: cleanup
python scripts/parallel_dispatch.py cleanup <repo> <branch>
```

`verify` fails loudly on a wrong branch or a dirty tree; `commit` refuses
an empty tree and signs with `-s` (DCO). This gives every parallel build
physical isolation -- two builders cannot collide, and the coordinator
verifies and commits per worktree. The check-style tests
(`scripts/test_parallel_dispatch.py`) cover all four commands with a fake
runner; run them with `python scripts/test_parallel_dispatch.py`.
