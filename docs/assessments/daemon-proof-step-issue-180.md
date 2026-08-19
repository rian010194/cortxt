# Daemon proof-step evidence — issue #180

Task 11 Step 2 of `docs/superpowers/plans/2026-08-19-supervisor-daemon-v1.md`:
"Manual proof-step — one real dispatch through the daemon," run manually
by the operator, 2026-08-19/20.

## Attempt 1 (2026-08-19, pre-fix)

`cortxt daemon start --repo rian010194/cortxt --once` claimed issue #180,
invoked Hermes, but the prompt sent was `issue["title"]` only — the issue's
full body (file path, exact content, commit-message convention, "new
branch" instruction) was never fetched by `github_scanner.list_ready_issues`
(`gh issue list` didn't request the `body` field) or passed to the Hermes
call. Hermes reported `succeeded` with no commit landed. The Evidence Gate
correctly froze the run (`"terminal status was 'failed', not 'succeeded'"`)
instead of trusting the self-report — the gate behaved exactly as designed,
but the underlying task never had enough context to succeed.

Root cause and fix: `agent-platform/fix(daemon): send full issue body to
Hermes, isolate each dispatch in its own worktree` (commit `867d80a`).
Also closed a related gap noted at the time — the daemon dispatched
directly onto whatever branch `workdir` had checked out, with no
isolation, even though issue #180 explicitly required "committed on a new
branch." Each dispatch now runs inside its own `git worktree` on a
`daemon/issue-<N>` branch.

## Attempt 2 (2026-08-19/20, post-fix)

Same command, after clearing the stale claim in `.daemon-state/claimed.json`.
Result: **PASS**.

- Daemon claimed `rian010194/cortxt#180`, created worktree
  `agent-platform-worktrees/rian010194-cortxt-issue-180` on branch
  `daemon/rian010194-cortxt-issue-180`.
- Hermes ran in ~33s (vs. ~5min timing out on Attempt 1) and committed:
  `c08eade docs: daemon proof-of-life log for #180`, adding exactly
  `docs/daemon-proof-log.md` with the one-line entry the issue specified,
  no other files touched.
- Evidence Gate: `commit_landed=True` (checked against the worktree, not
  the shared `workdir`), `decision="pause"` — correct, since `supervised`
  mode was on (no `--unattended`) and this class has not earned autonomy.
- Operator reviewed the diff and merged `daemon/rian010194-cortxt-issue-180`
  into `main` locally (merge commit, not yet pushed); worktree and branch
  removed after merge.

## Verdict

The daemon's claim → isolated-worktree → Hermes → Evidence-Gate loop works
end to end for a well-specified, single-file, low-blast-radius task. The
gate's `freeze`-on-unverifiable-completion behavior (Attempt 1) and its
`pause`-for-review behavior under supervision (Attempt 2) both matched what
a human reviewing the same evidence would have decided.

**Not proven by this test:** multi-file tasks, tasks needing repository
context beyond the issue body, autonomy-unlocked (`proceed`) behavior, or
any actual code/content review of what Hermes produced — the gate checks
"did a commit land," not "is it correct." A review/documentation role in
the loop remains an open, unbuilt thread (see handoff).
