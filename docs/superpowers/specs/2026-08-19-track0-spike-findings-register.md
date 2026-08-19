# Track 0 Spike Findings — Register

**Type:** Register (per this repo's convention: records what was found at a point in
time; never edited after this commit — if a later investigation contradicts it, a new
register document supersedes it, this one is not rewritten).
**Date:** 2026-08-19
**Branch:** `swarm/track0-orchestrator-mechanism`
**Full working notes (gitignored, not in version control):**
- `.hermes/plans/2026-08-19-track0-engine-spike-findings.md` — Pi / own-coding-agent invocation spike
- `.hermes/plans/2026-08-19-track0-kanban-mechanism-findings.md` — Kanban dispatch trigger mechanism spike

This document is the durable, version-controlled summary of both. The two files above
have the full step-by-step investigation detail and are the source of everything below;
consult them directly for anything not captured here. They are gitignored working notes
and can be lost or regenerated — this register is the only copy of these findings that
survives in git history.

---

## 1. Pi / own-coding-agent spike summary

**Pi: not found.** Searched `$env:PATH` (`Get-Command pi`, `where.exe pi`, and a full
directory scan for any `pi*` file — only unrelated Windows system binaries matched, e.g.
`PickerHost.exe`, `pidgenx.dll`, `pifmgr.dll`, `PimIndexMaintenance.dll`,
`PinEnrollmentBroker.exe`, `PING.EXE`, `pip.exe`). Checked the sibling-install-directory
pattern next to Hermes's own install (`AppData\Local\hermes\...`) — no `pi`/`pi-agent`
directory exists there. Grepped the v.02 swarm-orchestration spec and the Track 0 plan for
any prior mention of Pi's command name, install location, or config — none found; the spec
only uses "Pi" as an abstract future-engine label. No package install was attempted, since
guessing a package name to install would fabricate an invocation contract rather than
confirm one. **Verdict: no confirmed Pi installation on this machine; not ready for a
`pi_invoker.py` module.**

**"Own coding agent": identity unresolved, stays open.** The spec and Track 0 plan use
"own coding agent" only as a category label, never naming a specific tool or command.
`agent-platform/routing/engine_manifest.py` already declares a `claude-direct` engine
(`reliability_class="verified"`), presumably Claude Code itself invoked directly — but no
invoker module exists for it in `agent-platform/routing/` (unlike `hermes_invoker.py`), so
the repo alone cannot confirm whether "own coding agent" and `claude-direct` are the same
thing or two distinct things. `scripts/` and `harness/scripts/` were checked for a
self-built agent CLI — none found beyond the existing `dispatcher.py` /
`worker_adapters.py` (whose only worker adapter is `HermesAdapter`).

`claude.exe -p --output-format json` was confirmed as a real, observed one-shot CLI
contract (Claude Code CLI's own `--print` / `--output-format json` mode) — recorded here
for reference only, since it is a plausible invocation shape *if* "own coding agent" turns
out to be Claude Code itself. This was explicitly **not** treated as a confirmed contract
for a new engine.

The operator was asked directly and answered: **"Osäker men jag vet att vi har påbörjat
och testat en"** (uncertain, but knows one was started/tested). This answer does not
resolve the identity question — it neither confirms "own coding agent" == the existing
`claude-direct` manifest entry, nor names a separate tool. **This stays an open question.**
Neither `pi_invoker.py` nor `own_agent_invoker.py` is buildable yet.

---

## 2. Kanban mechanism root cause — the branch's key finding

**Question:** did the four autonomous Kanban dispatches that each self-reported
"completed" with a false or unverified result — GitHub issues #165, #166, #174, #175 — run
through `scripts/dispatcher.py` + `scripts/worker_adapters.py`, or through something else?

**`scripts/dispatcher.py` is decisively ruled out.** Read in full (405 lines, plus
`scripts/worker_adapters.py`, 261 lines). `Dispatcher`'s only two GitHub-touching code
paths are `claim()` (`workflow:ready -> workflow:in-progress` + a claim comment) and
`_sync_github()` (`workflow:in-progress -> workflow:review|blocked|ready` + a result
comment). There is no `gh issue create` and no `gh pr create` anywhere in either file — it
only ever acts on an issue that already exists and is already labeled `workflow:ready`; it
cannot originate a run from nothing and never opens a PR. Nothing found ties this
dispatcher to #165/#166/#174/#175.

**The actual mechanism: `harness/scripts/mirror-kanban-to-github.py`** (with its sibling
`harness/scripts/github-ready-to-kanban.py`), which reads/writes an external Hermes Kanban
SQLite DB (`$LOCALAPPDATA\hermes\kanban\boards\cortxt-cp\kanban.db`), entirely outside this
repo's git version control. It polls the Kanban DB for tasks with `status = 'done'`, and
for each one not yet mirrored, posts the task's self-reported `result`/`summary`/
`metadata` verbatim as a GitHub comment (`format_comment()`), then calls
`advance_workflow_label()`, which flips `workflow:ready -> workflow:review`
**unconditionally** — it never checks the associated git worktree/branch for an actual
commit or diff. It only checks that a `workflow:ready` label is present before flipping it.

**Confirmed byte-for-byte against the live GitHub issues** (`gh issue view <n> --json
labels,comments`, run with authenticated `gh`): all four issues (#165 task
`t_7c503d3f`, #166 task `t_94da7945`, #174 task `t_71929921`, #175 task `t_5dd2902f`) carry
a comment that is an exact match against `mirror-kanban-to-github.py`'s `format_comment()`
template — `## 📋 Kanban Run Complete`, `**Task:**`, `**Assignee:**`, `**Started:**`/
`**Finished:**`, `### Result` / `### Summary` / `### Metadata`, ending in the exact
sentence `*Mirrored automatically from Hermes Kanban \`cortxt-cp\`.*` — and all four sit at
label `workflow:review`, matching `advance_workflow_label()`'s one-shot transition.
`dispatcher.py`'s own claim/result comment formats are structurally different (a markdown
table, "Claimed by dispatcher.") and appear in none of the four issues. The timeline lines
up too: commit `9f42b44` ("restore kanban<->github/buzz mirror scripts, add
github->kanban importer (#162)", 2026-08-18 21:14) (re)introduced this exact pipeline hours
before all four issues were mirrored through it the same night.

**Root cause, now visible in code, not just inferred by absence:**
`mirror-kanban-to-github.py` treats the Hermes Kanban task's own `result`/`summary`/
`metadata` fields as ground truth. It never shells out to `git` to check whether the
referenced worktree/branch actually has a commit, a diff, or matches the `changed_files`
the task claims. A Kanban task that self-reports `status = done` with a confident summary
is mirrored and the issue advanced to `workflow:review` on that basis alone — this is the
confirmed root cause of the "self-reported completed, nothing committed" failure pattern
behind #165/#166/#174/#175.

**Verdict:** a post-hoc git-state verification gate (e.g. shelling out to `git -C
<workspace-from-task-body> log --oneline -1` and `git status --porcelain`, or diffing the
task's claimed `changed_files` against `git diff --name-only`, before posting/advancing) is
buildable **today**, in this repo, inside `mirror-kanban-to-github.py`, and would have
caught all four of #165/#166/#174/#175 before they reached `workflow:review`. This is a
strong candidate for a future plan — **deliberately not built in Track 0** (out of scope
for this branch). A true *mid-task* checkpoint (pausing the Kanban worker itself partway
through, rather than gating the after-the-fact mirror) is not implementable from this repo
alone; it would need a Hermes-side hook or wrapper, which does not exist yet. Also still
unconfirmed: whether `github-ready-to-kanban.py` + `mirror-kanban-to-github.py` actually
run on a schedule (cron) or were hand-run the night of 2026-08-18 —
`docs/agents/current-operating-model.md` (as of 2026-08-09) stated no mirror cron was
registered. Building the verification gate before knowing whether this pipeline is
scheduled or manual would repeat the same guess-the-contract mistake this whole effort is
trying to avoid, which is why it stays a future plan's job rather than being built here.

---

## 3. Status

Register document, written 2026-08-19. Never edited after this commit — if a later
investigation contradicts anything above, a new register document supersedes it (with a
`supersedes:` reference back to this one); this file's substance does not change.
