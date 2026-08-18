# Fas 5 — RLM v1 — design

Status: approved (interactive brainstorming dialogue with operator 2026-08-17)
Date: 2026-08-17
Authority: architectural proposal for one bounded vertical slice; does not override
`docs/agents/current-operating-model.md`
Related: `docs/architecture/cortxt-agent-platform-target-architecture.md` §7.3
(child-run-kontrakt), §7.4 (statusmappning, inkl. `lost` → `blocked`), §11 (RLM
Engine — grundloop, hårda gränser, stoppvillkor), §11.4 (dataklass vid
context-ingest), §17.2 (jämförelsekrav för ny reasoning-strategi mot baseline),
§19.1 (RLM-specifika bounds i dispatch-kontraktet), §20.3 (rekursionsrisk), §23
(Fas 5 — RLM v1, inkl. Supervisor-skalningsleverabeln), §25 (första
produktinkrementets 2-barn/djup-1-tak, uttryckligen överskridet av denna spec —
se beslut 1), §27 (Öppna beslut #3, #10, #11), §28 (Arkitektoniska invariants);
`2026-08-16-fas4-supervisor-v01-design.md` (mönstret detta bygger direkt på —
process-modell, IPC, budget, recovery, heartbeat); `2026-08-16-fas4-exit-
criterion-checklist.md` (vad som faktiskt är empiriskt bevisat i Fas 4, inklusive
miljöfakta för att köra riktig inference)

> **Reviderad efter Kimi K2.7-code-granskning (via Hermes, 2026-08-17).**
> Granskningen hittade fem interna motsägelser, sju punkter av avvikelse mot
> target-arkitekturen, sex felaktiga/ofullständiga kodpåståenden, nio obehandlade
> felfall och sju falsifierbarhetsproblem i eval-harnessen. Alla är adresserade
> nedan (markerade "(reviderat)" där texten ändrats i sak). Fullständig
> granskningstext: se sessionen dispatchad från denna brainstorming-konversation.

> **Grundfynd som formar hela denna spec:** `agent-platform/reasoning/recursive/
> rlm_engine.py` och hela `reasoning/`-paketet (kernel, recursive, geometric)
> existerar redan, men är en **helt in-process, synkron, deterministisk
> mekanik-bevisning** — ingen riktig inference (stub `InferencePort`), inget
> kontext-store, ingen persistens av `ProblemState`, rekursion sker via Python
> call-stack. `decompose_state` delar upp nästlade Python-listor, inte verkliga
> problem. `research_profile.py` är 7 rader med ett enda tool (`read_fixture_file`)
> och ingen materialiserad fixture. `Coordinator` i `agent-platform/supervisor/`
> har idag bara `run_m1`/`run_m2` — två scenario-specifika metoder, ingen generell
> rekursiv spawn-kapacitet. Fas 5 är alltså inte en förlängning av färdig
> infrastruktur i de flesta av dessa moduler — det är första gången de blir
> verkliga.

## Purpose

Prove Fas 5's exit criterion från fas-trappan (§23): **RLM slår en enklare baseline
på minst en långkontextklass inom godkänd total kostnad** (reviderat — §23 säger
"slår", inte "slår eller matchar"; se beslut 6 för den enda pass-regeln: RLM lyckas
i minst 2 av 3 oberoende rundor), med en i förväg definierad marginal, verifierat
över N=3 oberoende utvärderingsrundor. Om detta inte uppnås nedgraderas RLM-spåret
genom operatörsbeslut till en experimentell/diagnostisk strategi bakom Reasoning
Kernel (konsekvens för Fas 6, se §23).

Utöver reasoning-kapaciteten kräver §23 en egen, uttalad leverabel: **skalning av
Supervisor** från Fas 4 v0.1:s bevisade tak (2 barn, djup 1) till det djup och den
branch-budget RLM kräver (§19.1: `max_depth=2`, `max_total_children=6`). Detta är
inte ett antagande som redan är löst av Fas 4 — `Coordinator.run_m1`/`run_m2` har
ingen generell rekursion, så detta är ny mekanik som byggs enligt samma
processmodell, IPC och persistensdisciplin Fas 4 redan bevisade, inte en ny
disciplin.

## Scope decisions

Sju beslut, resolverade genom interaktiv brainstorming-dialog med operatören
2026-08-17. Recorded så "varför" inte går förlorat.

### 1. Rekursionsmekanism — process-baserad via Supervisor, inte in-process

**Beslut:** RLM:s barn-calls är riktiga Supervisor-spawnade child-processer
(detacherade OS-processer, file-based IPC via `session_state.py`), skalat till
`max_depth=2`/`max_total_children=6`. Inte en förlängning av dagens
`rlm_engine.py`-mönster (Python call-stack, in-process).

**Varför:** §23 kopplar Fas 5 explicit till en Supervisor-skalningsleverabel —
det är meningslöst om RLM:s rekursion aldrig anropar Supervisor. Process-baserad
rekursion ger också äkta, mätbara kostnads-/tidsbudgetar per gren (nödvändigt för
exit-kriteriets kostnadsjämförelse), vilket in-process-simulering inte kan ge
ärligt.

**Konsekvens:** dagens `rlm_engine.py` (in-process, stub-inference) blir en
referens-/prototypimplementation för bounds/stop-conditions-mekanik, inte v1:s
produktionskod. Den ersätts, inte förlängs.

### 2. Coordinator generaliseras till rekursiv `run_node`

**Beslut:** `Coordinator` byggs om från `run_m1`/`run_m2` (två hårdkodade
scenarier) till en generell `run_node(spec, depth, budget_pool)`.

**"Bibliotekskapacitet" preciserat (reviderat efter granskning):** Kimi
identifierade en motsägelse mellan att kalla detta en "bibliotekskapacitet,
inte en root-bunden tjänst" och data-flödets beskrivning av att ett barn "blir
själv spawner för sina egna barn". Upplösning: **koden** (modulen `coordinator.py`)
är återanvändbar av vilken process som helst — det är vad "bibliotek" syftar på.
Men **varje process som faktiskt dekomponerar vidare kör en fullständig
Coordinator-instans med full ansvarsbörda**: den äger sin egen `ProcessSpawner`,
skriver egna `child.spawned`/`spawn_failed`/`budget.*`-events till sin egen
sessionslogg, och övervakar sina egna barns heartbeat. Det är inte ett passivt
biblioteksanrop från root — root anropar bara sitt eget barn en gång (`spawn`);
det barnet blir därefter en fullvärdig spawner i sin egen rätt, oberoende av
root efter spawn-ögonblicket (detacherad process, per Fas 4 beslut 2). Djup 2 är
en riktig processgräns, inte simulerad in-process-rekursion i ett barn.

**Varför inte hybrid (djup 1 process, djup 2 in-process):** skulle bara delvis
uppfylla beslut 1:s motivering (ärlig kostnads-/tidsmätning) och komplicera
budget-modellen med två olika mätsätt beroende på djup.

**Budget — alla §11.2-gränser, inte bara `max_total_children` (reviderat efter
granskning):** Kimi noterade att `run_node`s signatur bara bar `depth` och en
`budget_pool` konflaterad med `max_total_children`, medan §11.2 listar åtta
gränser (`max_depth`, `max_branches_per_node`, `max_total_children`,
`max_model_invocations`, `max_context_reads`, `max_runtime_seconds`, `max_cost`,
`max_output_size`) som §20.3 kräver ska gälla "root samt samtliga barn tillsammans
som mål". `budget_pool` är därför inte en enda siffra utan en `RLMConfig`-liknande
struktur som bär **samtliga** åtta fält. Alla åtta hanteras genom samma disjunkta
förallokeringsprincip som `max_total_children` redan hade (Fas 4 beslut 7,
"post-hoc rollover only, no mid-flight borrowing"): root delar hela sin pool
(alla åtta dimensioner) bland sina direkta barn vid spawn; varje delträd delar
vidare sin egen tilldelning bland sina barn. Ingen realtidsaggregering över
processgränser för någon av de åtta dimensionerna (§27 #11 förblir öppet för alla
åtta, inte bara kostnad/tokens — v1 verkställer precis som v0.1, bara disjunkt
förallokering). Om ett delträds tilldelning (i någon dimension) tar slut måste
noden agera som löv (ett modellanrop på sin kontextskiva) istället för att
dekomponera vidare — en kontrollerad nedgradering, inte ett fel.

**Kombinatorisk konsekvens, uttalad explicit (reviderat — tillagd efter
granskning):** med `max_total_children=6` och `max_branches_per_node=3`: om root
spawnar 3 barn är 3 av 6 förbrukade direkt; återstående pool (3) delas mellan de
3 barnen, så vart och ett kan i genomsnitt allokera högst 1 barnbarn innan sin
egen andel av `max_total_children` tar slut. Djup 2 är alltså matematiskt smalt
vid v1:s bounds — de flesta grenar förväntas stanna vid djup 1 eller bli mycket
smala vid djup 2. Detta är en medveten konsekvens av att följa dispatch-
kontraktets §19.1-värden rakt av, inte en bugg — men v1:s eval-fixturer (se
beslut 6) måste vara utformade så att den dekomposition de faktiskt behöver får
plats inom detta smala träd, annars bevisar exit-kriteriet ingenting.

**Sibling-konkurrens (reviderat — tillagd efter granskning):** v1 spawnar syskon
**sekventiellt**, konsekvent med hur `run_m1` redan är implementerad idag
(`coordinator.py`, sekventiell spawn-loop). Parallell sibling-spawn är en
deferred decision (se tabellen längst ner) — inget scenario i v1 kräver det, och
det skulle komplicera den disjunkta budget-modellen (två syskon som förbrukar
samma pool samtidigt utan realtidsaggregering är precis den typ av race §20.3
varnar för).

### 3. Problem State-persistens — återanvänder `session_state.py`, ingen ny store

**Beslut:** Problem State har inget eget lagringsformat. Varje RLM-nod som
faktiskt blir en Supervisor-spawnad child (en dekompositionspunkt) får sin egen
hash-chained sessionslogg, exakt som Fas 2–4:s befintliga kontrakt. Problem
State-trädet (parent/child, confidence, applied_operator, transformation_log)
rekonstrueras av root som en **projektion över hela sessionsloggträdet** — samma
mönster som `run_tree.build_index` redan gör för Supervisors platta två-barn-fall,
nu applicerat rekursivt.

**Löser §27 punkt 3** (första persistensformatet för Problem State/trajectories,
tidigare öppet och blockerande).

**Varför inte en separat Problem-State-store:** Fas 4 beslut 4 avvisade explicit
en andra auktoritativ store med argumentet att en Supervisor-krasch mellan två
filer återinför precis den synk-bugg hash-chaining finns för att förhindra. Det
argumentet är starkare, inte svagare, vid djup 2/6 barn — fler noder, fler
tillfällen för två format att glida isär. Nackdelen (fler sessionsfiler vid djup
2) är en overhead-kostnad, inte en korrekthetsrisk — `session_state.py` är redan
dimensionerad för per-child-processer (Fas 4 skapar redan en session per child av
processisoleringsskäl).

**Nyansering:** inte varje `ProblemState`-nod blir en session — bara noder som
faktiskt spawnas som Supervisor-child. Interna reasoning-steg inom en och samma
child-process (t.ex. flera operatorer applicerade i sekvens innan den barnet
beslutar sig för att dekomponera vidare) loggas som events i den processens egen
sessionslogg, precis som `CodingLoop` idag loggar flera interna steg i en session.

**§7.3:s child-run-kontrakt vid djup 2 (reviderat — tillagd efter granskning):**
Kimi noterade att §7.3 kräver att varje child run bär `child_run_id`, samma
`issue_id` och root-`run_id`, avgränsat syfte/output-schema, allokerad
sub-budget, context-referens, max rekursionsdjup och queryable status — och att
spec:en inte sa hur detta hanteras vid djup 2. Upplösning: fälten ärvs
oförändrade nedåt i trädet — ett barnbarns session bär samma root-`run_id` och
`issue_id` som hela RLM-runet startade med (inte sin förälders session-id som
root), plus sitt eget `child_run_id` och `parent_run_id` (den nya, explicita
länken som saknas i Fas 4:s platta två-barn-modell där "parent" alltid var
root). `max recursion depth` i child-specen är `max_depth - depth_so_far`, så
ett barnbarn på djup 2 med `max_depth=2` startar med `max recursion depth=0` och
måste vara löv. Queryable status vid djup 2 fungerar identiskt med djup 1:
`run_tree.build_index` (se beslut 2:s omdesign nedan) läser hela trädet av
sessionsloggar, oavsett djup.

### 4. Context store — strukturell slicing, inga embeddings

**Beslut:** ny modul `agent-platform/context_store/` (peer till `state/`,
`inference/` — delad mellan RLM-noder, inte körningsspecifik som `runtime/`).
Lagrar stora externa kontexter (repo-filträd för Coding-klassen,
dokumentsamlingar för research-klassen) som **referenser**: `{source:
"repo"|"document_set", locator: <path>, range: [start, end]}` — fil/rad eller
sid/avsnitt/token-intervall. Inget embeddings-index.

**Varför inte embeddings-baserad semantisk slicing:** §27 punkt 10 flaggar
embeddings som olöst och explicit blockerande för **Fas 6**, inte Fas 5.
`InferencePort` normaliserar idag inte embeddings alls. Att kräva embeddings i
Fas 5 skulle koppla detta fas-exit till ett beslut som redan är uttalat som en
senare fas problem — en scope-utvidgning ingen leverabel i §23 kräver.

**Dataklass-ärvning:** varje slice ärver käll-dataklassen och förblir synlig för
Tool Gateway/provider eligibility genom hela RLM-trädet, enligt §11.4 (regeln
fanns redan, implementeras nu första gången på riktigt).

**Hur RLM använder den:** `decompose_state` (idag: delar nästlade Python-listor)
byggs om till att, givet en context-referens och problemformulering, välja vilka
delreferenser varje barn får läsa — aldrig hela källan. Varje slice-läsning
räknas mot `context_reads`-budgeten (§19.1).

**Persistens:** slice-referenser skrivs som `context.sliced`-events (locator +
range) i den spawnande nodens sessionslogg — ingen separat store-fil att hålla
synkad, konsekvent med beslut 3.

**Dataklass-propagering, mekanism preciserad (reviderat — tillagd efter
granskning):** §11.4 kräver att inläst kontext ärver och behåller sin dataklass,
synlig för Tool Gateway vid varje efterföljande anrop — spec:en påstod detta utan
mekanism. Konkret: `context.sliced`-eventet bär ett obligatoriskt `data_class`-
fält, kopierat från källans redan existerande per-nod/relation-metadata (§9.3,
som redan finns). Varje efterföljande tool-anrop som konsumerar en slice måste
inkludera dess `data_class` i sin Tool Gateway-admission-request (samma
schema-/permission-/effektklassvalidering Fas 3 redan bygger, §32.1) — Tool
Gateway avslår om dataklassen inte är godkänd för det anropande verktyget/
providern. Ärvningen är alltså en explicit fältkopiering vid varje slice-steg,
inte ett implicit antagande.

### 5. Två långkontextklasser i samma v1-leverans: Coding Agent och research/dokument

**Beslut:** exit-kriteriet kräver bara "minst en långkontextklass", men v1
levererar båda samtidigt, byggda och bevisade i sekvens inom samma fas (inte som
separat fast-follow).

- **Coding Agent-klassen:** återanvänder Fas 3:s vertikal och verktyg
  (read/search/patch/test) direkt. Fixture: en bugg/ändring som kräver att läsa/
  resonera över fler filer än ett enda modellanrops fönster rymmer. **Baseline
  (reviderat — kodpåstående var fel):** granskningen visade att `kernel/
  strategy.py`:s befintliga `Strategy.DIRECT` är **modellfri** — `engine.py`
  kör `inspect(state)` → `verify(state, expected)` via deterministiska,
  modellfria operatorer (`operators.py`) som flatten/summerar innehåll. Det är
  inte "ett modellanrop, trunkerad kontext". Baseline för Fas 5:s eval-harness
  är därför **ny kod**: en separat `baseline_direct.py` i eval-harnessen (inte
  en återanvändning av `kernel/strategy.py`) som gör exakt ett riktigt
  modellanrop med kontexten trunkerad till modellens fönster. Den delar namnet
  "direct" konceptuellt (encelligt, ingen dekomposition) men är inte samma kod
  som `Strategy.DIRECT`, som förblir oförändrad och fortsätter sin nuvarande
  roll i Reasoning Kernel.
- **Research/dokument-klassen:** `research_profile.py` (idag 7 rader, ett verktyg,
  ingen materialiserad fixture) byggs ut. Ny fixture: en syntetisk samling långa
  dokument (i linje med det redan refererade `vertical-01-ai-act`-namnet) där
  avgörande fakta är spridda över flera dokument, en är gömd bland decoys — samma
  "nål i höstack"-disciplin som Fas 4:s M2 använde aritmetik-decoys. **Inga
  riktiga kund-/kommundokument** (harness-dokumentets regel: sådana får aldrig
  committas) — fixturen är helt syntetisk. Nya verktyg: `list_fixture_documents`,
  utökad `read_fixture_file` med range/slice-parametrar mot `context_store`. Ny
  `verification_policy`: **`citation-match-v1`** — strukturell assertion mot
  förväntade extraherade fakta + källreferenser, inte modell-baserad grading
  (harness-dokumentets krav på att skilja strukturella assertions från
  probabilistisk grading). Det konkreta schemat (fältnamn, jämförelselogik för
  en referens-match) är inte låst i denna spec — implementationsplan-nivå-
  uppgift, nämnd här så den inte glöms mellan spec och plan.

**Varför sekvenserat inom fasen snarare än parallellt från start:** samma
disciplin som Fas 4:s M1→M2 — bevisa mekaniken (rekursiv Coordinator, context
store, budget-nedärvning) på den redan bevisade vertikalen (Coding Agent) först,
förläng sedan till research/dokument-klassen där både context_store-formen
(dokument istället för kod) och verifieringsmekanismen (`citation-match-v1`
istället för tester) är nya samtidigt. Isolerar felkälla precis som Fas 4:s
staging gjorde.

**Explicit operatörsbeslut:** detta breddar Fas 5:s scope utöver vad §23:s
exit-kriterium strikt kräver — en medveten avvikelse, inte en smygande
scope-utvidgning. Om tidsbudgeten pressas är research/dokument-klassen den delen
med lägst risk att skjuta till en uppföljande leverans, eftersom Coding-klassen
ensam uppfyller exit-kriteriet.

### 6. Eval/baseline-harness — binär success-jämförelse över N=3 oberoende rundor

**Beslut:** "slår baseline" mäts som task-success (tester gröna för
Coding-klassen, `citation-match-v1` för research-klassen), inte en glidande
poäng. Marginal (den enda pass-regeln, se Purpose-korrigeringen ovan): **RLM
lyckas i minst 2 av 3 oberoende rundor.** "Oberoende rundor" = tre olika
fixture-instanser per klass (annan gömd-fakta-placering, andra decoys),
seedad/deterministisk generering för reproducerbarhet — inte samma fixture kört
tre gånger.

**Fixturens giltighet fastställs analytiskt i förväg, inte genom att döma
resultatet i efterhand (reviderat — löser ett falsifierbarhetsproblem
granskningen hittade):** ursprunglig text sa "om baseline oväntat lyckas görs
fixturen om" — Kimi påpekade att detta skyddar hypotesen "RLM slår baseline"
från att någonsin kunna motbevisas av ett baseline-lyckande, eftersom regeln
per definition bortförklarar det utfallet. Ny regel: fixture-**generatorn**
(inte varje enskild instans efter körning) måste vid författandet bevisas
strukturellt omöjlig för baseline — ett dokumenterat argument (t.ex. "svaret
kräver att kombinera fakta från N disjunkta kontextskivor, ingen enskild
modellkontext innehåller alla N samtidigt") som gransknings av generatorns kod
en gång, inte omprövas per körning. Om baseline ändå lyckas i en verklig
N=3-runda **räknas det som en giltig baseline-vinst** — inte en anledning att
kassera rundan. Om det händer i fler än en av tre rundor är det ett tecken på
att fixture-generatorns strukturella argument var fel, och det utreds som ett
öppet fynd inför nästa version av generatorn — inte tystas bort under
implementationen.

**Kostnadstak, verifierat post-hoc (reviderat — löser en intern motsägelse
granskningen hittade):** ursprunglig text påstod både "ingen realtidsaggregering
över processgränser" (beslut 2) och "fail-closed mitt i en run" på kostnadstaket
— omöjligt samtidigt, eftersom root inte kan känna till nodträdets totala
kostnad förrän alla sessioner är terminala och deras loggar är lästa. Korrekt
regel: RLM:s totalkostnad (summan av `cost`-fältet från varje sessions
`RLMRun`, aggregerat av root **efter** att hela trädet nått terminalt tillstånd)
får vara högst **5× baseline:s kostnad** för samma fixture-instans, som v1:s
startvärde. En run som överskrider taket flaggas post-hoc som en förlorad
runda i N=3-utvärderingen — den avbryts inte mitt i, eftersom det inte finns
någon mekanism som kan upptäcka överskridandet förrän efteråt. Multiplikatorn
är policydata (samma klass som §12.4:s sök-vikter — versionsstyrd, testad mot
fixtures, inte inbränd i kod), inte en hårdkodad konstant, så den kan
differentieras per uppgiftstyp senare. Se "Deferred decisions" för nedåttrenden
Fas 6 förväntas bevisa.

**Kostnadskälla (reviderat — tillagd efter granskning):** `cost` kommer från
`InferencePort`/providerns egen usage-rapportering per modellanrop (samma väg
`runtime/text_inference_port.py` redan tracker), summerat in i varje sessions
`RLMRun.cost`-fält (fältet finns redan i `rlm_engine.py`). Utan en verklig
providerkälla är 5×-jämförelsen inte maskinellt beräkningsbar — detta var
tidigare outtalat.

**§17.2:s jämförelsekrav — explicit, uttalad avvikelse på en punkt (reviderat —
tillagd efter granskning):** §17.2 kräver att en ny strategi jämförs mot
baseline med samma task fixture, modell/provider, tool-/nätverksgränser,
**totalbudget**, verifieringsmetod och startstate. Fas 5 v1 uppfyller alla utom
totalbudget: baseline och RLM körs mot **samma modell/provider** (ingen
providerbias i jämförelsen) och **samma verifieringsmetod** (samma tester för
Coding-klassen, samma `citation-match-v1`-facit för research-klassen på samma
fixture-instans). Totalbudget avviker medvetet — RLM:s hela syfte är att göra
mer arbete (flera modellanrop över flera noder) för att lösa vad ett enda anrop
strukturellt inte kan; att kräva identisk budget skulle göra exit-kriteriet
olösbart per definition. §23:s exit-kriterium ("inom godkänd total kostnad")
är mer specifikt för detta fall och ersätter §17.2:s generella
budget-symmetri-krav här — 5×-multiplikatorn *är* den godkända kostnadsramen.
**Startstate skiljer sig också per design** (baseline får trunkerad kontext,
RLM får full kontext-referens) eftersom det är precis vad som testas — detta är
konsekvent med hur baseline är konstruerad för att vara strukturellt oförmögen,
inte en jämförelseasymmetri som bör elimineras.

**Verkligt modellanrop krävs för exit-beviset:** samma disciplin som Fas 4:s
sista steg — strukturella tester räcker inte för att hävda att RLM slår
baseline. N=3-rundorna för båda klasserna måste köras mot en riktig live-modell.

### 7. Felhantering — fail-closed per nod, konsekvent med §11.2/§20.3

**Beslut:** hårda gränser (redan definierade i `bounds.py`) verkställs fail-closed
per nod. Se tabellen i "Error handling" nedan för det fullständiga fallschemat.
Central princip: en gräns som skulle överskridas stoppar hellre grenen/noden än
att tyst trunkera eller degradera — samma disciplin `RLMEngine._solve` redan
följer, nu verkställt per processgräns istället för per Python-anrop.

## Components

**`agent-platform/context_store/`** (ny modul):

| Modul | Ansvar |
|---|---|
| `store.py` | Referensmodell `{source, locator, range}`. Ingen inbäddad kontext, ingen embeddings-indexering. Dataklass-ärvning från källa. |
| `slicer.py` | Given en context-referens och en dekompositionsplan: välj vilka delreferenser varje barn får. Räknar `context_reads`. |

**`agent-platform/supervisor/`** (utökad):

| Modul | Ändring |
|---|---|
| `coordinator.py` | Ny `run_node(spec, depth, budget_pool)` — generaliserar `run_m1`/`run_m2`. `run_m1`/`run_m2` behålls oförändrade (Fas 4:s exit-bevis rör dem inte) men RLM-flödet använder den nya metoden. |
| `run_tree.py` | **Signaturändring, inte bara utökning (reviderat — granskningen visade nuvarande signatur inte bär om till trädform):** dagens `build_index(root_session_doc, child_session_docs: dict[str, dict], total_budget)` är platt. Ny signatur tar en rekursiv insamling av sessionsdokument (t.ex. `build_index(root_session_doc, child_tree: dict[str, "NodeDocs"])` där `NodeDocs` själv kan bära sina egna barns dokument) — en redesign av datatypen barnen representeras med, inte samma dict-form applicerad "rekursivt" på ett oförändrat sätt. |
| `budget.py` | Disjunkt förallokering utökas till att rekursivt splitta ett delträds tilldelning (samtliga åtta §11.2-dimensioner, se beslut 2) bland sina egna barn (samma princip som Fas 4 beslut 7, en nivå djupare). |

**`agent-platform/reasoning/recursive/`** (ombyggd, inte bara utökad):

| Modul | Ändring |
|---|---|
| `rlm_engine.py` | Ersätts av process-baserad orkestrering via `Coordinator.run_node`. Nuvarande in-process-version blir referens/prototyp för bounds-mekanik, arkiveras eller flyttas till en `_prototype`-markering. |
| `decomposer.py` | Byggs om från att dela nästlade Python-listor till att, givet en context-referens (från `context_store`), producera delreferenser per barn. |
| `bounds.py` | **Korrigerat (granskningen visade två av fyra fält redan matchar):** endast `max_depth` (4→2) och `max_total_children` (12→6) behöver ändras — `max_model_invocations=20` och `max_context_reads=30` är redan dispatch-kontraktets §19.1-värden i dagens kod. |
| `integrator.py`, `challenger.py`, `stop_conditions.py` | Vidareanvänds, men måste hantera riktiga (inte stub-) resultat och ett `lost`-barn (se Error handling) som en möjlig integrationsinput. |

**`agent-platform/runtime/research_profile.py`** (utökad från 7 rader):

Nya verktyg `list_fixture_documents`, utökad `read_fixture_file` med
range/slice mot `context_store`. Ny `verification_policy`: `citation-match-v1`.

**Ny fixture-infrastruktur:**

- Coding-klassen: en repo-fixture vars nödvändiga kontext spänner fler filer än
  ett enda modellanrops fönster, seedad generering av tre oberoende varianter.
- Research-klassen: en syntetisk dokumentsamling-fixture, samma
  seedade tre-varianters-krav.
- Eval-harness: kör baseline (`direct`) och RLM på samma fixture-instans,
  jämför success + kostnad, producerar en rapport per runda.

## Data flow

**RLM-run (generell, oavsett klass):**

```
Root: ny RLM-run, content = context-referens + problemformulering
  → Reasoning Kernel väljer recursive (RLM) som strategi
  → Coordinator.run_node(spec, depth=0, budget_pool=max_total_children=6)
    Om dekomposition ger värde (RLM Engine-heuristik):
      slicer.py väljer delreferenser per barn
      spawn barn 1..N (ProcessSpawner, disjunkt budget-andel)
      varje barn: om depth+1 < max_depth OCH bedömer vidare dekomposition värd →
        rekursivt run_node(child_spec, depth+1, child_budget_pool)
      annars: barnet är löv → ett modellanrop mot sin kontextskiva
    Om inte: noden är löv direkt → ett modellanrop
  → integrator.py folder resultat uppåt trädet (samma mönster som idag,
    men över riktiga barn-sessioner istället för in-process-anrop)
  → challenger.py kontrollerar motsägelse vid varje integrationssteg
  → root: run_tree.build_index() projicerar hela sessionsloggträdet till
    Problem State, resultat + trajectory_ref returneras i result envelope (§19.2)
```

**Eval-runda (per klass, N=3):**

```
För var och en av 3 seedade fixture-varianter:
  kör baseline (ny baseline_direct-kod, ett riktigt modellanrop, trunkerad kontext,
    samma modell/provider som RLM) → success/fail, cost_baseline
  kör RLM (ovanstående flöde) → success/fail, cost_rlm
  EFTER att hela RLM-nodträdet är terminalt (inte mitt i — ingen realtidsaggregering,
    se beslut 2/6): aggregera cost_rlm = summan av cost över hela sessionsloggträdet
  post-hoc: cost_rlm <= 5 × cost_baseline? Om inte: run flaggas BUDGET_EXHAUSTED,
    räknas som förlorad runda (run stoppades inte mitt i — det fanns ingen
    mid-run-signal att stoppa på)
Aggregera: RLM måste lyckas i >= 2 av 3 rundor (den enda pass-regeln — se
  Purpose). Om baseline lyckas i en runda räknas det som en giltig baseline-vinst,
  inte en anledning att kassera rundan (se beslut 6:s falsifierbarhets-fix).
```

## Error handling

| Fall | Hantering |
|---|---|
| Ett delträd har slut på sin tilldelade `total_children`-andel | Noden agerar som löv (ett modellanrop på sin egen kontextskiva) — kontrollerad nedgradering, inte fel. |
| `max_depth` skulle överskridas | Samma som idag (`MaxDepthError` → `BudgetExhausted`), verkställt per processgräns. |
| En Supervisor-spawnad RLM-barnprocess kraschar/tappas | Samma `lost`-status som Fas 4 beslut 6. Föräldranoden hanterar ett saknat barn som ofullständig evidens i `integrate`/`challenge` — inte en krasch av hela trädet. Root blir `blocked`, orsak pekar på den förlorade grenen (**§7.4 i target-arkitekturen** — korrigerat citat; ursprunglig text hänvisade till "§27 punkt 4", som faktiskt är execution-sandbox-frågan, inte lost-child-statusmappningen). |
| Kontradiktion (`ContradictionError`) i ett delträd | Stoppar grenen. Fas 6:s riktiga attractor-detektering finns inte än — v1 eskalerar inte automatiskt till mänsklig operatör om inte `explicit_stop_policy` kräver det. |
| Kostnadstaket (5× baseline) skulle överskridas | **Post-hoc, inte mitt i en run (reviderat, se beslut 6):** upptäcks först när hela nodträdet är terminalt och kostnaderna summerade. `stop_reason=BUDGET_EXHAUSTED` sätts retroaktivt, räknas som förlorad runda i N=3-utvärderingen. |
| `context_store`-referens utanför dataklassens tillåtna scope | Tool Gateway avslår innan exekvering (Fas 3-mönster), baserat på `context.sliced`-eventets `data_class`-fält (se beslut 4) — strukturerat fel, inte tyst trunkerad kontext. |
| Baseline lyckas på en fixture-variant | **Räknas som en giltig baseline-vinst (reviderat, se beslut 6:s falsifierbarhets-fix)** — inte en anledning att kassera rundan. Upprepat baseline-lyckande (>1 av 3 rundor) utreds som ett tecken på att fixture-generatorns strukturella omöjlighets-argument var fel. |
| En depth-1-nod kraschar med levande barnbarn-processer (föräldralösa barnbarn, tillagt efter granskning) | Barnbarnen är detacherade processer (Fas 4 beslut 2) och överlever sin förälders krasch precis som förälderns barn skulle överleva rootens krasch. Recovery-mekanismen (Fas 4 beslut 6, PID + start-time) körs av den återupptagande processen på **varje nivå** — root återansluter sina direkta barn; ett depth-1-barn som återupptas (eller vars ansvar tas över av root vid full recovery) återansluter i sin tur sina egna barnbarn via samma mekanism. |
| Spawn-failure i en icke-root-nod (tillagt efter granskning) | Samma `spawn_failed`-event som root skriver idag (`coordinator.py`), men skrivet till **den spawnande nodens egen sessionslogg**, inte rootens — konsekvent med att varje dekomponerande nod äger sin egen Coordinator-instans (se beslut 2). |
| Timeout i en nästlad join (djup 2, tillagt efter granskning) | Varje nivå har sin egen timeout, ärvd nedåt som en andel av förälderns kvarvarande `max_runtime_seconds`-budget (samma disjunkta förallokeringsprincip som övriga §11.2-gränser, beslut 2). En timeout på djup 2 propagerar uppåt som ett förlorat/ofullständigt barn för djup-1-noden, som i sin tur hanterar det som i raden ovan ("lost"/ofullständig evidens). |
| Kontext-referens ogiltig vid läsning (fil ändrad/borttagen mellan slicing och läsning, tillagt efter granskning) | Strukturerat fel (`ContextReferenceStale`), hanteras som en löv-nivå-modellanrops-misslyckande — noden rapporterar ofullständig evidens uppåt, samma väg som ett `lost`-barn. Repo-/dokumentkopior är immutabla inom en runs livslängd (samma copy-in-workspace-princip som Fas 3), så detta förväntas vara sällsynt i v1:s fixturer, men hanteringen är explicit, inte outtalad. |
| Run avslutas (helt eller delvis) med `BUDGET_EXHAUSTED` på djup 1 (partial-result envelope, tillagt efter granskning) | §19.2:s result envelope-fält (`branches_explored`, `model_invocations`, `max_depth_reached` osv) fylls med de faktiska, delvisa värdena aggregerade från de noder som faktiskt terminerade — inte utelämnade. `termination_reason` sätts till `budget_exhausted` istället för `acceptance_criteria_verified`; `children`-listan i envelopet inkluderar även icke-terminala/`lost` barn med sin senast kända status, inte bara lyckade barn. |

## Testing strategy

- **Budget-nedärvning genom flera nivåer:** enhetstester för att en gräns
  ärvs korrekt root → barn → barnbarn, inklusive korrekt löv-degradering vid
  slut på tilldelning.
- **Recovery/`lost` på djup 2:** utökning av Fas 4:s recovery-simulering till
  att tappa ett barnbarn, inte bara ett direkt barn.
- **`run_tree.build_index()`-rekursion:** identiska sessionsloggträd in →
  identiskt Problem State-träd ut, oavsett anropsordning (samma renhetsgaranti
  som Fas 4, nu över godtyckligt djup).
- **`context_store`-slicing:** dataklass ärvs korrekt genom flera slice-steg;
  Tool Gateway avslår korrekt vid scope-överträdelse.
- **Staged fixture-rollout:** Coding-klassen bevisas isolerat innan
  research/dokument-klassen körs, samma felkälleisolering som Fas 4:s M1→M2.
- **Verkligt modellanrop för exit-beviset:** N=3-rundorna för båda klasserna
  måste köras mot en riktig live-modell (samma disciplin som Fas 4:s sista,
  avgörande steg) — strukturella/stubbade tester bevisar mekanik, inte
  exit-kriteriet.
- **Determinism i fixture-generering:** seedad generering så N=3-rundorna är
  reproducerbara vid granskning.

## Out of scope for this slice

- Embeddings-baserad semantisk context-slicing — strukturell (fil/rad,
  sid/avsnitt) slicing endast. Embeddings är §27 punkt 10, blockerande för
  Fas 6, inte ett Fas 5-krav (beslut 4).
- Realtidsaggregering av kostnad/tokens över processgränser (§27 punkt 11) —
  fortsatt disjunkt förallokering + post-hoc rollover, som v0.1.
- Geometric Reasoning-integration (`recursive_geometric`-strategin, §10.1) —
  Fas 6:s ansvar. Fas 5 bygger `recursive`-strategin fristående.
- Automatisk mänsklig eskalering vid kontradiktion utöver
  `explicit_stop_policy` — riktig attractor-detektering (§12.3) finns inte än.
- Mer än två långkontextklasser, eller klasser utöver Coding Agent och
  research/dokument.
- Riktiga kund- eller kommundokument i någon fixture — endast syntetiska
  dokumentsamlingar.
- Dynamisk, uppgiftsberoende kostnadsmultiplikator — 5× är en fast v1-policy;
  differentiering per uppgiftstyp är en deferred decision (se nedan).
- En operatörsdashboard för att följa en RLM-run live — samma out-of-scope-linje
  som Fas 4 (CLI/query räcker).
- Parallell sibling-spawn — v1 spawnar syskon sekventiellt (beslut 2, tillagt
  efter granskning), samma som dagens `run_m1`.
- Automatisk diskstädning/loggvolym-tak för sessionsloggträdet — vid djup 2 med
  upp till 6 barn växer antalet sessionsfiler märkbart (tillagt efter
  granskning); v1 har ingen städningspolicy utöver vad Fas 2–4 redan har.

## Deferred decisions (revisit triggers for later phases)

| Decision | Revisit when |
|---|---|
| Kostnadsmultiplikator (5×) som fast värde | Fas 6:s Geometric Reasoning (path-scoring, `escape_attractor`) ger mätbar evidens att kostnad per lyckad run kan trenda nedåt — då blir multiplikatorn en uppgiftsberoende, versionsstyrd policyparameter istället för en fast konstant. |
| Realtidsaggregering av kostnad/tokens över processgränser (§27 #11) | Konkurrerande/parallella barn i en framtida fas gör disjunkt förallokering för konservativt (analogt med Fas 4:s motsvarande deferred decision om mid-flight budget borrowing). |
| Embeddings-baserad context-slicing | Fas 6 löser §27 punkt 10 (embeddings-provider) — kan då utvärderas som ett tillägg ovanpå den strukturella slicingen, inte en ersättning. |
| Research/dokument-klassens fixture-djup (idag syntetisk, en domän) | Om Fas 5 v1:s exit är bevisat och en riktig operativ användning av research-klassen blir aktuell — fler dokumenttyper, riktiga (godkända) datakällor under rätt dataklasspolicy. |
| `rlm_engine.py`:s in-process-prototyp | Arkiveras eller omdefinieras explicit som teststöd för bounds-mekanik i isolation, inte lämnas som förvirrande dubbel implementation vid sidan av process-baserad `Coordinator.run_node`. |
| Parallell sibling-spawn (tillagt efter granskning) | En framtida fas visar att sekventiell spawn dominerar total runtime på ett sätt som spelar roll — samma "inte schemalagt, utvärderas mot verklig belastning"-disciplin som Fas 4:s IPC-deferral. |
| Diskstädning/loggvolym-tak (tillagt efter granskning) | Verklig produktionsvolym av RLM-runs visar att sessionsloggträdets diskavtryck faktiskt blir ett problem — inte en förhandsoptimering. |
