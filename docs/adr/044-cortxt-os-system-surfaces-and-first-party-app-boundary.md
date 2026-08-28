# ADR-044: Cortxt OS system surfaces and first-party app boundary

**Status:** Accepted (2026-08-28)  
**Date:** 2026-08-28  
**Deciders:** Rikard (operator; approved 2026-08-28)  
**Technical Story:** S5.5 simplified information architecture and retirement of Work Console

## Context

ADR-042 established Cortxt as work- and mandate-first and placed durable
Workstream authority above replaceable execution. Its pre-acceptance amendment
also named Work Console as the default Cortxt OS app. Subsequent shell work
introduced app registration, an unpinned session model, shell commands, deep
links, workstream context, Home, and dock/launcher separation. Work Console no
longer has a unique responsibility: workstream selection belongs to the global
router, attention belongs to a cross-app system surface, records belong to
Evidence, decisions belong to Decisions, and execution detail belongs to
Execution Inspector.

The S5.5 proposal calls the replacement primary app `Workspace`. The controlled
vocabulary already defines a Workspace as the optional Git branch and worktree
attached to a Workstream. Reusing that name for a product app would conflate
durable work with an execution resource and make the product language
ambiguous.

The architecture must now distinguish three kinds of product surface without
creating another source of authority: the Cortxt OS shell and its system
surfaces, first-party apps over Cortxt-owned contracts, and authoritative Core
state, which neither the shell nor an app may duplicate.

## Decision

Cortxt adopts the following boundary:

1. **Cortxt OS is a general shell and first-party app runtime.** It owns app
   registration and lifecycle, focus, windows, navigation, deep links, global
   context routing, presentation persistence, commands, search, notifications,
   and system chrome. It owns no Workstream, mandate, workflow, evidence,
   decision, policy, or Run authority.
2. **Work is the first work- and mandate-first app, not the identity of the
   operating system.** Its canonical app identifier is `work`, its initial
   route is `/work`, and it presents one coherent primary surface for the
   selected Workstream. It summarizes authoritative state and opens the app
   that owns each deeper interaction.
3. **Workspace retains its controlled domain meaning.** A Workspace is the
   optional Git branch and worktree attached to a Workstream. Product UI and
   contracts must not use `Workspace` as the name or identifier of the Work
   app.
4. **Work Console is retired rather than renamed.** The app identifier
   `work-console` is removed after an additive state migration. For one release
   cycle, saved state and deep links resolve `work-console` to `work`. Removing
   that compatibility alias requires a separate operator decision.
5. **Home and Activity Center are system surfaces.** Home is the entry,
   resume, onboarding, and discovery surface. Activity Center is a shell-owned
   attention surface. Neither is a domain authority or a second backlog.
6. **Activity Center consumes typed attention projections.** It may group,
   deduplicate, filter, mark read locally, dismiss locally where allowed, and
   dispatch a validated command to the responsible app and record. It may not
   approve, mutate workflow state, own decision requests, or reproduce an
   app's complete workflow.
7. **Apps integrate through versioned contracts.** Each registered app
   declares its identity, routes, required capabilities, provided commands,
   context bindings, lifecycle mode, and supported form factors. Apps read
   projections and request mutations through authorized action ports. They do
   not call another app's renderer or private state.
8. **Global context is optional and explicit.** The shell may provide an
   active Workstream and focused record reference, but an app that does not
   require a Workstream must be able to register and run without one. App-local
   state remains separate from shell presentation state and authoritative Core
   state.
9. **No first-party domain app is permanently pinned or required to remain
   open.** Work may be preinstalled, favored in onboarding, and presented as
   the principal app without becoming a shell invariant. The shell remains
   usable with no app window open.
10. **The S5.5 implementation remains a bounded first-party slice.** This
    decision does not authorize third-party app installation, an app
    marketplace, remote code loading, a new UI framework, or a general plugin
    sandbox.

## Attention projection boundary

An Activity Center item is a read-only presentation model, not an event,
decision request, workflow record, or notification authority. Its minimum
contract is versioned and includes:

```text
AttentionItemProjection
  id
  sourceCapability
  sourceRecordRef
  sourceVersion
  workstreamId?
  occurredAt
  severity
  requiresAttention
  title
  summary
  targetCommand
  dedupeKey?
  expiresAt?
```

The responsible app or Core capability owns the source record. Activity Center
owns only local presentation state such as read, dismissed, grouping, and
filter preferences.

## Relationship to ADR-042

ADR-042's core decision remains in force: Cortxt is work- and mandate-first,
and durable authority survives replaceable execution. ADR-044
supersedes only the parts of ADR-042 amendment B and C that require Work
Console to be the automatically opened default app and describe related apps
through Work Console. The Execution Inspector naming and all authority,
widget, CLI, MCP, and secure-execution boundaries remain unchanged.

## Consequences

### Positive

- A future first-party app can use Cortxt OS without pretending that its
  primary object is a Workstream.
- Work can evolve quickly without turning its private navigation or state into
  shell architecture.
- Activity Center provides cross-app attention without becoming an inbox or
  approval surface.
- Existing `Workspace` language stays aligned with the execution model.
- Work Console retirement has a bounded, reversible migration path.

### Negative

- The S5.5 brief, manifest proposal, migration names, deep links, tests, and
  mockups must replace `workspace` app identity with `work`.
- Current operating documentation still names Work Console as the default app
  until this ADR is accepted and materialized.
- A small app and command contract must stabilize earlier than the Work UI
  otherwise requires.

### Risks

- The shell may become a speculative general-purpose platform before a second
  real app proves the abstractions. S5.5 therefore adds only contracts exercised
  by current first-party surfaces.
- Activity Center may drift into a second backlog. Contract and acceptance
  tests must prohibit authoritative mutations and full embedded workflows.
- `Work` may still be confused with a Workstream. UI copy must use Work for the
  app and Workstream for the durable domain object.

## Alternatives considered

1. **Keep Work Console as the default app.** Rejected because its
   responsibilities have moved to the router, Activity Center, Work, Decisions,
   Evidence, and Execution Inspector.
2. **Rename Work Console to Workspace.** Rejected because Workspace already
   names an execution resource in the controlled vocabulary.
3. **Make the primary work surface shell-owned.** Rejected because it would
   duplicate app routing, lifecycle, deep-link, capability, mobile, and
   persistence mechanisms.
4. **Make Activity Center a registered app.** Rejected because cross-app
   attention, like the launcher and global router, is a system concern; its
   source records remain app- or Core-owned.
5. **Build a third-party plugin platform now.** Rejected because no current
   S5.5 acceptance criterion requires installation, untrusted code execution,
   signing, distribution, or a marketplace.

## Acceptance and materialization gate

Acceptance of this ADR authorizes documentation reconciliation, not the S5.5
implementation by itself. Before S5.5a starts:

- S5 must pass its existing operator merge gate;
- the S5 issue must reach `workflow:done`, and the integration branch must be
  synchronized;
- the S5.5 brief must replace the `workspace` app identity with `work`;
- S5.5 issues must carry approved scope, acceptance criteria, runtime and cost
  limits, and authoritative workflow state; and
- the operator must explicitly approve the S5.5a start.

This documentation change updates `CONTEXT.md`,
`CLAUDE.md`, `docs/agents/current-operating-model.md`,
`docs/design/os-app-identity-20260828.md`, the ADR index, and the architecture
review log. The controlled vocabulary must add App, System surface, Work, and
Attention item without changing Workspace's existing meaning.

## Review trigger

Review this decision when Cortxt admits its first independently developed app,
when an app requires no Workstream context, when remote or untrusted app code
is proposed, or when the one-release `work-console` compatibility period ends.
