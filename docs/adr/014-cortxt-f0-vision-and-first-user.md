# ADR-014: Cortxt Product Vision and First User (F0)

**Status:** Accepted  \
**Date:** 2026-08-13  \
**Deciders:** Rikard (operatör)  \
**Technical Story:** CORTXT F0/F1 beslutspaket, godkänd 2026-08-13 efter oberoende Codex-review (runda 2 GODKÄND); evidensbevis `.hermes/codex/f0f1-decision-packet-2026-08-13.md` (v0.2, gitignored lokalt)

## Context

Batch 0 Foundation Authority Freeze är genomförd: GitHub Project 4 är `Legacy AI Workspace Delivery — frozen`, den befintliga backloggen är legacy-backlog, och ett legacy-item är inte automatiskt Cortxt-roadmap eller dispatchbart. Innan roadmap- och dispatch-arbete kan börja måste Cortxts produktvision, första användare och primära problem vara explicit beslutade.

Underlagen som prövats:
- Målarkitekturens ägarhypotes (`docs/architecture/cortxt-agent-platform-target-architecture.md`, UNTRACKED proposal): användaren/organisationen äger arbetsförmågans mål, tillstånd, minne, reasoning, verktyg, evidens och utveckling, medan modeller/inferenceproviders/externa agentmotorer är utbytbara resurser.
- Produktpremisser (operatörskontext, delvis normativa): Cortxt är den enda produkten; Rikard är första faktiska användare; coding/research/analysis/compliance är profiler ovanpå Cortxt, inte produktgränsen; Agent Platform-målet är ett proposal; Operator Cockpit/web är pausad legacy.
- Repositoryinvariant: Problem State och trajectories ägs av Cortxt och är portabla; Agent Core importerar inte Hermes/Pi/Prime/provider (`agent-platform/README`, `cortxt-agent-platform-target-architecture.md`).

## Decision

**F0 — Balanserad vision.** Cortxt är ett system för att skapa, styra och utveckla långvariga intelligenta arbetsförmågor som resonerar, använder verktyg, minns, verifierar och agerar under mänskligt mandat — ägda av användaren/organisationen, med modeller och leverantörer som utbytbara resurser.

**Första användare:** Rikard (utvecklare, operatör, produktbyggare, researcher/analytiker, verksamhetsutvecklare, provider-/modellväljare, kostnads-/risk-/beslutsansvarig). Ingen fiktiv persona.

**Primära problem (första användaren):** Rikard kan idag köra enskilda agentarbeten, men kan inte ägligt skapa, återuppta, styra, verifiera och hålla providerneutrala långvariga arbetsförmågor med garanterad dataklass-/providerpolicy. Konsekvens: manuella handoffs, splittrad evidens, osäker kostnad, och risk att känsligt material hamnar hos icke-godkända providers.

**Produktdefinition:** Cortxt är en leverantörsneutral agentplattform där användaren äger arbetsförmågans tillstånd, reasoning, minne, verktyg, evidens och utveckling; modeller/inferenceproviders/externa agentmotorer är utbytbara resurser bakom Cortxt-ägda portar och kontrakt; coding/research/analysis/compliance är versionerade profiler ovanpå samma kärna.

**Non-goals (explicita):**
1. Cortxt tränar ingen egen generell grundmodell och skriver ingen egen CUDA-inference-engine.
2. Cortxt konkurrerar inte som GPU-marknadsplats eller som inferenceprovider i första generationen.
3. Cortxt löser inte enbart coding-, compliance- eller workflow-problemet — dessa är profiler, inte produktgränsen.
4. Cortxt tillåter inte obegränsad självmodifiering och ersätter inte operatörens mandat över irreversibla beslut.
5. Cortxt ersätter inte GitHub som kanoniskt task record och återstartar inte Operator Cockpit/webb som första produktyta av historisk tröghet.

## Consequences

### Positive
- Entydig produktgrund som separat vision, plattform, wedge, produkt, resa och milstolpe (ingen sammanblandning).
- Ägarhypotesen är stadfäst: providerneutralitet + portabelt tillstånd/evidens är differentieringen.
- Klargör vad som INTE ska byggas/konkurreras om (non-goals), vilket styr wedge-val och scope.

### Negative
- Målarkitekturen förblir proposal tills en separat ADR/accepterad arkitektur (se ADR-016); F0 bekräftar riktning men godkänner inte hela plattformsbygget.
- Norcom/CSL är ett proof environment, inte bevisad marknad; "kommuner som beachhead" förblir hypotes.

### Risks
- Att en wedge (coding eller compliance) reduceras till produktgräns — motverkas av non-goal 3.
- Att "agentiskt operativsystem" används som externt produktlöfte (för brett) i stället för framåtblickande ambition.

## Alternatives Considered
1. **Konservativ** (Cortxt = spårbart kontrollplan ovanpå Hermes/Pi/Codex) — förkastad: reducerar Cortxt till en förbättring av befintlig baseline och bryter mot ägarhypotesen/premiss 6.
2. **Expansiv** ("agentiskt operativsystem" för allt kunskaps-/kodarbete + egen inference) — förkastad: förväxlar vision med första produkt/wedge, visionsteaterrisk, kräver stora byggen före bevis.
3. **Balanserad** — vald.

## Validation
- [x] Codex oberoende review GODKÄND (runda 2, 2026-08-13); alla korrigerade fynd verifierade.
- [x] Rikards godkännande registrerat (2026-08-13).
- [ ] Beslutspaketet materialiseras som versionshanterad artefakt (denna ADR + ADR-015, 016).
- [ ] Dokumentation uppdaterad, evidens direktlänkar bevarade.

## Expiry/Review Trigger
- Review by: 2026-11-13
- Trigger: ny marknadseviden (betalning), uppdaterad ägarhypotes, eller ett observerat användarbehov som motsäger visionen.
