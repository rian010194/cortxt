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
- correlates to this run's `run_id`, `issue_id` and approved `request_id`. All
  three are **required** in the result envelope — an omitted field is not a
  passed check — and a Run record missing any of them cannot be correlated at
  all;
- is reachable from the run's registered `work/<run_id>` branch — a run that
  recorded no isolation has no branch to correlate against and fails closed;
- was committed **strictly after** the second in which the run was claimed.
  Git timestamps have one-second resolution, so a commit inside the claim's own
  second cannot be ordered against it and is refused;
- carries a `Signed-off-by:` DCO trailer;
- touches only what the approved artifact scope permits.

The approved scope resolves fail-closed, with no unrestricted outcome. An
explicit `artifact_paths` set on the Run wins; otherwise the gate uses the paths
named in backticks in the artifact policy, including single-segment
repository-relative paths such as `LICENSE`. A Run carrying neither is blocked
(`artifact_policy_missing`), and a policy naming no readable path is blocked
(`artifact_policy_unparsable`) rather than treated as permitting everything.
Every path on both sides must be repository-relative: an absolute path, a drive
letter or a `..` segment is refused, never silently skipped.

A mutating run is always isolated. `resume` derives "is this run mutating?" from
whether it was given its own worktree, and a mutating launch without isolation
is refused before any claim exists (`mutating_run_requires_isolation`) — the
Evidence Gate would refuse the result anyway, but only after the worker had
already run in the launcher's shared checkout. `create` states its approved
paths outright and the launcher persists them on the Run before dispatch.

The verified correlation is written onto the Run as `commit_evidence` and into
the result envelope. Anything else — a missing SHA, a foreign commit, a policy
breach, or a gate that cannot read the repository — converts the claimed
`succeeded` into `blocked` with a stable failure code.

The producer side supplies the correlation from the durable Run record, never
from worker prose (#506). Both `worker_adapters.dispatch_async` and
`work_launcher.submit()` inject the authoritative `run_id` / `issue_id` /
`request_id` into the envelope before the Run is completed, so an envelope that
echoes wrong values (or none) cannot move the correlation check — it is the
platform's identity to own. When the Run record carries no `request_id` at all,
a worker-supplied one is dropped rather than left standing in for approved
identity: the Run is refused as unapproved instead of correlated against the
worker's own claim.

Both paths also derive the `commit` when the worker reported none — `submit()`
from the launcher's repository, `dispatch_async` from the Run's own isolated
worktree, which is a git working directory for that Run's own branch. The live
path needs this in its own right: it is the path a real Cortxt OS launch takes
(`WorkLauncher._dispatch` -> `dispatch_async` -> adapter ->
`Dispatcher.complete`), and no adapter emits a `commit` field, so without
derivation every mutating Run on the live path stopped at `commit_missing` and
the accepted arm was structurally unreachable. A green `submit()` test does not
cover it. Only a claimed success is enriched with a commit; a failed Run must
not carry a field that reads as landed evidence.

The gate still re-verifies whatever commit is presented, so this enriches
without weakening. A `succeeded` report that lands nothing is still `blocked`
with `evidence_gate: "commit_correlation_failed"` — but on both paths the
recorded category is `commit_predates_run`, not `commit_missing`. A mutating
Run always has its branch created before dispatch, so derivation always
resolves a SHA: the baseline the branch started from, which the gate's
strictly-after-claim check refuses as this Run's output. `commit_missing`
remains reachable only where no branch resolves at all. A consumer that keyed
on `commit_missing` as the no-commit signal must read `evidence_gate` instead.
The worker prompt (`generate_worker_prompt`) states the result contract: commit
with a DCO `Signed-off-by:` trailer inside the run's own worktree and report
`run_id` / `issue_id` / `request_id` and the commit SHA in the result envelope.

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
