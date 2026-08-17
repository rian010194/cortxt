# Fas 8 — Kontrollerad learning loop — design

Status: **v1 — DESIGN-SPEC KLAR FÖR OPERATÖRSGRANSKNING.** Writer: Hermes (producer), 2026-08-18, branch
`spec/fas8-controlled-learning-loop` (grenad från `spec/fas7-self-hosted-inference`@`60b61a6`, dvs. efter
Fas 7 v1 avslutad; den lokala `main`-grenen är föråldrad / Fas 4-era och saknar `agent-platform/portability/`
från PR #135, så `-self-hosted-inference`-tip är den enda bas som innehåller allt beskrivet nuläge).

Ingen Kimi-granskning begärd (operatören har inte bett om det; denna spec följer den autonoma disciplinen —
Kimi-granskning sker ENDAST på operatörens explicita begäran).

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

### 1. Kandidattyp för v1-beviset: versionerad reasoning-policy (`CandidatePathScore`-vitketer), inte skill-version eller ny strategivariant

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

**Promotion-tolerans (medvetet konservativ):** en kandidat promotas bara om den (a) har success-rate
**≥ aktiv baselines success-rate** **och** (b) uppfyller kandidattypens specifika regel (Beslut 5) **och**
(c) inte regresserar någon befintlig säkerhetsfixture. Likhet = inte regression. Ingen "marginal-vinst
krävs för att promotas"-regel i v1 (för att undvika att fabrikera en godtycklig tröskel) — en försämring
avvisas, en förbättring/neutral promotas om regeln i övrigt är uppfylld. (Exakt om en *neutral* kandidat
bör promotas avgörs i plan-fasen; förslaget i denna spec är att neutrala **inte** auto-promotas eftersom
utbytesrisken inte motiveras av nytta — se Beslut 4.)

### 3. Promotion gate: regelstyrd automatisk grind för effektfria kandidater, operatörsgrind hårdkodad för allt med extern effekt (self-approval strukturellt omöjligt)

**Beslut:** promotion godkänns av **två oberoende lager**:

1. **Teknisk, regelstyrd grind (automatisk, auktoritativ kod):** offline eval-verdict (Beslut 2) + kandidattypens
   §31-promotion-regel. **Ingen modell/agent är inblandad i beslutet** — det är ren datalogik mot
   `EvidenceMatrix` + fixture-result. Detta uppfyller §28:s "*Modellen föreslår; auktoritativ kod validerar
   och verkställer*".
2. **Operatörsgrind (hård, icke-delegerbar)** för alla kandidatklasser där §31-tabellen kräver det: **"Ny
   behörighet, credential, extern effekt eller policy → alltid operatörsgrind"** och **"executable helper →
   namngiven mänsklig operatörsgrind"** och **"nytt tool → separat toolgranskning och operatörsbeslut"**.

**Konsekvens för v1-kandidattypens gate-konfiguration:** en effektfri **policy-parameter**-kandidat
(`CandidatePathScore`-vikter) har ingen extern effekt/credential/behörighet → dess §31-promotion-regel är
"Eval mot fixtures och regressioner" → kan **auto-promotas av den regelstyrda grinden**. En **skill**-kandidat
av typen "instruktion/exempel/källa" har också regeln "Eval mot fixtures och regressioner" → auto-gate
möjlig, men eftersom skill-eval i v1 är live-eval (budgetsteg) så begränsas skill-promotion i v1 till
**explicit planerad/demoo** och promotas aldrig tyst. En **tool**-kandidat rör alltid effektklassen
(`external_mutation`/`irreversible`/`credential` → §32.2) → **alltid operatörsgrind** (Beslut 5).

**Varför detta respekterar self-approval-förbudet (§28):** "Model proposes, authoritative code validates"
är uppfyllt eftersom (a) kandidaten *föreslås* av en agent/operatör men (b) *verkställs* enbart av kod-gaten
eller en namngiven operatör — algoritmen kan inte "vilja" promota sig själv, och kod-gaten har inget
intressekonflikt-objekt. Den regelstyrda auto-gaten är **inte** self-approval: det är en *fast, förprogrammerad
säkerhetsregel* (samma princip som `BudgetGate`s fail-closed-räkning), inte en fri-flytande agent som godkänner
sig själv.

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

### 5. Skill-promotion och Tool-evolution: byggda pipeline mot samma primitive, djup medvetet begränsat i v1

**Beslut:** §23 kräver båda som "fungerande byggd pipeline". De byggs som **kandidatadapter på samma
livscykelprimitive** — inte som två nya mekanismer:

- **Skill-promotion (§31):** `SkillCandidate`-adapter registrerar en version av en `SkillManifest`
  (återanvänder `HermesSkillAdapter`/`SkillManifest` från portability). Promotion-regeln hämtas från
  §31-tabellen per förändringstyp. v1 **domänspecifikt djup**: skill-eval i v1 är **fixture-deterministisk
  (struktur/regression) + dokumenterad live-eval som ett separat budgetstyrt steg** — ingen riktig
  modell-driven skill-instruktions-eval körs i v1 utan operatörsgodkänd budget. En skill-kandidat *kan*
  promotas automatiskt av kod-gaten (regeln tillåter det) men **v1 bevisar bara att gate-mekanismen körs**
  mot en deterministisk skill-fixture; verklig live-skill-eval-promotion är explicit v1.x/budgetsteg.
- **Tool-evolution (§32.3):** `ToolCandidate`-adapter registrerar ett tool med manifest + schemas +
  effektklass. §32.3:s candidate-checklista (schema-/felbeteende, permission denial, timeout/cancellation,
  credential-/nätverksisolering, output-sanitering, deterministic cleanup, dependency-/säkerhetskontroll,
  regression mot aktiv tool-version) implementeras som **gate-asserts**. **Effektklass-regeln från §32.2
  gör att varje tool-kandidat som rör `external_mutation`/`irreversible`/`credential` kräver operatörsgrind**
  → v1:s tool-promotion är **alltid operator-gated** (aldrig auto), och de säkerhetstunga checklistepunkterna
  (credential-/nätverksisolering, dependency-scanning) byggs som **stubs som fail-closed** plus en
  avgränsad deterministisk del (schema/permission/timeout mot befintlig `runtime/tools/gate.py`) — den fulla
  säkerhets-djupet är v1.x. Detta är ett **medvetet riskvals** (Beslut 5): full tool-security-checklista är
  en egen avgränsad säkerhetsleverans som inte ska gömmas i en "v1-promotionflow"-spec.

### 6. "Tränad operator- eller routingpolicy" (leverabel 4): explicit ut-scope för v1

**Beslut:** ren ML/RL-träning av en operator- eller routingpolicy **byggs inte i v1**. v1:s "learning" är
kandidatgenerering + verifierad promotion (§28:s mekanism), inte gradient-baserad träning. Skäl:

- Att träna en policy kräver en träningsloop, ett förlustmått, ett dataset och en separat eval/validering —
  det är en hel egen leverans som skulle förstöra Fas 8:s "liten, verifierbar livscykel" som enda mål.
- §28-invarianten "*Ett misslyckat experiment får inte förstöra den verifierade operativa vägen*" — en
  tränad policy som *ersätter* routing är en mycket större yta än en versionerad kandidat som *läggs till*.
- v1:s versionerade-parameter-kandidater (Beslut 1) är **det steg som ML-träning senare kan mata**: om en
  framtida Fas vill träna en policy, producerar den versionerade viktkandidater i EXAKT samma format som
  `CandidatePathScore`-kandidater — v1 bygger att dess utdata är promotbar, inte träningen som genererar den.

### 7. Rollback: versionerad state + aktiv-pekare i SQLite (atomär pekaråterställning)

**Beslut:** rollback är ingen separat "mekanism" — det är en **konsekvens av att state är versionerat**.
Varje kandidat är **immutabel** (manifest-hash-låst, `sha256` som `SkillRegistry.manifest_hashes()` redan
gör). En **aktiv-pekare** pekar på den aktuella promotade versionen. Promotion = **atomär transaktion** i
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
(`draft | eval_pending | promoted | rolled_back | rejected`) + aktiv-pekare-tabell. `rollback()` är en ren
transaktion. Testas deterministiskt (se Testing strategy).

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

## Components (nya/ändrade moduler)

**Ny modul** `agent-platform/learning/` (motsvarar "evolution och promotion"-ansvaret som §33 reserverar
för `agent-platform/skills`/`tools` men som idag inte existerar):

- `candidate.py` — typ-agnostisk `Candidate`-datamodell: `{id, type (policy|skill|tool), version,
  manifest_hash (sha256), status, payload-ref, proposed_at, promoted_by, promoted_at, rolled_back_at}`.
  Immutabel.
- `registry.py` — `CandidateRegistry`: SQLite-persisterad, `_ensure_table`, nycklad på
  `type@name@version`, aktiv-pekare-tabell (`active_candidates(type, active_version)`), deterministisk
  export/hash (samma principer som `SkillRegistry`).
- `evaluator.py` — kör `EvidenceMatrix`: för varje kandidatkörning mot fixture-set, samlar success/cost/latency
  + no-regression-flagga mot aktiv baseline. Återanvänder fixture-generatorerna från
  `agent-platform/harness/eval/` (t.ex. `run_task_class_eval`-liknande per-fixture-verdict, men
  multi-kandidat).
- `promotion_gate.py` — `PromotionGate.evaluate(matrix, candidate_type, rules) -> Verdict` där Verdict ∈
  `{PROMOTE, AWAIT_OPERATOR, REJECT}`. Ren, deterministisk, testbar funktion. `AWAIT_OPERATOR` hårdkodas för
  effektklasser (`external_mutation/irreversible/credential`, tool-kandidat, executavle helper per §31).
- `rollback.py` — `rollback(type)` → atomär pekaråterställning + audit-rad. Ren transaktionslogik.
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
  -> CandidateRegistry.add(Candidate(type=policy|skill|tool, version, payload, manifest_hash))  [draft|eval_pending]
      -> Evaluator.kör EvidenceMatrix                            (fixture-set + active_baseline, multi-kandidat)
          -> PromotionGate.evaluate(matrix, type, rules)         (ren funktion)
              -> AWAIT_OPERATOR  (tool / external-effekt / credential / executable-helper, §31-tabell)
              -> PROMOTE         (effektfri policy/skill, eval-verdict + no-regression + rule)
              -> REJECT          (försämrad / regressande / rule-fail)
  Promotion (PROMOTE):
      -> SQLite-transaktion: spara new-active-version, promoted_from=prev, promoted_at (atomär)
  Rollback (operatör eller kod-gate vid diff som flaggar regression i drift):
      -> SQLite-transaktion: flytta aktiv-pekare tillbaka till promoted_from (atomär, audit-rad)

Produktionsväg (ostörd tills en kandidat promotas):
  score_path(...) -> policy = learning.active_policy(...) or CandidatePathScore()   (default oförändrad)
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
    oavsett eval-resultat (fail-closed).
  - `Evaluator` multi-kandidat: EvidenceMatrix med ≥2 kandidater + baseline; no-regression-flagga korrekt.
  - `rollback`: promotion sedan rollback återställer aktiv-pekare + skriver audit-rad; idempotent (rollback
    av redan rullad-back är no-op eller explicit fel, inte korruption).
  - **Exit-test (produktion ostörd):** medan en kandidat evalueras/promotas/rullas tillbaka, returnerar
    befintliga `Engine.solve`/`score_path`-anrop EXAKT samma resultat som innan (default-policy oförändrad
    tills en kandidat faktiskt promotas, och även då är den nya policyn prefix-verifierad). Assertion mot
    geometriska fixtures (samma mönster som `tests/reasoning/geometric/`).
  - **Dubbel-riktnings-exit-tests:** (a) en medvetet *bättre* policy-kandidat kan promotas (mekanismen
    fungerar); (b) en medvetet *försämrad* policy-kandidat avvisas och produktionen berörs aldrig. Båda
    deterministiska, 0 inferensanrop.
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

## Hårda gränser (icke-delegerbara mänskliga gatear — gäller implementeraren, planen och review-grinden)

- **Vad som faktiskt promotas till produktion i en riktig körning är ett operatörsbeslut.** De deterministiska
  testerna bevisar att *mekanismen* kan promota; att *köra* en promotion som påverkar en riktig exekveringsväg
  (eller live-skill-eval) kräver operatörsgodkänd plan + budget (om live).
- **Merge/commit-till-huvudgren och deploy är operatörsbeslut** — denna spec committas på en egen branch
  (`spec/fas8-controlled-learning-loop`), och producerad implementation dispatchas till Hermes, granskas
  (efter operatörens önskemål, inte på eget start) och mergas endast efter operatörsgodkännande.
- **Självapproval av spec/plan är förbjudet** (§28). Ingen agent/modell godkänner sin egen spec eller plan.
- **Extern effekt, credential, producerad deploy, oåterkallelig skrivning** — alltid operatörsgrind.
- **Inga riktiga resurser (GPU, molntjänst, kontokrediter) spenderas av denna spec** — om en framtida
  live-eval körs, gäller Fas 7-disciplinen: verifiera claims mot primärkälla, skriv ingen gissad siffra, och
  en tydlig kostnadsram som operatören godkänner innan något spenderas.

## Byggarbete = dispatch

Som §28-kravet och `docs/agents`-reglerna: implementationskod skrivs inte direkt av denna
orchestrator-session om det kan undvikas — den **dispatchas till Hermes** (via befintlig Hermes Kanban /
manuell dispatch-adapter) efter att operatorn godkänt planen (TDD). Specifikationens artefakt (denna fil) är
det som denna session levererar, committat och redo för operatörsgranskning.
