# Fas 6 — Geometric Reasoning v1 — design

Status: **GODKÄND (Kimi re-review #2, 2026-08-17).** Writer: Hermes (producer), 2026-08-17,
branch `ci/adr-doc-currency-gate-clean`. Första Kimi-granskningen (kimi-k2.6, provider
kimi-coding, 2026-08-17) gav **KRÄVER ÄNDRINGAR**: 1 × P1 (P1.1 embeddings-isoleringen var
feltolkad — `GraphMetrics.semantic_closeness` konsumerar redan `hash_embedding`) och 4 × P2
(P2.1 node_type-ägarskap, P2.2 AttractorDetector är v0.1, P2.3 10 mått + guidance, P2.4
308-provenans). Alla fynd åtgärdade (märkta i texten). **Re-review #2 → GODKÄND, inga
kvarstående fynd.** Specen är godkänd för plan (TDD) och exekvering.
Authority: architectural proposal for one bounded vertical slice; does not override
`docs/agents/current-operating-model.md`.
Related: `docs/architecture/cortxt-agent-platform-target-architecture.md` §9 (Problem
State och Reasoning Graph), §10.1–10.2 (strategier och operatorer), §12 (Geometric
Reasoning Engine: 12.1 arbetsdefinition, 12.2 mått, 12.3 attractor-detektering, 12.4
första sökfunktionen), §23 (Fas 6 — Geometric Reasoning v1, inkl. exit-kriterium),
§27 öppna beslut **#8** (vilka geometric-mått som är beslutande kontra diagnostiska) och
**#10** (embeddings-provider, blockerande), §28 (arkitektoniska invariants);
`docs/adr/017-agent-platform-reasoning-acceptance.md` (reasoning-kärnan tracked/Accepted);
`2026-08-17-fas6-entrance-readiness.md` (lägesbilden denna spec löser);
`2026-08-17-fas5-rlm-v1-design.md` (föregående fas spec, format- och processmall);
`2026-08-17-fas5-exit-criterion-checklist.md` (sanningskälla för det empiriskt verifierade
Fas 5-exit-kriteriet som ligger till grund för denna fas).

## Why this spec is scoped to the deterministic core

Fas 6-entrén (dokumenterad i `2026-08-17-fas6-entrance-readiness.md`) identifierade två
blockerare för en *ren* Fas 6-start:

1. **§27 #10 embeddings-provider** — den enda embedding som finns är den deterministiska
   `hash_embedding`-stubben i `agent-platform/reasoning/geometric/embeddings.py`. En riktig
   embeddings-provider kräver credentials + en embedding-/inference-endpoint som inte är
   konfigurerad i denna miljö, samt ett operatörsbeslut om vilken provider. Detta är **inte
   ett kodskrivningsproblem jag kan lösa spekulativt** — det är en miljö + öppen-beslut-beroende.
2. **Fas 6-exit-kriteriets empiriska bevisning mot riktig live-modell** — Fas 5 bevisade sitt
   exit-kriterium mot en riktig InferX-modell (`Qwen3-Coder-Next-FP8`, Python312) och krävde
   inference-budget. En analog Fas 6-exit-bevisning (mätbar kostnads-/attention-förbättring)
   kräver riktiga modellanrop → budget. Detta är ett **separat, budgetstyrt steg**, inte en
   del av den deterministiska kärnan.

**Slutsats som formar hela denna spec:** alla Fas 6-leverabler utom själva
embeddings-*provider-integrationen* har en **deterministisk, embeddings-oberoende kärna**
som kan implementeras nu (0 modellanrop) mot den befintliga `EmbeddingFn`-ytan
(`hash_embedding` som default). Provider-bytet (§27 #10) blir därmed en **drop-in**-ersättning
av en enda funktion vid en senare tidpunkt — inte ett omtänk av datamodellen, operatorerna,
scoringen eller rapporten. Att bygga denna kärna är inte att "pappra över" blockeraren; det är
att bygga det som per definition inte beror på den. De två blockerarna lyfts separat som
operatörsbefattningar (se "Blockerade delar och operatörsbeslut"), men blockerar inte spec → review
→ plan → TDD-exekvering av kärnan.

## Verified current state (sanningskälla: kod + ADR-017 + entré-not)

`agent-platform/reasoning/geometric/` är ett **DM3 vertikalt slice** (landade via ADR-017,
tracked/Accepted): deterministisk, 0 modellanrop, 13 gröna tester
(`tests/reasoning/geometric/test_{metrics,explorer,attractor}.py`). Karta:

| Modul | Nuläge | Gap mot §23 |
|---|---|---|
| `graph_space.py` — `ReasoningNode`, `ProblemSpace` | Riktad graf, `shortest_path`, `has_cycle`, `neighbors`. Nod = 6 fält (id, content, evidence, contradiction, confidence, visited_count). | **Problem State schema** (§9) och **reasoning graph** med **relationstyper** / **nodtyper** / **minsta metadata** saknas. Kanttyp finns inte (bara otypade riktade kanter). |
| `embeddings.py` — `EmbeddingFn`, `hash_embedding`, `cosine` | Deterministic stub. | Blockerad bit: riktig provider (§27 #10). Ytan är rätt utformad för drop-in. |
| `metrics.py` — `GraphMetrics` | **10 mått ur §12.2** (semantic_closeness, graph_distance_to_goal, evidence_coverage, contradiction_degree, centrality, novelty, stability, revisit_ratio, path_diversity, information_gain), normaliserade [0,1], + 1 aggregerad `guidance`-funktion (explorerns heuristik, inte ett §12.2-mått). OBS: `semantic_closeness` konsumerar redan `hash_embedding` (se P1.1-åtgärd i Beslut 5). | Måtten finns; **path scoring-funktionen** (§12.4) saknas som versionsstyrd policy. |
| `attractor_detector.py` — `AttractorDetector` | Finns (k_threshold, stability_threshold) — **v0.1**: baseras på `visited_count >= k` + `stability > t`; §12.3:s interventionskrav (perspektivbyte, motexempel, oberoende child run, ändrad branch order) är **INTE** implementerade. | **Contradiction-detektering** som förstklassig mekanism saknas (contradiction är bara ett node-fält). |
| `escape_attractor.py` — `escape_attractor()` | Finns. | — |
| `explorer.py` — `Explorer`, `bfs_path`, `exploration_cost` | Finns, guidad exploration. | **Första operatoruppsättning** utöver escape_attractor saknas (§10.2). **Trajectory viewer/report** saknas helt. |

Det existerande `kernel/problem_state.py`-`ProblemState` är det **andra**, träd-baserade
kontraktet (parent/children, transformation_log) som Fas 5 använder; det ersätts inte och
berörs inte — denna spec rör geometric-grafens nodmodell. (Skillnad dokumenterad för att
undvika att de två "ProblemState"-begreppen förväxlas.)

## Purpose

Leverera de **deterministiska, embeddings-oberoende delarna** av Fas 6:
färdigställ §9/§12.1-arbetet som DM3 påbörjade — ett **typat Problem State + reasoning graph**,
en **första geometric-operatoruppsättning**, **contradiction-detektering** (komplement till den
befintliga attractor-detekteringen), **path scoring** enligt §12.4 med **versionsstyrda
policydata-vikter**, och en **trajectory-rapport** — allt mot `EmbeddingFn`-ytan med
`hash_embedding` som default (0 modellanrop). Målet är att Fas 6:s struktur är *färdig för
levande* så att när §27 #10 löses är det enda återstående steget att byta default-embeddern och
(därefter, som separat budgetstyrt steg) bevisa exit-kriteriet mot en riktig modell.

Detta följer samma process som Fas 2–5: spec → oberoende (Kimi) review → plan (TDD) → exekvering.
Ingen implementationskod skrivs före specen är godkänd.

## Scope decisions

Åtta beslut, resolverade genom granskning av target-arkitekturen och det verifierade nuläget.
Producer-owning rework gäller: KRÄVER ÄNDRINGAR → hash-bind → re-review tills GODKÄND.

### 1. Problem State-schema: utöka `ReasoningNode` bakåt-kompatibelt, skapa ingen ny klass

**Beslut:** `ReasoningNode` (geometric) utökas med (a) ett `node_type`-fält från §9.1:s
nodtyppslista (`goal|constraint|concept|claim|hypothesis|evidence|assumption|contradiction|
question|candidate_conclusion`) och (b) ett strukturerat `metadata`-fält som bär §9.3:s
minsta metadata: `provenance`, `confidence_source`, `evidence_refs`, `data_class`,
`reasoning_step_id`, `created_at`/`updated_at`, `status`, `version`.

**Varför bakåt-kompatibel utökning, inte ny klass:** `ReasoningNode`+`ProblemSpace` är
tracked/Accepted per ADR-017 och konsumeras av `pipeline.py`, `Explorer`,
`AttractorDetector` och 13 tester. En ny klass skulle förgrena modellen i onödan och bryta
pipeline-integrationen. Defaultvärden (t.ex. `node_type=None`, `metadata=None`) gör att alla
befintliga konstruktioner och tester förblir oförändrade och gröna.

**Konsekvens:** `metadata` är en `dict[str, Any]` (per-fält-typning görs i operatorer/rapport,
inte i nodmodellen — YAGNI för v1).

### 2. Reasoning graph: typade relationer + nodtyper på `ProblemSpace`

**Beslut:** `ProblemSpace.add_edge(src, dst)` får en valfri `rel_type`-parameter från §9.2:s
relationstyplista (`supports|contradicts|depends_on|causes|derived_from|generalizes|
specializes|analogous_to|alternative_to|observed_from`). Default `rel_type=None` (otypad)
behåller exakt dagens beteende. Nya accessorer: `edge_types(src, dst)` och en iterator över
(type, src, dst)-triplar. `ProblemSpace` håller en **sekundär indexering** av `node_type` per
nod-id (queryhjälp), men **`ReasoningNode.node_type` (Beslut 1) är den auktoritativa källan**
(P2.1-fix efter Kimi-granskning): indexet härleds ur nodernas fält, aldrig tvärtom, så de kan
inte divergera.

**Varför relationstyper specifikt:** §12.1 kräver "noder och relationer ger explicit
grafstruktur". Contradiction-detektering (Beslut 4) och `change_perspective` (Beslut 3) är
omöjliga att uttrycka meningsfullt utan att veta att en kant är en `contradicts`- vs en
`supports`-relation. Otypade kanter räcker för avstånd/exploration, inte för semantic
struktur.

**Konsekvens:** `successors`/`neighbors`/`shortest_path`/`has_cycle` förblir orörda (de bryr
sig inte om rel_type) — bakåt-kompatibelt.

### 3. Första operatoruppsättningen: tre nya deterministiska geometric-operatorer

**Beslut:** utöver den befintliga `escape_attractor` (finns, §10.2) implementeras tre
deterministiska operatorer som verkar över `ProblemSpace`:

| Operator (§10.2) | Implementering | Determinismkälla |
|---|---|---|
| `find_contradiction(space, nid)` | Hittar noder som står i `contradicts`-relation till `nid` **eller** vars `contradiction_degree` ≥ tröskel. Returnerar en `Contradiction`-enhet. | Graf- + node-fält, ren funktion. |
| `change_perspective(space, nid, target)` | Bygger om vy från `target` via `alternative_to`/`analogous_to`-relationer — producerar en ny subgraf (relevanta noder + kanter) sett från en annan position; används av attractor-escape- och diversity-mått. | Graf-filter, ren funktion. |
| `compare_paths(space, path_a, path_b, goal, policy)` | Rankar två kandidatbanor med path scoring (Beslut 5). | Path scoring, ren funktion. |

**Varför dessa tre, och bara dessa:** de driver Fas 6:s exit-relevanta mekanismer — sökval
(`compare_paths`), motsägelse (contradiction) och persistensbrytande perspektivskifte
(`change_perspective`). Övriga §10.2-operatorer (`abstract`, `concretize`,
`generate_counterexample`, `integrate`, `decompose`, `inspect`, `verify`) tillhör andra
strategier (kernel/recursive) eller kräver modell/verktyg och är **utanför scope** för v1
(YAGNI — se Out of scope).

### 4. Contradiction-detektering som förstklassig mekanism

**Beslut:** ny enhet `Contradiction` (mellan nod A och B, med käll-typen: `edge`(explicit
`contradicts`-kant) eller `degree`(tröskelbaserad)) och en `ContradictionDetector`
(tilläggsmodul) som hittar contradictions. Detta **kompletterar** `AttractorDetector` (som
redan finns och är grön) — båda är oberoende detektorer över samma graf.

**Varför:** §12.1 — "motsägelser skapar mätbar spänning" — och §12.3:s interventionslista
(ny evidens, motexempel, perspektivbyte) kräver att contradiction är en *detekterbar enhet*,
inte bara ett node-fält. Attractor-detektering finns; contradiction-detektering saknas. De två
är distinkta fenomen (attractor = stabil återkomst; contradiction = inkompatibel evidens) och
ska inte sammanblandas i en detektor.

### 5. Path scoring enligt §12.4 — versionsstyrd policy, vikter som policydata

**Beslut:** ny modul `path_scoring.py` med:

- `CandidatePathScore` — en **versionsstyrd policydataclass** som bär vikterna för §12.4:s formel
  (standardvärden som v1-policy, `version`-fält för auditerbarhet) plus en `embedder`-referens
  (default `hash_embedding`).
- `score_path(space, path, goal, policy) -> float` som beräknar:

```
score = w1·expected_information_gain + w2·goal_relevance + w3·evidence_coverage
        + w4·path_novelty − w5·contradiction_risk − w6·expected_cost − w7·policy_risk
```

Termerna kombinerar befintliga `GraphMetrics` (goal_relevance ←
`graph_distance_to_goal`/`path_diversity`; evidence_coverage ← `evidence_coverage`;
path_novelty ← `novelty`; contradiction_risk ← `contradiction_degree`; expected_cost ←
`exploration_cost`-anda; policy_risk ← v1-standard, t.ex. 0 eller en tröskelflagga) och
`expected_information_gain` ← hash-embedding-baserad similarity-mot-goal (via `cosine`).
`policy_risk` är en **policyregel** (visa node-types v1 flaggar som hög risk), inte en
hårdkodad konstant.

**Varför versionsstyrd policydataclass, inte funktion med hårdkodade vikter:** §12.4 är
explicit — "Vikter och trösklar är policy-data och ska utvärderas mot fixtures, inte döljas i
prompttext" — och Fas 5-specen etablerade samma mönster för kostnadsmultiplikatorn
(versionsstyrd policy, inte inbränd konstant). `CandidatePathScore.version` gör att
scoring-förändringar är spårbara och jämförbara över fixtures.

**Nyckelrelation till §27 #10 (reviderat efter Kimi-granskning, P1.1):** `CandidatePathScore.embedder`
är den enda **nya** plats i denna specs leverabler som konsumerar embeddings. **Men den befintliga
`GraphMetrics.semantic_closeness` (metrics.py) konsumerar redan `hash_embedding` i dag.** `semantic_closeness`
är ett av de diagnostiska måtten (Beslut 8) som `TrajectoryReport` kan komma att rapportera, så även existerande
kod påverkas av §27 #10 när den aktiveras. Hanteringen (reviderad): (a) `semantic_closeness` migreras till samma
`embedder`-injektionsmönster som `CandidatePathScore` (en valfri `embedder: EmbeddingFn = hash_embedding`-parameter),
så att path scoring och det diagnostiska närheten-måttet delar **en** injicerbar källa; (b) default förblir
`hash_embedding` (deterministisk, 0 modellanrop); (c) när §27 #10 löses byts default-embeddern på **båda** ställen
via samma injiceringsyta — formeln, vikterna, rapporten och övriga mått rörs inte. Detta gör kärnan embeddings-oberoende
i den meningen att *ingen ny* icke-injicerad embeddings-konsumtion introduceras, och den observerade befintliga
konsumtionen redovisas ärligt snarare än att döljas.

### 6. Trajectory: datakontrakt + rapport nu, GUI-viewer deferrad (explicit operatörsbeslut)

**Beslut:** ny modul `trajectory.py` med en `TrajectoryReport`-builder som tar en
`ProblemSpace` + en exploration (path, node-scores, attractor-/contradiction-flaggor) och
producerar en **serialiserbar, granskningsbar rapport** (nodlista med node_type + metadata +
scoring, relationstyplista, path-score med `CandidatePathScore.version`, attractor- och
contradiction-flaggor). Serialiseras till JSON (och en text-renderare). `TrajectoryReport` är
därmed **både datakontraktet och rapporten**.

**GUI-viewer är DEFERRED, inte levererad i denna v1 (explicit operatörsbeslut 2026-08-17):**
operatören bekräftade att vi definierar `TrajectoryReport`-datakontraktet + rapporten nu (detta
uppfyller §23:s "trajectory viewer **eller** rapport" via rapport-varianten) men **deferar själva
GUI-viewern** tills det finns riktiga runs-data att visa (efter att kärnan är byggd + §27 #10
löst + exit-kriteriet kört mot riktig modell). Viewern byggs då på **ny bas — inte på `web/`**,
som operatören klassat som **legacy** och inte ska användas som grund för ny UI. Se
"Deferred decisions".

**Varför:** rapporten är den deterministiskt testbara varianten av leverabeln och räcker för
exit-kriteriet (§23 handlar om mätbar förbättring på beslutande mått, inte om UI). En GUI-viewer
utan äkta runs-data skulle bara visa stub/hash-data, och en live-viewer kräver en datakälla som
inte existerar förrän efter §27 #10 + riktiga runs. Att defera viewern tills äkta data finns —
och bygga den på en ny, icke-legacy-bas — undviker både legacy-stacken och att skapa en viewer
utan verklig funktion. Rapportens granskningsbarhet är invarianten (§10.3 — strukturerade,
granskningsbara tillståndsförändringar, ingen privat chain-of-thought). Samma linje som Fas 4/5:
CLI/query räcker, operatörsdashboard out-of-scope tills levande behov.

### 7. Backward-kompatibilitet är en hård krav — ingen regression, inga nya modellanrop

**Beslut:** alla utökningar av `ReasoningNode`/`ProblemSpace` sker med defaultvärden; inga
befintliga metoder byter signatur bortom att lägga till valfria parametrar; `hash_embedding`
förblir default-embedder; `pipeline.py` och de 13 befintliga geometric-testerna förblir
oförändrade och gröna. Hela kärnan är **0 modellanrop** och körs i default-sviten
(`-m "not real_inference and not docker_required"`).

**Varför:** Fas 6 implementeras ovanpå tracked/Accepted-kod (ADR-017). En regression här
skulle bryta etablerad, granskad arkitektur. Nya moduler/operatorer läggs till sida vid sida,
inte genom omskrivning av befintlig funktionalitet.

### 8. Första förslaget på beslutande vs diagnostiska mått (§27 #8) — för review, inte låst

**Beslut (förslag till befintlighetsbeslut, ska bekräftas före exit-utvärdering):** för v1
föreslås `goal_relevance`, `evidence_coverage` och `contradiction_risk` (via path scoring) som
**beslutande** mått för sökval; övriga §12.2-mått (centrality, novelty, stability,
path_diversity, information_gain, revisit_ratio, semantic_closeness) som **diagnostiska** —
de rapporteras i trajectory-rapporten men styr inte aktivt.

**Varför inte låsa det här:** §23 Fas 6-exit-kriteriet kräver att "vilket/vilka mått i §12.2
som är beslutande är avgjort innan detta exit-kriterium utvärderas (§27 #8)". Detta är ett
**öppet beslut** som formellt ska avgöras (operatör + review) — specen föreslår en startpunkt
så implementeringen kan bygga mot något konkret, men beslutationsslaget ska inte klistras in
som fastslaget. Detta är ett operatörsbefattningsbyte-punkt som lyfts separat.

## Components (nya/ändrade moduler)

Allt under `agent-platform/reasoning/geometric/` (tracked scope). Nya moduler:
- `contradiction.py` — `Contradiction`, `ContradictionDetector`, `find_contradiction`.
- `operators.py` — `change_perspective`, `compare_paths` (och eventuellt re-export av
  `escape_attractor` för enhetlig operator-yta).
- `path_scoring.py` — `CandidatePathScore`, `score_path`.
- `trajectory.py` — `TrajectoryReport`-builder + JSON/text-renderare.
- `problem_state.py` (ny, geometric-specifik) — **eller** utökning direkt i `graph_space.py`.
  Beslut i plan: om `ReasoningNode`-utökningen + relationstypning blir för stor i
  `graph_space.py`, flyttas/återexporteras med `node_type`+`metadata`-fälten tydligt på
  `ReasoningNode`. (Plan-nivå-detalj; spec-safe i bägge fallen.)

Ändrade:
- `graph_space.py` — `ReasoningNode` (+`node_type`, +`metadata`), `ProblemSpace.add_edge`
  (+`rel_type`), nya accessorer, `ProblemSpace` nod-/kanttypträckare.
- `embeddings.py` — oförändrad (ytan finns); default `hash_embedding` kvar.
- `__init__.py` — re-export av nya symboler.
- `metrics.py` — **liten ändring (P1.1-fix):** `semantic_closeness` migreras till
  `embedder: EmbeddingFn = hash_embedding`-injektion (delar källan med `CandidatePathScore`);
  övriga mått och `guidance`/Explorer förblir oförändrade.

## Data flow

```
ProblemSpace (typade noder + relationer, §9)
  → operatorer (Beslut 3): find_contradiction / change_perspective / compare_paths / escape_attractor
  → detektorer (Beslut 4): ContradictionDetector, AttractorDetector
  → path scoring (Beslut 5): score_path(space, path, goal, CandidatePathScore(hash_embedding))
  → trajectory (Beslut 6): TrajectoryReport ← path + scoring + flaggor
```

När §27 #10 löses: `CandidatePathScore(embedder=<riktig provider>)` ersätter
`hash_embedding` — inget annat i kedjan ändras. När exit-kriteriet ska bevisas mot riktig
modell (separat, budgetstyrt): driven av en live-exploration som producerar riktiga banor;
själva scoring-/rapportkedjan är identisk.

## Error handling

| Fall | Hantering |
|---|---|
| `score_path` anropas med path som innehåller nod-id som inte finns i space | Strukturerat fel (`NodeMissingError`), fail-closed — inte tyst 0-poäng. |
| `CandidatePathScore` med okänd `version`-sträng | Avvisas (okänt policyschema) — samma fail-closed-disciplin som Fas 5:s versionsstyrda policy. |
| `find_contradiction` på nod med varken `contradicts`-kant eller tröskelöverskridande | Returnerar tom uppsättning (inget fel) — "ingen motsägelse detekterad" är en giltig utgång. |
| `change_perspective` på nod utan `alternative_to`/`analogous_to`-relationer | Returnerar tom/identisk subgraf med `no_perspective_change`-flagga — degradering, inte fel. |
| Trajectory-report med ofullständig metadata | Rapporten fyller `metadata` med `null`-värden, `status="incomplete"` — aldrig fabricerad data. |
| Nya modell-invocationer oavsiktligt introducerade | Fail via test-gate: `test_no_external_deps` + ett nytt assert att geometric-kärnan gör 0 modellanrop. CI:default-sviten inkluderas. |

## Testing strategy

- **TDD, vertikala skivor** (skilj från horisontell slicing — en test → en implementation →
  repeat), enligt `test-driven-development`-skillen. Varje ny funktion: RED → verifiera fail →
  GREEN → verifiera pass.
- **Backward-kompatibilitet:** efter alla ändringar körs hela default-sviten
  (`pytest agent-platform/ -m "not real_inference and not docker_required"`) = **308 passed +
  de nya**. Inga regressioner. (P2.4-provenans: 308 är den senast verifierade gröna körningen på
  branch `ci/adr-doc-currency-gate-clean`, fas 5-slut, som producenten bekräftade om innan denna
  spec skrevs.)
- **Inga modellanrop:** nytt test som assertar att geometric-operatorerna/path-scoring/
  trajectory gör 0 modellanrop (kör default, inget `real_inference`-beroende).
- **Path scoring mot fixtures:** `score_path`-test med kända värden (inte tautologi — förväntade
  värden från handräknade exempel/policydata, inte omberäknade av koden); posterior-policy
  ändrar score deterministiskt.
- **Contradiction:** explicit `contradicts`-kant → detekteras; tröskelbaserad → detekteras;
  ingen → tom.
- **Relationstyper:** `add_edge` med `rel_type` lagrar och returnerar rätt; default otypad
  behåller gamla beteenden.
- **Trajectory-rapport:** samma space+path → identisk serialisering (renhet); metadata och
  version inkluderas.
- **Fixtures:** seedade, deterministiska geometric-fixtures (små grafer med kända
  contradiction/attractor/path-egenskaper) — reproducerbara vid review.

## Out of scope for this slice

- **Riktig embeddings-provider** (§27 #10): providerbeslut + credentials + integration. Kärnan
  byggs mot `EmbeddingFn`-ytan; providern byts in senare som drop-in.
- **Exit-kriteriets empiriska bevisning mot riktig live-modell** (kostnad/attention-data):
  kräver inference-budget; lyfts som separat operatörsfråga.
- **GUI trajectory-viewer / live-dashboard** — *deferred* (inte out-of-scope för alltid): se
  Beslut 6 och "Deferred decisions". Blickar bort från `web/` (legacy per operatör) mot ny bas
  när riktiga runs-data finns.
- Övriga §10.2-operatorer (`abstract`, `concretize`, `generate_counterexample`, `integrate`,
  `decompose`, `inspect`, `verify`) — tillhör andra strategier eller kräver modell/verktyg.
- Förändring av `kernel/problem_state.py` (det träd-baserade RLM-kontraktet) eller
  `recursive/` — geometrisk kärna rör dem inte.
- Embeddings-baserad context-slicing (Fas 5 deferred — kräver §27 #10).
- Realtidsaggregering av kostnad/tokens över processgränser (§27 #11) — fortsatt disjunkt,
  ur scope.
- Dynamisk, uppgiftsberoende policydata — `CandidatePathScore`-vikterna är fasta v1-standarder
  (versionsstyrda), precis som Fas 5:s 5×-multiplikator.

## Blockerade delar och operatörsbeslut (att lyfta)

Följande **kräver operatörsbefattning** och blockerar *inte* denna spec/plan/implementering av
kärnan, men måste lyftas explicit:

1. **§27 #10 — embeddings-provider.** Vilken embedding/endpoint ska ersätta `hash_embedding`,
   och hur `InferencePort` ska normalisera embeddings. Kärnan är drop-in-redo; själva
   provider-bytet är ett beslut + credentials-gated arbete.
2. **§27 #8 — beslutande vs diagnostiska mått.** Specen föreslår en startpunkt (Beslut 8),
   men det formaliserade beslutet ska fattas innan exit-kriteriet utvärderas.
3. **Inference-budget för Fas 6-exit-bevis** (analogt Fas 5): om det empiriska exit-kriteriet
   ska bevisas mot en riktig modell krävs budget. Detta är systemhanterat (inget tal från
   operatören) men kräver att budgeten faktiskt sätts vid exits-tidpunkten.

## Deferred decisions

| Decision | Revisit when |
|---|---|
| Riktig embeddings-provider (§27 #10) | Providerbeslut + credentials tillgängliga; drop-in via `CandidatePathScore.embedder`. |
| Beslutande vs diagnostiska mått (§27 #8) | Före Fas 6-exit-utvärdering; specen föreslår startpunkt. |
| Fler §10.2-operatorer (abstract/concretize/counterexample) | När en operator behövs av en beslutande metric eller en annan strategi. |
| Embereddings-baserad context-slicing | §27 #10 löst — då som tillägg ovanpå Fas 5:s strukturella slicing. |
| GUI trajectory-viewer (på ny bas) | När riktiga runs-data finns att visa: kärnan byggd + §27 #10 löst + exit-kriteriet kört mot riktig modell. Byggs på ny bas, **inte legacy `web/`** (explicit operatörsbeslut 2026-08-17). `TrajectoryReport`-datakontraktet (rapporten) levereras i denna v1. |
| Uppgiftsberoende `CandidatePathScore`-vikter | När kostnad/attention-data från riktiga runs (budgetstyrt) motiverar differentiering. |
