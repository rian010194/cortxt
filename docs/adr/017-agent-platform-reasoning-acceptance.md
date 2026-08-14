# ADR-017: Agent Platform — reasoning-kärnan accepterad som tracked arkitektur

**Status:** Accepted  \
**Date:** 2026-08-14  \
**Deciders:** Rikard (operatör); oberoende review (Kimi) GODKÄND 2026-08-14  \
**Technical Story:** ADR-016 krävde ett vertikalt slice som bevisar agent-platform-behovet innan untracked-scaffold-tillståndet kan upphävas. Detta vertikala slice (reasoning-kärnan DM1–DM4) är nu i `main` via PR #113.

## Context

ADR-016 (bounded context, InferencePort, provider-assurance) etablerade att `agent-platform/` + `adapters/` förblir **untracked scaffold** "tills ett vertikalt slice bevisar behovet (inga stabila interface före det)". Detta ADR bekräftar att ett sådant slice nu existerar och formellt befordrar reasoning-kärnan till **tracked/Accepted** arkitektur inom bounded context Agent Platform — samtidigt som allt övrigt under `agent-platform/` förblir Proposal/Untracked.

## 1. Vertical Slice Evidence

Reasoning-kärnan DM1–DM4 (Reasoning Kernel + RLM Engine + Geometric Engine + integrerad pipeline) är levererad, checkpoint-reviewed (oberoende Kimi-review CP1.1–CP4.1 GODKÄND) och **i `main` via PR #113** (`feat/reasoning-kernel`, commit `09f1d8a`).

Verifierbara invariantar (commit `09f1d8a`):
- **58 pytest gröna**, **93 % coverage** för `reasoning/`, **0 model-anrop** (inference är en stubb).
- `tests/reasoning/test_no_external_deps.py` garanterar att `reasoning/` **inte importerar Hermes/Pi/InferX/provider** — ADR-016:s repositoryinvariant (kärnan beror bara på interna portar/kontrakt).
- Detta uppfyller ADR-016:s krav: ett vertikalt slice som bevisar behovet av `agent-platform/` (här: reasoning-kärnan) utan stabila interface-skulder.

## 2. Tracked Scope (Accepted)

Inom bounded context **Agent Platform** förklaras följande som **Accepted/tracked**:
- `agent-platform/reasoning/kernel/` — ProblemState, strategiväljare (direct/recursive/geometric), operatorer (inspect/decompose/integrate/verify), engine-loop.
- `agent-platform/reasoning/recursive/` — RLM Engine (bounded rekursiv dekomposition, hårda gränser, stop-conditions).
- `agent-platform/reasoning/geometric/` — Geometric Engine (ProblemSpace, mått, attractor-detektering, guidad explorer).
- `agent-platform/reasoning/pipeline.py` + `orchestrator.py` — integrerad reasoning-pipeline.
- `agent-platform/reasoning/__init__.py`, `tests/`, `pyproject.toml` — paket-/teststöd.

Dessa filsökvägar matchar exakt det som finns i `git ls-tree 09f1d8a agent-platform/reasoning/`.

## 3. Stability Matrix

| Område | Status |
| --- | --- |
| `agent-platform/reasoning/` (allt i §2) | **Accepted / tracked** (bevisat vertikalt slice DM1–4) |
| `agent-platform/adapters/` och övrig kod under `agent-platform/` (inference, memory, skills, tools, supervisor, profiles, state, runtime) | **Fortsatt Proposal / Untracked** (inga stabila interface bevisade; kräver egna vertical slices) |

**Negativ avgränsning (explicit):** `adapters/` samt alla andra `agent-platform/`-paket **klassas INTE som Accepted** av detta ADR. Bara reasoning-kärnan befordras.

## 4. Authority Amendment (ADR-016)

ADR-016:s beslut om att `agent-platform/` förblir untracked scaffold **upphävs partiellt** för reasoning-kärnan: det vertikala slice-kriteriet i ADR-016 §Konsekvenser är uppfyllt (se §1 ovan), så `agent-platform/reasoning/` övergår från untracked/Proposal till tracked/Accepted. Beslutet i ADR-016 raderas inte — det modifieras via detta ADR (principen att befintliga beslut bevaras och ändras genom nya ADR, inte genom att skriva om historik). Allt annat i ADR-016 (InferencePort, provider-assurance, dataklass→gate) står fast.

## Consequences

### Positive
- Reasoning-kärnan får formell arkitekturstatus (tracked/Accepted) med bevisat vertikalt slice.
- Inga stabila interface ges till icke-bevisade delar (adapters etc. förblir Proposal/Untracked).
- ADR-016:s egen decision-state-regel (Accepted vs Proposal) upprätthålls konsistent.

### Negative
- Endast reasoning/ är Accepted — resten av agent-platform är fortfarande scaffold; ingen bredare promotion.
- Legacy-ADR:arna 011/012/013 är inkompatibla med F0/F1-eran och behöver explicit superseded-markering (görs i samma rörelse).

### Risks
- Auktoritetsglidning (adapters implicit befordrad) — motverkas av explicit negativ avgränsning i §3.
- Konsistensbrott med ADR-016 — motverkas av att 016 endast får ett tilläggspostscript (partiellt upphävt), inget borttag.
- Ghost authority i legacy-ADR:ar — motverkas av frontmatter-mutation + legacy-notis i 011/012/013.

## Validation
- [x] Vertikalt slice (DM1–4) i `main` via PR #113 (commit `09f1d8a`); 58 pytest, 93 % cov, 0 model-anrop, `test_no_external_deps` grön.
- [x] Oberoende review (Kimi) av detta ADR → **GODKÄND** (Checkpoint 1.1 GODKÄND efter rework; Checkpoint 2.1 GODKÄND efter rework; 2026-08-14).
- [x] ADR-016 får ett postscript-notis (partiellt upphävt för reasoning/) — 016:s Validation-blank rad uppdaterad till `[x] ... AMENDMENT ... tracked/Accepted per ADR-017` + STATUS-AMENDMENT högst upp; inget borttag av kärnbeslut.
- [x] ADR-011/012/013 markeras `Superseded` i frontmatter + legacy-notis.

## Expiry/Review Trigger
- Review by: 2026-11-14
- Trigger: om ett nytt vertikalt slice befordrar fler delar av agent-platform, eller om reasoning-kärnan ändras väsentligt (ny ADR krävs).
