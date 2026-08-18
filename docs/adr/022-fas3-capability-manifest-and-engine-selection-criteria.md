# ADR-022: Fas 3 v0.1 — capability manifest shape and engine-selection criteria

**Status:** Accepted
**Date:** 2026-08-18
**Deciders:** Rikard (operatör), Claude Code (utkast)
**Technical Story:** rian010194/cortxt#166 (Fas 2, klar), v.02-milstolpens Fas 3 (`.hermes/plans/2026-08-18-v02-milestone-wayfinder.md`)

## Context

ADR-019 (Accepted 2026-08-16) beslutade att routing mellan kodningsmotorer ska vara
dynamisk och per-uppgiftsklass (kostnad, kapabilitet, dataklass, tillgänglighet) — inte
en migrationsplan mot en enda motor. Dess egen valideringslista lämnade dock uttryckligen
öppet: *"Urvalskriterier (vilken uppgiftsklass → egen Coding Agent vs extern motor)
definierade — spåras som öppet beslut, inte avgjort av detta ADR."* Sökning i hela repot
(2026-08-18) bekräftar att inget urvalsmekanism, capability-manifest eller
routing-funktion existerar än — bara den öppna frågan i v.02-visionens §6 (commit
`7ea503c`, ren dokumentation) och ADR-019:s obockade checklisterad.

Samma kväll gav två Hermes-dispatches på samma uppgift (issue #165, #166) konkret
evidens för varför statiska antaganden om "vilken motor" är farliga: `deepseek-v4-flash`
var periodvis overksam (429 "all replicas at capacity"), en Hermes-worktree grenade av
fel bas pga ett verktygsfel, och ett dispatch-försök byggde fel yta trots en detaljerad
uppgiftsbeskrivning. Operatören har uttryckt att slutmålet är betydligt bredare än ett
statiskt val mellan två motorer: routingbeslutet ska på sikt kunna välja Hermes, Pi,
Claude direkt, eller en kedja av flera motorer i olika ordning, beroende på
uppgiftsklass — och att dagens Hermes-profiler (satta upp innan worktree-stödet fanns)
kan vila på föråldrade antaganden.

Detta ADR beslutar **inte** den fullständiga visionen (kedjad multi-motor-orkestrering).
Det beslutar den smala v0.1-skiva som Fas 3 kan bygga nu, utan att låsa in en design som
måste rivas upp när kedjning/inlärd tillförlitlighet läggs till senare.

**Viktigt att inte tappa bort:** target-architecture.md §29 punkt 5 slår redan fast att
"RLM och geometric reasoning ägs av Cortxt Agent Core" — orkestratorns routingbeslut är
alltså inte tänkt att för alltid vara den deterministiska `route()`-funktionen nedan.
Fas 5 (RLM v1) och Fas 6 (Geometric Reasoning v1) har redan design/implementation i
`agent-platform/reasoning/geometric/` och motsvarande specs
(`docs/superpowers/specs/2026-08-17-fas5-rlm-v1-design.md`,
`...fas6-geometric-reasoning-v01-design.md`). När v0.1:s statiska
mönstermatchning visar sig otillräcklig är den avsedda efterträdaren *den befintliga*
Geometric Reasoning-motorn i den här kodbasen — inte en ny, ouppfunnen ML-mekanism. Det
här ADR:et bygger v0.1 som en medveten bootstrap mot det målet, inte som en konkurrerande
permanent lösning.

## Decision

**v0.1-omfattning (Fas 3):**

1. **Capability-manifest — motoragnostiskt format.** Varje registrerad motor deklarerar:
   - `engine_id` (str) — t.ex. `claude-direct`, `hermes`
   - `task_shapes` (list[str]) — fria taggar motorn hanterar, t.ex. `tdd`, `widget-ui`,
     `research`, `security-review`. Inte NLP-klassificerade — uppgiften taggas av
     avsändaren (samma mönster som Fas 3-forskningsdokumentets §2.5 "capability tags":
     typad uppifrån, inte ett plattformskontrakt än).
   - `cost_class` (str: `free` | `cheap` | `metered`)
   - `reliability_class` (str: `verified` | `unverified` | `degraded`) — satt manuellt,
     inte inlärt i v0.1. Ikvällens `deepseek-v4-flash`-incident är exemplet: en motor kan
     markeras `degraded` för hand utan kodändring.
   - `notes` (str, valfri) — fri text för operatörskontext (t.ex. "profiler satta upp
     innan worktree-stöd fanns, verifiera before trust").

2. **Routing-funktion — enkel, deterministisk mönstermatchning.** `route(task_tags:
   list[str]) -> EngineChoice` väljer bland manifest vars `task_shapes` skär mot
   `task_tags`, filtrerar bort `degraded`, sorterar på `cost_class` (free före cheap
   före metered), och returnerar första träffen plus skälet (vilken tagg matchade, vilka
   uteslöts och varför). Ingen träff → deterministisk fallback till `claude-direct`
   (ikvällens erfarenhet: den enda motorn som inte behövde en omstart eller gav fel yta),
   med skälet loggat, inte tyst.

3. **Två registrerade motorer i v0.1:** `claude-direct` och `hermes`. Pi, Codex, Copilot
   läggs till som adaptrar när de faktiskt kopplas in (ADR-019 håller dem som permanenta
   routingval, men "adapter finns" ≠ "adapter registrerad i v0.1-manifestet" — att gissa
   deras `task_shapes`/`reliability_class` innan de faktiskt körts vore att koda in
   antaganden ingen verifierat).

**Explicit inte v0.1 (för att undvika att bygga fel abstraktion nu):**
- Kedjning av flera motorer i sekvens för en uppgift.
- Inlärd/dynamisk `reliability_class` baserad på faktisk track record (kräver Fas 8:s
  learning-loop-mekanik, inte uppfunnen på nytt här).
- ML- eller embedding-baserad uppgiftsklassificering (samma "bygg inte spekulativt"-regel
  som Fas 3-forskningsdokumentets §3.1 redan tillämpar på task-shape-igenkänning).
- Pi/Codex/Copilot-manifest (adaptrarna finns inte kopplade in än).

## Consequences

### Positive
- Löser ADR-019:s öppna punkt med en skiva liten nog att verifiera ikväll, utan att
  gissa på kedjning eller inlärning som ingen data finns för än.
- Manifestformatet är motoragnostiskt från start — att lägga till Pi/Codex senare är att
  lägga till en post, inte en omdesign (samma mönster som Fas 3-forskningens
  dict-constant-att-YAML-serialiseringsresonemang, applicerat på routing istället för
  tool-kontrakt).
- `reliability_class: degraded` ger en konkret, kodfri väg att agera på ikvällens
  Hermes-erfarenhet utan att vänta på en inlärningsmekanism.

### Negative
- Statiskt/manuellt satta `reliability_class`-fält kräver att någon (operatören eller
  Claude) faktiskt uppdaterar dem när en motor visar sig otillförlitlig — inget
  automatiskt facit än.
- Fallback-till-`claude-direct` betyder att routingbeslutet i praktiken favoriserar en
  motor tills fler är verifierade — en medveten bias, inte en neutral algoritm.

### Risks
- Om Pi/Codex läggs till utan att uppdatera `task_shapes` ärligt (gissade taggar istället
  för verifierade) uppstår samma "kodade in gissningar som kontrakt"-misstag ADR-016
  redan varnat för på ett annat lager.
- Fri-text `task_shapes` utan normalisering (samma öppna fråga som Fas 3-forskningens §7
  punkt 3, ärvd hit) kan drifta mot inkonsekventa taggar mellan avsändare.

## Alternatives Considered
1. **Bygg kedjad multi-motor-orkestrering direkt** — förkastad: ingen verifierad data om
   vilka uppgiftsklasser som faktiskt gynnas av kedjning; skulle gissa en arkitektur
   ADR-019 själv varnar för att låsa fast för tidigt.
2. **Behåll status quo (allt via Hermes-profiler)** — förkastad: exakt det ADR-019
   beslutade emot, och ikvällens två misslyckade dispatches är direkt evidens mot att
   lita blint på en enda motor.
3. **Inlärd routing (embeddings/ML) från start** — förkastad: samma
   bygg-inte-spekulativt-regel som redan gäller task-shape-igenkänning i
   Fas 3-forskningsdokumentet; ingen träningsdata finns.

## Validation
- [ ] Manifest-schema implementerat och testat (minst `claude-direct` + `hermes`)
- [ ] `route()`-funktion har testtäckning för: träff, ingen träff (fallback), degraded
      motor exkluderad, kostnadssortering
- [ ] Ikvällens Hermes-attempt-1/attempt-2-erfarenhet manuellt kodad som exempel i
      `hermes`-manifestets `notes`-fält (spårbarhet, inte bara i minnesloggen)
- [ ] Dokumentation uppdaterad: `.hermes/plans/2026-08-18-v02-milestone-wayfinder.md`
      Fas 3-avsnittet pekar hit istället för mot `ADAPTER_REGISTRY`

## Expiry/Review Trigger
- Review by: 2026-09-18
- Trigger: en tredje motor (Pi, Codex, eller Copilot) faktiskt kopplas in och behöver ett
  verkligt manifest, ELLER track record-data visar att statisk `reliability_class` inte
  räcker och en inlärningsmekanism (Fas 8-mönster) behövs, ELLER Geometric
  Reasoning-motorn (Fas 5/6) är redo att ta över `route()`:s roll — se Context-notisen
  om target-architecture.md §29 punkt 5.
