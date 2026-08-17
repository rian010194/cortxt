# Fas 5 — RLM v1 — design

Status: approved (interactive brainstorming dialogue with operator 2026-08-17)
Date: 2026-08-17
Authority: architectural proposal for one bounded vertical slice; does not override
`docs/agents/current-operating-model.md`
Related: `docs/architecture/cortxt-agent-platform-target-architecture.md` §11 (RLM
Engine — grundloop, hårda gränser, stoppvillkor), §19.1 (RLM-specifika bounds i
dispatch-kontraktet), §20.3 (rekursionsrisk), §23 (Fas 5 — RLM v1, inkl. Supervisor-
skalningsleverabeln), §25 (första produktinkrementets 2-barn/djup-1-tak), §27 (Öppna
beslut #3, #10, #11), §28 (Arkitektoniska invariants); `2026-08-16-fas4-supervisor-v01-
design.md` (mönstret detta bygger direkt på — process-modell, IPC, budget, recovery,
heartbeat); `2026-08-16-fas4-exit-criterion-checklist.md` (vad som faktiskt är
empiriskt bevisat i Fas 4, inklusive miljöfakta för att köra riktig inference)

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

Prove Fas 5's exit criterion från fas-trappan (§23): **RLM slår eller matchar en
enklare baseline på minst en långkontextklass inom godkänd total kostnad**, med en i
förväg definierad marginal, verifierat över N=3 oberoende utvärderingsrundor. Om
detta inte uppnås nedgraderas RLM-spåret genom operatörsbeslut till en
experimentell/diagnostisk strategi bakom Reasoning Kernel (konsekvens för Fas 6,
se §23).

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
scenarier) till en generell `run_node(spec, depth, budget_pool)` som är en
**bibliotekskapacitet**, inte en root-bunden tjänst. En Supervisor-spawnad
barnprocess som RLM Engine bedömer behöver vidare dekomposition kör samma
Coordinator-logik i sin egen process och blir själv spawner för sina egna barn.
Djup 2 är en riktig processgräns, inte simulerad in-process-rekursion i ett barn.

**Varför inte hybrid (djup 1 process, djup 2 in-process):** skulle bara delvis
uppfylla beslut 1:s motivering (ärlig kostnads-/tidsmätning) och komplicera
budget-modellen med två olika mätsätt beroende på djup.

**Budget:** `max_total_children=6` hanteras genom disjunkt förallokering nedåt i
trädet (samma princip som Fas 4 beslut 7, "post-hoc rollover only, no mid-flight
borrowing") — root delar sin pool bland sina direkta barn vid spawn; varje
delträd delar vidare sin egen tilldelning bland sina barn. Ingen realtidsaggregering
av kostnad/tokens över processgränser (§27 #11 förblir öppet — v1 verkställer
precis som v0.1, bara disjunkt förallokering, inte löpande aggregering). Om ett
delträds tilldelning tar slut måste noden agera som löv (ett modellanrop på sin
kontextskiva) istället för att dekomponera vidare — en kontrollerad
nedgradering, inte ett fel.

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

### 5. Två långkontextklasser i samma v1-leverans: Coding Agent och research/dokument

**Beslut:** exit-kriteriet kräver bara "minst en långkontextklass", men v1
levererar båda samtidigt, byggda och bevisade i sekvens inom samma fas (inte som
separat fast-follow).

- **Coding Agent-klassen:** återanvänder Fas 3:s vertikal och verktyg
  (read/search/patch/test) direkt. Fixture: en bugg/ändring som kräver att läsa/
  resonera över fler filer än ett enda modellanrops fönster rymmer. Baseline:
  `kernel/strategy.py`:s befintliga `direct`-strategi (encelligt anrop, trunkerad
  kontext), körd på samma fixture-instans.
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
  probabilistisk grading).

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
poäng. Marginal: **RLM lyckas i minst 2 av 3 oberoende rundor; baseline
förväntas lyckas i 0 av 3** (baseline är konstruerad för att strukturellt inte
kunna hitta den avgörande informationen — om baseline oväntat lyckas är fixturen
för lätt och görs om, räknas inte som en RLM-förlust). "Oberoende rundor" = tre
olika fixture-instanser per klass (annan gömd-fakta-placering, andra decoys),
seedad/deterministisk generering för reproducerbarhet — inte samma fixture kört
tre gånger.

**Kostnadstak:** RLM:s totalkostnad per run (summan över hela nodträdets
sessioner) får vara högst **5× baseline:s kostnad** för samma fixture-instans,
som v1:s startvärde. Multiplikatorn är policydata (samma klass som §12.4:s
sök-vikter — versionsstyrd, testad mot fixtures, inte inbränd i kod), inte en
hårdkodad konstant, så den kan differentieras per uppgiftstyp senare. Se
"Deferred decisions" för nedåttrenden Fas 6 förväntas bevisa.

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
| `run_tree.py` | `build_index` utökas till att rekursivt projicera ett träd av sessionsloggar, inte bara Fas 4:s platta två-barn-fall. |
| `budget.py` | Disjunkt förallokering utökas till att rekursivt splitta ett delträds tilldelning bland sina egna barn (samma princip som Fas 4 beslut 7, en nivå djupare). |

**`agent-platform/reasoning/recursive/`** (ombyggd, inte bara utökad):

| Modul | Ändring |
|---|---|
| `rlm_engine.py` | Ersätts av process-baserad orkestrering via `Coordinator.run_node`. Nuvarande in-process-version blir referens/prototyp för bounds-mekanik, arkiveras eller flyttas till en `_prototype`-markering. |
| `decomposer.py` | Byggs om från att dela nästlade Python-listor till att, givet en context-referens (från `context_store`), producera delreferenser per barn. |
| `bounds.py` | `RLMConfig`-defaults justeras till att matcha dispatch-kontraktets §19.1-värden (`max_depth=2`, `max_branches_per_node=3`, `max_total_children=6`, `max_model_invocations=20`, `max_context_reads=30`) som v1:s faktiska policy, inte kvarvarande toy-defaults (`max_depth=4`, `max_total_children=12`). |
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
  kör baseline (direct-strategi, ett anrop, trunkerad kontext) → success/fail, cost_baseline
  kör RLM (ovanstående flöde) → success/fail, cost_rlm
  assert cost_rlm <= 5 × cost_baseline (annars: BUDGET_EXHAUSTED, räknas som förlorad runda)
Aggregera: RLM måste lyckas i >= 2 av 3 rundor; baseline förväntas 0 av 3
```

## Error handling

| Fall | Hantering |
|---|---|
| Ett delträd har slut på sin tilldelade `total_children`-andel | Noden agerar som löv (ett modellanrop på sin egen kontextskiva) — kontrollerad nedgradering, inte fel. |
| `max_depth` skulle överskridas | Samma som idag (`MaxDepthError` → `BudgetExhausted`), verkställt per processgräns. |
| En Supervisor-spawnad RLM-barnprocess kraschar/tappas | Samma `lost`-status som Fas 4 beslut 6. Föräldranoden hanterar ett saknat barn som ofullständig evidens i `integrate`/`challenge` — inte en krasch av hela trädet. Root blir `blocked`, orsak pekar på den förlorade grenen (§27 punkt 4 i target-arkitekturen). |
| Kontradiktion (`ContradictionError`) i ett delträd | Stoppar grenen. Fas 6:s riktiga attractor-detektering finns inte än — v1 eskalerar inte automatiskt till mänsklig operatör om inte `explicit_stop_policy` kräver det. |
| Kostnadstaket (5× baseline) skulle överskridas mitt i en run | Fail-closed: run stoppas, `stop_reason=BUDGET_EXHAUSTED`, räknas som förlorad runda i N=3-utvärderingen — aldrig tyst nedgradering. |
| `context_store`-referens utanför dataklassens tillåtna scope | Tool Gateway avslår innan exekvering (Fas 3-mönster) — strukturerat fel, inte tyst trunkerad kontext. |
| Baseline lyckas oväntat på en fixture-variant | Fixturen är för lätt konstruerad — görs om, räknas inte som en RLM-förlust. |

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

## Deferred decisions (revisit triggers for later phases)

| Decision | Revisit when |
|---|---|
| Kostnadsmultiplikator (5×) som fast värde | Fas 6:s Geometric Reasoning (path-scoring, `escape_attractor`) ger mätbar evidens att kostnad per lyckad run kan trenda nedåt — då blir multiplikatorn en uppgiftsberoende, versionsstyrd policyparameter istället för en fast konstant. |
| Realtidsaggregering av kostnad/tokens över processgränser (§27 #11) | Konkurrerande/parallella barn i en framtida fas gör disjunkt förallokering för konservativt (analogt med Fas 4:s motsvarande deferred decision om mid-flight budget borrowing). |
| Embeddings-baserad context-slicing | Fas 6 löser §27 punkt 10 (embeddings-provider) — kan då utvärderas som ett tillägg ovanpå den strukturella slicingen, inte en ersättning. |
| Research/dokument-klassens fixture-djup (idag syntetisk, en domän) | Om Fas 5 v1:s exit är bevisat och en riktig operativ användning av research-klassen blir aktuell — fler dokumenttyper, riktiga (godkända) datakällor under rätt dataklasspolicy. |
| `rlm_engine.py`:s in-process-prototyp | Arkiveras eller omdefinieras explicit som teststöd för bounds-mekanik i isolation, inte lämnas som förvirrande dubbel implementation vid sidan av process-baserad `Coordinator.run_node`. |
