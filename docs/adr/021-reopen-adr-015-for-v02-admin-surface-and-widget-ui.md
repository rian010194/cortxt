# ADR-021: Reopen ADR-015 for v.02 Admin Surface + Widget UI (F2 treatment)

**Status:** Proposed  
**Date:** 2026-08-18  
**Deciders:** Rikard (operatör) — pending Accepted decision  
**Technical Story:** GitHub issue rian010194/cortxt#157; v.02-milestone-wayfinder Fas 0 (`.hermes/plans/2026-08-18-v02-milestone-wayfinder.md`)

## Context

ADR-015 (Cortxt F1 — First Wedge and Product Surface) pausade web/Operator Cockpit as a product surface in favor of "repository-native + CLI (primärt)" and left an explicit review trigger: "observerad användarefterfrågan pekar på en annan wedge" (ADR-015, Expiry/Review Trigger section — ADRs in this repo are not §-numbered internally, unlike target-architecture.md).

As of 2026-08-18, that trigger has been observed: the operator's own growing need for an admin surface (§2 of the v.02 vision doc) and the side-by-side widget + CLI prototypes on `prototype/widget-cli-v02` both point toward a second product layer complementing the CLI-primary decision. No ADR yet formally addresses this. ADR-020 (proof-environment naming) and ADR-021 are sibling follow-ups to the F0/F1 decision package; ADR-021 specifically reopens the product-surface question without reopening the wedge B decision that ADR-015 already accepted.

This ADR exists solely to carry that review trigger to a formal decision. It does not authorize any implementation. Implementation authorization is gated separately: Fas 2+ of the v.02 wayfinder does not count as authoritative product surface until ADR-021 is Status: Accepted, set by Rikard.

## Decision

**F2 treatment — ADR-015 is reopened only for the product-surface dimension, not for the wedge decision.**

ADR-015's core decision (Wedge B as first wedge, provider-/dataklassstyrd long-running analysis, Norcom/CSL as proof environment B) remains Accepted and unaffected. ADR-021 reopens only the question ADR-015 left open: may a visual surface (widget UI) and a second product layer (admin surface on top of the CLI) exist, as a complement to ADR-015's "repository-native + CLI (primärt)" decision — not a replacement.

**The narrow decision is:**

- Yes — a widget UI (thin shell mirroring orchestrator state, no independent logic) and an admin surface (operational layer on top of the CLI) are explicitly permitted to exist as a complement to the CLI-primary product surface decided in ADR-015.
- This does not repeal, supersede, or weaken ADR-015's CLI-primary decision. The CLI remains the source of truth; the widget mirrors its state.
- This does not decide naming, the credential-storage security model, pricing, or the addon review process — those are separate open questions in §6 of the v.02 vision doc and remain open. They are addressed in later wayfinder phases (Fas 1 security model, Fas 6 pricing), not by this ADR.
- This does not authorize starting Fas 2+ of the wayfinder. Only Rikard setting Status: Accepted on this ADR does that, per the wayfinder's own standing decision ("Fas 0 (ADR) körs alltid först. Inget i Fas 2+ räknas som auktoritativ produktyta förrän ADR-021 är Accepted").

This ADR is therefore **necessary but not sufficient** for Fas 2+ implementation. It clears the ADR-level gate; the operator's Accepted decision unlocks the build gate.

## Consequences

### Positive

- The product-surface review trigger in ADR-015 is formally addressed, closing a gap between the accepted wedge decision and the operator's observed admin-surface need.
- The widget + CLI prototypes already on `prototype/widget-cli-v02` gain an ADR anchor: they are no longer speculative sketches but a permitted complement to the accepted CLI-primary surface, subject to the invariants below.
- The wayfinder's Fas 0 gate becomes explicit and auditable: no Fas 2+ work is authoritative before ADR-021 Accepted. This protects against the common failure mode where prototypes silently become de facto product decisions.
- Separates the product-surface question from the security-model, pricing, and addon-review questions that legitimately belong to later phases — prevents this ADR from becoming a dumping ground for unresolved issues.

### Negative

- Reopening any Accepted ADR creates review burden and risks drift between "wedge B is Accepted" and "now a second surface is permitted" if the relationship is not kept explicit. This ADR mitigates that by restricting the reopening to one dimension.
- The phrase "complement, not replacement" requires ongoing discipline in implementation: a future implementer could quietly let the widget acquire independent logic or let the admin surface drift from CLI state. This ADR cannot mechanically enforce that — it relies on the invariants in Risks and on later review gates (Fas 2 Codex review, PromotionGate for addons).

### Risks

- **Operator mandate over irreversible decisions (target-architecture.md §28):** A visual admin surface can make operational actions feel cheaper and more casual than CLI equivalents. The invariant is that the operator retains mandate over irreversible decisions regardless of the surface used to initiate them. This ADR does not itself guarantee that invariant — it only permits the surface to exist. The invariant must be rechecked against the actual implementation before Fas 2+ ships: any irreversible action reachable through the widget/admin surface must still carry the same operator-mandate guard as the CLI equivalent, not a softer "the widget shows cost so it must be safe" assumption. The vision doc's own §6 flags that "an always-working fleet" must be checked against §28/§11 before being built, not assumed safe because the widget displays cost information.
- **RLM hard limits on budget/depth/stop (target-architecture.md §11):** A fleet/admin surface that presents "always-working" as a property of the UI can mask the fact that the underlying RLM still has hard limits on budget, depth, and stop. This ADR permits the surface; it does not relax those limits. Any future "always-working fleet" feature built on top of this surface must be validated against §11 limits explicitly — the widget showing cost or status is not equivalent to the limits being satisfied. This is the same class of risk the vision doc §6 calls out: assuming safety from UI affordances rather than from architectural guarantees.
- **Scope creep into naming/security/pricing/addon-review:** Because this ADR touches the admin surface, there is gravitational pull to also "just decide" naming, credential storage, pricing, and addon review here. That would overload a narrow gate ADR and delay the Accepted decision. Those questions are deliberately left to their own phases (Fas 1, Fas 6, Fas 5 respectively) and are explicitly NOT decided by this ADR.
- **Prototype-to-main promotion confusion:** The widget + CLI prototypes on `prototype/widget-cli-v02` already exist and the operator likes the direction. This ADR permits them to exist as a complement; it does not authorize promoting them to main as product code. That authorization is a separate step gated on ADR-021 Accepted plus the Fas 2 implementation review.

## Alternatives Considered

1. **Leave ADR-015 untouched and let the widget/admin surface proceed as an untracked prototype.** — Rejected: ADR-015's review trigger is explicit and has been observed. Ignoring it means the product-surface question is decided by prototype momentum rather than by ADR process, which is exactly the drift the ADR system exists to prevent. The wayfinder already treats ADR-021 Accepted as a gate for Fas 2+; skipping the ADR would make that gate meaningless.

2. **Reopen ADR-015 fully (wedge + surface together).** — Rejected: wedge B is already Accepted with evidence and a validation plan (T1–T5). Reopening the whole ADR would reopenedecided evidence and create needless review churn. The observed trigger is specifically about the surface dimension, so the reopening should be dimension-scoped. ADR-021 takes that scoped approach.

3. **Defer the surface question to a later ADR after Fas 2 is already built.** — Rejected: that inverts the wayfinder's own standing decision (Fas 0 ADR first) and would make the ADR a post-hoc rationalization rather than a gate. The operator's instruction is explicit that the ADR precedes the build, not follows it.

4. **ADR-021 decides everything in §6 of the vision doc at once (naming, security, pricing, addon review, surface).** — Rejected: that overloads a single ADR, conflates decisions with different owners and review needs, and delays the narrow surface gate behind unrelated debates. This ADR deliberately limits itself to the surface-complement question and leaves the other §6 items to their own phases.

## Validation

- [ ] ADR-021 exists at `docs/adr/021-....md` with Status: Proposed, referencing ADR-015 and issue rian010194/cortxt#157.
- [ ] Consequences/Risks explicitly addresses target-architecture.md §28 (operator mandate over irreversible decisions) and §11 (RLM hard limits on budget/depth/stop) — the vision doc §6 "always-working fleet" assumption is flagged as requiring check against these invariants before build, not assumed safe from UI affordances.
- [ ] ADR does not decide naming, credential-storage security model, pricing, or addon review process — those remain open per vision doc §6 and are deferred to later wayfinder phases.
- [ ] ADR does not itself authorize starting Fas 2+ of the wayfinder — only Rikard setting Status: Accepted does that.
- [ ] Review: Claude Code reviews the draft before it goes to the operator for the Accepted decision (not Codex, per explicit operator instruction — deviates from this repo's usual review-agent default for this one ADR only).

## Expiry/Review Trigger

- Review by: 2026-11-18 (3 months from proposal; aligns with ADR-014/015 review horizon)
- Trigger: Rikard sets Status: Accepted (closes this ADR as a gate), or the v.02 wayfinder is abandoned/re-scoped such that the admin-surface question no longer applies, or a new observed user demand points to yet another surface dimension not covered by this ADR.
