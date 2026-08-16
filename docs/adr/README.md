# ADR-index (Architecture Decision Records)

Auktoritativt index över arkitekturbesluten i detta repo. Status per decision-state-regeln i
`docs/style-guide.md` / ADR-mönstret: **Accepted** = normativt inom sitt scope; **Proposal** = reviewbart
förslag, inte implementeringsauktoritet; **Superseded** = historisk referens, ersatt av nyare beslut.

Uppdaterat: 2026-08-16 (ADR-019, permanent multi-engine routing för kodningsmotorer).

| # | Titel | Status | Notis |
| --- | --- | --- | --- |
| 011 | Model Router for Coordinator Fallback | **Superseded** (ADR-017) | Predaterar F0/F1; statisk fallback-kedja ersatt av providerneutral inference (ADR-016) + reasoning (ADR-017) |
| 012 | Disaster Recovery for Profiles, Skills, and Memory | **Superseded** (ADR-017) | Predaterar F0/F1; portabilitet förskjuts mot Cortxt-ägda portar/tillstånd |
| 013 | Skill Composition Model | **Superseded** (ADR-017) | Predaterar F0/F1; statisk skill-pack-modell ersatt av providerneutral arkitektur |
| 014 | Cortxt Product Vision and First User (F0) | **Accepted** | Produktvision + första användare |
| 015 | Cortxt First Wedge and Product Surface (F1) | **Accepted** | Wedge B: provider-/dataklassstyrd långvarig analys; repository+CLI |
| 016 | Agent Platform bounded context, InferencePort och provider-assurance | **Accepted** (amended 2026-08-14 för reasoning/ per ADR-017) | Bounded context + InferencePort + dataklass→gate; reasoning/ nu tracked/Accepted |
| 017 | Agent Platform — reasoning-kärnan accepterad som tracked arkitektur | **Accepted** (post-review) | Vertikalt slice DM1–4 (PR #113, commit `09f1d8a`) bevisar behovet; `agent-platform/reasoning/` → tracked |
| 018 | Workflow-state carrier — GitHub Issue labels | **Accepted** | `workflow:*`-labels är tillståndsbärare (ADR-018); Project 4 frusen legacy |
| 019 | Coding execution — permanent multi-engine routing, not Pi/Hermes replacement | **Accepted** | Pi/Hermes/Codex (+ framtida Copilot) permanenta routingval jämte egen Coding Agent; upphäver §24.2-ersättningskriterier i target-architecture.md |

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
