---
title: Status and roadmap (Atlas)
description: Live-derived status page for the Cortxt roadmap, generated from Atlas maps.
---

## Roadmap status

This page is derived automatically from the [Atlas roadmap maps](
https://github.com/rian010194/cortxt/issues/214) -- the GitHub issues remain the single source of truth. Last successful sync: `2026-08-22T23:15:16Z`.

### Roadmap areas

- **MCP lifecycle and dispatch stack** -- milestone: Open-source product packaging, open: 0, closed: 4

### Actionable frontier

- CI fixture: real dispatch commit proof (#207)
- Build: cortxt mandate CLI — operator issuance + inspect surface (ADR-032 Open Question) (#281)

Claimed work in progress (workflow:in-progress):
(none)

### Blockers

(none)

### Milestone overview

- Open-source product packaging: open 0, closed 4
- Vertical 01 v0.1: open 0, closed 7
- Web surface decision: open 0, closed 1

### Discipline violations (one workflow:* label required)

(none)

### Review evidence

- CORTXT T5-001 — Deterministic provider-assurance policy gate (#103): contract fit = MISSING; repository fit = MISSING
- CORTXT T5-002 — Offline provider-policy CLI and synthetic fixtures (#105): contract fit = MISSING; repository fit = MISSING
- CORTXT T1-001 — Local resumable capability state with evidence chain (#107): contract fit = MISSING; repository fit = MISSING
- CORTXT VERTICAL-002 — Provider-resilient model execution (#108): contract fit = MISSING; repository fit = MISSING
- Minimal end-to-end-dispatcher for wedge B (#122): contract fit = MISSING; repository fit = MISSING
- CI-pipeline: scope maste beslutas (#126): contract fit = MISSING; repository fit = MISSING
- ADR-021: formally reopen ADR-015 for v.02 admin surface + widget UI (#157): contract fit = MISSING; repository fit = MISSING
- Threat model: centralized credential broker for connected agent tools (#158): contract fit = MISSING; repository fit = MISSING
- Research: capability-manifest extension points for Fas 3 (no build, no decisions) (#159): contract fit = MISSING; repository fit = MISSING
- Research: real cost math for Fas 6 pricing (no pricing decision) (#160): contract fit = MISSING; repository fit = MISSING
- Fas 2: orkestrator-i-CLI grundskelett — koppla widget/CLI mot verklig sessionsstate (#165): contract fit = MISSING; repository fit = MISSING
- Fas 2 follow-up: finish widget wiring + fix review findings from #165 (#166): contract fit = MISSING; repository fit = MISSING
- cortxt runtimes + cortxt credentials CLI (Fas 4 admin-surface wiring) (#174): contract fit = MISSING; repository fit = MISSING
- cortxt addons CLI (Fas 5 admin-surface wiring) (#175): contract fit = MISSING; repository fit = MISSING
- License: switch to Apache-2.0 (open source) (#182): contract fit = MISSING; repository fit = MISSING
- fix(ci): gate test_subprocess_windows on Windows (Linux CI red) (#183): contract fit = MISSING; repository fit = MISSING
- Builder workers: enable write permission for subagent-claude-code (dontAsk blocks writes) (#189): contract fit = MISSING; repository fit = MISSING
- SDK name collision: rename agent-platform/mcp to cortxt_mcp (first workflow:ready dispatch) (#202): contract fit = MISSING; repository fit = MISSING
- Dispatch follow-up: worker invocation cannot run in current sandbox (default DSH model route + shell EPERM) (#204): contract fit = MISSING; repository fit = MISSING
- Atlas: automated roadmap maps on top of GitHub issues (global + per-area, auto-synced + coordinator-driven) (#210): contract fit = MISSING; repository fit = MISSING
- Website + docs site: Astro + Starlight on Cloudflare Pages (cortxt.io / docs.cortxt.io) [#185 build] (#211): contract fit = MISSING; repository fit = MISSING
- Visual identity: unified design across CLI, widget, and web (landing + docs) (#217): contract fit = PASS - AC 1-6 verified by Hermes independent review (lab/hermes-review-identity-217.md); scope + design direction per issue comments 2026-08-22; PR #218.; repository fit = PASS - CI green (site-build, agent-platform-tests, agent-platform-docker-tests, web-checks, adr-doc-currency, CodeRabbit); zero a/o/u-with-diacritics; no semantic/contract changes.
- Parallel work launcher: CLI + widget + MCP to generate and start many jobs at once (#219): contract fit = MISSING; repository fit = MISSING
- ADR-018: record clarifying amendment (map exemption, authority separation, single-process atomicity) (#223): contract fit = MISSING; repository fit = MISSING
- ADR-032: enforce max_runtime_seconds as an authorized v1 bound (#224): contract fit = MISSING; repository fit = MISSING
- Public readiness: implement DCO contribution policy and exclude legacy web/ from first release (#225): contract fit = MISSING; repository fit = MISSING
- MCP step 2: mandate-bound run lifecycle tools (create/resume/submit_for_review) (#230): contract fit = MISSING; repository fit = MISSING
- Phase 6 embeddings: ADR-035 (provider decision) + reproducible live exit evidence + first wiring slice (#233): contract fit = MISSING; repository fit = MISSING
- ADR-033 implementation: versioned mandate signing keys (kid keyring) + overlap rotation + revocation store (#241): contract fit = MISSING; repository fit = MISSING
- Free-tier inference route: hermes-free manifest entry + env-configurable model/provider via Hermes (#243): contract fit = MISSING; repository fit = MISSING
- MCP research lifecycle step 3: asynchronous create + cortxt_run_status polling (#245): contract fit = MISSING; repository fit = MISSING
- MCP lifecycle dogfood: real external client end-to-end proof (async create -> status -> submit) (#247): contract fit = MISSING; repository fit = MISSING
- MCP lifecycle step 4: daemon review-sync pass consuming review_submission_id (#249): contract fit = MISSING; repository fit = MISSING
- Widget platform design: composable data/action widgets + parallel-execution map (#251): contract fit = MISSING; repository fit = MISSING
- ADR-037 live acceptance proof: real daemon review-sync GitHub transition (#252): contract fit = MISSING; repository fit = MISSING
- hermes-free free-tier route live arm (issue #243 follow-up) (#253): contract fit = MISSING; repository fit = MISSING
- Fast fix: parallel builder isolation via git worktrees (scripts/parallel_dispatch.py) (#257): contract fit = MISSING; repository fit = MISSING
- Build: widget contract foundation (schema, loader, registry, read-only renderer) — ADR-038 (#259): contract fit = MISSING; repository fit = MISSING
- Build: candidates widget vertical slice (all open issues, frontier first) under `cortxt widget` (#260): contract fit = MISSING; repository fit = MISSING
- Build: execution map core and durable claims (graph, collision, pre-flight) — ADR-039 (#261): contract fit = MISSING; repository fit = MISSING
- Build: coordinator and launcher execution-map integration (parallel-safe dispatch) (#262): contract fit = MISSING; repository fit = MISSING
- Phase 7 v2 self-hosted live arm: Vast.ai status + liveness proof (read-only) (#263): contract fit = MISSING; repository fit = MISSING
- Materialize ADR-038 + ADR-039 (Proposed) from the widget-platform design (#265): contract fit = MISSING; repository fit = MISSING
- Build: candidates view rendered through the widget contract into the loopback browser widget (#274): contract fit = MISSING; repository fit = MISSING
- Build: first authorized action ports — mark-ready (operator gate) + claim/run through the execution map (#276): contract fit = MISSING; repository fit = MISSING
- Build: Open in CLI handoff controls in the browser candidates view (#278): contract fit = MISSING; repository fit = MISSING
- Build: session-pulse widget — contract-compliant orchestrator/session state view (#282): contract fit = MISSING; repository fit = MISSING

### Relationship drift

(none)

### Last successful sync

2026-08-22T23:15:16Z
