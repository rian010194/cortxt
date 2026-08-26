# CLAUDE.md — ai-workspace-control-plane (Cortxt)

Cortxt is a provider-neutral platform for creating, steering, resuming, and
verifying long-running AI work under **human mandate**. Users own the work's
state, memory, tools, evidence, and evolution; models, inference providers,
and external agent engines are replaceable resources behind Cortxt-owned
contracts.

**This is a description** — it asserts what is true now and must change in the
same commit as the thing it describes. It is the Claude-Code entry point for
this repository: it loads unconditionally from the working directory and its
parents. `AGENTS.md` carries the agent-facing operating boundaries; read it
too, and read `CONTEXT.md` for the controlled vocabulary.

## Non-negotiable rules

1. **The operator is the source of truth for scope, evidence, and approval.**
   No agent, contributor, or automation approves, merges, deploys, publishes,
   or closes its own work. Workers may not approve, merge, deploy, publish, or
   close their own work.

2. **No secrets, customer documents, prompts, or model reasoning** go into the
   repository or its GitHub issues. Real customer inputs and run outputs must
   remain outside Git history in an explicitly approved, isolated workspace.

3. **GitHub Issues are the durable source of truth** for scope, evidence,
   review, and approval. Workflow state is carried by exactly one
   `workflow:*` Issue label at a time — `inbox` / `ready` / `in-progress` /
   `review` / `blocked` / `done` (ADR-018). GitHub Project 4 is frozen legacy
   and must not be used for new dispatch. Runtime task lists (including any
   Kanban) are execution ledgers only and must correlate to a GitHub issue.

4. **Authoritative `workflow:ready` is not execution approval by itself.**
   Do not dispatch before the issue has approved scope, acceptance criteria,
   worker role, time limit, cost limit, and human approval.

5. **A merged delivery pull request never leaves its issue at
   `workflow:inbox`.** The issue moves to `workflow:done` at merge time via the
   state its delivery path prescribes (ADR-040 label invariant).

6. **Do not infer the operating model from one experiment or one runtime
   README.** Read the orientation documents in order before evaluating the
   architecture, proposing a new execution path, or dispatching work.

7. **Accepted ADRs are normative.** When you change an Accepted ADR, add a row
   to `docs/architecture/REVIEW_LOG.md` in the same pull request (the
   `adr-doc-currency` CI gate enforces this).

## Required orientation

Before evaluating the architecture, proposing a new execution path, or
dispatching work, read these files in order:

1. `docs/agents/current-operating-model.md`
2. `docs/architecture/dispatch-contract.md`
3. `docs/architecture/runtime-and-evaluation-harness.md`
4. `docs/agents/atlas.md` — roadmap maps derived from GitHub Issues (#210); see
   also `docs/agents/issue-tracker.md`'s Wayfinding section
5. the GitHub issue and any explicitly designated current planning state

A limitation in one runtime's native delegation does not mean that platform
routing is unverified or should be bypassed. The current operating model is the
authority for what is verified now; accepted ADRs in `docs/adr/` are the
normative record of decisions.

## Product surface and status

- The product surface is **CLI-primary** (ADR-015, operator decision in issue
  #186): the `cortxt` CLI is the source of truth for interacting with the
  platform. The external integration surface is an **MCP server**
  (`cortxt mcp serve`) per ADR-024. A thin `cortxt widget` mirrors CLI state
  (ADR-021). The legacy web prototype was removed before the first public
  release (issue #225); it is not the product surface.
- GitHub Issues are the durable records for approved scope, evidence, review,
  and decisions (ADR-018).
- Worker dispatch's workflow-state carrier is the GitHub Issue `workflow:*`
  labels (ADR-018), executed by `scripts/dispatcher.py` and the parallel
  `cortxt work` entry point (`docs/agents/work-launcher.md`).
- Delivery execution paths and the label invariant are ADR-040; Atlas maps
  (`scripts/atlas_sync.py`) are derived views, never a second backlog.
- Real customer inputs and run outputs must remain outside Git history in an
  explicitly approved, isolated workspace.

## What lives here

| Path | Role today |
| --- | --- |
| `agent-platform/` | Cortxt-owned platform boundary (reasoning, runtimes, CLI, MCP server, state, adapters). `agent-platform/reasoning/` is accepted per ADR-017; `agent-platform/adapters/inference/` holds the live provider-neutral inference adapters. |
| `verticals/` | Domain packages consumed by the agent runtime (profiles, CodingLoop) and tests — live, not historical. |
| `contracts/` | Interface schemas and contract experiments. |
| `schemas/` | Machine-readable schema definitions. |
| `scripts/` | Dispatcher, worker adapters, and profile tooling used by the platform. |
| `docs/` | Architecture and decisions for the current baseline (ADRs, operating model, dispatch contract, security). |
| `site/` | Product/documentation site source. |
| `AGENTS.md` | Agent-facing operating boundaries and coordination rules. |
| `CONTEXT.md` | Controlled vocabulary for the domain. |

Internal working documents (agent session plans, handoffs, assessments) are
kept out of the repository and archived locally.

## Build and test

- **Python package**: `agent-platform/` (requires Python ≥ 3.11; the CI runs
  3.12). Install with `pip install -e agent-platform/`; the MCP server needs
  the `mcp` extra (`pip install -e 'agent-platform[mcp]'`). Dependencies:
  `pyyaml`, `jsonschema`, `cryptography`.
- **Test command**: `pytest agent-platform/ -m "not real_inference and not
  docker_required"`. Opt-in markers: `real_inference` (real L0 model calls) and
  `docker_required` (needs a running Docker daemon) are excluded by default —
  a skip on `docker_required` is NOT a pass.
- **CI** (`.github/workflows/ci.yml`) also runs a site build from `site/`
  (Node 26, `npm ci && npm run build`) and a DCO sign-off gate on pull
  requests: every commit must carry a `Signed-off-by: Name <email>` trailer.
- **Conventional commits** are used throughout (e.g. `feat(...)`, `fix(...)`,
  `docs(...)`, `docs(review-log): ...`). Reference the issue in the commit and
  the pull request.
- All documentation is written in **English**.

## Delivery execution paths (ADR-040)

Three paths are sanctioned; every path upholds the label invariant:

1. **Dispatched runtime build** — dispatcher claim (`ready -> in-progress`),
   isolated worktree, agent runtime, result envelope, then `review -> done` on
   independent review plus operator approval.
2. **Coordinator-direct build** (fast fix) — build directly on a feature
   branch; the pull request's CI plus the operator merge are the review and
   approval gate (`ready -> in-progress` at start, `-> done` at merge).
3. **Docs/ADR materialization** — no code; feature branch plus pull request
   plus operator merge (`review -> done` in step with the merge).

## Daemon dogfood

The Supervisor Daemon (`cortxt daemon`, `agent-platform/daemon/`) is the
unattended dispatch loop: it scans GitHub for `workflow:ready` issues, claims
them, routes them to an engine, invokes the worker in an isolated worktree,
runs the Evidence Gate, and syncs review submissions (ADR-037). Dogfood it in
every session that advances ready issues.

Commands:

- `cortxt daemon start --repo owner/repo --state-dir <dir> --snapshot <file>`
  — run the dispatch loop. `--once` runs a single iteration and exits
  (testing/proof steps); `--unattended` skips forced supervised-mode pausing
  (only after a class has earned autonomy: 3 consecutive clean runs per
  engine/task-shape).
- `cortxt daemon stop --state-dir <dir>` — request a stop.
- `cortxt daemon status --snapshot <file>` — read the daemon section of the
  widget snapshot (claimed issues, budget, last gate outcome, review-sync
  counts).
- `cortxt daemon sync-review --state-dir <dir>` — mechanically transition
  submitted reviews to `workflow:review` (ADR-037); runs automatically at the
  start of each daemon iteration.

How the loop behaves (verified in `agent-platform/daemon/loop.py`):

- It lists issues via `gh issue list --label workflow:ready --state open` and
  skips issues with no routable task tag — it never guesses.
- It persists the claim **before** dispatching: a crash window produces a
  stuck claim (visible in `claimed.json`, requires manual clear), never a
  duplicate real-world dispatch.
- Each dispatch gets its own git worktree and branch `daemon/<issue-id>`,
  created from the daemon's working directory. The daemon **never removes
  them**: branch cleanup and merge are operator decisions.
- It sends the full issue body as the prompt and treats a "succeeded" report
  with no landed commit as a failure — the Evidence Gate checks a real
  signal, not self-reported status.
- Default is supervised mode (`supervised=True`): a clean run pauses for
  review rather than continuing unattended. Operator approval remains the
  final gate; the default unattended path for real build issues is not yet
  the exercised default (see `docs/agents/current-operating-model.md`).

Session discipline:

- Advance `workflow:ready` issues through the daemon or `cortxt work`
  (`docs/agents/work-launcher.md`) instead of ad-hoc manual execution, and
  observe the loop via `cortxt daemon status`.
- Run `cortxt daemon sync-review` before claiming new work so submitted
  reviews land on `workflow:review` first.
- Never clean up or merge a `daemon/<issue-id>` branch/worktree without an
  operator decision; never bypass the Evidence Gate.

## Session coordination

Parallel sessions coordinate deliveries through a file-based inbox outside the
repository at `lab/inbox/` (workspace-local, never tracked). Conventions:

- Each session has an `out/` and `in/` directory under `lab/inbox/`.
- A session that produces something another session (or the coordinator)
  should see writes a message file to `lab/inbox/<target>/in/` with YAML
  frontmatter: `from`, `to`, `type` (`delivery` | `request` | `handoff`),
  `created`, `artifact`, `affects`.
- The coordinator reads `lab/inbox/*/in/` at the start of each work round and
  presents new messages; consumed messages move to `lab/inbox/done/`.
- Messages are English, zero a/o/u-with-diacritics, and contain no secrets,
  prompts, or model reasoning — only artifact pointers plus a short
  description.
- See `lab/DESIGN-session-injection.md` for the design; this is its v1.
- `scripts/session_inbox_contract.py` is a read-only checker for this
  contract (frontmatter fields, `type`, diacritics, artifact existence). It
  never writes to, moves, or deletes anything under `lab/inbox/`.

Handoffs live in `lab/` (workspace-local, never tracked) and are the durable
start point for each session; the inbox supplements them with live deliveries
between running sessions.

## Guardrails against common misreadings

Do not:

- treat any external runtime (Hermes, Pi, Codex, DSH, Buzz) as the product —
  they are replaceable resources behind Cortxt-owned ports (ADR-014/016);
- treat the removed legacy web prototype as a product surface — the CLI is
  primary (ADR-015/021, issues #186 and #225);
- invent a second backlog or independent Kanban outside GitHub;
- describe a successful smoke test as a finished production workflow;
- add a new entry point before checking whether it preserves the dispatch
  contract and existing component ownership;
- bypass the operator's approval over irreversible decisions.

## Authority and reconciliation

For implementation and runtime behavior, this repository and its architecture
contracts are authoritative. Accepted ADRs in `docs/adr/` are the normative
record of decisions. If a document and an ADR disagree, stop and reconcile the
conflict rather than silently selecting one account. See `CONTEXT.md` for the
controlled vocabulary and `docs/style-guide.md` for writing rules.
