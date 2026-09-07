# ADR-046: TypeScript is the source language for the Cortxt OS frontend

**Status:** Accepted
**Date:** 2026-09-03
**Deciders:** Rikard Andersson (operator)
**Technical Story:** #503 (foundation), #504 (renderer/manifest contracts)

## Context

The Cortxt OS frontend is hand-written ES5-compatible JavaScript served as
static files from `agent-platform/widget/` and hand-copied to
`site/public/widgets/`, where a mirror-parity test asserts the two are
byte-identical. There is no type layer, no build step, and no single source of
truth: the copy is manual, and the parity test detects drift only after it has
been committed.

TypeScript has been the stated intent since the S5.5 work
(`lab/os-acceptance-418/typescript-migration-recommendation.md`, 2026-08-28)
but was explicitly held outside every S5.5 slice and never received its own
implementation issues. The older brief called the track "S8"; that label now
means cross-engine continuity on GitHub and must not be reused.

Two recent defects show the cost of the missing type and contract layer
directly. #498: `next_action` was consumed by browser gates but emitted only by
fixtures, so the launch control was structurally unreachable on a live host.
Its follow-up fix: the Next summary read `nextAction`, a second fixture-only
field, and rendered "No next action pending." above a working control. Both are
the same failure — a field the browser depends on that no production projection
emits — and both were invisible to a green test suite because the fixtures
supplied what production did not.

## Decision

TypeScript is the source language for the Cortxt OS frontend.

1. Frontend code is authored in a TypeScript source tree and **compiled** to
   the static JavaScript the host serves. Generated output is not hand-edited.
2. The compiled output is the single source for both consumers: the local
   action host and the public web mirror are **generated** from one build, via
   an explicit allowlist. Runtime, private, or operational data is never
   copied into the public web output.
3. Migration is incremental and ordered: build foundation → renderer and app
   manifest contracts → shell, commands, apps → Maker last. Unmigrated
   JavaScript keeps working unchanged alongside migrated modules.
4. New frontend logic is written in TypeScript once the build foundation
   exists. A short-term deviation must be stated explicitly in the issue that
   takes it, never taken by omission.
5. No new UI framework is adopted, and the site toolchain is not upgraded
   under this decision.
6. TypeScript does not replace runtime validation of server data. A field
   Python fails to emit is a runtime fact, not a compile-time one; it is
   caught only by typed contracts checked against the actual projection at
   runtime. #498 is the worked example: types alone would not have found it.

This decision authorizes the direction and the foundation. It does **not**
approve a full frontend rewrite, does not touch the Python backend, and does
not gate S7 delivery behind migration.

## Consequences

### Positive
- One source of truth for widget code; the mirror becomes build output rather
  than a hand-copy that a test polices after the fact.
- The renderer/manifest seam every app depends on gets a checked contract.
- A `tsc --noEmit` CI gate makes a whole class of field/shape drift fail before
  review rather than in a browser.

### Negative
- A build step enters a frontend that currently has none; the static files
  stop being directly editable.
- A Node toolchain must be pinned and maintained in CI.

### Risks
- Believing types cover server-contract drift. They do not (point 6).
- Toolchain contamination from the unrelated site-build failure (#357); the
  widget build must pin its own verified toolchain and not inherit that chain.
- Scope creep into a full rewrite. Mitigated by the ordered, per-module
  migration and by S7 remaining ahead of the migration.

## Alternatives Considered
1. **Keep hand-written JavaScript, add JSDoc types** — Rejected: it leaves the
   two hand-copied trees as the source of truth, which is half the problem.
2. **Adopt a UI framework alongside TypeScript** — Rejected: explicitly out of
   scope; the runtime surface stays the same static files.
3. **Migrate everything in one slice** — Rejected: it would put a full
   frontend rewrite in front of the first useful operator loop (S7).

## Validation
- [ ] Reproducible TS build and `tsc --noEmit` type-check run in CI (#503)
- [ ] Mirror parity asserts build-output equality, not two hand-edited copies (#503)
- [ ] Renderer and app-manifest contracts are typed and validated at runtime (#504)
- [ ] Unmigrated JavaScript continues to work unchanged (#503, #504)

## Expiry/Review Trigger
- Review by: 2027-03-03
- Trigger: the foundation issues (#503, #504) close, a UI framework is
  proposed, or the site toolchain upgrade (#357) lands and changes the
  toolchain constraints this ADR assumes.
