# Cortxt OS app identity, responsibilities, and contracts

Date: 2026-08-28
Issue: rian010194/cortxt#422
Status: design proposal, awaiting operator review; no implementation in this issue.

## Purpose

Define the real app boundaries of Cortxt OS before any app gains richer content.
Work Console, Decisions, Evidence, and Studio must not remain different views of
one generic app; Execution Inspector, Policies, Atlas, and Connections need clear
distinct roles. This document fixes, for each app: **identity** (what it is),
**responsibility** (what it owns and does not own), **navigation** (how it is
reached and how it relates to other apps), **state** (what it reads/writes; what
is shell-owned vs app-local vs platform-owned), and **contract** (which
ADR-038 widget-contract reads/actions it uses, or its explicit non-widget
surface).

Boundaries that bind this document (normative):

- **ADR-042**: the shell owns presentation, app lifecycle, focus, navigation,
  layout, persistence, command/search, and notifications; the shell does NOT own
  workflow, mandate, evidence, decisions, or approval state. Apps share the
  selected Workstream through a shell-owned context contract; they do not fork
  domain state or couple directly to Work Console. Work Console is the default
  app. Studio configures or authors apps/compositions and is not the launcher or
  the product identity.
- **ADR-038**: any app surface is expressed through the declarative widget
  contract (typed reads/render/actions, authorized action ports) and must not
  widen authority. Widgets are inert projections over platform-owned state.
- **ADR-043**: canonical design-system tokens; no private palette.
- **CONTEXT.md**: controlled vocabulary (Workstream, Run, Agent Session, Lane,
  Segment, Workspace, Issue, Workflow state).

## Workstream context contract (shell-owned)

The shell provides the **selected Workstream** to every mounted app:

- What the shell provides: a single `context.workstreamId` (persisted), the
  current Workstream projection (id, title, outcome, workflow, attention,
  decision, evidence, authority, acceptance criteria) and the fail-closed
  data-loading boundary (synthetic vs local mode).
- What an app may read: the Workstream projection and the shell mode banner.
- What an app may NEVER do: fork or duplicate Workstream/domain state; couple
  directly to Work Console; mutate platform authority (workflow labels, mandate,
  evidence, decisions) except through a registered authorized action port with
  operator approval; own the selection (selection changes are shell actions).
- App-local state (e.g. Work Console's sub-view) stays in `state.apps[appId]`,
  persisted under the single shell key; it never becomes authoritative.

## App definitions

### Work Console
- Identity: the operator's default app; the work- and mandate-first home.
- Responsibility: active Workstreams, desired outcomes, pending human decisions,
  mandate/policy blocks, evidence requiring review; entry point into a
  Workstream's mandate, progress, evidence, decisions, and execution.
- Does not own: workflow state, mandate, decisions, approval; it projects them.
- Navigation: default app, opened at cold start; opens review surfaces and
  related apps (Decisions, Evidence).
- State: reads Workstream projections; app-local view state only.
- Contract: ADR-038 widget surface with `workstream.summary.v1`-class reads and
  the `record-decision` action (review -> done) behind the operator gate.

### Decisions
- Identity: the authority app for human decisions on Workstreams.
- Responsibility: pending decisions and their evidence in one place; the single
  authorized approve action (workflow:review -> workflow:done) with approval
  reference and explicit confirmation; fail closed without reviewed authority.
- Does not own: the decision itself until the operator acts; cannot define scope.
- Navigation: related app reachable from Work Console and shell chrome; reflects
  the selected Workstream.
- State: reads pending-decision projection; writes only via the authorized
  action port.
- Contract: ADR-038 with `decision.pending.v1` read and `workflow.record-decision.v1`
  action (github-transition port, operator mode).

### Evidence
- Identity: the attribution app for accepted and candidate evidence.
- Responsibility: show evidence per Workstream and per Run; distinguish accepted,
  complete, and conflicting evidence; keep evidence attributable.
- Does not own: acceptance; acceptance is a decision action in Decisions.
- Navigation: related app; opens from review surfaces and shell chrome.
- State: reads evidence projections; no writes in this phase.
- Contract: ADR-038 with `evidence.comparison.v1`-class reads; read-only.

### Studio
- Identity: the authoring/configuring app for apps and compositions.
- Responsibility: configure or author apps/compositions under ADR-038; a
  workspace for composition specs.
- Does not own: launching apps, the OS identity, product identity, or domain
  authority. Studio is not the launcher and not the product.
- Navigation: a windowed app; iframe-hosted Widget Maker surface.
- State: composition drafts only; never platform authority.
- Contract: ADR-038 composition surface; deferred in the shell registry today.

### Execution Inspector
- Identity: the operations/diagnostics app (ADR-042 item 3 reframed, canonical
  name per amendment D).
- Responsibility: agent/runtime participants, sessions, terminals/logs,
  pipelines, execution timelines, workspaces/worktrees/sandboxes,
  provider/engine detail, cost/usage — available from a Workstream.
- Does not own: durable work authority; it is subordinate diagnostics.
- Navigation: from a Workstream; not the product entry point.
- State: reads run/session/lane projections; read-only.
- Contract: ADR-038 read surfaces over session/execution-map data; planned as an
  operator surface (issue E).

### Policies
- Identity: the policy surface for mandate/provider rules and data-class limits.
- Responsibility: show applicable policies per Workstream/Work (mandate,
  provider policy, data class, evidence gates).
- Does not own: policy decisions; it projects platform policy state.
- Navigation: related app from a Workstream.
- State: reads policy projections; read-only in this phase.
- Contract: ADR-038 reads; planned as an operator surface (issue E).

### Atlas
- Identity: the roadmap/map surface derived from GitHub Issues (issue #210;
  `scripts/atlas_sync.py`), never a second backlog.
- Responsibility: show roadmap maps and derived views; correlate to issues.
- Does not own: backlog state; it is a derived projection.
- Navigation: shell app; opens the Atlas view for the selected context.
- State: reads atlas-derived projections; read-only.
- Contract: ADR-038 reads over atlas data; distinct role from Work Console
  (planning vs operations) (issue F).

### Connections
- Identity: the integration surface for external systems (webhooks, providers,
  runtimes, MCP consumers).
- Responsibility: show and manage integration state (webhooks, adapters,
  providers) behind authorized action ports.
- Does not own: the integrations' authority; mutations only via authorized ports.
- Navigation: shell app; distinct from Atlas and Policies.
- State: reads connection/webhook projections; authorized writes only.
- Contract: ADR-038 reads + authorized action ports (issue F).

## ADR-038 mapping summary

| App | Reads | Actions | Ports | Notes |
|---|---|---|---|---|
| Work Console | workstream summary, attention | record-decision | github-transition | default app |
| Decisions | decision pending | record-decision | github-transition | operator-gated |
| Evidence | evidence comparison | — | — | read-only |
| Studio | composition drafts | composition authoring | cli (allow-listed) | deferred today |
| Execution Inspector | session/execution-map | — | — | planned (E) |
| Policies | policy projections | — | — | planned (E) |
| Atlas | atlas maps | — | — | planned (F) |
| Connections | webhook/connection | authorized mutations | mcp/cli | planned (F) |

## Proposed issue breakdown (C/D/E/F)

| Issue | Title (proposal) | File scope (non-overlapping) | Depends on | Kind |
|---|---|---|---|---|
| C | Build: Work Console complete operator app | `agent-platform/widget_contract/` (work-console reads), `agent-platform/widget/work-console.js` console panels, `site/public/widgets/` mirror, fixtures | B (this doc) | delivery |
| D | Build: Decisions and Evidence authority journey | `agent-platform/widget_contract/` (decision/evidence reads+action), `agent-platform/widget/work-console.js` decisions/evidence windows, `action_host.py`, fixtures | B | delivery |
| E | Plan: Execution Inspector and Policies operator surfaces | `docs/` (scoping) only | B | docs |
| F | Plan: Atlas, Connections, Studio distinct roles | `docs/` (scoping) only | B | docs |

Non-overlap: C owns Work Console panel + its contract reads; D owns Decisions/
Evidence windows + their reads/action; E and F are docs-only. No file is shared
between C and D except `work-console.js` (the shell file) — C and D must either
be sequenced or split that file's ownership explicitly; recommendation:
sequence C then D on separate branches, or give D its own window renderer
module. C/D run only after operator approval of this design.

## Consistency check

- ADR-042: this document keeps authority out of the shell and apps; every
  mutation is a registered authorized action port. Pass.
- ADR-038: every surface is mapped to the widget contract; no bespoke
  authority-widening surface. Pass.
- ADR-043: no new palette; all apps consume canonical tokens. Pass.
- CONTEXT.md: vocabulary used consistently (Workstream, Run, Issue, Workspace).
  Pass.
- Conflicts flagged: none blocking; `docs/superpowers/` is gitignored, so this
  design deliberately lives in the tracked `docs/design/` path.

## Supersedes / absorbs

- Issue #416 (research: OS current-state architecture) and #417 (diagnosis: OS
  test gaps) remain open and `workflow:blocked`; this design absorbs their
  intent (architecture mapping, acceptance coverage). The operator may close or
  retry them separately; no automatic transition performed here.
