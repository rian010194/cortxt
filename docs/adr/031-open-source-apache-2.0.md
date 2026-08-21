# ADR-031: Open-source license — Apache-2.0

**Status:** Accepted
**Date:** 2026-08-21
**Deciders:** Rikard (operator)
**Technical Story:** GitHub issue rian010194/cortxt#182

## Context

Since its start the repository has been "viewable, not open source" (all
rights reserved; viewing and forking for personal, non-distributed reference
permitted, all other use requires written permission). Ahead of product
packaging — Cortxt as a product other developers can use and contribute to —
the operator decided on 2026-08-21 to open the source code. The license choice
is the starting point for all distribution and for the contribution model.

## Decision

**Cortxt is licensed under the Apache License 2.0.** `LICENSE` is replaced with
the verbatim Apache-2.0 text (copyright: Rikard Andersson). All traces of
"viewable, not open source" are removed from the repository documentation.

Apache-2.0 was chosen over MIT for its explicit patent grant (§3) and its
patent-retaliation clause — relevant for a platform with routing and inference
contracts — while remaining compatible with the MIT-licensed skills already
adopted.

## Consequences

### Positive
- Other developers can use, modify, and contribute; a basis for distribution.
- The explicit patent grant reduces patent risk for contributors and users.
- A standard license with broad ecosystem support.

### Negative
- Copyright is held by one person; future contributions require a clear
  DCO/CLA policy (not decided here).

### Risks
- The contribution model (DCO/CLA) is still unspecified — followed up
  separately before external contributions are accepted at any larger scale.

## Alternatives Considered
1. **MIT** — simplest, but no explicit patent grant; rejected in favor of
   Apache-2.0's patent protection.
2. **AGPL-3.0** — copyleft that covers network use; too strong for a platform
   meant to be consumed bottom-up (ADR-023) without forcing consumers into
   copyleft.
3. **Keep "viewable, not open source"** — blocks use and contribution;
   rejected as incompatible with the product goal.

## Validation
- [x] `LICENSE` is the verbatim Apache-2.0 text (with the copyright line).
- [x] No "viewable, not open source" remnants remain in the repository
      documentation.
- [x] The ADR index (`docs/adr/README.md`) is updated with 031.

## Expiry/Review Trigger
- Review by: 2026-11-21
- Trigger: a contribution/CLA policy is introduced, or a distribution
  (packaging) decision requires revisiting the license form.
