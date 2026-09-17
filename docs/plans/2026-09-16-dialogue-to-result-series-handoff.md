# Handoff — Cortxt dialogue-to-result series

**Document type:** register. It records why these choices were made, at one point in time.
It is never edited. If it is wrong, write a new one that sets `supersedes:` to this file.

**Status:** plan approved by the operator, 2026-09-16.
**Execution is NOT authorized by this document.**

**Prepared:** 2026-09-16.
**Prepared against:** `f6dba33ac6869ee5916b6c86a46338a94e7f8ecc` (GitHub `main` on that date).

---

## 1. Product goal

Cortxt takes the operator from dialogue to a reviewable result in one product.

The operator must be able to: analyse a problem and existing material; develop ideas and
product plans; have Cortxt carry out bounded development work; review results and iterate;
close Cortxt and resume later with context and decisions intact.

Analysis, planning and development are parts of one product.
**Analysis or a plan can be a finished result with no code change.**

### Non-negotiable product rules

1. **Dialogue is the entry point.** Both a loose idea and a definite assignment must work.
2. **Repository selection is never a mandatory first step.** Work is the starting point;
   a repository is a resource the work uses.
3. **Discovery and read access never grant write access.** Keep three levels distinct:
   *available context* → *possibly affected repositories* → *approved change targets*.
4. **Partial completion is never rendered as complete.** Multi-repo results are summarised
   jointly, with per-repository status and evidence.
5. **The operator never writes parser-correct markdown headings or reads internal status
   codes.**
6. **Every product milestone requires acceptance through the operator's own entry point** —
   the browser journey. Direct API probes supplement it; they never replace it.

### Chosen scope boundaries

- Local web app with a simple start shortcut. Main work happens in Cortxt.
- **Cortxt owns everything up to the PR. GitHub is used for final review and merge via an
  explicit handover.** No native desktop app; no replacement of GitHub.
- Two-repository case only: `cortxt` ↔ `cortxt-agents`. Sequential, no dependency graph.

### Explicitly out of scope

App store or general plugin platform; multi-user or remote hosting; full frontend rewrite;
general autonomous background operation; automatic merge or deploy; broad integration of
many agent engines. Only a demonstrated, concrete dependency reopens any of these.

### Open product questions (the operator's, not the coordinator's)

1. Physical location and backup routine for the Cortxt data home. The Core store itself
   declares backup an OPEN point (S4-B6 / P2-9, `agent-platform/state/core_store.py`).
2. Whether a finished analysis result may be published off-machine, and where.
   `cortxt-deliverables` is a candidate but is not checked out locally.
3. How much Cortxt may propose unprompted.

None of these block M1.

---

## 2. Verified baseline — and the instruction to re-verify

All findings below were read at `f6dba33` using `git show` / `git grep`, with no checkout,
fetch, pull or other mutation.

> **First action for the new coordinator: re-verify current `main` before planning any work.**
> `f6dba33` was GitHub `main` on 2026-09-16. Confirm the current head with
> `gh api repos/rian010194/cortxt/commits/main`. Read code at that revision without mutating
> any working copy.

**Baseline trap, observed 2026-09-16:** local `main` was `37ff2f9` (2026-09-12) while GitHub
`main` was `f6dba33` — four days behind, and **`f6dba33` was not an ancestor of local `main`**.
The primary working copy was on branch `fix/571-cli-v2-digest` at `3a23bf3`, with untracked
`contracts/build/` and `keepalive_dispatch_542.py`.
**Reading "main" locally shows a world before the W-series. Do not trust a local branch name.**

### Verified findings

| # | Finding | Evidence @ `f6dba33` |
|---|---|---|
| V1 | ADR-047 (ACP as client) is **Accepted but entirely unimplemented**. No `AcpAdapter`; `invoke()` has no `on_event` / `supports_events` | `docs/adr/047-*.md`; `agent-platform/runtime/adapters/` (claude, codex, dsh, hermes, hermes_free only); `agent-platform/runtime/engine_adapter.py:17` |
| V2 | **No repo speaks ACP.** Zero matches for `agentclientprotocol`, `acp_`, `jsonrpc`, `json-rpc` across all five Cortxt repos | grep across `cortxt`, `cortxt-agents`, `cortxt-resilient-inference`, `cortxt-vault`, `cortxt-state-portability` |
| V3 | Packaging routes exist but are **unreachable**: the store is never passed in the documented start | `widget/action_host.py:273`, `:304`, `:839-934`; `main()` calls `ActionHost(spec_path=...)`; `scripts/start_cortxt_os.py` delegates to it |
| V4 | **No renderer uses the packaging API** | grep "packaging" in `agent-platform/widget/` + `site/public/widgets/` matches only `action_host.py` |
| V5 | W-6 compose is an issue form — fields `repo`, `title`, `body`, `labels`; **`repo` is the first required field** | `widget/app-renderer-start-mission.js:200-214` |
| V6 | Both reported #489 dogfood defects are **live**: title passed positionally without `--title`; synthetic issue identity | `widget_contract/adapters/github_ports.py:205`, `:213` |
| V7 | The #489 fix is **not on origin** — no branch, no PR. Open PRs: #556, #521, #505 | `git ls-remote --heads origin`; `gh pr list` |
| V8 | **No `data_home`.** State is derived from module location: `.dispatch/`, `.sessions`, `.mandate`. The Core store explicitly requires the opposite | `cortxt_mcp/run_lifecycle.py:502`; `cortxt_mcp/server.py:73`; `state/core_store.py` docstring §5 |
| V9 | **No TypeScript build chain.** No tsconfig / vite / esbuild / rollup / webpack. The only TS is the Astro docs site | tree scan; `site/src/components/AtlasGraph.tsx` |
| V10 | **#503 / #504 CLOSED COMPLETED with no implementation on main.** PR #505 is **draft** and claims ADR-046, already taken by *versioned request digest*. Highest ADR on main is 048 | `gh issue view`; `gh pr view 505`; `docs/adr/046-versioned-request-digest.md` |
| V11 | **No repo discovery, no read scope, no multi-repo mandate** | grep `discover_repo`, `repo_discovery`, `scan_repos`, `read_scope`, `workspace_root` → only tests + `session_inbox_contract.py` |
| V12 | S4-B2 semantics are **built and tested**: append-only, typed `supersedes` validated against an existing record, CONFLICT-NOT-MERGE. **S4-B2 does not block M1** | `state/core_store.py:115`, `:302-305`, `:446`, `:470-472`; `state/test_core_store.py:58-71` |
| V13 | **DispatchRequest v2 is single-repo.** One required `issue_id`; no `repositories` array | `contracts/dispatch-request.v2.schema.json` |
| V14 | A multi-repo model already exists in packaging: `referenced_repositories` as required `{repo, sha}` with 40-hex sha | `schemas/packaging/revision.schema.json` |
| V15 | **`cortxt-agents` cannot install.** It pins `contracts/v2.0.0`; the core repo has **zero tags**. Issue #604, which would cut the tag, is OPEN | `cortxt-agents/requirements.txt`; `git ls-remote --tags origin` → 0 lines |
| V16 | `credential_broker: ""`; `BROKER_IMPLEMENTATIONS` empty until a core-side broker exists → every agent run declines | `cortxt-agents/config/default_config.yml` |
| V17 | **`RunRegistry` still carries the ADR-047 §3 defect**: whole store read once in `__init__`, in-process `RLock` only, no file lock, no atomic replace | `scripts/dispatcher.py:~262`, `:328` |
| V18 | `cortxt-agents` has a reusable fail-closed multi-repo write model: `allowed_write_repos` allowlist, `dry_run: true` default, no ambient credentials, secret scanning of envelopes | `orchestrator/config.py`; `config/default_config.yml`; `agents/base_agent.py` |
| V19 | `cortxt-agents` agents are **deterministic and make no model call** — a non-ACP worker runtime, not a dialogue engine | `agents/base_agent.py:79`; `agents/px_agent.py:59` |

### Repository map (verified 2026-09-16)

| Repo | Visibility | Local checkout | Branch |
|---|---|---|---|
| `cortxt` | public | `projects/ai-workspace-control-plane` | `fix/571-cli-v2-digest` |
| `cortxt-resilient-inference` | public | `projects/cortxt-resilient-inference` | `chore/project-urls` |
| `cortxt-agents` | private | `cortxt-agents` | `feat/604-contract-pinned-consumption` |
| `cortxt-vault` | private | `cortxt-vault` | `vault/d004-agent-repos` |
| `cortxt-deliverables` | private | **`C:\Users\rikar\Cortxt` — the workspace root itself** | `main` |

**None of the four project repositories is on `main`.** `cortxt-deliverables` is, and it is the
only entry in `allowed_write_repos`.

> **Correction, 2026-09-16.** An earlier revision of this register stated that
> `cortxt-deliverables` was *"not checked out"* and that *"none is on `main`"*. Both were false,
> and the error was found by B1.6's discovery run rather than by inspection. The workspace root
> `C:\Users\rikar\Cortxt` **is** a checkout of `cortxt-deliverables`, on `main`, with 27 tracked
> files under `_deliverables/`. The earlier reading missed it because the root was treated as a
> container of repositories rather than as one.
>
> **The consequence is a product finding, not a bookkeeping fix.** Because the workspace root is
> itself a repository, a read area pointed at it stops there: discovery does not descend into a
> repository once found, so `C:\Users\rikar\Cortxt` yields **exactly one** repository and hides
> all five projects beneath it. The behaviour is correct and the answer is honest; the
> configuration is the trap. Pointing the read area at `C:\Users\rikar\Cortxt\projects` instead
> returns 64 repositories — of which **3 are on `main`**, which is the premise of §2's baseline
> trap, measured rather than argued.
>
> Two decisions this hands forward: whether discovery should warn when a read-area root is itself
> a checkout, and whether `DiscoveryCaps.max_repositories = 64` is the right default when the real
> workspace contains exactly 64 and therefore truncates on first real use. Both are the operator's
> to settle; the truncation is already reported visibly rather than silently.

### Unresolved authority contradictions — resolve before building on them

- **ADR-047 D4 vs its own decision packet.** The ADR says the ACP `sessionId` is
  *"owned by Cortxt, created via `session/new`"*; `docs/561-acp-decision-packet.md` records
  *"CORRECTED in D4 (agent issues the ACP sessionId…)"*.
  **The operator decides. Do not silently pick one.**
- **#619 CLOSED COMPLETED while #501, the same deliverable B, is OPEN.**
- **#503 / #504 closed against an ADR that was never accepted, under a number that now means
  something else.** Operator decision on record: let **#584 / #592 / #593** carry the work;
  note #503 / #504 as wrongly closed; do **not** reopen them. **Close PR #505** and write a new
  ADR-**049** once the dialogue surface's shape is known.

---

## 3. Source and authority map

Read in this order before proposing any execution path: `CLAUDE.md`; `CONTEXT.md` (controlled
vocabulary); `AGENTS.md`; `docs/README.md` (authority map);
`docs/agents/current-operating-model.md`; `docs/architecture/dispatch-contract.md`;
`docs/agents/running-cortxt-os.md`; `docs/agents/work-launcher.md`.

| Concern | Authority |
|---|---|
| Dialogue session | The ACP agent (transient) |
| **Work record** — observations, proposals, open questions, goals, limits, acceptance criteria | **Local Core store, new domain.** Never synced to GitHub |
| Affected repos, change targets, limits | The mandate, derived from the work record |
| Scope, approval, `workflow:*` | GitHub Issues (ADR-018). Exactly one `workflow:*` label at a time |
| Run identity, status, evidence | Run registry + evidence ports |
| Packaging records | Local Core store (ADR-048) |
| Delivery paths and label invariant | ADR-040 |
| Execution policy profiles | ADR-045 |

`CONTEXT.md` already supports work-before-repo: *"A workstream may exist without a Git
workspace for research-only work"*; *"Workspace … is execution metadata, not the workstream's
identity."* **The vocabulary is right; the surface violates it** (see V5).

**A new ADR is required** for the work-record domain: ADR-048 covers product packaging only.
Extending local Core authority to a work domain is a decision, not an implementation detail.

Historical planning material — `lab/product-packaging-discovery/20260914/swarm-04/`,
`…/swarm-05/checkpoint.md`, `lab/w-series/` — is supplementary.
**Their historical work orders are not instructions to execute now.**

---

## 4. Collaboration model — Hermes coordinator with Claude Code builders

The operator requires the W-series working model for the whole series. The description below
is taken from that series' own primary sources: `lab/w-series/CHECKPOINT.md` (wave register,
mandate 2026-09-15) and `lab/w-series/w6-order.md` (the most evolved order file).

### Roles

**Hermes — coordinator profile session.** Drives the series. Verifies the frontier against
primary sources and pins it. Diagnoses root causes. Prepares order files. Registers worktrees
fresh from the pin. Dispatches builders. Repairs the environment before a run when the
environment is the blocker. Integrates, pushes, opens PRs and merges when the mandate allows.
Maintains the append-only wave register.

**Claude Code — builder, leaf, separate isolated context.** One registered worktree, one
branch, base = the pin. Executes one order. Commits locally. Reports.

**Independent review gates remain binding** and are not performed by the builder that produced
the work.

### The order file is the interface

A builder receives an order file and nothing else. Verified structure from `w6-order.md`:

1. **ROUND-N CORRECTIONS** — binding corrections from prior exploration and coordinator re-check.
2. **FROZEN MAP** — every anchor verified on the pin by the coordinator, grouped per commit.
3. **Trigger reads** — e.g. the design-system ADRs when a product UI renderer is touched.
4. **COMMIT SEQUENCE** — exact commits, DCO `-s`, conventional subjects, body `Refs #<issue>`.
5. **ALLOWED PATHS** — plus an explicit `NEVER:` list (other worktrees, the canonical checkout,
   contract JSON, virtualenvs).
6. **VERIFICATION** — exact commands, and a test floor that may never regress, with exact
   numbers reported.
7. **HARD RULES** — see below.
8. **Report format** — per-commit summary, suite numbers, deviations, open items.

**Orders carry everything the builder needs inline.** The artifact policy forbids reading
`lab/` from inside the run worktree; the W-2a run stated this as its own incompleteness driver,
and the retry inlined the payload objects.

### Builder hard rules (verbatim in substance from `w6-order.md`)

- **Never approve, merge or push. Commit locally only; the coordinator integrates.**
- No label writes beyond a transition the order names explicitly.
- No secrets, prompts or model reasoning in commits.
- Nothing that starts a Run unless the order says so.
- Do not comment on issues beyond a note the order specifies.
- **Honest early stop:** if blocked, stop, leave exact state, report.
- Cost: unknown, never 0.

### Known operational constraint

Builders hit a **per-run tool-iteration budget of roughly 50 API calls**. In the W-series both
Phase-1 and Phase-2 builders stopped before final verification and commits for this reason —
**not** because the orders were wrong. Keep orders narrow and gap-scoped, and inline the
payloads they need.

### Failure protocol

A failed run stops; the wave continues. Evidence is preserved in the worktree. The coordinator
diagnoses the root cause and dispatches a **changed-conditions retry** — never a plain repeat.
The change may be a narrowed supplement order, or coordinator-side environment repair before
the retry.

### Wave register

The coordinator maintains an append-only checkpoint per wave, following
`lab/w-series/CHECKPOINT.md`: mandate quoted verbatim, generation timestamp, author, frontier
verified against primary sources with the pin named, root causes diagnosed, decisions taken
within mandate, what is in flight, and cost. Later entries carry a `PREF:` hash of the previous
entry. **The coordinator declares its own writes** ("coordinated writes by the coordinator")
so that the freeze rule stays auditable.

---

## 5. Milestones, dependencies and work breakdown

**F0 — ACP probe (spike; decision input, not a delivery).** Step 0 maps which ACP-speaking
agents actually run locally on Windows without a paid route (necessary per V2). Then
installability; transport; streaming + elicitation; session resume. Throwaway code outside the
package tree. No `AcpAdapter`, no ADR edits, no remote transport, no paid routes. Touches none
of the five repos. Also observes who issues the ACP `sessionId`, to inform the operator's
decision on the ADR-047 D4 contradiction — it does not decide it.

**M1 — First real conversation.**
B1.1 data home → B1.2 store wiring → B1.3 work-record domain.
B1.4 projection validation and B1.6 read area + repo discovery run in parallel.
B1.5 dialogue surface is gated on F0. B1.7 resume-after-restart.
Discovery must report path, remote, branch, HEAD, dirty state and relation to remote `main` —
path alone is insufficient, per the baseline trap in §2.

**M2 — From conversation to plan.**
B2.1 revisable record via `supersedes`; B2.2 analysis/plan as a finished deliverable;
B2.3 mandate preparation replacing the repo-first form (V5), freezing to the packaging revision
shape (V14); B2.4 TS foundation + ADR-049, **conditional on the source-integrity question below
being settled first**.

**M3 — One assignment end to end.**
Build dependencies first: **#604** (V15), **RunRegistry migration + atomicity fix** (V17),
**credential broker** (V16). Then one repo, then `cortxt` ↔ `cortxt-agents`.
**Do not change the dispatch contract** (V13): N repos = N Runs, sequential, stop on first
refusal. **Aggregation supplies overview, never judgement, and is never greener than its weakest
evidence.** No seventh state, no upgrade of a Run's state.

**M4 — Improve and continue.** Retry without overwrite (mechanism already built, V12);
interruption and recovery; durable result and decision history.

### Dependency types — keep distinct

- **Build dependencies:** B1.1 before B1.3; #604, the RunRegistry fix and the credential broker
  before M3; the source-integrity decision before B2.4.
- **Verification dependencies:** live browser acceptance for every milestone.
- **External decisions (the operator's):** data home location and backup; publication of
  analysis results; ADR numbering.

**No time or cost estimates.** There is no basis that would make them anything but false
precision.

### The source-integrity constraint (blocks B2.4)

Cortxt OS has **no build chain**; what is in the repo is what is served (`widget/serve.py` is a
static file server with no request-handling logic). Four mechanisms exist to prove that
property: `source_signature()`, `--require-commit`, `--require-clean`, and the #608 containment
scan. **A TypeScript build inserts a derived artifact between source and served output and
breaks it.** Settle this — commit build output, or extend `source_signature` to cover built
assets — **before the first line of TS.**

---

## 6. Acceptance and evidence matrix

Every milestone requires **live browser acceptance through the operator's own entry point**.
Direct API probes supplement; they never replace. #619 scoped delivery to code/contract tests
and deferred live acceptance to dogfood — **that is how the gap in V3/V4 arose. Do not repeat
it.**

| Milestone | Live acceptance | Automated / integration | Required negative cases |
|---|---|---|---|
| F0 | n/a (produces a decision memo) | n/a | No counterpart agent found → report it, do not simulate success |
| M1 | Start from any checkout → same record; conversation with no repo named → explained proposals with revision state; close and reopen → record intact | Domain schema; `supersedes` refused against unknown digest; insert-if-absent under concurrency; discovery revision reporting; fail-closed config | Empty read area; repo off remote `main`; start without Core store; **record with no issue and no repo must work** |
| M2 | Revise a conclusion → old version still present, relation visible; finish an analysis with no code change; prepare a mandate without repo-first | Supersession chain; mandate freeze to `{repo, sha}` | Revision against unknown digest; mandate without pinned sha; mandate naming a repo outside the write allowlist |
| M3 | Approve → isolated run → progress → evidence → reviewable result; then the two-repo case | Per run: dispatch v2 validity, containment (#608), Evidence Gate, `completion_report.py` six states and the no-upgrade invariant — **tested on the aggregate too** | **Repo 1 done + repo 2 refused → "partially complete", never complete**; missing evidence rendered as missing; repo outside allowlist refused *before* start; repo moved off pinned sha → refusal; interruption → repo 1's result survives |
| M4 | Retry, interrupt, recover, reopen later | Append-only history across sessions | Denied retry does not overwrite the earlier result; interrupted run shown as interrupted, not failed |

**Evidence rule, carried from `completion_report.py`:** *a route that asked a question and got
no answer has not received a yes.*

---

## 7. Coordinator mandate boundaries

**Approved plan ≠ approved execution.** This document records an approved plan. It grants **no**
authority to run, delegate, write to GitHub, merge, or use paid routes. The operator issues the
execution mandate separately, naming the unit, the limits and the permitted effects.

**Once such a mandate exists, work independently within it without routine check-backs.**

Without an execution mandate the coordinator may: read at a named revision; re-verify the
baseline; refine the breakdown; prepare order files and drafts for operator review.

The coordinator may **never**, with or without a mandate: approve, merge, deploy, publish or
close its own work; weaken an evidence contract; bypass the Evidence Gate; grant write access to
a repo not explicitly approved; edit an accepted ADR to remove a contradiction (write a new one
that supersedes it); place secrets, customer documents, prompts or model reasoning in GitHub or
committed artifacts.

### Review, integration, rollback and reporting

- Independent review stays required; workers do not review their own work.
- One bounded unit at a time, with artifact and evidence handoff.
- Every change must state how it integrates and how it is rolled back.
- Report **observation, conclusion and uncertainty separately**. Support conclusions with a
  revision plus file/symbol or issue/PR. **Never invent components, estimates or already-working
  integrations.**
- Report failures faithfully: if a step was skipped, say so; if tests fail, show the output.

### Stop conditions — halt and return to the operator

1. Work would exceed the mandate's named unit, limits or permitted effects.
2. Two authorities contradict each other (e.g. ADR-047 D4 vs its decision packet; #619 closed vs
   #501 open; #503/#504 closed vs absent implementation).
3. Current `main` differs materially from the re-verified baseline in a way that invalidates a
   finding in §2.
4. A build dependency proves unresolvable — e.g. #604 cannot be cut, or no ACP counterpart
   exists on Windows.
5. Execution would require a paid route, a new worker, or write access beyond the approved
   allowlist.
6. A change would break the source-integrity property before that question is settled.
7. Acceptance cannot be demonstrated through the browser journey.

---

## 8. Coordinating with in-flight dogfood work — avoid duplication

**A separate session owns #489. Do not start a competing fix or dogfood track.**

Reported by that session: a dedicated `dogfood-489` worktree at `f6dba33`; a real host started
and a real `POST /api/action` attempted; compose stopped before issue creation; a regression test
written and verified red on `fix/d489-compose-gh-invocation`; a fix patched but **not retested,
committed or merged**; a tool warning contradicting the patch status on a path with a doubled
`agent-platform` segment; a separate snapshot-test ordering leak.

**Independently verified here (V6, V7):** both defects are live at `f6dba33`, and **no fix branch
or PR exists on origin.** Treat the fix status as **unconfirmed** until a current diff, commit/PR
and tests are verified.

**Rules:** do not stop, start or repoint any already-running host within a planning mandate.
Judge #489 by its own current closing condition and correlated real evidence — not by a merge or
a closed related issue. Before touching anything compose-related, check whether the #489 session
has landed a fix; if unclear, ask the operator rather than patching in parallel.

---

## 9. Recommended first bounded execution unit

**B1.1 + B1.2 — data home resolution, and wiring the store into the action host.**

Why this first: it is small and additive; it is a build dependency for everything after it; it
converts W-2/W-3 from dead code into reachable product function (V3, V4) — the cheapest real
product gain in the series; it is revertible in one commit; and it requires **no** unresolved
external dependency, unlike M3, which waits on #604, the RunRegistry fix and the credential
broker.

It does **not** move `.dispatch/runs.json`. That migration belongs with the RunRegistry atomicity
fix (V17) before M3 — same file, same tests, same evidence, done once. Until then the start
output must name **both** storage locations, so the split is visible and deliberate.

**Not the first unit:** F0 can run in parallel but produces a memo, not product function; B1.5
depends on F0's outcome.

When a mandate is given, this unit is dispatched as a builder order following §4: frozen map
verified on the pin, explicit allowed paths, a verification block with the current test floor,
the hard rules, and local commits only.
