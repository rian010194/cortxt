# ADR-index (Architecture Decision Records)

Auktoritativt index över arkitekturbesluten i detta repo. Status per decision-state-regeln i
`docs/style-guide.md` / ADR-mönstret: **Accepted** = normativt inom sitt scope; **Proposal** = reviewbart
förslag, inte implementeringsauktoritet; **Superseded** = historisk referens, ersatt av nyare beslut.

Uppdaterat: 2026-08-19 (ADR-022, ADR-023, ADR-024, ADR-025 tillagda).

| # | Titel | Status | Notis |
| --- | --- | --- | --- |
| 011 | Model Router for Coordinator Fallback | **Superseded** (ADR-017) | Predaterar F0/F1; statisk fallback-kedja ersatt av providerneutral inference (ADR-016) + reasoning (ADR-017) |
| 012 | Disaster Recovery for Profiles, Skills, and Memory | **Superseded** (ADR-017) | Predaterar F0/F1; portabilitet förskjuts mot Cortxt-ägda portar/tillstånd |
| 013 | Skill Composition Model | **Superseded** (ADR-017) | Predaterar F0/F1; statisk skill-pack-modell ersatt av providerneutral arkitektur |
| 014 | Cortxt Product Vision and First User (F0) | **Accepted** (amended 2026-08-16 för proof-env-namn per ADR-020) | Produktvision + första användare |
| 015 | Cortxt First Wedge and Product Surface (F1) | **Accepted** (amended 2026-08-16 för proof-env-namn per ADR-020) | Wedge B: provider-/dataklassstyrd långvarig analys; repository+CLI |
| 016 | Agent Platform bounded context, InferencePort och provider-assurance | **Accepted** (amended 2026-08-14 för reasoning/ per ADR-017) | Bounded context + InferencePort + dataklass→gate; reasoning/ nu tracked/Accepted |
| 017 | Agent Platform — reasoning-kärnan accepterad som tracked arkitektur | **Accepted** (post-review) | Vertikalt slice DM1–4 (PR #113, commit `09f1d8a`) bevisar behovet; `agent-platform/reasoning/` → tracked |
| 018 | Workflow-state carrier — GitHub Issue labels | **Accepted** | `workflow:*`-labels är tillståndsbärare (ADR-018); Project 4 frusen legacy |
| 019 | Coding execution — permanent multi-engine routing, not Pi/Hermes replacement | **Accepted** | Pi/Hermes/Codex (+ framtida Copilot) permanenta routingval jämte egen Coding Agent; upphäver §24.2-ersättningskriterier i target-architecture.md |
| 020 | Proof environment naming — redact product/partner name from public surface | **Accepted** | Terminologiredaktion: "Norcom/CSL" → "proof environment B" framåt; ADR-014/015 oredigerade och kvar Accepted för sakinnehållet |
| 021 | Reopen ADR-015 for v.02 admin surface + widget UI (F2 treatment) | **Accepted** | ADR-015 review-trigger observerad; beslutar endast produktyta-komplement (widget + adminyta ovanpå CLI), inte wedge, naming, säkerhetsmodell, pris eller addon-granskning; Fas 2+ i v.02-wayfindern nu auktoritativt |
| 022 | Fas 3 v0.1 — capability manifest shape and engine-selection criteria | **Accepted** | Motoragnostiskt capability-manifest + deterministisk `route()`; löser ADR-019:s öppna urvalskriterie-punkt |
| 023 | Cortxt supports both bottom-up and top-down integration, not one exclusively | **Accepted** | Top-down internt permanent + avsiktligt bottom-up-konsumerbar utåt; beslutar riktningen, inte ytan (deferrat till Fas 6) |
| 024 | External integration surface takes the form of an MCP server | **Accepted** | Beslutar ADR-023:s deferrade ytform: MCP-server, inte SDK/REST, för initial skiva |
| 025 | Geometric Reasoning's decisive vs. diagnostic metrics (§27 #8) | **Accepted** | Formaliserar vilka av §12.2:s tio mått som styr beslut idag (5) kontra bara rapporterar (5); löser upp `w1`/`information_gain`-namnkollisionen; löser upp Fas 6:s blockerande exitkriterium |

## Beslut och auktoritet

- **Reasoning-kärnan** (`agent-platform/reasoning/`) är **tracked/Accepted** per ADR-017, backat av vertikala
  slicet DM1–4 i `main` (PR #113, commit `09f1d8a`; 58 pytest, 93 % cov, `test_no_external_deps`).
- **`agent-platform/adapters/` och övriga agent-platform-paket** förblir **Proposal/Untracked** tills egna
  vertical slices (ADR-016/017).
- **ADR-016** är **Accepted** efter amendment 2026-08-14 (partiellt upphävt untracked-scaffold-beslut för
  reasoning/); InferencePort + provider-assurance står fast.

## Sökbar status

Använd `grep -n "Status:" docs/adr/*.md` för aktuell status per fil. Inga filer utanför `docs/adr/`
skapar arkitekturauktoritet; `docs/style-guide.md` hanterar modul-/skrivregler.
