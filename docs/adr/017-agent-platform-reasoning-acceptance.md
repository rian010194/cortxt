# ADR-017: Agent Platform — reasoning core accepted as tracked architecture

**Status:** Accepted  \
**Date:** 2026-08-14  \
**Deciders:** Rikard (operator); independent review (Kimi) APPROVED 2026-08-14  \
**Technical Story:** ADR-016 required a vertical slice proving the agent-platform need before the untracked-scaffold status can be lifted. This vertical slice (reasoning core DM1–DM4) is now in `main` via PR #113.

## Context

ADR-016 (bounded context, InferencePort, provider-assurance) established that `agent-platform/` + `adapters/` remain **untracked scaffold** "until a vertical slice proves the need (no stable interfaces before that)". This ADR confirms that such a slice now exists and formally promotes the reasoning core to **tracked/Accepted** architecture within the Agent Platform bounded context — while everything else under `agent-platform/` remains Proposal/Untracked.

## 1. Vertical Slice Evidence

The reasoning core DM1–DM4 (Reasoning Kernel + RLM Engine + Geometric Engine + integrated pipeline) is delivered, checkpoint-reviewed (independent Kimi review CP1.1–CP4.1 APPROVED) and **in `main` via PR #113** (`feat/reasoning-kernel`, commit `09f1d8a`).

Verifiable invariants (commit `09f1d8a`):
- **58 pytest green**, **93 % coverage** for `reasoning/`, **0 model calls** (inference is a stub).
- `tests/reasoning/test_no_external_deps.py` guarantees that `reasoning/` **does not import Hermes/Pi/InferX/provider** — ADR-016's repository invariant (the core depends only on internal ports/contracts).
- This satisfies ADR-016's requirement: a vertical slice that proves the need for `agent-platform/` (here: the reasoning core) without stable-interface debt.

## 2. Tracked Scope (Accepted)

Within the **Agent Platform** bounded context, the following are declared **Accepted/tracked**:
- `agent-platform/reasoning/kernel/` — ProblemState, strategy selector (direct/recursive/geometric), operators (inspect/decompose/integrate/verify), engine loop.
- `agent-platform/reasoning/recursive/` — RLM Engine (bounded recursive decomposition, hard limits, stop conditions).
- `agent-platform/reasoning/geometric/` — Geometric Engine (ProblemSpace, metrics, attractor detection, guided explorer).
- `agent-platform/reasoning/pipeline.py` + `orchestrator.py` — integrated reasoning pipeline.
- `agent-platform/reasoning/__init__.py`, `tests/`, `pyproject.toml` — package/test support.

These file paths match exactly what is in `git ls-tree 09f1d8a agent-platform/reasoning/`.

## 3. Stability Matrix

| Area | Status |
| --- | --- |
| `agent-platform/reasoning/` (all of §2) | **Accepted / tracked** (vertical slice DM1–4 proven) |
| `agent-platform/adapters/` and other code under `agent-platform/` (inference, memory, skills, tools, supervisor, profiles, state, runtime) | **Still Proposal / Untracked** (no stable interfaces proven; requires its own vertical slices) |

**Negative boundary (explicit):** `adapters/` and all other `agent-platform/` packages are **NOT classified as Accepted** by this ADR. Only the reasoning core is promoted.

## 4. Authority Amendment (ADR-016)

ADR-016's decision that `agent-platform/` remains untracked scaffold is **partially lifted** for the reasoning core: the vertical-slice criterion in ADR-016 §Consequences is satisfied (see §1 above), so `agent-platform/reasoning/` moves from untracked/Proposal to tracked/Accepted. The ADR-016 decision is not deleted — it is modified via this ADR (the principle that existing decisions are preserved and changed through new ADRs, not by rewriting history). Everything else in ADR-016 (InferencePort, provider-assurance, data-class→gate) stands.

## Consequences

### Positive
- The reasoning core gets formal architecture status (tracked/Accepted) with a proven vertical slice.
- No stable interfaces are granted to unproven parts (adapters etc. remain Proposal/Untracked).
- ADR-016's own decision-state rule (Accepted vs Proposal) is upheld consistently.

### Negative
- Only reasoning/ is Accepted — the rest of agent-platform is still scaffold; no broader promotion.
- The legacy ADRs 011/012/013 are incompatible with the F0/F1 era and need explicit superseded marking (done in the same move).

### Risks
- Authority drift (adapters implicitly promoted) — countered by the explicit negative boundary in §3.
- Consistency break with ADR-016 — countered by 016 receiving only an addendum postscript (partially lifted), no removal.
- Ghost authority in legacy ADRs — countered by frontmatter mutation + legacy notice in 011/012/013.

## Validation
- [x] Vertical slice (DM1–4) in `main` via PR #113 (commit `09f1d8a`); 58 pytest, 93 % cov, 0 model calls, `test_no_external_deps` green.
- [x] Independent review (Kimi) of this ADR → **APPROVED** (Checkpoint 1.1 APPROVED after rework; Checkpoint 2.1 APPROVED after rework; 2026-08-14).
- [x] ADR-016 receives a postscript notice (partially lifted for reasoning/) — 016's Validation blank line updated to `[x] ... AMENDMENT ... tracked/Accepted per ADR-017` + STATUS-AMENDMENT at the top; no removal of core decisions.
- [x] ADR-011/012/013 marked `Superseded` in frontmatter + legacy notice.

## Expiry/Review Trigger
- Review by: 2026-11-14
- Trigger: if a new vertical slice promotes more parts of agent-platform, or if the reasoning core changes substantially (a new ADR is required).
