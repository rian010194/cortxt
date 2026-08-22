# ADR-015: Cortxt First Wedge and Product Surface (F1)

**Status:** Accepted  \
**Date:** 2026-08-13  \
**Deciders:** Rikard (operator)  \
**Technical Story:** CORTXT F0/F1 decision packet, approved 2026-08-13 after independent Codex review (round 2 APPROVED); evidence `.hermes/codex/f0f1-decision-packet-2026-08-13.md` (gitignored locally)

> **STATUS-AMENDMENT (2026-08-16, ADR-020):** the proof environment name below
> should be read as **"proof environment B"** in all new references — terminology redaction ahead of repo publication;
> the decision (Wedge B) below is unchanged and remains Accepted.

## Context

F0 (ADR-014) is approved. The next decision is the first wedge: the smallest coherent product experience that solves a real problem, can be used by Rikard, can be handed over to a second user, demonstrates a part of the larger vision, does not require building the entire Agent Platform first, and produces evidence that determines the next investment.

Four clearly distinct candidates were compared (Part F of the decision packet):
- A: developer coding workflow
- B: provider-/data-class-driven long-running research and analysis session (auditable "capability")
- C: compliance/gap-analysis workflow
- D: combined developer workflow (coding + research + policy)

## Decision

**F1 — Best balance: Wedge B.** The first wedge is a provider-/data-class-driven long-running research and analysis session as an auditable "capability", delivered through a **repository-native + CLI hybrid**, with **proof environment B as the proof environment**.

**Product surface:** repository-native + CLI (primary); web/cockpit is not used as the first surface (paused legacy, see premise 11).

**Distinctions (first product ≠ wedge ≠ journey ≠ milestone):**
- First product (F0/F1 decision): a bounded value proposition (Balanced vision + wedge B).
- First wedge: provider-/data-class-driven long-running analysis (this ADR).
- First user journey: 12 steps (trigger → … → delivered result) in decision packet Part G.
- First technical milestone (not product): Inference Gateway / Phase 1 in the target architecture — see ADR-016.

**The recommendation was based on qualitative trade-offs (not scores alone):** wedge B demonstrates the ownership hypothesis (provider neutrality, resumability, evidence, human mandate) without reducing Cortxt to coding (A) or compliance (C), and is the smallest coherent resolution that does not require the entire Agent Platform. Wedge A gives the fastest signal but the coding market is saturated (hypothesis, requires separate validation) and reduces Cortxt to a coding agent. Wedge C is strategically differentiating but risks domain lock-in and a slow regulated sales cycle; it is a natural second step (via proof environment B evidence), not the first.

## Consequences

### Positive
- Proves the core value (owned state + provider neutrality + evidence + verification) before platform build.
- Proof environment B is used as a real proof environment without becoming the whole product.
- The validation plan (Part H) is defined: T1 (Rikard), T2 (another dev), T3 (proof environment B generalizability), T4 (provider neutrality), T5 (provider assurance). No customer data.

### Negative
- The provider-assurance policy is still incomplete — wedge B depends on a minimal data-class→assurance policy.
- Long-running research/analysis requires supervisor/resume, which is currently missing from the baseline (proposal).

### Risks
- Provider policy and data-class groups become a bottleneck; InferX is not approved for confidential material before completed assurance (ADR-016).
- That wedge B overlaps A/C and becomes too large — countered by clear ACs and the smallest coherent definition.

## Alternatives Considered
1. **Wedge A (developer coding)** — not chosen as first: hypothesis of a saturated market (requires separate validation), lowest differentiation, reduces Cortxt to a coding agent.
2. **Wedge C (compliance/gap)** — not chosen as first: strong differentiation but domain lock-in and sales-cycle risk; better as a second step via proof environment B.
3. **Wedge D (combined)** — not chosen: too complex and too large for v0.1.
4. **Wedge B** — chosen: best balance between signal, differentiation, and proof of the ownership hypothesis.

## Validation
- [x] Codex independent review APPROVED (round 2, 2026-08-13).
- [x] Rikard's approval registered (2026-08-13).
- [ ] Wedge B validation T1–T5 completed (Part H) before product code.
- [ ] The provider-assurance policy (minimal, data-class→gate) established as a prerequisite.

## Expiry/Review Trigger
- Review by: 2026-11-13
- Trigger: any of T1–T5 is falsified, or an observed user demand points to a different wedge.
