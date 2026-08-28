---
title: Current product vs. direction
description: What is verified on main today, what is accepted product direction, and what is experimental or future.
---

Cortxt is work- and mandate-first (ADR-042): durable authority, replaceable
execution. This page separates what that means concretely — what a visitor
can rely on today versus what is accepted direction versus what is still
experimental or unapproved.

## Available and verified

Demonstrably present on `main` today:

- GitHub Issues and `workflow:*` labels as durable workflow authority
  (ADR-018).
- Mandate issuance and verification for scoped authority over mutating
  actions (ADR-032).
- The provider/data-class policy gate (ADR-016), fail-closed on malformed
  evidence.
- Dispatch and Run identity (`scripts/dispatcher.py`, the dispatch contract).
- Evidence and independent-review mechanisms tied to GitHub Issues/PRs.
- The `cortxt` CLI, including `cortxt mcp serve` (ADR-024).
- Engine adapters for external agent runtimes (Hermes, Pi, Codex, DSH) behind
  Cortxt-owned ports.
- Declarative widget contracts and single-widget generation
  (`cortxt widget generate/edit/remove/reset`, ADR-038).
- A bounded continuity proof.
- ADR-042 (accepted 2026-08-26) and ADR-044 (accepted 2026-08-28).

## Accepted direction

Normative direction established by an accepted ADR, not yet fully delivered:

- Cortxt OS as the general shell and first-party app runtime, with Work as
  its first principal app (ADR-042, ADR-044). Work Console is retired by
  ADR-044 through a bounded compatibility migration to Work; Workspace keeps
  its execution-resource meaning.
- Studio: composing multiple generated widgets into coherent views/apps
  (ADR-042, ADR-041) — the single-widget building blocks exist; the
  composition surface does not yet.
- Execution Inspector as the reframed home for cockpit/runtime detail
  (sessions, pipelines, execution maps) inside a Workstream (ADR-042,
  amendment D).

## Experimental or in progress

Living on branches, worktrees, PRs, or bounded proofs — not on `main` as a
shipped product surface, or on `main` but incomplete:

- Cortxt OS / Work app-shell implementation (phase-5 work).
- Broader prompt-generated, multi-widget app composition beyond the merged
  single-widget commands above.

## Future or conditional

Not implemented, not foundational, and not committed direction:

- Hosted synchronization and managed services.
- Broader engine/adapter support beyond the currently supported set.
- OpenShell-backed secure execution (ADR-042 explicitly does not adopt
  OpenShell or NemoClaw as Cortxt's foundation; it may be evaluated later
  behind a generic secure-execution capability).
- Team or private-tenant capabilities.

## How to read claims elsewhere in these docs

- "Compatible engines" / "supported adapters" — a named, bounded set, never
  "any agent" or "any provider."
- "Accepted product direction" — normative per an ADR, not yet fully built.
- "Active development" — code exists and is changing; do not treat it as
  finished.
- "Demonstrated continuity proof" — one bounded proof exists; this is not a
  general guarantee.
