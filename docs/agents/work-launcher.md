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

## Working-directory isolation

Isolation is decided on the server, from the approved mandate, and the launch
result reports what actually happened:

| Path | Isolation | Reported |
| --- | --- | --- |
| `cortxt work new` / `WorkLauncher.create` | always one linked git worktree plus a `work/<run_id>` branch | `isolation: "worktree"`, real `branch` and `worktree` |
| Work app launch (`workflow.claim-run.v1` -> `gh_claim_run_resume`) | `dispatch.request.v1`'s `isolation` field, derived from the approved `## Artifact policy` | whichever it derived |
| `cortxt work resume` | `--isolate` (default off; the CLI is the local/power-user surface) | whichever was asked for |

`isolation` is a field of the immutable dispatch request, so it is covered by
`request_id`: the browser supplies nothing that can choose it, a tampered
value changes the digest and the confirmation is rejected as stale, and the
confirmation view can show the operator which isolation they are approving.

It **fails closed**. `isolation_for_artifact_policy` returns `worktree` for
every policy -- including the default one and an issue with no artifact-policy
section at all -- and returns `shared-checkout` only when the approved policy
explicitly waives isolation ("shared checkout", "no isolated worktree",
"without an isolated worktree"). A worktree that cannot be created fails the
launch with `worktree_creation_failed` rather than silently downgrading, and
the launcher verifies the directory exists before reporting `isolation:
"worktree"` -- a zero exit code that produced no directory is not proof, and
`_dispatch` binds the worker only to a worktree that is really there.

The isolation mode is written onto the durable Run record, so a reviewer reads
what actually happened instead of inferring it from a branch name.

This closes the #472 dogfood findings 6 and 8. `resume` previously created no
worktree on the Work launch path yet returned `branch: work/<run_id>`
regardless -- a name constructed from the run_id rather than projected from
durable state -- so a reviewer saw a plausible branch that had never existed
while the change had landed in the shared checkout, and a mandate requiring
the change to stay "inside the run's isolated worktree" was unenforceable
rather than merely unenforced.

## Evidence Gate: a mutating run must land a correlated commit

Isolation says where a run worked. It does not say whether the run produced
anything. A run whose approved mandate expects it to change the repository is
recorded as **mutating** on its durable Run record — `create` always, `resume`
whenever the mandate carries an artifact policy, and either way by the
launcher, never by the worker. A registry that cannot carry the flag fails the
launch (`mutating_run_not_recordable`) instead of running a mutating worker
under no gate at all.

A mutating run may not be recorded `succeeded` unless
`scripts/commit_evidence.py` verifies a landed commit that:

- exists in the repository;
- correlates to this run's `run_id`, `issue_id` and approved `request_id`;
- is reachable from the run's registered `work/<run_id>` branch — a run that
  recorded no isolation has no branch to correlate against and fails closed;
- was committed after the claim;
- carries a `Signed-off-by:` DCO trailer;
- touches only what the approved artifact policy permits (the paths the policy
  names in backticks, or an explicit `artifact_paths` set; an unscoped policy
  restricts no path but still requires a non-empty change).

The verified correlation is written onto the Run as `commit_evidence` and into
the result envelope. Anything else — a missing SHA, a foreign commit, a policy
breach, or a gate that cannot read the repository — converts the claimed
`succeeded` into `blocked` with a stable failure code.

This closes #490. The #485 run `run-6d936b467f804939a4ce734ac5f45dd8` reported
`succeeded` with `artifacts: ["run-log:..."]` and evidence "hermes-free
reported status=succeeded", while `git log --all` for the mandated path
returned zero commits. Nothing required an artifact, so the claim was accepted
and relayed to the Issue.

## Review is earned, not asserted

A terminal worker status never moves the Issue to `workflow:review`. The order
is fixed (#493):

1. the worker reaches a terminal candidate status;
2. the Evidence Gate verifies the result and the commit correlation above;
3. `agent-platform/daemon/review_submission.py` writes a complete, idempotent
   `run.review_submitted` event to the session store — the submission id is
   derived from the `run_id`, so a replay, a resync and a restarted host all
   address the same submission;
4. `cortxt daemon sync-review` (`daemon/review_sync.py`, ADR-037) performs
   `in-progress -> review` from that durable submission, and only from it.

The dispatcher still syncs the transitions that are its own — `cancelled`
returns the Issue to `workflow:ready`, a failing status takes it to
`workflow:blocked` — and still posts the result comment. It no longer moves
the Issue forward. With no session store configured there is no submission
path, so a completed run stays `workflow:in-progress`: the transition is
withheld rather than taken on a worker's word.

Because that failure mode is silent-but-terminal, `default_launcher` always
wires the submitter. The store resolves from the registry —
`agent-platform/.dispatch/runs.json` -> `agent-platform/.sessions`, the same
store `cortxt sessions` and `cortxt daemon sync-review` use — and never from
the process cwd, for the reason `action_host.py` resolves the registry that
way: a cwd-relative store is how #485's Run records ended up in a second,
unaudited registry root. Pass `review_store` to override it.

On #485 the label moved `in-progress -> review` at 12:16:38 and the result
comment landed at 12:16:40 — the ordered pair `_sync_github()` emits — while
no `run.review_submitted` event existed in any store.

## Recovery out of a stranded claim

`workflow.recover-to-ready.v1` is the one sanctioned actuator for
`workflow:in-progress -> workflow:ready`. It exists because a Run that failed
or stranded previously left its Issue at `workflow:in-progress` with no way
back through the action ports, so recovery meant a manual `gh issue edit`
outside the contract (#472 finding 2). Like the other two transitions it
re-reads the Issue immediately before the write and refuses any state that is
not exactly `workflow:in-progress`; it is not a general label editor. It
approves, merges, closes, and completes nothing, and it starts no Run --
returning to `ready` re-opens the dispatch gate so a fresh Run stays a
separate operator decision through `workflow.claim-run.v1`.

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

## S7c live Run status source

The S7c live Run status surface reads its terminal facts (`engine`,
`provider`, `model`, `usage`, `cost`, `cost_status`, `artifacts`, `evidence`,
`error`, `incomplete`, `conflicting`) from ``run.terminal.v1`` as projected by
``agent-platform/widget_contract/run_authority.py`` and served through
``read_run_terminal_v1`` in ``agent-platform/widget_contract/adapters/store_reads.py``.
It never reads those fields from browser state. When a correlated MCP session
document exists, the projection draws the ``run.engine_turn`` payload from that
session; when it does not, it falls back to the exact dispatcher result stored
for the run (commit cf22288). Free-text evidence, filesystem paths, and
unstructured usage are dropped before projection; only content-free fields
defined in the ``run.terminal.v1`` schema in ``agent-platform/widget_contract/registry.py``
are returned.
