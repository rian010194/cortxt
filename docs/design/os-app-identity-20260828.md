# Cortxt OS app identity, responsibilities, and contracts

Date: 2026-08-28
Issue: rian010194/cortxt#422
Status: Reconciled with accepted ADR-044 on 2026-08-28; implementation remains separately gated.

## Purpose

Define the boundary between Cortxt OS system surfaces, registered first-party
apps, and Cortxt-owned authoritative state. ADR-044 supersedes this document's
earlier proposal to make Work Console the mandatory default app. Work Console
is retired through a bounded compatibility migration; Work is the first
principal app but is not the identity of the OS.

## Normative boundaries

- **ADR-042**: Cortxt is work- and mandate-first. Durable authority survives
  replaceable execution.
- **ADR-044**: Cortxt OS is a general first-party app runtime. Work is its first
  principal app; Home and Activity Center are system surfaces; Workspace keeps
  its execution-resource meaning.
- **ADR-038**: apps consume typed reads and request mutations through
  authorized action ports. UI composition cannot widen authority.
- **ADR-043**: every system surface and app consumes the canonical design
  system through its declared adapter.
- **CONTEXT.md**: Work, Workstream, Workspace, App, System surface, and
  Attention item are distinct controlled terms.

The shell owns presentation, app lifecycle, focus, navigation, layout,
persistence, validated commands, global context, search, notifications, and
system chrome. It owns no workflow, mandate, evidence, decision, policy, or Run
authority.

## Context and state contract

The shell may provide an active Workstream and focused record reference to a
mounted app. These bindings are optional: an app that does not require a
Workstream must be able to register and run without one.

State remains separated:

- shell state owns open apps, focus, layout, global context, and system-surface
  presentation;
- app-local state owns only that app's presentation preferences;
- authoritative platform state owns Workstreams, mandates, workflow, Runs,
  evidence, decisions, and policy; and
- synthetic mode projects deterministic data and exposes no authoritative
  mutations.

An app may never fork domain state, read another app's private state, invoke
another app's renderer, or mutate authority outside a registered action port.

## System surfaces

### Home

Home is the entry, resume, onboarding, discovery, and product-status surface.
It is not a domain app and owns no Workstream state.

### Activity Center

Activity Center is the shell-owned cross-app attention surface. It consumes
typed Attention item projections, may group or deduplicate them, and dispatches
validated commands to the responsible app and source record. Read, dismissed,
grouping, and filter state are local presentation state.

Activity Center cannot approve, mutate workflow state, own a decision request,
become a backlog, or reproduce a complete app workflow.

### Other system surfaces

Launcher, dock, global Workstream router, search/command entry, and
profile/settings are system surfaces. Their presence does not make their
referenced domain state shell-owned.

## Registered apps

### Work

- **Identity:** first principal work- and mandate-first app, app ID `work`.
- **Responsibility:** present one coherent surface for the selected Workstream:
  outcome, mandate summary, progress, blockers, next meaningful action,
  decision and evidence summaries, milestones, and related resources.
- **Does not own:** Workstream, workflow, mandate, decisions, evidence,
  approval, or execution state.
- **Navigation:** opens the responsible deep app with the exact Workstream and
  record context. It is not permanently pinned and need not remain open.
- **Contract:** versioned Workstream projections and validated app commands;
  no private cross-app calls.

### Decisions

- **Identity:** authority app for human decisions on Workstreams.
- **Responsibility:** present pending decisions and their evidence; request the
  authorized approval transition with explicit confirmation and approval
  reference.
- **Does not own:** scope or workflow state before the operator acts.
- **Contract:** `decision.pending.v1`-class reads and the
  `workflow.record-decision.v1` authorized action.

### Evidence

- **Identity:** attribution app for accepted and candidate evidence.
- **Responsibility:** distinguish accepted, complete, incomplete, and
  conflicting evidence per Workstream and Run.
- **Does not own:** evidence acceptance; Decisions owns the operator action.
- **Contract:** `evidence.comparison.v1`-class reads; read-only in this phase.

### Execution Inspector

- **Identity:** operations and diagnostics app subordinate to a Workstream.
- **Responsibility:** Runs, agent/runtime participants, sessions, timelines,
  terminals and logs, Workspaces, worktrees, sandboxes, provider/engine detail,
  cost, and usage.
- **Does not own:** durable work authority.
- **Contract:** read surfaces over session and execution-map projections.

### Policies

- **Identity:** policy explanation surface.
- **Responsibility:** show applicable mandate, provider, data-class, and
  evidence-gate rules.
- **Does not own:** policy authority or decisions.
- **Contract:** policy projections; read-only in the initial phase.

### Atlas

- **Identity:** roadmap and map surface derived from GitHub Issues.
- **Responsibility:** show derived planning views and issue correlations.
- **Does not own:** backlog or workflow state.
- **Contract:** read-only Atlas projections.

### Connections

- **Identity:** external integration surface.
- **Responsibility:** show and manage webhooks, adapters, providers, runtimes,
  and MCP consumers through authorized ports.
- **Does not own:** an integration's external authority.
- **Contract:** connection reads and explicitly authorized mutations.

### Studio

- **Identity:** authoring and configuration app for declarative compositions.
- **Responsibility:** edit composition drafts under ADR-038.
- **Does not own:** app launching, OS identity, domain authority, or the app
  distribution model.
- **Contract:** deferred composition surface; third-party app installation is
  outside S5.5.

## Registration contract

Each app declares:

```text
id
version
title
routes
requiredCapabilities
providedCommands
contextBindings
lifecycleMode
supportedFormFactors
```

The S5.5 slice must prove that Work registration adds no Work-specific branch
to shell core, an app without Workstream context can register and open, and all
mutations pass through authorized action ports.

## Compatibility boundary

For one release cycle, `#app=work-console` and saved `work-console` state
resolve to `work` while preserving the selected Workstream, favorites, and
other open apps. Removing the alias requires a separate operator decision.

The S5.5 implementation remains blocked until S5 passes its operator merge
gate, its issue reaches `workflow:done`, the integration branch is synchronized,
the S5.5 brief adopts the `work` identity, and the operator approves the first
implementation slice.
