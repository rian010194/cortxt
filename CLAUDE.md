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
   README.** Before evaluating the architecture, proposing a new execution
   path, or dispatching work, read the orientation documents in the order given
   under "What to read for the work you have".

7. **Accepted ADRs are normative.** When you change an Accepted ADR, add a row
   to `docs/architecture/REVIEW_LOG.md` in the same pull request (the
   `adr-doc-currency` CI gate enforces this).

## What to read for the work you have

Read what your task needs. No worker has to load the whole roadmap.
`docs/README.md` is the navigation and authority map for everything below.

**A bounded fix** — a defect, a test, a documentation correction, one file or
one contract you already know:

1. The GitHub issue: scope, acceptance criteria and limits.
2. The non-negotiable rules above and "Build and test" below.
3. The contract or guide the change touches (`docs/README.md` names them).

**Architecture, planning or dispatch** — proposing an execution path,
evaluating the architecture, or starting work for someone else. Read in order:

1. `docs/agents/current-operating-model.md`
2. `docs/architecture/dispatch-contract.md`
3. `docs/architecture/runtime-and-evaluation-harness.md`
4. `docs/agents/atlas.md` — roadmap maps derived from GitHub Issues (#210)
5. The GitHub issue and any explicitly designated current planning state

A limitation in one runtime's native delegation does not mean that platform
routing is unverified or should be bypassed. The current operating model is the
authority for what is supported now; Accepted ADRs in `docs/adr/` are the
normative record of decisions. A Proposed ADR binds nothing.

## Product surface and status

- Per **ADR-042/044**, Cortxt is **work- and mandate-first**: durable
  authority, replaceable execution. Cortxt OS is the general shell and
  first-party app runtime; Work is its first principal app, not the identity
  of the OS. Both remain under active development. The `cortxt` CLI remains the local,
  automation, bootstrap, diagnostic, and power-user interface (ADR-015/021,
  issue #186) and today is the most complete verified interface. The
  external, mandate-protected integration surface is an **MCP server**
  (`cortxt mcp serve`) per ADR-024/032. A thin `cortxt widget` surface
  provides declarative views/apps (ADR-021/038), not a top-level product
  category. The legacy web prototype removed before the first public release
  (issue #225) is unrelated history. Work Console is retired by ADR-044 with a
  bounded compatibility migration to Work.
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
- **`scripts/` suites are not covered by that command.** `pytest
  agent-platform/` never descends into `scripts/`, and several `scripts/`
  suites are `main()`-style programs that a `pytest` path would collect as
  zero tests while still reporting green. Run them as programs:
  `python scripts/<test_file>.py` (exit 0 = pass). The four dispatch-path
  suites — `test_dispatcher.py`, `test_worker_adapters.py`,
  `test_work_launcher.py`, `test_launcher_integration.py` — are run this way
  by the `dispatch-path-tests` CI job, one process each, because they share
  `sys.modules["dispatcher"]`, the process-wide `ADAPTER_REGISTRY` and
  `CORTXT_BOUNDED_WORKER` and are not isolated from one another in a single
  interpreter. They need no dependencies beyond the standard library and use
  fake GitHub, fake providers and temporary state only — but they do need
  `PYTHONPATH=agent-platform`, because `worker_adapters` imports
  `routing.worker_outcome` (#520) from a package `scripts/` does not put on
  `sys.path`. An editable install of `agent-platform` supplies that import on a
  developer machine, which is why a suite can pass locally and fail in CI; set
  the variable rather than relying on the install.
- **CI** (`.github/workflows/ci.yml`) also runs a site build from `site/`
  (Node 26, `npm ci && npm run build`) and a DCO sign-off gate on pull
  requests: every commit must carry a `Signed-off-by: Name <email>` trailer.
- **Conventional commits** are used throughout (e.g. `feat(...)`, `fix(...)`,
  `docs(...)`, `docs(review-log): ...`). Reference the issue in the commit and
  the pull request.
- All documentation is written in **English**.
- UI changes follow ADR-043 and `docs/design/global-design-system.md`. Run
  `python scripts/design_system_conformance.py`, keep generated token artifacts
  synchronized, and include relevant desktop/narrow, focus, preset, and
  reduced-motion evidence.

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

## Current execution boundary

Milestone A is **OS -> WorkLauncher -> Dispatcher**: start, follow, review and
retry work that is *already approved*. Milestone B — originating and approving
new mandates in the OS — comes after it and is not implied by finishing A.
Adapting Supervisor Daemon dispatch to the mandate-and-Run chain is deferred to
W15, outside Milestone A's acceptance: do not require daemon dispatch for
routine work, and do not treat registration in the daemon's runtime context as
WorkLauncher eligibility.

Deferring daemon dispatch does **not** defer review-sync. Run `cortxt daemon
sync-review --state-dir <dir>` against the intended state directory as the
delivery path requires, so durably submitted reviews land on `workflow:review`.
Never bypass the Evidence Gate, and never clean up or merge a `daemon/<issue-id>`
branch or worktree without an operator decision. Diagnostic daemon status is not
OS end-to-end proof.

`docs/agents/current-operating-model.md` holds the detail: which adapter
registries exist, why they are not interchangeable, and what today's evidence
does and does not establish. `docs/agents/running-cortxt-os.md` and
`docs/agents/work-launcher.md` are the practical guides.

## Cost-effective use of harnesses and models

Optimize **accepted delivery** under the operator's quality, time and budget
constraints — not cheapest-model-first. Weigh harness and model suitability,
subscription quota, provider charges, retries, handoffs, review effort and
operator time. The routing manifest is static bootstrap configuration, not a
measured optimizer.

Give a worker a coherent bounded unit with explicit acceptance criteria. Use
scripts for mechanical checks and compact evidence at handoffs rather than
having several premium sessions repeat every planning, execution and monitoring
step. Required independent review still applies. Additional workers, paid calls,
fallback routes and scope changes must fit an existing mandate; this guidance
does not authorize them.

## Session coordination

Parallel sessions coordinate deliveries through a file-based inbox outside the
repository at `lab/inbox/`, alongside handoffs in `lab/` — both workspace-local
and never tracked. `AGENTS.md` states the conventions and the read-only checker
that enforces them; that is the single copy, so change it there.

Handoffs and the inbox are **supplemental**. Everything required to do the work
is in the repository: an agent starting from a clean checkout must not be
missing an instruction because a local file is absent.

## Guardrails against common misreadings

Do not:

- treat any external runtime (Hermes, Pi, Codex, DSH, Buzz) as the product —
  they are replaceable resources behind Cortxt-owned ports (ADR-014/016);
- treat the removed legacy web prototype as a product surface or as the origin
  of Work — it is unrelated history (issues #186 and #225);
- treat Work as the identity of Cortxt OS, call the Work app Workspace, or
  describe the OS or Work as fully shipped (ADR-044);
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
