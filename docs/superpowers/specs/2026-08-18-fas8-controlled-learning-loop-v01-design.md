# Fas 8 — Kontrollerad learning loop — design

Status: **v3 — KIMI-REVIEW GENOMFÖRD (KRÄVER ÄNDRINGAR), ALLA FYND ÅTGÄRDADE — REDO FÖR KIMI RE-REVIEW.
Writer: Hermes (producer), 2026-08-18, branch
`spec/fas8-controlled-learning-loop` (grenad från `spec/fas7-self-hosted-inference`@`60b61a6`, dvs. efter
Fas 7 v1 avslutad; den lokala `main`-grenen är föråldrad / Fas 4-era och saknar `agent-platform/portability/`
från PR #135, så `-self-hosted-inference`-tip är den enda bas som innehåller allt beskrivet nuläge).

**Kimi-granskning (2026-08-18, kimi-k2.6 via `hermes -p coordinator --provider kimi-coding`):**
**VERDIKT = KRÄVER ÄNDRINGAR.** Fullt utlåtande i `agent-platform/runs/fas8-spec-kimi-review.out`
(gitignored, committas ej). Producer äger rework: samtliga fynd hash-bindas nedan och åtgärdas i v3.
- **P0.1** `CandidatePathScore` är mutable → bryter hash-garantin → **åtgärdat (Beslut 7/9):** registry hash-låser
  det **serialiserade payload-objektet** (dict/json), inte runtime-instansen; `CandidatePathScore` noteras som
  ett payload-format som kan göras frozen i plan-fasen.
- **P0.2** `PromotionGate.evaluate(matrix, rules)` tog `rules` från adaptern → self-approval-bypass → **åtgärdat
  (Beslut 3):** `evaluate` tar INTE emot regler från adaptern; den resolverar kandidatens typ-registrerade
  regler internt ur `CandidateRegistry` och union:ar alltid med `MANDATORY_OPERATOR_GATES`.
- **P0.3** `PromotionRule`-datamodellen för ofullständig → **åtgärdat (Beslut 3):** utökad med `candidate_type`,
  `metric`, `threshold`, `comparator`.
- **P1.1** Geometric-safety på policy-vikter = kategori-fel → **åtgärdat (Beslut 10a):** ersatt med konkreta
  policy-constraint-säkerhetsregler; geometric-genomsyrandet ligger nu ärligt på selektionssidan (`score_path`).
- **P1.2** Voyage-injektion utan kostnadsgräns → **åtgärdat (Beslut 10b):** Evaluator pre-computar/förcachar alla
  embeddings före `score_path`.
- **P1.3** EvidenceClassifier underdefinierad → **åtgärdat (Beslut 10c):** konkret exempel för policy-evidence.
- **P1.4** "Tränad policy" ut-scope med falsk trygghet → **åtgärdat (Beslut 6):** kontraktet specificerat som
  parametriskt-bärande; icke-parametriska kräver utvidgning av `payload_ref`/`Evaluator`.
- **P1.5** `rollback(type)` → **åtgärdat (Beslut 7/Components):** `rollback(type, name)`.
- **P1.6** Skill/tool som "beskriven modell" → **åtgärdat (Beslut 5):** ärligt omdefinierat som
  "mekanism-kopplade, ej djup-verifierade" med §23-djupet för dessa två i v1.x.
- **P1.7** Intern motsägelse om neutrala kandidater → **åtgärdat (Beslut 2):** endast strikt-bättre auto-promotas;
  neutrala gör det inte.
- **P2.1–P2.3** polish → åtgärdade/noterade (active_policy-detalj, `Engine.solve`-verifiering, test-baslinje-caveat).
- **V01-rekommendationer** → inkorporerade i "Vägen till det större målet" + "V01-close-out" (byte:
  samlad `V01-exit-report.md`, Supervisor läser aktiv policy, N=3-gröna exit-körningar).

**Operatörens direktiv 2026-08-18 (inkorporerat i v2):** (a) specen ska lägga grunden för det större målet,
inte bara en liten mekanism-demo — därför v2:s Beslut 9 (stabila typ-agnostiska kontrakt) + "Vägen till det
större målet"-avsnittet; (b) recursive-geometric reasoning ska **genomsyra** det som byggs och **Voyage**
utnyttjas — Beslut 10a/10b; (c) Cloudflare **Agent Memory**-arkitekturen (multi-typ-klassificering +
verifier-checks + multi-channel-retrieval) lånas som **designinspiration** utan beroende på betatjänsten —
Beslut 10c; (d) BÅDE denna spec och den efterföljande TDD-planen skickas till **Kimi för oberoende review**
innan TDD-plan skrivs respektive innan operatörsinspektion; (e) operatören vill inspektera innan exekvering;
(f) i Kimi-reviewen begärs dessutom **rekommendationer för V01-helhet** — Fas 8 är den *sista* fasen i v0.1,
så Kimi ska också ge 3–5 prioriterade rekommendationer för att knyta ihop säcken till en bra, sammanhållen
V01 och förbereda v.02-starten (se review-promten, runs/).
Detta är en **explicit begärd Kimi-gate** (undantag från den autonoma sparsamhetsregeln), en granskning per
artefakt.

Authority: architectural proposal for one bounded vertical slice; does not override
`docs/agents/current-operating-model.md`.
Related: `docs/architecture/cortxt-agent-platform-target-architecture.md` §23 (Fas 8 — Kontrollerad learning
loop: leverabler + exit), §28 (arkitektoniska invariants — **dessa är kravspec, inte bakgrund**), §31 (Skill
Platform + §31.1 Skill Evolution + promotion-tabellen), §32.3 (Tool Evolution), §12.4 (versionerad
path-scoring-policy), §29 (beslut); `docs/adr/018`-arbetsflödesetiketter (workflow:* för GitHub-carry);
`docs/agents/dispatch-contract.md` (result envelope — promotion-evidence återanvänder sitt mönster);
`agent-platform/portability/skills/` (SkillManifest/HermesSkillAdapter/SkillRegistry, PR #135 — det närmaste
befintliga mönstret för "versionerad, portabel kandidat"); `agent-platform/harness/eval/` (Fas 5/6/7:s
N=3-eval-harness-mönster — `runner.py`, `baseline_direct.py`, `selfhosted_task_class.py`);
`docs/superpowers/specs/2026-08-17-fas7-self-hosted-inference-v01-design.md` (föregående fas, format- och
processmall); GitHub issue **#138** (Strategy Portability — idén denna spec avgränsar in i sitt scope);
PR #135 (`refactor(portability): move skill layer under agent-platform/`).

## Why this spec is scoped the way it is

§23 kräver för Fas 8: (1) versionerade förbättringskandidater, (2) offline eval och promotion flow, (3)
rollback, (4) eventuellt tränad operator- eller routingpolicy, samt Skill Platform-promotion (§31) och Tool
Platform-evolution (§32.3) som **fungerande byggd pipeline, inte bara en beskriven modell**. Exit: **ingen
automatisk ändring kan nå produktion utan verifierad promotion**.

Den centrala observationen som formar hela denna spec: **Fas 8:s värde ligger inte i någon enskild
kandidattyp utan i själva livscykelmekanismen** — kandidat → offline eval → verifierad promotion → rollback.
Det är den mekanismen som gör §28-invarianten "*Learning sker genom versionsstyrda kandidater och verifierad
promotion*" sann och exit-kriteriet "*ingen automatisk ändring når produktion utan verifierad promotion*"
upprätthållbart. Därför bygger v1 **en generisk, kandidattyp-agnostisk livscykelprimitive** (registry + eval
gate + promotion state machine + rollback store) och bevisar den **end-to-end på en deterministisk
kandidattyp först** (versionerad reasoning-policy — `CandidatePathScore`-vikter), som sedan appliceras på de
två §23-utpekade pipeline-kraven (Skill-promotion, Tool-evolution) som *samma* primitives andra och tredje
applikation — inte som nya mekanismer.

**Detta är medvetet grunden för ett större mål, inte en envändnings-demo.** Målbilden (ADR-014/015,
`docs/agents/goal-operating-model.md`, F0/Milestone-2) säger att användaren/operatören äger sin arbetsförmågas
state, reasoning, minne, **tools, evidens och evolution** — och att profiler ska återanvända en gemensam kärna.
Fas 8 är den fas som institutionaliserar **evolutionen**: plattformens egen arbetsförmåga (skills, tools,
reasoning-strategier, routing-/operator-policies) ska kunna förbättras *styrt* under ett explicitt mandat,
utan att en agent tyst ger sig själv nya rättigheter (§31.1:s varning). För att denna mekanism ska kunna
växa till att bära hela spektrat av kandidattyper — inklusive tränade policies och automatisk
kandidatgenerering från trajectorier (§31.1) — definierar v1 **stabila, typ-agnostiska kontrakt** (Beslut 9),
inte bara en fungerande demo på en kandidattyp. Varje framtida kandidattyp är då en *adapterregistrering* på
samma kontrakt, inte en omdesign. Denna grundsyn löper genom hela specen och sammanfattas i avsnittet
"Vägen till det större målet" nedan.

Att bygga livscykelprimitiven först och applicera den på policy-parametrar först är medvetet:

1. **Deterministisk kärna, 0 externa resurser** (samma split som Fas 6/7 gjorde för embeddings/inference):
   en reasoning-policy-kandidat (`CandidatePathScore`-vikter) kan utvärderas helt deterministiskt mot de
   befintliga geometriska fixture-raderna i `tests/reasoning/geometric/` — **ingen live-modell, ingen GPU,
   inga kontokrediter krävs** för att bevisa att hela loopen (skapa kandidat → offline eval → promotion →
   rollback) faktiskt fungerar. Detta är hur Fas 8 uppfyller exit-kriteriet *inom den disciplin som Fas 2–7
   etablerat*: deterministisk kärna bevisar mekanismen, budgetstyrt live-steg (om det behövs) är ett separat
   operatörsgodkänt steg.
2. **Testar loopen, inte en specifik domän.** En skill-instruktionsändring kräver live-inference för att
   vara *meningsfull* att utvärdera (Samma-fixture-svar ändras bara om en modell körs). En policy-viktändring
   kräver inte det. Att bevisa mekanismen på policy-parametrar isolerar variabeln till "fungerar
   promotion/rollback-mekanismen", vilket är exakt vad Fas 8 behöver bevisa innan det appliceras på dyrare
   kandidattyper.
3. **Minskar v1-scopet medvetet, inte "allt".** "Kandidat" kan betyda ny skill-version, ny strategivariant,
   ny policyparameter eller alla tre. v1 väljer **en** deterministisk kandidattyp (policy) som bevis och
   implementerar **två** ytterligare kandidattypers *lifecycle-integrering* (skill- och tool-kandidat) mot
   samma primitive — men djupet på deras domänspecifika eval/granskning begränsas (se Beslut 2 och 5).

**Strategiportabilitet (#138) hör hemma i detta uppdrag och viks in, inte som eget spår:** issue #138
(Strategy Portability) beskriver ett `StrategyManifest`-koncept (versionerade strategivarianter kopplade till
vertikala profiler) som en parallel till skill-portabiliteten, och säger uttryckligen "återuppta när Fas 8
grillas". Fas 8:s versionerade-policy-kandidatmekanism (§12.4 `CandidatePathScore` + den generiska loopen) är
**exakt det substrat #138 efterfrågar**. Därför förs #138 in i detta uppdrags scope som en *mekanism-first*-
referens (Beslut 4): den generiska kandidatmekanismen ÄR strategiversioneringen i botten. Full tillämpning
per-vertikalprofil (en vertikalprofil ackumulerar sin egen beprövade strategivariant över tid) är en
dokumenterad **v1.x-utvidgning av samma primitive**, inte ett nytt spår — eftersom AI Act-vertikalen idag inte
är ett utforskningsproblem (#138:s eget "varför inte nu") och Fas 8:s exit-kriterium inte kräver det.

**"Tränad operator- eller routingpolicy" (leverabel 4) är ut-scope för v1 — explicit beslut:** ren
ML/RL-träning av en policy är en stor, separat leverans med egen databehovs- och iterationcykel. Det skulle
förvandla en disciplinerad, verifierbar livscykelmechanism till ett otestbart och resursslukande projekt.
v1:s "learning" tolkas operationellt som **kandidatgenerering + verifierad promotion** (en modell/agent
*föreslår* en variant; auktoritativ kod *evaluerar och verkställer* promotion) — exakt i linje med §28:s
"*Modellen föreslår; auktoritativ kod validerar och verkställer*". Ingen gradient-/RL-träning byggs. Se
Beslut 6.

## Verified current state (sanningskälla: kod + PR-logg + #138 + Fas 6/7-exit-checklistor)

| Komponent | Nuläge | Relevans för Fas 8 |
|---|---|---|
| `agent-platform/portability/skills/` (`SkillManifest`/`HermesSkillAdapter`/`SkillRegistry`) | Formatneutralt, versionerat, hash-deterministiskt skill-manifest; `name@version`-nycklat register; sha256-idempotens (`manifest_hashes()`); Hermes-adapter läser SKILL.md → neutralt manifest. Landad via PR #135 (merge `7c1a1424`), närvarande i denna bas. | **Det närmaste befintliga mönstret** för "versionerad, portabel kandidat" som Fas 8 generaliserar: manifest + registry + hash + version. Fas 8 lägger på **livscykeln** (eval-pending → promoted → rollback), som idag inte finns här. |
| `agent-platform/reasoning/geometric/path_scoring.py` — `CandidatePathScore` | **Redan kallad "versioned policy dataclass"** (§12.4): `version="v1"`, vikterna w1..w7 (additiva summa 1.0, subtraktiva summa 1.0), `embedder`-parameter; `score_path(space, path, goal, policy=...)` tar en policy. | Den **konkreta, deterministiska kandidattypen** Fas 8 bevisar loopen på: en ny viktuppsättning = en ny versionerad policykandidat. Redan konstruerad för drop-in (`policy=`-param). |
| `agent-platform/reasoning/kernel/strategy.py` — `Strategy` + `select_strategy()` | Deterministisk strukturbaserad strategi-val (direct/recursive/geometric/model/coding/human). 0 modellanrop. | Strategi-val är idag **hårdkodad strukturlogik, inte en ruttad/valbar policy**. #138 vill göra strategival evolutionärt. Fas 8 v1 rör **inte** att göra `select_strategy` till en promotbar policy (det är v1.x); strategiportabilitet landar här som versionerad **policy** (`CandidatePathScore`), se Beslut 4. |
| `agent-platform/harness/eval/` — `run_eval_class`, `run_task_class_eval`, `run_baseline`, `EvalRoundResult` | Fas 5/6/7:s N=3-mönster: binär success-per-runda, kostnad, `rlm_pass = passes >= 2`, jämförelse mot **en** baseline. | Återanvänds som **fixture- och success-definitionskälla**, men **generaliseras**: Fas 8:s offline eval jämför **flera kandidater samtidigt** mot samma active-baseline (EvidenceMatrix), inte bara en. Se Beslut 3. |
| `agent-platform/runtime/tools/gate.py` | Befintlig tool-file-gate (path/symlink-scope-validering). | Fristående verktyg för Tool-evolution (Beslut 5) — del av tool-kandidatens "regression mot aktiv toolversion"-check. |
| Produktionsexekveringsvägar | Inga agent/operator/routing-polcies är idag *promotade* som versionerade kandidater; inget promotion/rollback-lager existerar. | Första steget mot §28-invarianten; bygger det saknade livscykellagret. |
| `fas2a_inference_spend`, `BudgetGate` (SQLite) | Befintlig SQLite-spend-tabell + fail-closed budget-gate över `route_id`. | Etablerar **SQLite-persistensmönstret** Fas 8's rollback/livscykel-återanvänder (samma `_ensure_table` + transaktionsmönster), för dump-bar/git-oberoende, auditerbar beständig state. |
| Tests-baslinje | `328 passed, 3 skipped, 21 deselected` på `-m "not real_inference and not docker_required"`. | **OBS — 3 fail i `tests/runtime/test_text_inference_port.py` (route_id-tester) i DENNA bas:** `TypeError: 'NoneType' object is not callable` vid `_HttpAdapter(...)` (rad 120), orsakad av att `cortxt_resilient_inference`-paketet är **inte installerat i denna venv**, inte av en kodregression (statisk import-fallback sätter `_HttpAdapter = None`). Detta är ett **miljö-/beroendecaveat** som föregår Fas 8 — Fas 7:s own exit-checklista dokumenterar Fas 7 som empiriskt stängt; de 3 testerna är Fas 7-spår som väntar på att `cortxt_resilient_inference` installeras i en korrekt venv. Fas 8:s "ingen regression"-baslinje definieras mot de **328 green** testerna och kräver att dessa 3 route_id-tester förstår samma env-caveat (inte nytt Fas 8-introducerat). Se Testing strategy, "Ingen regression". |

## Purpose

Leverera Fas 8:s fyra §23-leverabler som en **liten, avgränsad vertikal slice** som bygger den saknade
livscykelmekanismen och bevisar den deterministiskt:

1. **Versionerade förbättringskandidater** — ett `CandidateRegistry` (SQLite-persisterat) som lagrar
   kandidater av typ skill | policy | tool, var och en med manifest-hash, version, status och
   rollback-pekare, utöver närvarande `SkillRegistry`-mönstret (in-memory, export-oriented) med en typ-agnostisk,
   beständig, livscykelmedveten variant.
2. **Offline eval och promotion flow** — en `PromotionGate` (regelstyrd) som kör en EvidenceMatrix (flera
   kandidater vs active-baseline), applicerar regler (främst §31:s promotion-tabell) och producerar en
   promotion/await/avvisa-beslut. Promotion = atomär pekarflytt i DB. **self-approval omöjliggörs strukturellt**
   (Beslut 5): kandidaten kan aldrig promota sig själv; auktoritativ kod-gate + operator-grind för
   external-effektklasser.
3. **Rollback** — versionerad state + aktiv-pekare gör rollback till en atomär
   "återställ pekaren till föregående version"-transaktion, med audit-spår.
4. **Skill Platform-promotion (§31) och Tool Platform-evolution (§32.3) som byggd pipeline** — samma
   livscykelprimitive appliceras på skill-kandidater (reglerna ur §31:s promotion-tabell) och tool-kandidater
   (§32.3:s candidate-checklista) som andra/tredje kandidattyp; djupet begränsas medvetet (Beslut 5).

Exit-kriteriet verifieras i ett **separat, deterministiskt steg**: en TDD-körning bevisar att en
policy-kandidat kan promotas (mekanismen fungerar) och att **en deliberately försämrad kandidat avvisas och
att produktionen aldrig berörs** — den mekaniska opposition mot exit-testerna byggs som en "fail via
test-gate"-assertion (samma mönster som Fas 6:s no-external-deps-assert och Fas 7:s kostnadsassert).

Detta följer samma process som Fas 2–7: spec → (valfri) oberoende review → plan (TDD) → exekvering. Ingen
implementationskod, ingen live-modell, inga riktiga kandidater promotas i en riktig produktionsväg innan
**operatören godkänt den specifika planen och (om live-eval begärs) kostnaden** (hård grind, se "Hårda
gränser").

## Scope decisions

### 1. Kandidattyp för v1-beviset: versionerad reasoning-policy (`CandidatePathScore`-vikter), inte skill-version eller ny strategivariant

**Beslut:** v1 bevisar hela livscykelloopen end-to-end på en **policy-parameter-kandidat** — en ny
viktuppsättning för `CandidatePathScore` mot geometriska fixtures. Detta är den **enda kandidattypen vars
offline eval är helt deterministisk** (0 modellanrop): `score_path` är en ren funktion över en `ProblemSpace`
+ en policy, och `tests/reasoning/geometric/` har redan beprövade fixture-rader och mått.

**Varför inte skill-version som bevis:** en skill-instruktionsändring påverkar bara faktiskt svar om en
modell körs mot fixtures. Att bevisa *loopen* (framför allt promotion + rollback) på skills skulle kräva
antingen en live-inference (budgetsteg) eller en artificiell deterministisk surrogat-eval som inte testar
skill-instruktionens verkliga effekt. Policy-vikter har ingen sådan artificiellhet — deras effekt är ren och
verifierbar direkt.

**Varför inte ny strategivariant som bevis:** en *ny* strategi (`Strategy`) kräver en ny solver i
`_SOLVERS`-diktet i `engine.py` — det är en ny exekveringsväg, en större och riskablare ändring, och `#138`
själv säger att fas 8-exit inte kräver det och att per-vertikal strategi-ackumulering inte behövs nu.
Strategivariant som *kandidattyp* registreras i v1.x (Beslut 4) men byggs inte i v1.

**Konsekvens:** Fas 8:s "improvement candidate" för v1 = **en versionerad policy-parameter** (+ registry /
gate / rollback runt den). Skill- och tool-kandidaternas *lifecycle-integrering* byggs (Beslut 5) men
deras fulla domänspecifika djup (live-eval för skills, komplett §32.3-säkerhetschecklista) delas till v1.x.

### 2. Offline eval: generalisera Fas 5/6/7:s N=3-fixture-mönster till en multi-kandidat EvidenceMatrix — inte en ny eval-metodik

**Beslut:** återanvänd Fas 5/6/7:s **fixture- och success-definitionsmönster** (binär success-per-runda per
fixture, samma fixture-set, N rundor) men **generalisera körern**: Fas 8:s offline eval kör **flera
kandidater samtidigt** mot samma aktiva baseline och producerar en `EvidenceMatrix` — per kandidat: success-
rate, kostnad (om relevant), latency, och **"no-regression mot active baseline"**-flagga.

**Varför detta, inte bara ett N=3-återbruk:** Fas 5/6/7 jämförde **en** kandidat (RLM, selfhosted-route) mot
**en** baseline — `run_eval_class` / `run_task_class_eval` tar en run-funktion och en baseline-funktion.
Fas 8 måste jämföra **flera kandidater parallellt** för att promotion-beslutet ska kunna välja *den bästa
som slår baseline utan regression* — det är vad "verifierad promotion" (exit) och §31.1:s
"regression och safety comparison → promotion decision" kräver. Den logiska formen ändras från
`(candidate, baseline) -> verdict` till `(candidates[], baseline) -> EvidenceMatrix -> decision`.

**Promotion-tolerans (medvetet konservativ, P1.7-korrigering):** en kandidat promotas automatiskt ENDAST om
den (a) är **strikt bättre** än den aktiva baslinjen på det beslutande måttet (success-rate > baseline, eller
kostnad < baseline vid given success — exakt metric per kandidattyp, Beslut 5/10), **och** (b) uppfyller
kandidattypens övriga regler, **och** (c) inte regresserar någon befintlig säkerhetsfixture. Likhet = inte
regression. **Neutrala/tie-kandidater auto-promotas INTE** (utbytesrisken motiveras inte av nytta) — de blir
`AWAIT_OPERATOR` om en operatör ändå vill ta in dem, annars lämnas de i `eval_pending`. Detta eliminerar den
tidigare internmotsägelsen (v2): konsekvent "strikt-bättre → auto; neutral → ej auto".

### 3. Promotion gate: en regelstyrd regel-*exekutor* (rules-as-data), operatörsgrind representerad som ett regelobjekt (self-approval strukturellt omöjligt)

**Beslut:** promotion godkänns av **två oberoende lager**, och — avgörande för det större målet (Beslut 9)
— implementeras grinden som en **ren regel-*exekutor* över ett `promotion_rules`-register**, inte som en rad
hardcodade if-satser per kandidattyp. Varje kandidattyp registrerar sin egen uppsättning regelobjekt (härledda
ur §31-tabellen och §32.2-effektklasserna); grinden evaluerar dem mot `EvidenceMatrix` + fixtures och
producerar ett Verdict. En framtida kandidattyp (strategi, tränad policy) är då bara *en ny
regelregistrering och en ny evaluerare*, utan att röra gate-koden. Detta är den mekaniska anledningen till
att Fas 8 kan vara grunden för hela spektrat av kandidattyper.

De två lagren:

1. **Teknisk, regelstyrd grind (automatisk, auktoritativ kod):** offline eval-verdict (Beslut 2) + kandidattypens
   §31-promotion-regel(er), utvärderade som data av gate-exekutorn. **Ingen modell/agent är inblandad i
   beslutet** — det är ren datalogik mot `EvidenceMatrix` + fixture-result. Detta uppfyller §28:s
   "*Modellen föreslår; auktoritativ kod validerar och verkställer*".
2. **Operatörsgrind (hård, icke-delegerbar):** representerad som ett **`OperatorGateRule`-regelobjekt** som — när
   tillämpad — returnerar `AWAIT_OPERATOR` tills en namngiven operatörmottagare ger godkännande. Inga
   modell-anrop kan producera ett `PROMOTE` när en `OperatorGateRule` är aktiv. Reglerna för vilka klasser som
   kräver operatörsgrind är **inte deletable av någon kandidat** — de härleds ur den oföränderliga
   §31-tabellen (se "icke-delegerbara regler" nedan).

**`PromotionRule`-kontraktet (data, Beslut 9; P0.3-korrigering):** en regel är självständigt evaluerbar som
data — den bär tillräcklig semantik för att gate-exekutorn ska kunna avgöra pass/fail *utan* hårdkodade
if-satser per typ:

```python
@dataclass(frozen=True)
class PromotionRule:
    candidate_type: str                         # "policy" | "skill" | "tool" | ... (framtida)
    kind: "eval" | "safety" | "operator_gate"
    # för eval/safety:
    metric: str | None                          # t.ex. "success_rate"|"no_regression"|"normalized_weights"
    threshold: float | None                     # t.ex. 0.0 (= strikt bättre), 1.0 (= summa)
    comparator: str = "gte"                     # "gte" | "gt" | "lte" | "eq"
    # för operator_gate:
    operator_scope: str | None                  # t.ex. "tool"|"credential"|"external_effect"|"policy"|"executive_helper"
    # en AWAIT_OPERATOR-regel har ingen eval-tröskel; den blockerar alltid tills godkänd.
```

- `kind="eval"` med `metric`/`threshold`/`comparator`: kandidaten promotas om metric-värdet i `EvidenceMatrix`
  uppfyller tröskeln (t.ex. `success_rate gte 0.0` = strikt bättre; `no_regression eq true`). Regelobjektet
  evalueras rent som data.
- `kind="safety"`: kandidaten promotas endast om alla säkerhetsfixtures/constraints passerar (fail-closed).
- `kind="operator_gate"` med `operator_scope`: **alltid** `AWAIT_OPERATOR` oavsett eval-resultat; kräver en
  namngiven människa (per §31: "credential/extern effekt/policy → alltid operatörsgrind"; "executable helper →
  namngiven operatör"; "nytt tool → separat toolgranskning").

**`PromotionGate` — regler RESOLVERAS INTERNT, tas ALDRIG emot från adaptern (P0.2-korrigering):**
`PromotionGate.evaluate(matrix, candidate_id) -> Verdict` (där Verdict ∈ `{PROMOTE, AWAIT_OPERATOR, REJECT}`):
1. slår upp `candidate_id` i `CandidateRegistry` för att få kandidattypen;
2. hämtar kandidattypens **registrerade** regler ur `promotion_rules`-registret (inte från anroparen);
3. **union:ar alltid** med den okrossbara `MANDATORY_OPERATOR_GATES`-regelbasen (härledd ur §31/§32.2);
4. evaluerar regelobjekten (datadrivet) mot `EvidenceMatrix`.

Adaptern kan aldrig skicka in egna regler eller utesluta en `operator_gate`-regel → self-approval-bypass är
strukturellt omöjligt. Detta är den mekaniska garantin för §28:s self-approval-förbud (se nedan).

**Icke-delegerbara regler (data som inte kan överskridas):** en kandidat kan aldrig registrera bort en
`operator_gate`-regel. `MANDATORY_OPERATOR_GATES` (§31/§32.2-härledd) injiceras av gate-exekutorn i **varje**
utvärdering oavsett vad adaptern registrerade. `.evaluate` tar aldrig emot regler utifrån, så registret är
den enda källan + den okrossbara unionen. Det är datasäkerheten i registret + unionen, inte per-typ-koden,
som garantierar self-approval-förbudet.

**Konsekvens för v1-kandidattypens gate-konfiguration:** en effektfri **policy-parameter**-kandidat
(`CandidatePathScore`-vikter) har ingen extern effekt/credential/behörighet → dess regeluppsättning är
`[eval, safety]` → kan **auto-promotas** av den regelstyrda grinden. En **skill**-kandidat av typen
"instruktion/exempel/källa" har också `[eval, safety]` → auto-gate möjlig, men eftersom skill-eval i v1 är
live-eval (budgetsteg) så begränsas skill-promotion i v1 till **explicit planerad/demoo** och promotas aldrig
tyst. En **tool**-kandidat rör alltid effektklassen (`external_mutation`/`irreversible`/`credential` → §32.2)
→ `MANDATORY_OPERATOR_GATES` gör den **alltid `AWAIT_OPERATOR`** (Beslut 5), oavsett eval-resultat.

**Varför detta respekterar self-approval-förbudet (§28):** "Model proposes, authoritative code validates"
är uppfyllt eftersom (a) kandidaten *föreslås* av en agent/operatör men (b) *verkställs* enbart av gate-exekutorn
över oföränderliga regler som **resolveras internt ur registret + unionen** (aldrig från anroparen), eller av
en namngiven operatör — algoritmen kan inte "vilja" promota sig själv, och gate-exekutorn har inget
intressekonflikt-objekt och kan inte skriva om sin egen regelbas. Den regelstyrda auto-gaten är **inte**
self-approval: det är samma princip som `BudgetGate`s fail-closed-räkning (fast regler som data), inte en
fri-flytande agent som godkänner sig själv. **Testet som bevisar detta:** (a) en adapter som försöker
registrera bort en `operator_gate`-regel misslyckas med ett `ImmutableRuleError`; (b) `PromotionGate.evaluate`
accepterar ingen `rules`-parameter — en försökt bypass via signaturen är omöjlig (P0.2).

### 4. Strategiportabilitet (#138): förs in i scope som mekanismen, full per-vertikal-evolution avsiktligt v1.x

**Beslut:** issue #138:s `StrategyManifest`-idé **inkluderas i detta uppdrags scope** som den *mekanistiska
basen*: den generiska versionerade-kandidatmekanismen (v1) ÄR strategiversioneringens botten. Men **full
per-vertikalprofil-ackumulering** (en vertikalprofil bygger upp, och väljer mellan, sina egna beprövade
strategivarianter över tid) är en **explicit v1.x-utvidgning**, inte en v1-leverans. Skäl:

- **#138:s eget "varför inte nu":** AI Act-klassificeringen (enda vertikalen idag) är *inte* ett
  utforskningsproblem — dess Fas 2-loop är `direct`-only och har inget strategival att evolvera. Att bygga
  full per-vertikal strategi-ackumulering nu vore att bygga för en andra vertikalprofil som inte finns.
- **Exit-kriteriet kräver det inte:** "ingen automatisk ändring når produktion utan verifierad promotion"
  uppfylls av livscykelmekanismen, inte av per-vertikal strategiakumulering.
- **v1 lägger grunden som #138 pekar på:** `CandidatePathScore`-versionering (Beslut 1) och en
  typ-agnostisk `CandidateRegistry` som kan bära ett framtida `StrategyManifest` (typ="strategy") — att lägga
  in en `strategy`-typ är en v1.x-adaptionsregistrering, ingen ny mekanism.

**Konsekvens:** specen refererar #138 som en *ingår-i-scope, mekanism-first* requirement; en ny GitHub-issue
för **Fas 8** bör referera #138 som "part of" om dispatcher-behovet uppstår. Inga kodändringar för
per-vertikal prod-fil i v1.

### 5. Skill-promotion och Tool-evolution: mekanism-kopplade pipelines, djup medvetet begränsat — §23:s fulla "fungerande byggd pipeline" för dessa två uppnås i v1.x (P1.6-ärlighet)

**Beslut (P1.6-korrigering — ärlig deklaration av vad v1 faktiskt bygger):** §23 kräver Skill Platform-promotion
(§31) och Tool Platform-evolution (§32.3) som "fungerande byggd pipeline, inte bara en beskriven modell". v1
bygger **mekanismen** som båda pluggar in på (den generiska loopen — registrera → evaluera → gate → promota),
och bygger **funktionella adaptrar** som kan registrera, strukturellt evaluera och per-§31-regel gata en
skill/tool-kandidat. Men v1 verifierar **inte på djupet** att dessa två *faktiskt* kan promota en verklig
produktions-skill eller -tool: skill påverkande eval kräver live-instruktionseval (budgetsteg) och tool kräver
full §32.3-säkerhetschecklista. Därför: v1 = **"mekanism-kopplade, ej djup-verifierade"** pipelines, och
**§23:s "fungerande byggd pipeline" för just skill/tool uppnås i v1.x** (live-skill-eval + full tool-security).
Fas 8:s exit-kriterium ("ingen automatisk ändring når produktion utan verifierad promotion") uppfylls av
policy-kandidaten (Beslut 1/4) — det blockerar inte att skill/tool-djupet är v1.x, men det är **inte** tyst:
det deklareras här som en medveten scope-begränsning, inte som en färdig leverans.

- **Skill-promotion (§31):** `SkillCandidate`-adapter registrerar en version av en `SkillManifest`
  (återanvänder `HermesSkillAdapter`/`SkillManifest` från portability). Promotion-regeln hämtas från
  §31-tabellen per förändringstyp. v1 **domänspecifikt djup**: skill-eval i v1 är **fixture-deterministisk
  (struktur/regression) + dokumenterad live-eval som ett separat budgetstyrt steg** — ingen riktig
  modell-driven skill-instruktions-eval körs i v1 utan operatörsgodkänd budget. En skill-kandidat *kan*
  promotas automatiskt av kod-gaten (regeln tillåter det, §31-tabellen "instruktion/exempel/källa → eval mot
  fixtures och regressioner") men **v1 bevisar bara att gate-mekanismen körs** mot en deterministisk
  skill-fixture; verklig live-skill-eval-promotion är explicit v1.x/budgetsteg.
- **Tool-evolution (§32.3):** `ToolCandidate`-adapter registrerar ett tool med manifest + schemas +
  effektklass. §32.3:s candidate-checklista (schema-/felbeteende, permission denial, timeout/cancellation,
  credential-/nätverksisolering, output-sanitering, deterministic cleanup, dependency-/säkerhetskontroll,
  regression mot aktiv tool-version) implementeras som **gate-asserts**. **Effektklass-regeln från §32.2
  gör att varje tool-kandidat som rör `external_mutation`/`irreversible`/`credential` kräver operatörsgrind**
  → v1:s tool-promotion är **alltid operator-gated** (aldrig auto), och de säkerhetstunga checklistepunkterna
  (credential-/nätverksisolering, dependency-scanning) byggs som **stubs som fail-closed** plus en
  avgränsad deterministisk del (schema/permission/timeout mot befintlig `runtime/tools/gate.py`) — den fulla
  säkerhets-djupet är v1.x. Detta är ett **medvetet riskval** (Beslut 5): full tool-security-checklista är
  en egen avgränsad säkerhetsleverans som inte ska gömmas i en "v1-promotionflow"-spec, och som inte kan
  presenteras som "fungerande" i v1 utan att ljuga.

### 6. "Tränad operator- eller routingpolicy" (leverabel 4): explicit ut-scope för v1, kontraktet parametriskt-bärande (P1.4-ärlighet)

**Beslut:** ren ML/RL-träning av en operator- eller routingpolicy **byggs inte i v1**. v1:s "learning" är
kandidatgenerering + verifierad promotion (§28:s mekanism), inte gradient-baserad träning. Skäl:

- Att träna en policy kräver en träningsloop, ett förlustmått, ett dataset och en separat eval/validering —
  det är en hel egen leverans som skulle förstöra Fas 8:s "liten, verifierbar livscykel" som enda mål.
- §28-invarianten "*Ett misslyckat experiment får inte förstöra den verifierade operativa vägen*" — en
  tränad policy som *ersätter* routing är en mycket större yta än en versionerad kandidat som *läggs till*.
- **P1.4-korrigering (ärlig gräns, ingen falsk trygghet):** v1:s `payload_ref`/`Evaluator`-kontrakt är
  specificerat som **parametriskt-bärande** — det kan uttrycka en versionerad vikt-/parameterkandidat
  (t.ex. `CandidatePathScore`-vikter), vilket är den typ av utdata en enkel policy-regression/optimering
  producerar. Men en **icke-parametrisk** tränad policy (neural nätverks-viktmatris, embeddings-baserad
  representation) kräver en **utvidgning av `payload_ref`-formatet och `Evaluator`-porten** — det lovar
  v1:s kontrakt INTE att klara utan ändring. Alltså: v1 lägger rätt för *parametriska* viktkandidater, och
  dokumenterar att *icke-parametriska* är en framtida kontraktsutvidgning, inte en drop-in.

### 7. Rollback: versionerad state + aktiv-pekare i SQLite (atomär pekaråterställning)

**Beslut:** rollback är ingen separat "mekanism" — det är en **konsekvens av att state är versionerat**.
Varje kandidat är **immutabel i registret** — hash-låst på det **serialiserade payload-objektet** (dict/json),
`sha256` som `SkillRegistry.manifest_hashes()` redan gör. **P0.1-korrigering (viktigt):** skillnaden mellan
den **beständiga, hash-låsta kandidat-payloaden** (det som registreras och audit-loggar) och en eventuell
**runtime-instans** (t.ex. en `CandidatePathScore`-dataclass, som i dagens kod är `@dataclass` utan
`frozen=True`) är explicit: registret lagrar och hash-låser det *serialiserade* payload-dict:et, inte den
mutable runtime-objektet. En mutation av en runtime-instans efter registrering ändrar INTE den hash-låsta
kandidat-payloaden (den är en separat, immutabel snapshot i DB:n). I plan-fasen noteras att
`CandidatePathScore` kan göras `frozen=True` för att förhindra att runtime-instansen muteras, men
korrektheten beror inte på det — den garanteras av att hash:en är bunden till den serialiserade payloaden.
En **aktiv-pekare** pekar på den aktuella promotade versionen. Promotion = **atomär transaktion** i
SQLite (`BEGIN` → flytta aktiv-pekare → `COMMIT`), med `promoted_from` (föregående version) och
`promoted_at`-stämpel. **Rollback = en atomär transaktion som återställer aktiv-pekaren till föregående
version**, med en `rolled_back`-räknare och audit-rad.

**Varför SQLite, inte git-baserad / en fil:**
- **Konsistens:** repot använder redan SQLite för `BudgetGate` (`fas2a_inference_spend`) — samma
  `_ensure_table`- + transaktionsmönster, ingen ny persistensarkitektur.
- **Atomär och auditerbar:** en DB-transaktion gör pekarbytet atomärt (ingen halv-promotion), och varje
  promotion/rollback skriver en stämpel- och ursprungsrad — det git-läget inte ger per-run-audit utan
  konventionell commit-disciplin.
- **Inte git-as-database:** att promota en kandidat *ska* återspeglas i båda (manifestet checkas in +
  pekaren i DB pekar på den), men den *aktiva* versionen är ett runtime-beslut som DB:n äger — git säger vad
  som *finns*, DB säger vad som *är aktivt*.

**Minimal v1-rollback-behov:** ingen separat infra. En `CandidateRegistry`-tabell med `status`-kolumn
(`draft | eval_pending | promoted | rolled_back | rejected`) + aktiv-pekare-tabell. **P1.5-korrigering:**
eftersom registret är nycklat på `type@name@version` och det kan finnas flera kandidater av samma `type`
under olika `name` (t.ex. "geometric-path-scoring" vs "branch-ranking"), är API:t **`rollback(type, name)`**
— det pekar entydigt ut vilken kandidat som ska rullas tillbaka. `rollback` är en ren transaktion. Testas
deterministiskt (se Testing strategy).

### 8. Var lever kandidatens "tillstånds-maskin" och var bekräftas produktionens ostördhet?

**Beslut:** hela livscykeln ägs av en **`LearningLoop`-enhet** i `agent-platform/learning/` (ny modul):
`CandidateRegistry` (persistens, typ-agnostisk), `PromotionGate` (regelstyrd beslutaren),
`RollbackStore` (eller del av registry), `Evaluator` (digital `EvidenceMatrix`). **Produktionsvägarna
(kernel `_SOLVERS`, reasoning `select_strategy`, `BudgetGate`, portklasser) rörs inte i v1 förutom att en
"aktiv policy"-läsning kan injiceras.** Den enda beröringspunkten med en exekveringsväg är att den aktiva
`CandidatePathScore`-versionen kan tillhandahållas som aktuell policy till `score_path` — en ren injektion
som inte ändrar befintliga default (v1-policy = default = `CandidatePathScore()` oförändrad).

**Exit-testet ("produktion ostörd"):** en TDD-assertion bekräftar att medan en kandidat evalueras, promotas
eller rullas tillbaka, så returnerar befintliga `Engine.solve`/`score_path`-anrop exakt samma resultat som
innan (default-policyn är ostörd tills en kandidat faktiskt promotas, och även då är den *nya* policyn
prefix-verifierad). Detta är den deterministiska motsvarigheten till §28:s "misslyckat experiment förstör
inte verifierad väg".

### 9. Stabila, typ-agnostiska kontrakt — grunden för det större målet (Beslut 3 utvidgat)

**Beslut:** för att Fas 8 ska vara *grunden*, inte en demo, fastställer v1 **fem stabila kontrakt** som alla
framtida kandidattyper pluggar in på utan att röra kärnmekanismen. Dessa är v1:s verkliga leverans —
mekanismen som "bara fungerar för policy" är underordnad de kontrakt som låter den växa:

1. **`Candidate`-datamodellen (typ-agnostisk):** `{id, type, name, version, manifest_hash (sha256),
   status, payload_ref, proposed_at, promoted_by, promoted_at, rolled_back_at}`. En framtida
   `type="strategy"`- eller `type="trained_policy"`-kandidat är bara en ny `type`-sträng + en adapter som
   mappar sin payload till `payload_ref` — ingenting i registry/gate/rollback ändras.
2. **`Evaluator`-porten (kandidattyp-parameter):** en interface `Evaluator(candidate_payload, fixtures,
   active_baseline) -> EvidenceMatrix`. V1 implementerar `PolicyEvaluator` (deterministisk, `score_path`).
   En framtida `SkillEvaluator` (live, budgetgated) eller `TrainedPolicyEvaluator` är en ny implementering
   av samma port — evaluatorn byts per typ, köreren ändras inte.
3. **`PromotionRule`/`promotion_rules`-registret (data, Beslut 3):** regler är data per kandidattyp + en
   okrossbar `MANDATORY_OPERATOR_GATES`-regelbas. En framtida kandidattyp registrerar bara sin regeluppsättning
   och evaluerare; gate-exekutorn är typ-agnostisk.
4. **`CandidateRegistry`-schemat (SQLite, persistent, versionerad):** `candidates` + `active_candidates`-tabeller
   med hash-låsta, immutabla rader och audit-kolumner. Samma schema bär policy, skill, tool och framtida typer
   — inga per-typ-tabeller.
5. **Candidate-*ingångsdörren* (§31.1-ready):** `submit_candidate(type, payload, provenance)`-inkomstfunktion
   som validerar manifest-hash + typregistrering och lägger en kandidat i `eval_pending`. Framtida
   *automatisk* kandidatgenerering från trajectorier (§31.1: observation → pattern detection → skill
   candidate) kan då mata in via samma dörr som manuell/agent-proponering — skillnaden är bara *varifrån*
   payloaden kommer, inte *hur* den behandlas. Detta gör att v1 inte blockerar den automatiska genereringsänden.

Dessa fem kontrakt är vad som gör Fas 8 till fundamentet för hela den kontrollerade learning-loopen i
målbilden. Alla fem finns som deterministiska, testbara ytor i v1 (0 live-resurser). Se "Vägen till det
större målet" för hur v1.x-stegen (strategiportabilitet, tränad policy, §31.1-auto-generation, drift-monitor)
var och en bara är en ny implementering/registrering på ett av dessa kontrakt.

### 10. Recursive + geometric reasoning genomsyrar loopen; Voyage som semantisk grund; Agent Memory som evidens-/retrieval-inspiration (operatörsdirektiv 2026-08-18)

**Beslut (operatörens direktiv):** recursive-geometric reasoning ska **genomsyra** det vi bygger, **Voyage**
utnyttjas som den semantiska grunden, och **Cloudflare Agent Memorys arkitektur** (multi-typ-klassificering +
multi-channel-retrieval + verifier-checked) lånas som **designinspiration** för loopens evidens-/provenance-
hantering — **utan att bero på Cloudflares beta-tjänst** (ingen SLA, prissättning okänd; operatörens egen
bedömning). Detta är tre sammanflätade teman som Fas 8 konkretiserar enligt nedan.

**10a. Recursive-geometric reasoning som loopens substrat.** Den kontrollerade learning-loopen är i sig ett
reasoning-problem, inte bara en mekanisk pipeline. v1 använder det **redan accepterade geometric-paketet**
(`agent-platform/reasoning/geometric/`, ADR-017) som den naturliga ramen istället för att uppfinna en
parallell struktur:

- **Candidate space = reasoning graph:** kandidaterna (+ den aktiva baslinjen) modelleras som noder i en
  `ProblemSpace`; kantevärden bär "kan utvärderas tillsammans"-relationen. **`score_path` + `CandidatePathScore`
  (Beslut 1) är redan den versionsstyrda policy som rankar kandidatbanor** — loopens "välj bästa kandidat"
  är alltså ett anrop till den befintliga geometriska sökfunktionen, inte ny mekanik.
- **Recursive decomposition:** en komplex promotion/eval uppgift dekomponeras (recursive-mönstret) i
  del-evals per kandidat och re-integreras till en EvidenceMatrix — samma operator-mönster som
  `reasoning/kernel/engine.py`'s `_solve_recursive` formaliserar.
- **Säkerhetsregler för policy-kandidater (P1.1-korrigering — konkret, ingen kategori-fel):** eftersom
  `AttractorDetector`/`contradiction` opererar på `ProblemSpace` + `node_id` (grafnoder), och en
  `CandidatePathScore`-kandidat är sju skalärer, inte en grafnod — att applicera dessa detektorer direkt på
  en viktuppsättning vore ett kategori-fel utan ärlig mekanisk väg. Därför ersätts det i v1 med **konkreta,
  deterministiska policy-constraint-säkerhetsregler** för viktkandidaten (som `kind="safety"`-regler, Beslut 3):
  - **`normalized_weights`**: additiva vikter (w1..w4) summa = 1.0 och subtraktiva (w5..w7) summa = 1.0
    (överträdelse av §12.4:s normaliseringskontrakt → `REJECT`); `comparator="eq", threshold=1.0`.
  - **`non_negative_weights`**: inga negativa vikter (en negativ målviktsvikt är en contradiction mot policy-
    kontraktet → `REJECT`); `comparator="gte", threshold=0.0`.
  - **`bounded_weights`**: alla vikter inom [0,1].
  Detta är den ärliga, testbara motsvarigheten till "ett misslyckat experiment får inte förstöra den
  verifierade operativa vägen": en viktkandidat som bryter normaliserings-/boundedness-kontraktet avvisas
  mekaniskt innan den kan påverka någon väg. (För *framtida* kandidattyper där en candidate faktiskt ÄR en
  grafnod — t.ex. en strategi som introducerar nya noder/kanter i ett reasoning-graf — kan
  `AttractorDetector`/`contradiction` återanvändas som äkta geometric-säkerhetsregler; det noteras i
  "Vägen till det större målet", men byggs inte i v1 eftersom v1:s kandidattyp är skalärer.)

**10b. Voyage som semantisk grund.** `CandidatePathScore.embedder` accepterar redan en `EmbeddingFn`, och
`EmbeddingPort` (`agent-platform/runtime/embedding_port.py`, Fas 6) är en drop-in Voyage-embedder
(`voyage-4-lite`, dim 1024, env `CORTXT_EMBEDDING_URL/API_KEY`, operatörsstyrd). Den semantiska termen i
`score_path` — `expected_information_gain` (semantisk närhet mellan kandidatinnehåll och mål) — blir **meningsfull
endast med en riktig embedder; `hash_embedding` förblir den deterministiska defaulten men rankar bara på id/text,
inte semantik** (vilket Fas 6 bevisade: hash mis-rankar semantiskt, Voyage korrigerar). Fas 8 utformar
policy-kandidat-evalen så att **Voyage kan injiceras som den semantiska embeddern**
(för det deterministiska core-testet körs `hash_embedding`; för en riktig, promotion-berättigad semantisk
jämförelse körs Voyage som ett **budgetgated steg** med samma cache+sleep-rate-limit-disciplin Fas 6
etablerade). Detta gör
att Fas 8:s promotion-beslut i sin live-form "ser" semantisk förbättring, inte bara strukturell — direkt i
linje med operatörens direktiv att utnyttja Voyage.

**10c. Cloudflare Agent Memory som designinspiration.** Agent Memorys arkitektur — en **verifier** som kör
flera checks innan ett minne klassas i fyra typer (**facts, events, instructions, tasks**) och **multi-channel
retrieval** (fulltext / exact fact-key / raw message / vector / HyDE-vector) som **fuseras** — är ett mer
sofistikerat schema än det nuvarande session-per-child-logging-approach (Fas 5, option 1). Fas 8 lånar **idén,
inte tjänsten**:

- **Typad kandidat-/evidensklassificering:** varje kandidat + dess eval-evidence klassificeras i ≤ fyra typer
  (`facts`, `events`, `instructions`, `tasks`) med en **verifier-liknande `EvidenceClassifier`** som kör
  deterministiska strukturella checks (manifest-form, hash-integritet, fixture-täckning, no-regression) innan
  evidens tillåts bära vikt i en promotion. Samma princip som Agent Memorys verifier: *inget minne/evidens
  klassas utan att först klara checks* — här: *ingen kandidat får promotionsvikt utan verifierad evidens*.
- **Multi-channel retrieval som grund för framtida kandidatgenerering:** v1 lagrar klassificerad evidens i
  `CandidateRegistry`-schemat (Beslut 9, punkt 5) med tydliga nycklar; en v1.x-`EvidenceRetriever` kan sedan
  söka över flera kanaler (typ / manifest-hash / raw payload / framtida Voyage-vektor) och fusera resultaten
  för att *mata* §31.1:s automatiska kandidatgenerering. v1 bygger klassificeringen + lagringsschemat (så att
  multi-channel-retrieval är plug-in-klart), men själva den fuserade retrieval-queryn är v1.x.
- **Explicit icke-beroende:** inget i v1 beror på Cloudflares Agent Memory-API/beta. Vi lånar arkitekturen
  (typifiering + verifier-checks + multi-channel) som tolkningsram för evidens-hantering; betatjänstens
  brist på SLA/okänd prissättning (operatörens egen riskbedömning) gör att den **inte** används i produktion.

**Konsekvens för v1-komponenter:** `agent-platform/learning/` får en `EvidenceClassifier` (typifiering +
verifier-checks), kör mot `ProblemSpace`/`score_path` för kandidat-rankning (10a), tillåter Voyage-injektion
som drop-in-embedder (10b), och lagrar typad evidens i registry-schemat (10c). Allt detta har en deterministisk
kärna (hash-embedder, mockade fixtures, 0 live-resurser) plus budgetgateda live-armar (Voyage). Det är en
*tillämpning av operatörens direktiv som genomsyrar hela loopen* — inte en eftermonterad extrafunktion.

## Components (nya/ändrade moduler)

**Ny modul** `agent-platform/learning/` (motsvarar "evolution och promotion"-ansvaret som §33 reserverar
för `agent-platform/skills`/`tools` men som idag inte existerar):

- `candidate.py` — typ-agnostisk `Candidate`-datamodell: `{id, type (policy|skill|tool), name, version,
  manifest_hash (sha256), status, payload_ref, proposed_at, promoted_by, promoted_at, rolled_back_at}`.
  **P0.1:** `payload_ref` pekar på den **serialiserade, hash-låsta payloaden** (immutabel snapshot),
  inte på en mutable runtime-instans.
- `registry.py` — `CandidateRegistry`: SQLite-persisterad, `_ensure_table`, nycklad på
  `type@name@version`, aktiv-pekare-tabell (`active_candidates(type, active_version)`), deterministisk
  export/hash (samma principer som `SkillRegistry`).
- `evaluator.py` — kör `EvidenceMatrix`: för varje kandidatkörning mot fixture-set, samlar success/cost/latency
  + no-regression-flagga mot aktiv baseline. Återanvänder fixture-generatorerna från
  `agent-platform/harness/eval/` (t.ex. `run_task_class_eval`-liknande per-fixture-verdict, men
  multi-kandidat). **Kandidat-ranking sker via den befintliga geometriska `score_path` + `CandidatePathScore`
  (Beslut 10a), med `embedder` injicerbar: `hash_embedding` som deterministisk default, `EmbeddingPort`
  (Voyage, Fas 6) som budgetgated drop-in (Beslut 10b).** **P1.2:** vid live-eval **pre-computar/förcachar
  evaluatorn ALLA embeddings för fixture-nodes + goal INNAN `score_path` anropas**, så `embedder` är en
  lookup under eval (inte ett API-anrop per node/path) — samma cache-disciplin som Fas 6 bevisade (unique=6).
- `evidence.py` — **`EvidenceClassifier` (Beslut 10c):** typifierar varje kandidats evidens i ≤ fyra typer
  (`facts | events | instructions | tasks`) och kör **verifier-liknande deterministiska checks** (manifest-form,
  hash-integritet, fixture-täckning, no-regression) innan evidens får bära promotionsvikt. Ren, deterministisk,
  testbar; lagrar till registry-schemat som typad evidens (plug-in-klar för framtida multi-channel-retrieval).
  **P1.3 (konkret exempel, policy-kandidat):** `facts = {success_rate: 0.92, baseline_delta: +0.03}`,
  `events = {eval_run_at: <iso-ts>, fixtures: "geometric_N3"}`,
  `instructions = {active_candidate: "geometric-path-scoring@v2"}`,
  `tasks = {rollback_plan: "revert_to_v1", next: "re-review"}`.
- `promotion_gate.py` — **typ-agnostisk regel-*exekutor***: `PromotionGate.evaluate(matrix, candidate_id) -> Verdict`
  där Verdict ∈ `{PROMOTE, AWAIT_OPERATOR, REJECT}`. **P0.2 (regler resolveras internt, aldrig från anroparen):**
  `.evaluate` slår upp `candidate_id` i `CandidateRegistry` för att få kandidattypen, hämtar typens registrerade
  regler ur `promotion_rules`-registret, union:ar alltid med `MANDATORY_OPERATOR_GATES`, och evaluerar
  regelobjekten (data, Beslut 3/9). Adaptern kan aldrig skicka in egna regler eller utesluta en
  `operator_gate`-regel (`ImmutableRuleError` vid försök att registrera bort) → self-approval strukturellt omöjligt.
- `rollback.py` — **`rollback(type, name)`** (P1.5) → atomär pekaråterställning till `promoted_from` +
  audit-rad. Ren transaktionslogik.
- `submit.py` — candidate-**ingångsdörren** (`submit_candidate(type, name, payload, provenance)`); validerar
  manifest-hash + typregistrering, lägger kandidat i `eval_pending` (Beslut 9, punkt 5).
- `__init__.py` — publika exports.

**Nya kandidatadapters** (ett torrt anpassat lager ovanpå `candidate.py`):
- `adapters/learning/policy_candidate.py` — `CandidatePathScore` (eller en serialiserad vikt-dikt) →
  `Candidate(type="policy")`; evaluering = `score_path` mot geometriska fixtures med den kandidatens vikter.
- `adapters/learning/skill_candidate.py` — `SkillManifest` → `Candidate(type="skill")`; återanvänder
  `HermesSkillAdapter`/`SkillRegistry`. Promotion-regel ur §31-tabellen.
- `adapters/learning/tool_candidate.py` — tool-manifest → `Candidate(type="tool")`; §32.3-checkliste-gate
  (v1: deterministisk del + fail-closed-stubs, Beslut 5).

**Ändrad (minimal, injektion; Beslut 8):** en punkt där den aktiva policyn kan läsas in — lämpligen en
funktion `learning.active_policy("policy", "geometric-path-scoring") -> CandidatePathScore | None` som
`score_path`-anropsplatsen (eller en framtida konfig) kan anropa; **default = None = befintlig `CandidatePathScore()`**
så att alla befintliga anrop/tester är oförändrade. Ingen ändring i `Engine`, `select_strategy`,
`BudgetGate` eller portklasser.

**TDD-relevant NOTE:** `agent-platform/harness/eval/__init__.py` dokumenterar att `baseline_direct.py` inte
återanvänder `reasoning/kernel/strategy.py`'s `Strategy.DIRECT`. Fas 8 följer samma försiktighet: Fas 8:s
policy-kandidat-eval bygger sitt eget deterministiska evalueringsanrop mot `score_path` + geometriska
fixtures — den antar **inte** att `Strategy.DIRECT` (som är model-fri och gör något strukturellt annorlunda)
kan återanvändas rakt av som Fas 8-evals villkor.

## Data flow

```text
Kandidatproponering (agent/operatör föreslår en variant)
  -> submit_candidate(type, payload, provenance)                          (ingångsdörr, Beslut 9.5)
      -> EvidenceClassifier.verifier-checks + typifiering (facts|events|instructions|tasks, Beslut 10c)
          -> CandidateRegistry.add(Candidate(type, version, manifest_hash, status=eval_pending))
              -> Evaluator kör EvidenceMatrix (fixture-set + active_baseline, multi-kandidat)
                  -> kandidat-rankning via geometric score_path + CandidatePathScore
                     (embedder = hash_embedding default / Voyage via EmbeddingPort, Beslut 10b)
                  -> safety-regler: policy-constraints (normalized/non_negative/bounded vikter, Beslut 10a)
                  -> PromotionGate.evaluate(matrix, candidate_id)          (regler resolveras internt, Beslut 3)
                      -> AWAIT_OPERATOR  (MANDATORY_OPERATOR_GATES: tool/external-effekt/credential/exec-helper)
                      -> PROMOTE         (effektfri policy/skill: [eval, safety]-regler + strikt bättre+no-regression)
                      -> REJECT          (sämre / regressande / constraint-brott / rule-fail)
  Promotion (PROMOTE):
      -> SQLite-transaktion: spara new-active-version, promoted_from=prev, promoted_at (atomär)
  Rollback (operatör eller kod-gate vid drift-regression):
      -> SQLite-transaktion: flytta aktiv-pekare tillbaka till promoted_from (atomär, audit-rad)

Produktionsväg (ostörd tills en kandidat promotas):
  score_path(...) -> policy = learning.active_policy(...) or CandidatePathScore()   (default oförändrad)

Framtida (v1.x, samma kontrakt):
  EvidenceRetriever (multi-channel, Agent Memory-inspirerad) -> matar §31.1 pattern detection -> submit_candidate
```

## Error handling

| Fall | Hantering |
|---|---|
| Kandidat-manifest-hash kolliderar med befintlig `type@name@version` | `RegistryError` — registret är nycklat på `type@name@version` (samma som `SkillRegistry`): ett dubblett-`add` avvisas eller behandlas idempotent (precis som `SkillRegistry.add` vid lika manifest), aldrig tyst överskrivning. |
| Eval-fixture saknas / fixture-generator misslyckas | Evaluatorn fail-closes: rundan räknas som misslyckad (inte fabrikerad) och EvidenceMatrix-raden `error`-flaggas — samma "degradering, inte fel"-princip som Fas 6:s `change_perspective`. Ingen kandidat promotas på ofullständig evidens. |
| Promotion-Gate får inkomplett matrix (saknade rundor) | `CannotDecide` — Verdict blir `REJECT`/`AWAIT` (fail-closed), aldrig `PROMOTE` på partiell evidens. |
| `active_policy`-injektion saknar rad (ingen promotad version) | Returnerar `None` / default — befintlig väg oförändrad (Beslut 8). |
| DB-transaktion för promotion/rollback misslyckas | Transaktionen rullas tillbaka (inte tillämpad) — state förblir på förra giltiga pekaren; inget "halv-promotat" tillstånd (Beslut 7). |
| Tool-kandidat med external-mutation/credential/irreversible skickas till kod-gate | `AWAIT_OPERATOR` hårdkodat ur §32.2/§31 — koden KAN aldrig auto-promota en sådan (Beslut 5). Testet bevisar fail-closed. |

## Testing strategy

- **TDD, vertikala skivor** enligt `test-driven-development`-skillen.
- **Deterministisk kärna först (0 live-resurser):**
  - `CandidateRegistry`: add/get/export/hash-idempotens (adaptation av `SkillRegistry`-testernas principer);
    persistens över registry-instanser (SQLite round-trip); nyckelkonflikt.
  - `PromotionGate`: ren funktion — givet beprövade matrices, verifiera `PROMOTE`/`AWAIT_OPERATOR`/`REJECT`
    för varje kombination; framför allt: försämrad kandidat → `REJECT`; tool/external-effekt → `AWAIT_OPERATOR`
    oavsett eval-resultat (fail-closed). **P0.2 (self-approval-bypass-test):** (a) en adapter som försöker
    registrera bort en `operator_gate`-regel → `ImmutableRuleError`; (b) `evaluate` accepterar ingen
    `rules`-parameter — en försökt bypass via signaturen är omöjlig; (c) `MANDATORY_OPERATOR_GATES` union:as
    alltid in oavsett vad registret innehåller.
  - `Evaluator` multi-kandidat: EvidenceMatrix med ≥2 kandidater + baseline; no-regression-flagga korrekt.
  - `rollback`: promotion sedan rollback återställer aktiv-pekare + skriver audit-rad; idempotent (rollback
    av redan rullad-back är no-op eller explicit fel, inte korruption). **P1.5:** `rollback(type, name)` väljer
    rätt kandidat bland flera `name` under samma `type`.
  - **Policy-constraint safety-rules (Beslut 10a, P1.1-korrigering):** `PromotionGate` med `safety`-regler
    `normalized_weights` / `non_negative_weights` / `bounded_weights` — en viktkandidat som bryter
    normaliserings-/boundedness-kontraktet → `REJECT`, oavsett eval-success. Testas mot mockade viktvektorer
    (0 live-resurser). (Ingen `AttractorDetector` på viktvektorer — kategori-fel, se Beslut 10a.)
  - **`EvidenceClassifier` (Beslut 10c):** typifiering i `facts|events|instructions|tasks` korrekt; en kandidat
    vars evidens inte klarar verifier-checks (bruten hash, ofullständig fixture-täckning, regresserande) får
    INTE promotionsvikt (fail-closed). Deterministik.
  - **Voyage-injektion (Beslut 10b, P1.2):** `Evaluator`-porten accepterar en `EmbeddingFn`; fastställ att
    `hash_embedding`-default ger deterministisk (om än id-baserad) ranking, att en mockad "Voyage-lik"
    embedder (som korrekt rangordnar semantiskt närliggande kandidatinnehåll) ändrar ranking som väntat, och
    att **embeddingar förcache:as (embedder är en lookup under eval, inga upprepade anrop)** — allt med mock,
    0 riktiga anrop. En riktig Voyage-körning är en separat `real_inference`-arm (se nedan).
  - **Exit-test (produktion ostörd):** medan en kandidat evalueras/promotas/rullas tillbaka, returnerar
    befintliga `Engine.solve` / `score_path`-anrop EXAKT samma resultat som innan (default-policy oförändrad
    tills en kandidat faktiskt promotas, och även då är den nya policyn prefix-verifierad). Assertion mot
    geometriska fixtures (samma mönster som `tests/reasoning/geometric/`). *(P2.2-not: `Engine.solve` finns som
    klassmetod i `agent-platform/reasoning/kernel/engine.py` — verifierad i denna bas.)*
  - **Dubbel-riktnings-exit-tests:** (a) en medvetet *bättre* policy-kandidat kan promotas (mekanismen
    fungerar); (b) en medvetet *försämrad* policy-kandidat avvisas och produktionen berörs aldrig. Båda
    deterministiska, 0 inferensanrop.
- **Budgetgated live-arm (separat, utom default-sviten, `real_inference`):** en Voyage-semantisk policy-eval
  som bevisar semantisk förbättring (kandidat vars `expected_information_gain`-term med Voyage rankar bättre
  än hash-baselinjen), med samma cache+sleep-rate-limit-disciplin som Fas 6, budgetgated via isolerad
  `db_path`. Kräver operatörssatta `CORTXT_EMBEDDING_URL/API_KEY` + godkänd budget (Hårda gränser). En skippad
  live-arm är INTE ett pass (samma regel som Fas 6).
- **Ingen regression:** hela default-sviten (`pytest agent-platform/ -m "not real_inference and not
  docker_required"`) förblir grön på de **328** befintliga passen (de 3 `test_text_inference_port`-route_id-
  testerna är ett **miljö-/beroendecaveat** — `cortxt_resilient_inference`-paket ej installerat — som föregår
  Fas 8 och inte introduceras av denna spec; se Verified state). Nya tester adderas, inget befintligt rörs
  (Beslut 8 garanterar strukturellt att `Engine`/`select_strategy`/`BudgetGate`-vägar är orörda).
- **Skill-/tool-kandidat-tester (deterministiska, ingen live-skills/live-tool-eval i v1):** skill-adaptern
  testar att en `SkillManifest`-variant registreras + att dess §31-regel-led (instruktion vs executable
  helper) producerar rätt gate-utdata; tool-adaptern testar att en external-mutation-tool ger `AWAIT_OPERATOR`
  och att schema/permission-grundcheckarna fail-closed (mot `runtime/tools/gate.py`-mönstret). Ingen riktig
  skill-instruktions-live-eval / ingen riktig tool-security-scan i v1.

## Out of scope for this slice (v1)

- **Ren ML/RL-träning av operator- eller routingpolicy** — leverabel 4, explicit ut-scope (Beslut 6). v1 är
  kandidatgenerering + verifierad promotion, inte träning.
- **Full per-vertikal strategiportabilitet (#138)** — mekanismen in-scope, full per-vertikal
  strategi-ackumulering/exekvering är v1.x (Beslut 4).
- **Faktisk production-gren av en kandidat i en riktig exekveringsväg i en löpande körning** — kräver
  operatörsgodkänd plan och, för live-eval, budget (hård grind, se "Hårda gränser"). Denna spec bygger
  mekanismen och bevisar den deterministiskt; den promotar inget i en riktig produktionsväg.
- **Live model-driven skill-instruktions-eval (promotion-berättigad)** — ett separat budgetstyrt steg,
  inte v1:s deterministiska kärna (Beslut 2/5).
- **Första explicita tool's fulla §32.3-säkerhetschecklista (credential-/nätverksisolering,
  dependency-scanning)** — v1 bygger fail-closed-stubs + deterministisk del (schema/permission/timeout);
  full säkerhets-djupet är en egen avgränsad v1.x-säkerhetsleverans (Beslut 5).
- **`select_strategy` → promotbar routingpolicy** — strategi-val förblir hårdkodad strukturlogik i v1;
  att göra det till en promotbar policy är v1.x (Beslut 4).
- **Kanban/CI-integration, dashboard, operator-UI för promotion** — CLI/query-status räcker (samma linje
  som Fas 4–7: operatörsdashboard out-of-scope tills levande behov).
- **Automatisk kandidatgenerering från trajectories** (§31.1's "pattern detection → skill candidate") —
  den observerande/genererande änden är v1.x; v1 bygger att en *given* kandidat kan evalueras, promotas och
  rullas tillbaka. (Manuell/agent-proponerad kandidat är input.)
- **Beroende på Cloudflares Agent Memory-tjänst (API/beta)** — vi lånar arkitekturen (typifiering +
  verifier-checks + multi-channel), använder **inte** betatjänsten i produktion (ingen SLA, okänd prissättning;
  operatörens egen riskbedömning, Beslut 10c). Den fuserade multi-channel-retrieval-queryn är v1.x, inte v1.
- **Live Voyage-semantisk policy-eval som promotion-berättigad** — ett budgetgated steg (Beslut 10b), separat
  från v1:s deterministiska kärna (hash-embedder). Kräver operatörsgodkänd budget + att
  `CORTXT_EMBEDDING_URL/API_KEY` är operatörssatta (samma disciplin som Fas 6/7).
- **Att göra `select_strategy` (kernel) till en promotbar routingpolicy** — v1.x, se ovan; v1 rör
  `CandidatePathScore`/geometric-policy, inte `Strategy`-enumen.

## Vägen till det större målet (hur v1 är grunden, inte en återvändsgränd)

Varje v1.x-steg nedan är en **ny implementering eller registrering på ett av Beslut 9:s fem kontrakt** (eller
en ny adapter/regel på Beslut 3/10) — ingen kärnmekanism behöver rivas. Det är detta som gör v1 till
fundamentet för F0-målbilden (ADR-014/015, goal-operating-model): plattformens egna arbetsförmåga (skills,
tools, strategies, policies, memories) blir *styrt förbättringsbar* över tid.

| v1.x-steg | Vilken kontrakt/typ det pluggar in på | Varför det inte är v1 |
|---|---|---|
| **Strategiportabilitet (#138), full per-vertikal** | Ny `type="strategy"`-kandidat + `StrategyEvaluator` (Evaluator-porten) + `CandidatePathScore`-eller-`Strategy`-payload | En andra vertikalprofil som faktiskt behöver strategieval finns inte än (Beslut 4); exit kräver det inte |
| **`select_strategy` → promotbar routing-policy** | Policy-kandidat som wrapperar strategi-valet (Evaluator-porten) | Att göra kernels strategival till en promotbar policy är en ny exekveringsyta, v1.x (Beslut 4/10) |
| **Tränad operator-/routing-policy (leverabel 4)** | `type="trained_policy"` + `TrainedPolicyEvaluator`; **parametriskt-bärande** `payload_ref` (P1.4: kan bära vikt-/parameterkandidater; icke-parametriska/neurala kräver kontraktsutvidgning) | Ren ML-träning är en egen stor leverans (Beslut 6) — men v1 redan gjort *parametriska* utdata promotbara |
| **§31.1 automatisk kandidatgenerering från trajectorier** | Candidate-**ingångsdörren** (`submit_candidate`); `EvidenceClassifier`/multi-channel-retrieval (10c) matar "pattern detection"-steget | Genereringsänden är v1.x; v1 gör att en *given* kandidat (vem som än föreslår den) klarar verifierad promotion |
| **Drift-monitor / online-feedback (rollback vid driftregression)** | Lagret ovanpå den aktiva-pekaren (aktiva policy-versionen är redan versionerad + rullbar) | v1 rullar tillbaka *manuellt/kod-gat*; automatisk drift-detektering och online-feedback är en separat v1.x-mekanism |
| **Multi-channel-evidence-retrieval (Agent Memory-riktig)** | Typad evidens i `CandidateRegistry`-schemat (10c) | v1 lagrar typad evidens; den fuserade flerkanals-queryn (fulltext/fact-key/raw/vector/HyDE) är v1.x |
| **Live Voyage-semantisk promotion-berättigad eval** | `EmbeddingPort` som drop-in-embedder i `Evaluator` (10b) | Budgetgated steg, separat från deterministisk kärna |

**Vad som ALDRIG förändras över dessa steg** (de icke-delegerbara garantierna som verifieras i v1 och skyddas
av varje efterföljande fas): ingen kandidat promotar sig själv (regelbasen är okrossbar, Beslut 3/9); inget
experiment förstör den verifierade operativa vägen (rollback + prefix-verifierad promotion, Beslut 7/8);
promotion kräver alltid verifierad evidens (EvidenceClassifier-verifier-checks, Beslut 10c); operatorn
behåller mandatet över allt med extern effekt/credential/irreversibelt (Beslut 3/§31/§32).

### V01-close-out (Kimi-rekommendationer inkorporerade, operatörens direktiv "knyt ihop säcken")

Fas 8 är den **sista fasen i v0.1**. Kimi-rekommendationer (2026-08-18) för att göra V01 till en sammanhållen
helhet (inte sju isolerade PR:ar) adopteras här som explicita V01-close-out-deliverables som hänger på Fas 8:

1. **Samlad `V01-exit-report.md`** (`docs/superpowers/V01-exit-report.md`): listar varje fas (0–8), dess
   exit-kriterium, bevis (commit-hash + testresultat + N=3-körningar) och caveats. Utan detta är V01 en
   commit-historia, inte en produkt — prioriteras i V01-slutet.
2. **Evidens-continuitet Fas 5/6/7 → 8:** en enda "evidence-registry"-vy (JSON/SQLite-export) som visar alla
   fasers N=3-exit-bevis — så V01 läses som en plattform, inte isolerade faser.
3. **Integrationspunkt Supervisor → aktiv policy:** dokumentera (och lämpligen stubba) att
   `Supervisor` (Fas 4) läser aktiv policy via `learning.active_policy()` vid session-start — så den
   versionerade policyn är synlig för dispatch (inte bara internt i `score_path`).
4. **Integrationspunkt ToolGate → tool-kandidat:** dokumentera var en framtida promotad tool-version ersätter
   `ToolGate` (Fas 3), även om implementationen är en stub i v1.
5. **N=3-gröna exit-körningar:** exit-beviset körs i tre konsekutiva gröna omgångar (samma N=3-mönster som
   Fas 5/6/7), inte en enda körning.

Dessa close-out-punkter tillhör Fas 8-avslutningen / den omedelbara V01-färdigställningen och noteras här som
en medveten del av "knyta ihop säcken" — utan att de läggs på Fas 8:s deterministiska kärna (de är
dokumentation + integrationsnoteringar + en samlad rapport).

## Hårda gränser (icke-delegerbara mänskliga gatear — gäller implementeraren, planen och review-grinden)

- **Vad som faktiskt promotas till produktion i en riktig körning är ett operatörsbeslut.** De deterministiska
  testerna bevisar att *mekanismen* kan promota; att *köra* en promotion som påverkar en riktig exekveringsväg
  (eller live-skill-eval) kräver operatörsgodkänd plan + budget (om live).
- **Merge/commit-till-huvudgren och deploy är operatörsbeslut** — denna spec committas på en egen branch
  (`spec/fas8-controlled-learning-loop`), och producerad implementation dispatchas till Hermes, granskas
  (efter operatörens önskemål, inte på eget start) och mergas endast efter operatörsgodkännande.
- **Självapproval av spec/plan är förbjudet** (§28). Ingen agent/modell godkänner sin egen spec eller plan.
- **Extern effekt, credential, producerad deploy, oåterkallelig skrivning** — alltid operatörsgrind.
- **Voyage-credentials och eventuell live-eval-budget** — `CORTXT_EMBEDDING_URL/API_KEY` sätts av operatören,
  ALDRIG av en agent (Fas 6-disciplin, §27#10); en live Voyage-eval som påverkar promotion är ett operatörs-
  godkänt budgetsteg (Beslut 10b). Varje siffra (kostnad, tak) skrivs bara efter verifiering mot primärkälla.
- **Inga riktiga resurser (GPU, molntjänst, kontokrediter) spenderas av denna spec** — om en framtida
  live-eval körs, gäller Fas 7-disciplinen: verifiera claims mot primärkälla, skriv ingen gissad siffra, och
  en tydlig kostnadsram som operatören godkänner innan något spenderas.
- **Oberoende granskning (Kimi) per operatörens direktiv 2026-08-18:** BÅDE denna design-spec och den
  efterföljande TDD-planen skickas till Kimi för oberoende granskning **innan** TDD-planen skrivs respektive
  innan operatörsinspektion/exekvering. Producenten äger rework (KRÄVER → hash-bind → re-review tills GODKÄND
  eller max rundor). Detta är en explicit operatörsbegärd gate, inte rutinmässig Kimi-användning (sparsamma
  Kimi-anrop; en granskning per artefakt).

## Byggarbete = dispatch

Som §28-kravet och `docs/agents`-reglerna: implementationskod skrivs inte direkt av denna
orchestrator-session om det kan undvikas — den **dispatchas till Hermes** (via befintlig Hermes Kanban /
manuell dispatch-adapter) efter att operatorn godkänt planen (TDD). Specifikationens artefakt (denna fil) är
det som denna session levererar, committat och redo för operatörsgranskning.
