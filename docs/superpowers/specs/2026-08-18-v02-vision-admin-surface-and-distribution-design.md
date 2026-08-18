# Cortxt v.02-vision: adminyta, distribution och open-core

Status: **FÖRSLAG — inte beslutat.** Detta dokument följer samma disciplin som
`cortxt-agent-platform-target-architecture.md` §29: det föreslår riktningar
för repositoryts beslutsprocess, det beslutar dem inte. Inget här är
auktoritativt förrän det går genom en ADR.

Skriven efter en session (2026-08-18) som (1) verifierade wedge B-valideringens
verkliga status, (2) städade repot (mergade Fas 5–8, stängde döda
issues/grenar), och (3) förde ett brainstorming-samtal om vad som kommer
efter Fas 8. Detta dokument är resultatet av del 3.

## 1. Utgångsläge (verifierat, inte antaget)

- **Fas 0–8 i target-architecture.md är klara.** `main` är grönt (441 tester
  passerar), Fas 5–8 (RLM, geometric reasoning, self-hosted inference,
  learning loop) är mergat.
- **Wedge B (ADR-015) är formellt stämplad validerad (#101/#116) men svagare
  i praktiken än stämpeln säger.** T2 ("annan utvecklare klarar handover")
  var bara delvis bevisad — en riktig person testade en liten del, resten
  var en simulerad agent. T3–T5 ströks inte om under den här sessionen.
- **Ingen sammanhängande "börja här"-väg fanns** genom wedge B förrän den här
  sessionen byggde `agent-platform/cli/unified_cli.py` — en gemensam
  entry point som kedjar de tidigare 6 separata CLI:erna. Detta landade
  direkt på `main` utan PR/review (processavsteg, inte kvalitetsproblem —
  koden är testad).
- **README:s licensrad står fast:** "viewable, not open source." Rikard är
  formellt fortfarande första och enda användaren (ADR-014).

## 2. Vad som förändrades i det här samtalet

Operatören uttryckte, i tur och ordning:
1. Han vill fler användare på sikt, men det är inte beslutat ännu (ADR-014
   står fast: en användare, ej OSS).
2. Cortxts differentiering är fyrfaldig: multi-engine routing,
   portabilitet/leverantörsoberoende, kontrollplattan som vallgrav,
   reasoning-lagret som långsiktig fördel över tid.
3. **Ett pip-installerbart CLI-paket räcker inte.** Han vill ha en yta där
   han administrerar sina agenter och verktyg — inte bara ett kommando.
4. **Ytan ska automatiskt upptäcka vilka agenter/verktyg som finns
   installerade** (Buzz, Hermes, Claude, Codex, m.fl.), låta operatören
   koppla på dem, och hantera en nyckel som sätts in i respektive system —
   "1-klicksinstallation" för hela stacken.
5. **Monetisering: open-core.** Det som ligger i det här repot kan vara
   gratis/öppet lager; adminytan/plattformslagret är det som eventuellt
   monetiseras. Exakt modell är inte beslutad.

Punkt 3–4 river uttryckligen upp **ADR-015**, som pausade webb/Operator
Cockpit som produktyta till förmån för "repository-native + CLI (primärt)".
ADR-015 har en explicit review trigger: *"en observerad
användarefterfrågan pekar på en annan wedge."* Operatörens egen växande
behov av en adminyta är den signalen — det är därför detta dokument finns,
inte en genväg runt ADR-015.

## 3. Förslag: Admin-/Discovery-yta

**Arbetsnamn:** Cortxt Control Surface (namn inte beslutat).

**Reviderad form (efter vidare samtal samma session): orkestrator-i-CLI +
widget-UI + enhetlig addon-mekanism.**

- **Orkestratoragenten kör i/via CLI:t** — den lokala processen, inte en
  hostad backend. Detta löser en av §6:s ursprungliga öppna frågor: adminytan
  är lokal, inte SaaS, eftersom den bara är ett visuellt skal ovanpå en
  process operatören redan kör.
- **UI:t är en tunn widget**, inte en fullständig separat applikation — dess
  jobb är att visualisera och styra vad orkestratorn redan gör, inte äga egen
  logik. Visuell referens (operatörens egen jämförelse): Windows
  snabbinställningar/notisyta — litet, kompakt overlay-fönster som ligger
  ovanpå annat arbete, inte ett eget fullskärmsfönster man växlar till.
  **Innehåll (föreslaget):** ett levande flöde, inte statiska paneler —
  ett "vattenfall" av vad som byggs just nu, löpande kostnad, fynd
  orkestratorn själv gjort om vad som kan förbättras (kopplar till Fas
  8:s learning-loop-kandidater, §18 i target-architecture.md), och en
  översiktsvy över hela agentflottan. **Uttalat mål:** kunna hålla igång
  en stor agentflotta som aldrig slutar arbeta, överblickbar via ett
  mycket rent UI/UX — inte en yta man aktivt måste läsa i detalj för att
  lita på att allt går rätt.
- **Addons är en enhetlig mekanism, inte bara visuell:** en addon kan lika
  gärna vara en ny agent-adapter (backend, t.ex. stöd för ett nytt
  agent-runtime) som en ny UI-panel (frontend) — samma
  tilläggsmekanism för båda. Detta är i praktiken samma mönster som §31/§32
  i target-architecture.md redan beskriver för Skill Platform/Tool
  Platform — addons bör troligen VARA skills/tools i den meningen, inte ett
  tredje, parallellt tilläggssystem.
- Kärnfunktion (fortfarande föreslagen, inte specad i detalj): skannar
  operatörens miljö för kända agent-runtimes (Hermes, Buzz, Claude Code,
  Codex, Pi, …) — motsvarande det redan existerande mönstret i
  `scripts/worker_adapters.py`:s `ADAPTER_REGISTRY` — låter operatören koppla
  på/av varje upptäckt runtime, och hanterar credentials/nycklar centralt
  ("1-klicksinstallation").
- Detta **är** den tidigare sparade "credential broker"-idén
  (`project_credential_broker_idea` i minnet), nu upphöjd från
  roadmap-anteckning till en konkret del av v.02-scope.

**Relation till befintlig arkitektur:**
- Detta är en ny produktyta ovanpå samma Control Plane-kärna
  (§6 i target-architecture.md) — inte en ny kärna. Invarianterna i §28
  gäller oförändrat: Control Plane äger mandat, agenten äger inte sitt eget
  scope, self-approval är förbjudet.
- Om addons kan utöka orkestratorns förmågor (ny agent-adapter, nytt
  verktyg), gäller §31/§32:s evolutions-/versioneringsregler även för
  addons — en addon som utökar logik är inte undantagen granskning bara för
  att den kom in via UI:t istället för via kod.
- Nyckelhantering över flera externa system är ett **säkerhetskänsligt**
  ytterligare ansvar Control Plane idag inte har. Kräver ett eget
  threat-model-avsnitt innan implementation — se öppna frågor nedan. Detta
  väger tyngre nu: en addon-mekanism som kan installera ny körbar logik
  (inte bara UI) är en bredare attackyta än en ren visualiseringswidget.

## 4. Förslag: Distribution och prissättning

**Reviderad (efter vidare samtal): inte ett lager-baserat gratis/betalt-snitt
utan en användningsbaserad modell.** Operatörens formulering: CLI, UI och
orkestrering kan vara gratis rakt av — värdet som motiverar betalning är att
rätt modell-/agent-/runtime-val (routing) sparar användaren pengar i
tokenkostnad, inte att UI:t eller CLI:t i sig är låsta bakom en betalvägg.

**Föreslagen form (hypotes, inte beslutad, siffror indikativa):**
- Gratis, obegränsat av tid initialt eller en tidsbegränsad trial (~2
  veckor nämnt) — full tillgång till CLI, widget-UI, orkestrering och
  routing mot förkonfigurerade gratismodeller.
- Därefter en låg månadsavgift (~49 kr/månad nämnt som riktmärke, **inte
  en beräknad siffra** — se öppen fråga nedan) för fortsatt full
  användning.
- **Den specifika betaldifferentieraren kan vara embedding-/
  routingmotorn** — d.v.s. exakt den mekanism som kontinuerligt förbättrar
  effektiviteten över tid (Fas 6:s geometric reasoning/Voyage-embeddings,
  Fas 8:s learning loop). Det är motorn som gör routingen bättre än ett
  statiskt val, inte CLI:t/UI:t som är produkten man betalar för.
- **Positioneringsreferens operatören själv drog:** likt OpenRouter/
  liknande modell-aggregatorer, men med ett orkestreringslager och UI
  ovanpå — inte bara ren modell-proxy.

Detta ändrar inte grundprincipen i §5 (kollegor ser repot, kunder ser bara
paketet/widgeten) men **ersätter** den tidigare idén om ett strikt
lager-baserat gratis/betalt-snitt.

Detta är en **utökning** av ADR-015:s "repository-native + CLI"-beslut, inte
en ersättning: CLI:t förblir den primära, gratis ingången. Adminytan är ett
nytt, andra lager ovanpå.

## 5. Relation till repo-hygien (denna sessions andra spår)

Den städning som redan gjorts (mergat Fas 5–8, stängda döda issues, döda
grenar identifierade för radering) är oberoende av v.02-visionen och
behöver inte vänta på den. Men den bekräftar samma distinktion som §2:
**kollegor/portfolio-publik** kan se det här repot (rensat), **kundpublik**
ska aldrig behöva det — de möter bara det installerbara paketet (§4.1) eller
adminytan (§3).

## 6. Öppna frågor (flaggade, inte gissade)

- Namn på adminytan, orkestratoragenten och det installerbara paketet.
- ~~Hosted kontra lokal adminyta~~ — löst i samtalet: orkestratorn kör
  lokalt i/via CLI:t, UI:t är en widget ovanpå den. Kvarstående fråga:
  betyder det ändå att ADR-015:s "webb pausad"-beslut formellt behöver
  upphävas/kompletteras med en ny ADR, eftersom "widget-UI" ändå är en
  visuell yta ADR-015 inte förutsåg?
- **"En agentflotta som aldrig slutar jobba"** — målet i §3 om en stor,
  ständigt aktiv agentflotta måste stämmas av mot befintliga invarianter
  (§28: operatören behåller mandat över irreversibla beslut; §11:
  RLM-motorns hårda gränser för budget/djup/stopp) INNAN det byggs, inte
  efteråt. Att göra flottan "överblickbar via rent UI" löser inte
  runaway-cost- eller runaway-scope-risken i sak, bara hur den syns.
  Behöver ett eget kostnads-/gränsavsnitt, inte antas vara löst av att
  widgeten visar kostnad.
- Var addon-mekanismen ska specas: är addons formellt samma sak som
  §31/§32:s skills/tools (troligt, men inte beslutat), eller ett eget
  fjärde begrepp? Om addons kan installera körbar logik (inte bara UI)
  gäller samma granskningskrav som för skills/tools — vem godkänner en
  addon innan den får köra?
  **Delvis besvarat:** Rikard äger/underhåller kärn-addons, men
  **community-addons tillåts** — modellen är Obsidian-plugins: en
  "granskad av oss"-badge markerar vad som gått igenom review, ogranskade
  community-addons finns kvar men syns som just ogranskade. Detta är i
  praktiken samma form som Fas 8:s PromotionGate (kandidat → evidens →
  verifierad befordran, §18/plan `2026-08-18-fas8-...`), fast applicerad
  på addons istället för learning-kandidater — sannolikt samma mekanism
  bör återanvändas, inte byggas parallellt. Fortfarande öppet: vem/vad
  utför granskningen i praktiken (Rikard manuellt, Codex-review, automatisk
  policy-check, eller en kombination), och vad som händer vid en addon som
  visar sig skadlig efter att den redan fått badge.
- **Konkretiserar kopplingen till Fas 8 ytterligare:** en learning-kandidat
  (`agent-platform/learning/candidate.py`) som visar sig användas mycket
  ska med ett knapptryck kunna publiceras som en addon på "marknaden" —
  d.v.s. PromotionGate-flödet (redan byggt, testat, 441 gröna tester)
  utökas till att sluta med "publicera som addon" som ett möjligt utfall,
  inte bara "aktivera internt." Detta stärker rekommendationen ovan att
  addon-mekanismen bör byggas som en förlängning av PromotionGate, inte
  som ett separat system.
- Säkerhetsmodell för att lagra tredjepartsnycklar (Hermes/Claude/Codex-API-
  nycklar) centralt: kryptering i vila, åtkomstkontroll, vad händer vid
  intrång i adminytan (blast radius om en nyckel-broker komprometteras är
  större än om ett enskilt verktyg gör det). Väger tyngre nu: en addon som
  kan installera ny logik är en bredare attackyta än en ren widget.
- **Prissättningen är ännu en hypotes, inte en beräkning.** ~49 kr/månad
  och "2 veckor gratis" är riktmärken operatören nämnde, inte
  räknade fram — enligt egen arbetsregel ska inget kostnadspåstående
  stå som fakta förrän det finns en verklig uträkning (t.ex. faktisk
  Inference Gateway-kostnad per genomsnittsanvändare mot vad routing
  sparar). Innan prissättning skrivs in i en ADR: räkna på faktiska
  provider-/embedding-kostnader mot vad routing verkligen sparar, för
  minst ett realistiskt användningsmönster.
- Var exakt gränsen går mellan "gratis rakt av" och "kräver betalning" om
  det inte är ett lager-snitt längre utan tid/användning — trial-period,
  kvot, eller båda?
- Hur mäts/bevisas "sparar tokens genom rätt val" konkret för en
  användare (vad är baslinjen routing jämförs mot)?
- Tidsförhållande till T2–T5: ska adminytan vänta tills wedge B är på
  riktigt validerad (inte bara formellt stämplad), eller byggas parallellt?
- Om/när ADR-015 formellt behöver en ny ADR som ändrar/kompletterar den.

- **Orkestratorn bör känna till varje anslutet verktygs faktiska kommando-/
  skill-yta** (t.ex. Claude Codes slash-kommandon, Hermes egna kommandon,
  Codex-flaggor) — inte bara att verktyget finns, utan vad det specifikt
  kan anropas med. Annars riskerar orkestratorn att uppfinna en omväg när
  ett redan implementerat kommando löser uppgiften bättre. Sannolikt en
  strukturerad capability-manifest per adapter (utökning av
  `ADAPTER_REGISTRY`-mönstret), inte fri dokument-RAG — men om manifestet
  blir stort/fritextigt kan Voyage-embeddings från Fas 6 återanvändas för
  sökning inom det. Inte beslutat: var manifestet hämtas ifrån (statisk,
  eller live `--help`-introspektion), och hur det hålls i synk när ett
  verktyg uppdateras.
  **Vidareutveckling av samma punkt:** detta gäller inte bara agent-val
  utan **skill-val inom agenten** — t.ex. orkestratorn känner igen att en
  uppgift matchar `mattpocock-skills:tdd` och väljer Claude för den
  specifika uppgiften, medan en dokumentationstung uppgift routas till
  Codex, eller att ett Hermes-specifikt verktyg är bäst i klassen för en
  deluppgift och kan kedjas med en `superpowers`-skill som körs någon
  annanstans. Routing bör alltså kunna ske på skill-nivå, inte bara
  agent-nivå, och skills bör kunna kombineras/kedjas över agentgränser och
  i flera nivåer — samma komposition som barn/barnbarn-frågan ovan
  (Fas 5:s RLM recursive Supervisor-design), fast applicerad på skill-val
  snarare än agent-spawning. Inte beslutat: hur "känner igen uppgiftens
  form" konkret avgörs (mönstermatchning, embedding-likhet via Voyage,
  eller en enklare regelbaserad triage), och var gränsen går mellan
  orkestratorns egen routing-logik och att bara delegera valet till
  respektive agents egen skill-triggering (Claude Codes egen
  `using-superpowers`-mekanism gör redan denna typ av matchning internt —
  dubblerar orkestratorn det arbetet, eller läser den av vad agenten redan
  valde?).

## 7. Rekommenderat nästa steg

Detta dokument beskriver riktning, inte en implementationsplan. Rekommenderat
nästa steg är att lösa öppna frågor i §6 tillräckligt för att skriva en ny
ADR som formellt adresserar ADR-015:s review-trigger, innan admin-ytan
specas i detalj eller kod skrivs. Inte skriva kod mot denna vision innan
den ADR:en finns.
