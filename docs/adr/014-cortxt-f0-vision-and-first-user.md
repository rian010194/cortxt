# ADR-014: Cortxt Product Vision and First User (F0)

**Status:** Accepted  \
**Date:** 2026-08-13  \
**Deciders:** Rikard (operator)  \
**Technical Story:** CORTXT F0/F1 decision packet, approved 2026-08-13 after independent Codex review (round 2 APPROVED); evidence `.hermes/codex/f0f1-decision-packet-2026-08-13.md` (v0.2, gitignored locally)

> **STATUS-AMENDMENT (2026-08-16, ADR-020):** the proof environment name in Negative consequences below
> should be read as **"proof environment B"** in all new references — terminology redaction
> ahead of repo publication; the decision below is unchanged and remains Accepted.

## Context

Batch 0 Foundation Authority Freeze is complete: GitHub Project 4 is `Legacy AI Workspace Delivery — frozen`, the existing backlog is a legacy backlog, and a legacy item is not automatically on the Cortxt roadmap or dispatchable. Before roadmap and dispatch work can begin, Cortxt's product vision, first user, and primary problems must be explicitly decided.

The grounds considered:
- Target architecture ownership hypothesis (`docs/architecture/cortxt-agent-platform-target-architecture.md`, UNTRACKED proposal): the user/organization owns the work capability's goals, state, memory, reasoning, tools, evidence, and development, while models/inference providers/external agent engines are interchangeable resources.
- Product premises (operator context, partially normative): Cortxt is the only product; Rikard is the first actual user; coding/research/analysis/compliance are profiles on top of Cortxt, not the product boundary; the Agent Platform goal is a proposal; Operator Cockpit/web is paused legacy.
- Repository invariant: Problem State and trajectories are owned by Cortxt and portable; Agent Core does not import Hermes/Pi/Prime/provider (`agent-platform/README`, `cortxt-agent-platform-target-architecture.md`).

## Decision

**F0 — Balanced vision.** Cortxt is a system for creating, governing, and developing long-running intelligent work capabilities that reason, use tools, remember, verify, and act under human mandate — owned by the user/organization, with models and providers as interchangeable resources.

**First user:** Rikard (developer, operator, product builder, researcher/analyst, business developer, provider/model selector, cost/risk/decision owner). No fictional persona.

**Primary problems (first user):** Rikard can today run individual agent jobs, but cannot, as owner, create, resume, govern, verify, and maintain provider-neutral long-running work capabilities with guaranteed data-class/provider policy. Consequence: manual handoffs, fragmented evidence, uncertain cost, and risk that sensitive material ends up with non-approved providers.

**Product definition:** Cortxt is a provider-neutral agent platform where the user owns the work capability's state, reasoning, memory, tools, evidence, and development; models/inference providers/external agent engines are interchangeable resources behind Cortxt-owned ports and contracts; coding/research/analysis/compliance are versioned profiles on top of the same core.

**Non-goals (explicit):**
1. Cortxt does not train its own general foundation model and does not write its own CUDA inference engine.
2. Cortxt does not compete as a GPU marketplace or as an inference provider in the first generation.
3. Cortxt does not solve only the coding, compliance, or workflow problem — these are profiles, not the product boundary.
4. Cortxt does not allow unrestricted self-modification and does not replace the operator's mandate over irreversible decisions.
5. Cortxt does not replace GitHub as the canonical task record and does not restart Operator Cockpit/web as the first product surface out of historical inertia.

## Consequences

### Positive
- Unambiguous product foundation as separate vision, platform, wedge, product, journey, and milestone (no conflation).
- The ownership hypothesis is confirmed: provider neutrality + portable state/evidence is the differentiation.
- Clarifies what should NOT be built/competed on (non-goals), which guides the wedge choice and scope.

### Negative
- The target architecture remains a proposal until a separate ADR/accepted architecture (see ADR-016); F0 confirms the direction but does not approve the entire platform build.
- The proof environment B is a proof environment, not a proven market; "municipalities as beachhead" remains a hypothesis.

### Risks
- That a wedge (coding or compliance) is reduced to a product boundary — countered by non-goal 3.
- That "agentic operating system" is used as an external product promise (too broad) instead of a forward-looking ambition.

## Alternatives Considered
1. **Conservative** (Cortxt = a traceable control plane on top of Hermes/Pi/Codex) — rejected: reduces Cortxt to an improvement of the existing baseline and violates the ownership hypothesis/premise 6.
2. **Expansive** ("agentic operating system" for all knowledge/coding work + own inference) — rejected: conflates vision with the first product/wedge, vision-theater risk, requires large builds before proof.
3. **Balanced** — chosen.

## Validation
- [x] Codex independent review APPROVED (round 2, 2026-08-13); all corrected findings verified.
- [x] Rikard's approval registered (2026-08-13).
- [ ] The decision packet is materialized as a version-controlled artifact (this ADR + ADR-015, 016).
- [ ] Documentation updated, evidence direct links preserved.

## Expiry/Review Trigger
- Review by: 2026-11-13
- Trigger: new market evidence (payment), an updated ownership hypothesis, or an observed user need that contradicts the vision.
