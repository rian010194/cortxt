# ADR-016: Agent Platform bounded context, InferencePort and provider-assurance principle

**Status:** Accepted  \
**Date:** 2026-08-13  \
**Deciders:** Rikard (operator)  \
**Technical Story:** CORTXT F0/F1 decision packet approved 2026-08-13; transition of the target architecture toward the ADR process (Part K decision 8)

> **STATUS-AMENDMENT (2026-08-14):** ADR-016 is **Accepted** — motivated by the F0/F1 approval and
> the Codex independent review APPROVED (2026-08-13), already noted in its Validation, and on the basis that
> its core decisions (bounded context, InferencePort, provider-assurance data-class→gate) are normative.
> **Partially lifted for reasoning/ per ADR-017:** the vertical slice DM1–4 (PR #113, commit `09f1d8a`)
> proves the need, so `agent-platform/reasoning/` is now tracked/Accepted (ADR-017). `adapters/` and
> other `agent-platform/` packages remain Proposal/Untracked until their own vertical slices. Other decisions in
> this ADR stand.

## Context

F0 (ADR-014) establishes Cortxt as a provider-neutral agent platform where the user owns state/reasoning/memory/tools/evidence/development, with models and providers interchangeable. F1 (ADR-015) chooses wedge B (provider-/data-class-driven long-running analysis) and requires a minimal provider-assurance policy as well as an InferencePort that lets the same agent code switch between ≥2 approved endpoints (the first technical milestone).

The current target architecture (`docs/architecture/cortxt-agent-platform-target-architecture.md`, UNTRACKED proposal) and the routing package (`docs/architecture/beslutspaket-routing-malarkitektur-2026-08-10.md`, UNTRACKED proposal) describe where the architecture should develop, but are not an approved baseline. This ADR makes decisions that move the target architecture further toward an ADR process without approving the entire platform build.

## Decision

1. **Agent Platform = bounded context.** Cortxt builds its own agent platform within the existing control plane. `agent-platform/` (supervisor, runtime, reasoning, state, memory, skills, tools, inference, profiles) and `adapters/` (inference, agent-runtime, tools, storage) are treated as a new bounded context/proposal. Core packages may depend only on internal ports and contracts; they may not import Hermes/Pi/Prime/InferX or a specific provider (repository invariant). Hermes/Pi are used during migration as adapters/fallback/benchmark, never as hidden core dependencies.

2. **InferencePort (first technical milestone).** A provider-neutral model-invocation port is built early. It normalizes provider/exact model version, messages + structured outputs, tool-calling, reasoning settings, token usage, latency/timeout/cancellation, cost + cost-confidence, retries/error classification, and data-class/provider eligibility. The agent core depends only on `InferencePort`; concrete providers live behind `adapters/inference/`. Exit criterion: the same agent code can switch between ≥2 approved endpoints without changes to the reasoning core.

3. **Provider-assurance principle (data-class → gate).** A minimal policy that conditions provider choice on data class:
   - L0 (public/synthetic): any approved provider.
   - L1 (internal, not sensitive): ZDR + encryption.
   - L2 (confidential): DPA + subprocessors + hosting region + incident process + **completed** independent assurance (e.g. SOC 2/ISO).
   - L3+ (personal data/critical): additional requirements per assessment.
   - `In progress` assurance is never described as completed compliance.

4. **Provider practice (InferX).** InferX (model.inferx.net) is currently **experimental and not approved for confidential material** (issues #64/#73/#74; primary source: `inferx.net/security`, SOC 2 Type II in progress target Q3 2026; GDPR/HIPAA in progress; DPA/subprocessors/incident not published). Before completed assurance, only data class L0 may be used at InferX (e.g. #74's synthetic pilot, 10 USD cap). Other providers are consumed behind `adapters/inference/` under the same data-class vetting.

## Consequences

### Positive
- The target architecture gets a proposed direction (bounded context + InferencePort) that can be formally adopted through this ADR process, without committing to the entire platform build at once.
- Provider neutrality becomes operational: one port, many interchangeable adapters.
- The data-class→gate policy protects confidential data (InferX is rejected for L2+ until completed assurance) and gives wedge B a prerequisite.

### Negative
- `agent-platform/` + `adapters/` remain untracked scaffold until a vertical slice proves the need (no stable interfaces before that).
- InferencePort + provider policy is a real build (Phase 1 in the target architecture); it is the first technical milestone, not the wedge delivery itself.

### Risks
- That the ADRs (014-016) sneak in new/extended scope — countered by limiting each ADR to exactly its own decision.
- That gitignored local evidence (`.hermes/codex/f0f1-*`) is mistaken for a normative source — it is evidence, not norm; normative are these ADRs + existing normative contracts.
- That the frozen Project 4 is reused as an active roadmap — it is not; upcoming Cortxt work should use a new planning surface.

## Alternatives Considered
1. **No own platform (control plane only on top of Hermes/Pi)** — rejected: contradicts the F0 ownership hypothesis and provider neutrality.
2. **Build the entire Agent Platform first (Phase 0-8)** — rejected: too large, vision-theater risk; wedge B proof does not need the whole platform.
3. **Bounded context + InferencePort first, wedge B as validation** — chosen: smallest correct progress that anchors decisions and delivers the first technical milestone.

## Validation
- [x] F0/F1 approved; Codex independent review APPROVED (round 2, 2026-08-13).
- [ ] InferencePort adapter with ≥2 approved endpoints (Phase 1 exit criterion) verified.
- [ ] The provider-assurance policy (data-class→gate) version-locked and reviewed.
- [x] `agent-platform/` and `adapters/` scaffold justified by a vertical slice before stable interfaces. **AMENDMENT (2026-08-14, ADR-017):** the vertical slice of the reasoning core DM1–4 is in `main` via PR #113 (commit `09f1d8a`); `agent-platform/reasoning/` is thereby **tracked/Accepted** per ADR-017. `adapters/` and other `agent-platform/` packages remain untracked/Proposal until their own vertical slices. The original decision is not deleted — it is partially lifted through ADR-017.
- [ ] Documentation (docs/authority-map) updated so the ADRs are normative.

## Expiry/Review Trigger
- Review by: 2026-11-13
- Trigger: a second inference provider is approved, InferX is re-evaluated after completed assurance, or wedge B validation changes the provider need.
