# ADR-023: Cortxt supports both bottom-up and top-down integration, not one exclusively

**Status:** Proposed
**Date:** 2026-08-19
**Deciders:** Rikard (operatör), Claude Code (utkast)
**Technical Story:** Operatörsdiskussion 2026-08-19 (jämförelse mot [Hindsight](https://hindsight.vectorize.io/)); v.02-visionens §6 (`docs/superpowers/specs/2026-08-18-v02-vision-admin-surface-and-distribution-design.md`, tillägg 2026-08-19)

## Context

Cortxts README-tagline ("Users own the work's state, memory, tools, evidence, and
evolution; models, inference providers, and external agent engines remain replaceable
resources behind Cortxt-owned contracts") beskriver en **top-down**-arkitektur: Cortxt
äger kontrollplanet, externa motorer (Hermes, Pi, Codex, Claude Code) är utbytbara
resurser bakom Cortxt-ägda kontrakt. Alla mönster byggda i v.02-milstolpen hittills
(routing/`engine_manifest.py`, `credential_broker.py`, `addon_review.py`) förutsätter
den riktningen — de fungerar bara för att Cortxt äger orkestreringsloopen.

Operatören jämförde 2026-08-19 mot Hindsight, en specialiserad minnestjänst för
AI-agenter. Hindsights integrationsstruktur är motsatt: **bottom-up** — en smal,
väldefinierad tjänst som *andra* ramverk (LangGraph/LangChain, CrewAI, Vercel AI SDK)
och coding-agenter (Claude Code, Codex CLI, Cursor CLI, m.fl.) kopplar in sig mot, utan
att Hindsight äger deras orkestrering.

Jämförelsen synliggjorde en verklig avvägning, inte bara en stilfråga:

- **Bottom-up** vinner på adoptionshastighet (lägg till en integration, inget
  stackbyte) och lågt inlåsning för den som integrerar — men kan aldrig garantera
  helhetsegenskaper (mandat, audit, no-self-approval) över en uppgifts hela
  livscykel, bara inom sin egen skiva.
- **Top-down** vinner på att kunna hålla ihop precis de invarianter ADR-019 och
  ADR-022 redan bygger på — men kräver en mycket större yta byggd rätt innan något
  är användbart, och en tyngre första-ask till en ny användare.

Detta är inte en avvägning som måste lösas åt ena hållet. Ingenting hindrar Cortxt
från att vara top-down internt (mot de engines den förvaltar) samtidigt som den
erbjuds bottom-up utåt (till andra ramverk/agenter som vill konsumera dess
kontrollplan som en tjänst) — samma sätt Hindsight själv erbjuds till Claude
Code/Cursor/CrewAI idag, fast med Cortxt som tjänsten istället för minnet.

## Decision

**Cortxt är top-down internt, permanent — det ändras inte av detta beslut.**
Kontrollplanet äger routing, mandat, audit och kontrakt mot alla engines den
förvaltar (ADR-019, ADR-022). Inget av detta öppnas upp.

**Cortxt blir också avsiktligt bottom-up-konsumerbar utåt, som en andra,
parallell integrationsväg — inte en ersättning för den första.** Andra ramverk
(LangGraph/LangChain, CrewAI, Vercel AI SDK, m.fl.) eller andra coding-agenter ska
på sikt kunna anropa in i Cortxts kontrollplan som en tjänst (t.ex. "ge mig
mandat-verifierad routing/audit för den här uppgiften"), utan att själva behöva
flytta sin egen orkestrering till Cortxt.

**Detta ADR beslutar riktningen, inte ytan.** Vilken konkret form den bottom-up-vända
integrationen tar (Python/TypeScript/Go-SDK, MCP-server, REST-API) är **inte**
beslutat här — det är samma öppna fråga som Fas 6:s "installerbara paket" (§4.1 i
visionsdokumentet) redan brottas med, och löses där, inte här. Det här ADR:et
säkerställer bara att det arbetet designas med en extern konsument i åtanke, inte
bara den lokala CLI/widget-operatören.

## Consequences

### Positive
- Löser upp en falsk motsättning: v.02-arbetet hittills (routing, credential broker,
  addon-gate) behöver inte överges eller kompromissas för att också stödja externa
  konsumenter — de är ortogonala, inte konkurrerande, riktningar.
- Öppnar en adoptionsväg som inte kräver att någon flyttar sin befintliga
  LangGraph/CrewAI-stack till Cortxt för att få nytta av dess mandat-/audit-garantier.
- Ger ett konkret ramverk för att utvärdera framtida API-designbeslut: "fungerar
  detta för en extern konsument, inte bara den interna CLI:n?" blir en verklig fråga
  att ställa, inte en eftertanke.

### Negative
- Två integrationsytor att underhålla i längden (intern kontrollplans-API + extern
  konsument-yta) istället för en.
- Risk att den externa ytan byggs för smalt (bara det den interna CLI:n råkar
  behöva) om den inte designas medvetet — samma typ av misstag ADR-016 redan
  varnat för på ett annat lager (att koda in en enda användares antaganden som ett
  plattformskontrakt).

### Risks
- Utan en tydlig prioritetsordning kan "bygg i båda riktningarna" tolkas som
  "bygg allt samtidigt" — inte avsikten. Fas-sekvensen (topp-down-arbetet pågår
  redan, Fas 4/5/6) fortsätter före den externa ytan; detta ADR ändrar inte
  ordningen, bara bekräftar att den externa riktningen inte är avfärdad.
- Den externa ytans säkerhetsmodell (vem/vad får anropa in i kontrollplanet
  utifrån, med vilket mandat) är inte specad här — kräver ett eget avsnitt när
  arbetet faktiskt påbörjas, samma disciplin som credential-broker-hotmodellen
  (Fas 1) höll för den interna ytan.

## Alternatives Considered
1. **Enbart top-down, avfärda extern konsumtion** — förkastad: stänger av en
   adoptionsväg utan verklig kostnad att hålla öppen just nu (ingen kod behöver
   skrivas för att bara *inte stänga dörren*), och matchar inte operatörens
   uttalade avsikt att jobba i båda riktningarna.
2. **Enbart bottom-up, bygg om Cortxt som en tjänst andra orkestrerar** —
   förkastad: river upp hela v.02-milstolpens grundpremiss (kontrollplanet äger
   mandat/audit) och gör redan byggda mönster (ADR-019, ADR-022,
   credential-brokern) meningslösa.
3. **Vänta med beslutet tills Fas 6:s paketeringsfråga är löst** — förkastad:
   riktningen (båda) påverkar hur Fas 6-arbetet designas; att vänta skulle bara
   flytta samma beslut till en punkt där mer kod redan antar bara-top-down.

## Validation
- [ ] Fas 6:s "installerbara paket"-arbete (§4.1) refererar till detta ADR när
      den externa integrationsytans form specas.
- [ ] Ingen framtida kontrollplans-API designas utan att uttryckligen fråga "hur
      ser detta ut för en extern konsument?"
- [ ] Ett eget säkerhets-/mandatavsnitt skrivs för den externa ytan innan den
      implementeras, inte efteråt.

## Expiry/Review Trigger
- Review by: 2026-11-19
- Trigger: Fas 6:s paketeringsarbete når en punkt där den externa ytans konkreta
  form (SDK/MCP/REST) måste väljas, ELLER en extern integrationsförfrågan
  (t.ex. någon vill koppla LangGraph mot Cortxt) gör frågan akut tidigare.
