# ADR-018: Workflow-state carrier — GitHub Issue labels

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Rikard (operatör)
**Technical Story:** #101 (CORTXT Foundation — Wedge B validation), #117 (Utse workflow-state carrier + tillståndsmappning)

## Context

`docs/architecture/dispatch-contract.md` och `docs/agents/issue-tracker.md` har sedan Batch 0 Foundation Authority Freeze deklarerat att worker dispatch är suspenderat tills operatören explicit utser en ersättare för det frysta GitHub Project 4 som bärare av `Inbox`/`Ready`/`In progress`/`Review`/`Blocked`/`Done`-tillstånd. GitHub Issues i sig kodar inte dessa tillstånd (bara open/closed).

Två kandidater identifierades:
1. Befintliga labels `workflow:inbox`, `workflow:ready`, `workflow:in-progress`, `workflow:review`, `workflow:blocked`, `workflow:done` — redan skapade i repot, ingen extern infrastruktur.
2. Hermes Kanban-board `cortxt-cp` — redan verifierad med gateway dispatch (36s `ready → running → done`), men kräver ett mirror-skript/cron tillbaka till GitHub Issues och introducerar en andra tillståndskälla som kan driva isär från GitHub.

**Oberoende granskning:** ej genomförd i denna session (ingen Codex-tillgång tillgänglig här). Avviker från mönstret i ADR-014/015/016/017. Operatörsgodkännande registrerat 2026-08-14; en efterhandsgranskning rekommenderas innan nästa arkitektoniska beslut bygger vidare på detta.

## Decision

**Workflow-state carrier = GitHub Issue-labels `workflow:*`.** Ett issue bär exakt en `workflow:*`-label åt gången (ömsesidigt uteslutande); labeln *är* tillståndet, ingen spegling eller extern källa krävs.

**Tillståndsmappning:** identitetsmappning — `workflow:inbox` → `Inbox`, `workflow:ready` → `Ready`, `workflow:in-progress` → `In progress`, `workflow:review` → `Review`, `workflow:blocked` → `Blocked`, `workflow:done` → `Done`.

**Claim-mekanism:** en claim enligt `dispatch-contract.md` byter `workflow:ready` → `workflow:in-progress` och postar `run_id`, runtime, claim-tid och lease/timeout som en strukturerad kommentar på issuet. Retry skapar ett nytt `run_id` i en ny kommentar; tidigare run-evidens skrivs aldrig över.

**Konsekvens för #118:** mirror-cron-biljetten blir onödig och stängs — det finns inget att spegla när GitHub Issues redan är både scope-källa och tillståndsbärare.

## Consequences

### Positive
- Ingen ny infrastruktur; tillstånd och scope/evidens bor i samma system.
- Eliminerar en hel klass av bugg (mirror-drift mellan Kanban och GitHub).
- Label-ändringar loggas automatiskt av GitHub med tidsstämpel och aktör — gratis audit-trail.
- Följer repots egna principer: "GitHub Issues remain the durable source of truth" och "use the smallest verified path".

### Negative
- Ingen visuell Kanban-yta för operatören (kan läggas till senare som en läsande vy ovanpå labels, inte som sanningskälla).
- Ingen inbyggd lease/heartbeat-mekanism i labels själva — måste implementeras i dispatcher-lagret (samma krav skulle funnits med Hermes Kanban också).

### Risks
- Concurrent label-ändringar kan racea om två dispatchers agerar samtidigt på samma issue — dispatchern måste göra atomisk claim (t.ex. villkorad label-swap + kommentar i samma operation), inte labels ensamma.

## Alternatives Considered
1. **Hermes Kanban `cortxt-cp`** — förkastad som förstahandsval: redan bevisad men kräver mirror-cron (extra rörlig del, dubbel sanningskälla-risk); kan återupptas senare som en ren visualisering ovanpå label-tillståndet om behov uppstår.
2. **Fortsatt suspenderad dispatch (inget beslut)** — förkastad: blockerar #101:s återstående T-tester och all vidare dispatch-utveckling utan att lösa något.

## Validation
- [x] Operatörsgodkännande registrerat (2026-08-14, via #117).
- [ ] Oberoende granskning (Codex eller motsvarande) — utestående, rekommenderas innan nästa beslut bygger vidare på detta.
- [x] Dokumentation uppdaterad (denna ADR + `dispatch-contract.md` + `issue-tracker.md` + `current-operating-model.md`).
- [ ] Implementation: dispatcher som faktiskt utför atomisk claim via label-swap (spåras i #122).

## Expiry/Review Trigger
- Review by: 2026-11-14
- Trigger: concurrent-claim-race observeras i praktiken, eller ett behov av visuell Kanban-yta blir akut nog för att motivera att lägga till Hermes Kanban som en spegling (aldrig som primär källa).
