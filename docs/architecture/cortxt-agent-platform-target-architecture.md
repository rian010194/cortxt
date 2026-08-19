# Cortxt Agent Platform — målarkitektur

Status: proposed target architecture  
Authority: architectural proposal; does not override the current operating model  
Date: 2026-08-12 (original)  
Last updated: 2026-08-17  
Owner: Rikard  
Review trigger: before implementation scope is approved and whenever a major platform boundary changes

> Cortxt ska utvecklas från ett kontrollplan som huvudsakligen styr externa
> agentmotorer till en egen, leverantörsneutral agentplattform. Plattformen ska
> äga agentens tillstånd, reasoning, rekursion, minne, verifiering och
> livscykel. Modeller, inferencekapacitet och externa körmotorer ska förbli
> utbytbara resurser.

## Dokumentets roll

Detta dokument beskriver den långsiktiga målbilden och en stegvis väg dit. Det
är inte en beskrivning av vad som är produktionsverifierat idag.

Vid konflikt gäller dokumentationsordningen nedan (ADR-016 planerade en
`docs/authority-map` för detta, men den punkten i ADR-016:s Validation-lista
är fortfarande ogjord — `docs/README.md` finns inte i repot). Framför allt:

- `docs/agents/current-operating-model.md` beskriver dagens verifierade väg;
- `docs/architecture/dispatch-contract.md` är fortsatt normativt för dispatch,
  run identity och result envelope;
- `docs/architecture/runtime-and-evaluation-harness.md` är fortsatt normativt
  för isolering och utvärdering;
- detta dokument beskriver vart arkitekturen ska utvecklas.

## 1. Sammanfattning

Cortxt ska inte kasta bort dagens kontrollplan. Systemet ska kompletteras med
den agentiska kärna som hittills huvudsakligen har tillhandahållits av Hermes,
Pi och andra externa agentharness.

Målprodukten består av:

1. ett kontrollplan för mandat, policy, budget, workflow och godkännanden;
2. en egen supervisor för mål, sessionslivscykel och koordinering;
3. en egen agentruntime för coding, research och andra agentprofiler;
4. en reasoning kernel med flera valbara strategier;
5. en egen RLM-motor för rekursiv problemlösning över extern kontext;
6. ett geometriskt reasoning-lager med explicit problem- och relationsmodell;
7. en inference gateway som kan använda både egenhostade och externa modeller;
8. en isolerad execution runtime för verktyg och kod;
9. ett oberoende evaluation- och evidenslager;
10. versionsstyrda vertical packages för domänspecifika förmågor.

Hermes koordinerande roll används under migrationen som adapter, fallback och
benchmark och ersätts stegvis av Cortxt Supervisor (§24.1). Hermes, Pi och
Codex som kodningsmotorer är däremot permanenta parallella routingval enligt
ADR-019 (2026-08-16) — de ersätts inte, oavsett hur Cortxt Agent Platform
utvecklas (se §22.3/§24.2).

## 2. Produktvision

Cortxt Agent Platform ska vara ett agentiskt operativsystem för långvarigt,
spårbart och verifierbart kunskaps- och kodarbete.

Plattformens differentierande tes är:

> Reasoning kan behandlas som transformationer av ett explicit, dynamiskt
> problemrum. Rekursiv inference utforskar problemrummet, medan verifiering och
> evidens avgör vilka banor som håller.

Coding Agent är den första kompletta applikationen av plattformen, inte den
slutliga produktgränsen. Samma kärna ska senare kunna bära research,
arkitekturarbete, dokumentanalys och vertikala verksamhetsflöden.

## 3. Designmål

### 3.1 Funktionella mål

- Lösa avgränsade koduppgifter utan Hermes eller Pi.
- Köra research- och analysuppgifter över material som överstiger en modells
  context window.
- Skapa, pausa, återuppta och avbryta långvariga agentsessioner.
- Dela upp arbete rekursivt med hårda tak för djup, grenar, tid och kostnad.
- Representera hypoteser, evidens, motsägelser och öppna frågor explicit.
- Välja modell och inferenceprovider utan att förändra reasoning-kärnan.
- Verifiera resultat med deterministiska tester, oberoende modeller och
  mänskliga beslutspunkter.
- Lära från verifierade trajectories utan att produktionsbeteendet ändras
  tyst eller oåterkalleligt.

### 3.2 Kvalitetsmål

- Leverantörsneutralitet.
- Återupptagbarhet efter process- eller klientavbrott.
- Förklarbar routing och mätbar reasoning-strategi.
- Fail-closed vid policy-, budget- eller isoleringsfel.
- Inga externa sidoeffekter utan uttryckligt mandat.
- Ingen lagring av privat chain-of-thought.
- Reproducerbara evals och versionslåsta resultat.
- Minsta nödvändiga behörighet för varje agent och verktyg.

### 3.3 Icke-mål för första produktgenerationen

- Att träna en egen generell grundmodell.
- Att skriva en egen CUDA-baserad inference engine.
- Att konkurrera som global GPU-marknadsplats.
- Obegränsad självmodifiering eller rekursion.
- Att ersätta GitHub som dagens kanoniska task record innan ett separat beslut.
- Att automatisera bort operatörens mandat över irreversibla beslut.

## 4. Stabil begreppsmodell

| Begrepp | Ansvar |
| --- | --- |
| Control Plane | Äger scope, policy, workflow state, budgetram, evidens och operatörsgrindar. |
| Agent Platform | Hela Cortxts agentiska exekveringssystem under kontrollplanet. |
| Supervisor | Äger mål, sessionslivscykel, delegering, beroenden, återhämtning och koordinering. |
| Agent Runtime | Kör en agentsession och förvaltar agentloop, context, tools och session state. |
| Agent Profile | Versionsstyrd konfiguration av roll, operatorer, verktyg, behörighet, minne, modellpolicy och verifiering. |
| Reasoning Kernel | Väljer reasoning-strategi och nästa tillåtna transformation av Problem State. |
| Problem State | Explicit och beständigt tillstånd för mål, claims, hypoteser, evidens, motsägelser och öppna frågor. |
| Reasoning Graph | Typad graf som representerar objekten och relationerna i Problem State. |
| Reasoning Strategy | Algoritm för hur problemrummet utforskas, exempelvis direct, recursive eller geometric. |
| Reasoning Operator | En avgränsad transformation, exempelvis decompose, challenge eller integrate. |
| RLM Engine | Utför rekursiv dekomposition, context inspection, child calls och syntes inom budget. |
| Inference Gateway | Leverantörsneutral gräns för model invocations, routing, usage och fel. |
| Inference Provider | Tjänst eller lokal endpoint som kör en modell, exempelvis InferX eller egenhostad vLLM. |
| Agent Harness | Programlager runt en modell för tools, context, memory och agentloop. Cortxt Agent Runtime är målbildens primära harness. |
| Execution Runtime | Isolerad miljö där shell, kod och andra verktyg faktiskt körs. |
| Evaluation Harness | Oberoende lager för assertions, graders, jämförelser och verdicts. |
| Vertical Package | Domänpaket med workflows, scheman, instruktioner, fixtures och evals. |
| Trajectory | Strukturerad följd av tillstånd, beslut, actions och verifierade utfall; inte privat chain-of-thought. |

## 5. Målarkitektur

```text
Operator / API / UI
        |
        v
CONTROL PLANE
scope | policy | workflow | budget | approval | evidence
        |
        v
CORTXT SUPERVISOR
goals | sessions | dependencies | child runs | recovery
        |
        v
AGENT RUNTIME
agent loop | context | profiles | tool admission | persistence
        |
        +--------------------+
        |                    |
        v                    v
REASONING KERNEL       EXECUTION RUNTIME
Problem State          sandbox | files | shell
RLM                    browser | external tools
Geometric reasoning
verification planning
        |
        v
INFERENCE GATEWAY
local models | external providers | routing | usage
        |
        v
EVALUATION HARNESS
tests | graders | adversarial verification | evidence
        |
        v
CONTROL PLANE / OPERATOR GATE
```

### 5.1 Ansvarsregel

Modellen får föreslå nästa reasoning-step eller action. Den komponent som äger
auktoritativ state måste validera och verkställa förslaget.

Exempel:

- modellen föreslår att ett underproblem skapas;
- Reasoning Kernel kontrollerar reasoning-budgeten;
- Supervisor skapar child run och identitet;
- Execution Runtime upprätthåller behörighet och isolering;
- Control Plane stoppar externa eller irreversibla effekter vid grind.

## 6. Control Plane

Det befintliga kontrollplanet behålls. Det ansvarar fortsatt för:

- kanoniskt scope och acceptance criteria;
- dataklass, riskklass och policyversion;
- route eligibility;
- total budget och hårda ceilings;
- claim, `run_id` och workflow state;
- operatörsgodkännanden;
- evidens- och resultatreferenser;
- beslut om merge, deploy, publicering och Done.

Kontrollplanet ska inte innehålla domänreasoning eller modellberoende
agentlogik.

## 7. Cortxt Supervisor

Supervisor ersätter stegvis Hermes koordinerande ansvar.

### 7.1 Ansvar

- ta emot ett godkänt dispatch request;
- skapa eller återuppta en root session;
- tilldela agent profile och reasoning policy;
- skapa och övervaka child sessions;
- fördela delbudget utan att höja totalbudgeten;
- hantera beroenden och join-punkter;
- ge querybar status och heartbeat;
- utföra cancellation och timeout;
- återhämta sessioner efter processavbrott;
- integrera terminala delresultat;
- producera ett fullständigt result envelope.

### 7.2 Supervisor state machine

```text
ADMITTED
  -> FRAMING
  -> READY_TO_REASON
  -> REASONING
  -> EXECUTING
  -> INTEGRATING
  -> VERIFYING
  -> WAITING_FOR_OPERATOR | SUCCEEDED | BLOCKED | FAILED
```

Varje övergång ska vara explicit, versionsstyrd och möjlig att läsa tillbaka.

### 7.3 Child runs

Varje child run ska ha:

- eget `child_run_id`;
- samma `issue_id` och root `run_id`;
- avgränsat syfte och output schema;
- tilldelad delbudget;
- relevant context reference, inte okontrollerad kopia av hela parent context;
- maximalt rekursionsdjup;
- querybar status;
- terminalt strukturerat resultat.

### 7.4 Statusmappning mot result envelope

Supervisorns state machine (§7.2) och dispatch-kontraktets normativa
result-envelope-status använder inte samma vokabulär. Mappningen:

| Supervisor state / händelse | Result envelope status |
| --- | --- |
| ADMITTED … VERIFYING, WAITING_FOR_OPERATOR | inget envelope ännu (icke-terminalt) |
| SUCCEEDED | `succeeded` |
| BLOCKED | `blocked` |
| FAILED | `failed` |
| timeout | `timed_out` |
| budgettak nått | `budget_exceeded` |
| cancellation | `cancelled` |
| child status `lost` (Fas 4, §27 #4) | root `blocked` med reason som pekar till förlorat barn |

Envelopen i §19.2 utökas inte av denna tabell — dispatch-kontraktet är
normativt och ändras bara via separat godkännande (§19.1). Verifierat mot
Fas 4-koden (final-fix-rapport, Fix 1): Supervisor v0.1 mappar i praktiken
timeout till `blocked` med reason, inte till ett eget `timed_out`-fält.
Målbilden bör lyfta `timed_out` och `budget_exceeded` till förstaklassiga
terminalorsaker i en senare fas.

## 8. Agent Runtime

Agent Runtime är Cortxts egna agent harness. Den kompletterar Pi, Hermes och
Codex som ett permanent parallellt routingval för kodningsuppgifter (ADR-019,
se §22.3/§24.2) — den ersätter dem inte.

### 8.1 Gemensam runtime

Coding, research och coordinator ska inte vara separata tekniska produkter.
De är profiler på samma runtime:

```yaml
agent_profile:
  id: coding-v1
  reasoning_strategies: [direct, recursive, geometric]
  operator_set: coding-core-v1
  tools: [repository_search, file_read, patch, shell, tests, diff]
  permissions: bounded-workspace-write
  memory_policy: session-plus-run-state
  model_policy: coding-balanced-v1
  verification_policy: tests-plus-independent-review-v1
```

### 8.2 Runtimeansvar

- agentloop och turhantering;
- prompt- och context assembly;
- tool discovery och tool admission;
- model invocation genom Inference Gateway;
- context compaction;
- session persistence och resume;
- structured output;
- trajectory events;
- koppling till Supervisor och Execution Runtime.

Runtime får inte själv godkänna externa sidoeffekter eller utöka budget.

## 9. Problem State och Reasoning Graph

Problem State är den centrala domänmodellen för reasoning.

```text
ProblemState
|- goal
|- constraints
|- concepts
|- claims
|- hypotheses
|- evidence
|- assumptions
|- contradictions
|- perspectives
|- unresolved_questions
|- candidate_conclusions
|- reasoning_frontier
|- verification_state
`- termination_state
```

### 9.1 Nodtyper

- `goal`
- `constraint`
- `concept`
- `claim`
- `hypothesis`
- `evidence`
- `assumption`
- `contradiction`
- `question`
- `candidate_conclusion`

### 9.2 Relationstyper

- `supports`
- `contradicts`
- `depends_on`
- `causes`
- `derived_from`
- `generalizes`
- `specializes`
- `analogous_to`
- `alternative_to`
- `observed_from`

### 9.3 Minsta metadata

Varje nod och relation ska kunna bära:

- stabil identitet;
- provenance;
- confidence och confidence source;
- evidensreferenser;
- dataklass;
- skapande `reasoning_step_id`;
- timestamps;
- status och version.

### 9.4 Lagringsprincip

Första implementationen ska använda enkla, portabla format och en vanlig
databas. En separat grafdatabas införs först när mätbara query- eller
skalningsbehov motiverar den.

## 10. Reasoning Kernel

Reasoning Kernel väljer hur Problem State ska utvecklas. Den får inte reduceras
till en enda stor systemprompt.

### 10.1 Strategier

- `direct`: ett begränsat model invocation och verifiering;
- `retrieval_augmented`: hämta riktad extern kontext före svar;
- `tool_augmented`: använd verktyg för att observera eller förändra miljön;
- `recursive`: dela upp, lös och integrera rekursivt;
- `geometric`: utforska problemrummets struktur och alternativa banor;
- `recursive_geometric`: geometriskt val av rekursiva grenar;
- `adversarial`: försök falsifiera aktuell kandidat;
- `ensemble`: jämför oberoende lösningskandidater;
- `human_escalation`: stoppa och begär ett materiellt beslut.

### 10.2 Operatorer

| Operator | Syfte |
| --- | --- |
| `inspect` | Läs en avgränsad del av extern kontext. |
| `decompose` | Skapa beroende eller oberoende underproblem. |
| `abstract` | Sök en gemensam princip bakom flera observationer. |
| `concretize` | Testa en abstrakt idé mot ett konkret fall. |
| `change_perspective` | Modellera problemet från en annan position. |
| `find_contradiction` | Sök inkompatibla claims, constraints eller evidens. |
| `find_missing_dimension` | Sök en variabel eller relation som problemmodellen saknar. |
| `generate_counterexample` | Försök falsifiera en hypotes. |
| `compare_paths` | Jämför alternativa reasoning trajectories. |
| `integrate` | Sammanför kompatibla delresultat. |
| `escape_attractor` | Tvinga fram en oberoende alternativ modell eller bana. |
| `verify` | Kör lämpliga verifierare mot en kandidat. |

### 10.3 Reasoning step

Privat chain-of-thought ska inte lagras. Systemet lagrar strukturerade och
granskningsbara tillståndsförändringar:

```yaml
reasoning_step_id: step-00042
operator: generate_counterexample
input_refs: [hypothesis-12, evidence-7]
output_refs: [counterexample-3, contradiction-4]
decision_summary: "Hypotesen testades mot ett gränsfall."
confidence_before: 0.78
confidence_after: 0.51
model_invocation_ref: invocation-81
evidence_refs: [artifact://run/source-14]
```

## 11. RLM Engine

RLM Engine behandlar stora kontexter som extern, adresserbar data och använder
rekursiva child calls som en programmerbar operation.

### 11.1 Grundloop

```text
inspect problem and context references
  -> determine whether decomposition adds value
  -> create bounded subproblems
  -> allocate branch budgets
  -> execute child runs
  -> integrate structured results
  -> challenge integrated candidate
  -> stop, recurse or escalate
```

### 11.2 Hårda gränser

Varje RLM-körning ska ha:

- `max_depth`;
- `max_branches_per_node`;
- `max_total_children`;
- `max_model_invocations`;
- `max_context_reads`;
- `max_runtime_seconds`;
- `max_cost`;
- `max_output_size`;
- explicit stop policy.

### 11.3 Stoppvillkor

- acceptance criteria är verifierade;
- förväntad informationsvinst är under tröskel;
- återstående budget räcker inte till en meningsfull gren;
- alla relevanta grenar är integrerade;
- en materiell motsägelse kräver operatör eller ny evidens;
- policy eller säkerhetsgräns stoppar fortsatt arbete.

### 11.4 Dataklass vid context-ingest

Inläst kontext ärver och behåller sin dataklass. Aggregerad kontext i Problem
State klassas som den högsta ingående dataklassen. Klassen ska vara synlig för
Tool Gateway och provider eligibility (ADR-016 dataklass→gate) vid varje
efterföljande anrop som konsumerar den aggregerade kontexten. Detta bygger på
dataklass-metadata som redan krävs per nod och relation (§9.3).

## 12. Geometric Reasoning Engine

Geometric reasoning v1 är en operationell systemmodell, inte ett påstående om
att informationsgeometri är en etablerad fysisk naturkraft.

### 12.1 Arbetsdefinition

Reasoning behandlas som banor och transformationer i ett strukturerat
problemrum:

- noder och relationer ger explicit grafstruktur;
- embeddings ger mjuk semantisk närhet;
- mål och constraints påverkar vilka riktningar som är relevanta;
- motsägelser skapar mätbar spänning;
- verifiering förändrar confidence och frontier;
- stabila slutsatsfamiljer kan identifieras som attractorer.

### 12.2 Geometriska mått i första versionen

- semantisk närhet mellan noder;
- grafavstånd till mål eller acceptance criterion;
- evidenstäckning;
- motsägelsegrad;
- centralitet;
- novelty;
- stabilitet under perspektivbyte;
- antal återbesök till samma slutsatsfamilj;
- path diversity;
- information gain per reasoning step.

### 12.3 Attractor-detektering

En kandidat attractor föreligger när systemet återkommer till samma
slutsatsfamilj trots en eller flera av följande interventioner:

- ny evidens;
- perspektivbyte;
- explicit motexempel;
- oberoende child run;
- förändrad branch order.

Detta ska utlösa `escape_attractor`, starkare adversarial verification eller
mänsklig eskalering. Det ska inte automatiskt tolkas som att slutsatsen är sann.

### 12.4 Första sökfunktionen

En kandidatbana kan rankas med en versionsstyrd funktion baserad på:

```text
expected_information_gain
+ goal_relevance
+ evidence_coverage
+ path_novelty
- contradiction_risk
- expected_cost
- policy_risk
```

Vikter och trösklar är policydata och ska utvärderas mot fixtures, inte döljas
i prompttext.

## 13. Coding Agent

Coding Agent är den första fullständiga vertikalen på Agent Runtime.

### 13.1 Förmågor

- läsa repositoryinstruktioner;
- kartlägga filer, symboler och beroenden;
- formulera och testa felhypoteser;
- läsa och ändra endast godkänt workspace;
- skapa minimala patchar;
- köra tester och statiska kontroller;
- inspektera diff mot scope;
- upptäcka scope expansion;
- producera artifacts, evidence och result envelope;
- återuppta arbetet efter kontrollerat avbrott.

### 13.2 Kodspecifika operatorer

- `locate_ownership`
- `build_dependency_map`
- `form_bug_hypothesis`
- `find_minimal_reproduction`
- `compare_contract_to_implementation`
- `propose_minimal_patch`
- `analyze_blast_radius`
- `generate_regression_test`
- `inspect_diff_against_scope`
- `falsify_fix`

### 13.3 Säkerhetsgräns

Coding Agent kör inte shell eller kod direkt i agentprocessen. Den begär actions
genom Tool Gateway och Execution Runtime, som validerar workspace, kommando,
nätverk, timeout och artifact policy.

## 14. Inference Gateway och egen inference

### 14.1 Inference Gateway

Inference Gateway ska byggas tidigt och ägas av Cortxt. Den normaliserar:

- provider och exakt modellversion;
- messages och structured outputs;
- tool calling;
- reasoning- och outputinställningar där de finns;
- input-, output-, cache- och reasoning tokens;
- latency, timeout och cancellations;
- kostnad och cost confidence;
- retries och felklassificering;
- dataklass och provider eligibility.

Agentkärnan ska endast bero på ett internt `InferencePort`.

### 14.2 Inference providers

Följande kan existera parallellt bakom gatewayn:

- externa endpoints, exempelvis InferX;
- Prime Inference eller andra tjänster;
- OpenAI-kompatibla gateways;
- lokala modeller;
- Cortxt-hostad vLLM eller SGLang;
- framtida egen servinginfrastruktur.

### 14.3 Vägen till en egen inferenceprodukt

1. Eget gateway-API och egna kontrakt.
2. En extern provideradapter för bootstrap.
3. En lokal eller hyrd GPU med öppen modell.
4. Modellpool, liveness och lastbalansering.
5. Caching, batching och kapacitetsmätning.
6. Multi-tenant-isolering och usage accounting.
7. Kundexponerat inference-API först efter separat produkt- och säkerhetsbeslut.

En egen inferenceprodukt innebär inte att Cortxt måste skriva en egen låg-nivå
inference engine i första generationen.

## 15. Tool Gateway och Execution Runtime

Tool Gateway är den enda vägen från Agent Runtime till externa handlingar.

Execution Runtime äger:

- sandbox och containerpolicy;
- writable scope;
- nätverks- och egresspolicy;
- process limits;
- command timeout;
- credential injection utan persistence;
- artifact capture;
- logg- och usagegränser;
- deterministic cleanup.

Reasoning och exekvering ska vara separata failure domains. En persistent
reasoning-session får inte i sig innebära persistent operativsystemsbehörighet.

## 16. Memory och context

### 16.1 Minnestyper

| Minne | Scope | Exempel |
| --- | --- | --- |
| Turn context | En modellturn | Utvald input till nästa invocation. |
| Session state | En agentsession | Problem State, frontier och aktiva handles. |
| Run memory | Root run och barn | Strukturerade delresultat och artifacts. |
| Project memory | Ett repository/projekt | Godkända konventioner och verifierade fakta. |
| Skill memory | En capabilityversion | Procedurer, schemas och verktygsinstruktioner. |
| Evidence memory | Tvärgående utvärdering | Aggregerade, innehållsminimerade utfall. |

### 16.2 Context assembly

Agent Runtime ska sätta samman nästa modellinput från:

- aktuellt mål;
- relevant del av Problem State;
- vald reasoning operation;
- explicit hämtad extern kontext;
- tool schemas;
- policy- och output constraints.

Hela sessionhistoriken ska inte okontrollerat återges vid varje invocation.

### 16.3 Compaction

Compaction får sammanfatta konversation och rå observation, men får inte ersätta
auktoritativa strukturer såsom:

- mål och constraints;
- öppna motsägelser;
- budget;
- run identity;
- evidensreferenser;
- operator- och verifieringsstatus.

## 17. Verification och Evaluation

Verifiering är en separat fas och ibland en separat aktör.

Prioritetsordning:

1. deterministiska assertions och tester;
2. schema- och policyvalidering;
3. property- och metamorphic tests;
4. adversarial reasoning och counterexamples;
5. oberoende modellgranskning;
6. domänexpert eller operatör när beslutet kräver det.

### 17.1 Reasoning-mått

- task success;
- first-attempt success;
- evidenstäckning;
- olösta materiella motsägelser;
- confidence calibration;
- branch efficiency;
- information gain per invocation;
- attractor escapes som förbättrade resultatet;
- total kostnad per verifierad arbetsenhet;
- operatörsingripanden;
- stabilitet mellan repetitioner.

### 17.2 Jämförelsekrav

En ny reasoning-strategi ska jämföras mot minst en enklare baseline med samma:

- task fixture;
- modell och provider när strategin isoleras;
- tool- och nätverksgränser;
- totalbudget;
- verifieringsmetod;
- startstate.

## 18. Learning och självförbättring

Cortxt ska kunna förbättras från verifierade trajectories, men produktion får
inte självmodifieras utan kontroll.

### 18.1 Två loopar

```text
Inre loop:
agenten löser aktuell uppgift inom låst policy och budget

Yttre loop:
evalsystemet analyserar flera verifierade trajectories och skapar en kandidat
till ändrad strategy, operator, prompt, memory rule eller agent profile
```

### 18.2 Promotion

Varje förbättringskandidat ska:

1. ha provenance och motivering;
2. vara en separat versionslåst artifact;
3. testas mot regression- och säkerhetsfixtures;
4. jämföras mot aktiv baseline;
5. kunna rullas tillbaka;
6. godkännas enligt policy innan produktion.

### 18.3 När träning blir relevant

Modellträning övervägs när det finns tillräckligt med kvalitetsmärkta data för
ett avgränsat mål, exempelvis:

- val av nästa reasoning operator;
- branch ranking;
- context selection;
- stop prediction;
- verifieringsbehov;
- attractor escape policy.

Träning av en generell grundmodell är inte ett beroende för RLM eller
geometric reasoning v1.

## 19. Kontrakt

### 19.1 Utökad dispatch request

Målkontraktet behöver på sikt kompletteras med:

```yaml
agent_profile: coding-v1
reasoning_policy:
  allowed_strategies: [direct, recursive, geometric]
  max_reasoning_steps: 30
  max_depth: 2
  max_branches_per_node: 3
  max_total_children: 6
  max_model_invocations: 20
  max_context_reads: 30
verification_policy: tests-plus-adversarial-v1
memory_policy: run-scoped-v1
```

Det befintliga dispatch-kontraktet ändras inte förrän schema, kompatibilitet och
migration har godkänts separat.

### 19.2 Utökat result envelope

Se §7.4 för mappningen mellan Supervisorns interna state machine och
statusfälten nedan.

```yaml
agent:
  platform_version: cortxt-agent-v0.1
  profile: coding-v1
reasoning:
  strategy_versions: [recursive-v1, geometric-v1]
  steps_used: 18
  branches_explored: 4
  max_depth_reached: 2
  model_invocations: 11
  contradictions_found: 3
  contradictions_resolved: 2
  termination_reason: acceptance_criteria_verified
  trajectory_ref: artifact://run/trajectory.json
children:
  - child_run_id: child-01
    status: succeeded
verification:
  policy: tests-plus-adversarial-v1
  verdict: passed
```

## 20. Säkerhetsmodell

### 20.1 Grundregler

- Modellen är aldrig en policy authority.
- Reasoning Kernel får inte ge sig själv större budget.
- Supervisor får inte skapa barn utanför root runens mandat.
- Tool Gateway avslår actions utanför verktygs- och dataklasspolicy.
- Execution Runtime använder minsta möjliga behörighet.
- Reviewer får inte mergea, deploya eller sätta Done.
- Learning loop får inte tyst ändra aktiv produktionskonfiguration.
- Privat chain-of-thought, credentials och kundinnehåll får inte hamna i
  evidensregistret.

### 20.2 Prompt injection och främmande instruktioner

Extern text, repositories, webbsidor och dokument betraktas som data. De kan
inte ändra systempolicy eller ge nya behörigheter. Tool actions kräver separat
admission även när instruktionen kommer från material som agenten analyserar.

### 20.3 Rekursionsrisk

Rekursion får aldrig vara den enda stoppmekanismen. Hårda ceilings verkställs
utanför modellen och gäller root samt samtliga barn tillsammans som mål.

Mekanismen skiljer sig från målet: i v0.1 (detacherade processer, Fas 4)
verkställs detta genom disjunkt förallokerad delbudget per barn plus
post-hoc rollover vid integrering, inte genom realtidsaggregering av
kostnad/tokens över processgränser. Realtidsaggregering över detacherade
barn är ett öppet beslut (§27).

## 21. Observability och evidens

Varje run ska kunna följas utan att exponera privat reasoning:

- root och child run identity;
- state transitions;
- reasoning strategy och operatornamn;
- model invocation metadata;
- tool actions och resultatstatus;
- budgetförbrukning;
- artifacts och hashvärden;
- verifieringsutfall;
- termination reason;
- operator gates och beslut.

Telemetry och product/customer payloads ska hållas separata.

## 22. Migration från dagens system

Migrationen följer ett strangler pattern. Gammal och ny exekveringsväg kan
samexistera bakom kontrollplanets routeval.

```text
Approved Dispatch
       |
       v
Routing policy
  |                              |
  v                              v
Hermes/Pi                     Cortxt Agent Platform
kodning: permanent routingval   target path
(ADR-019); koordinering: migreras (§24.1)
  |                              |
  +-------> common result envelope and evaluation
```

### 22.1 Vad som behålls

- kontrollplan och operatörsgrindar;
- dispatch- och resultkontraktens grundprinciper;
- run identity och claims;
- runtime-/sandboxkrav;
- evaluation harness;
- vertical packages;
- leverantörsneutral routing;
- evidence registry;
- befintliga fixtures och verifierade arbetssätt.

### 22.2 Vad som ersätts stegvis

| Nuvarande ansvar | Målkomponent |
| --- | --- |
| Hermes koordinering | Cortxt Supervisor |
| Hermes agentprofiler | Cortxt Agent Profiles |
| Extern agent-memory | Cortxt Problem State och Memory |
| Ad hoc agentdekomposition | Cortxt RLM Engine |
| Modellbunden tool loop | Cortxt Agent Runtime + Tool Gateway |

Pi coding harness stod tidigare i denna tabell som en ersättningsrad. Per
ADR-019 (2026-08-16) är det inte längre korrekt: Cortxt Agent Runtime +
Coding Profile är ett **tillägg** till, inte en ersättning för, Pi. Se 22.3.

### 22.3 Övergångs- och permanenta roller

Hermes koordinerande roll, Prime Agent och andra icke-kodningsmotorer kan
under migrationen användas som:

- benchmark;
- fallback;
- kompatibilitetsadapter;
- inspirations- eller referensimplementation;
- experimentväg för att testa hypoteser innan egen implementation är klar.

**Kodningsmotorer (Pi, Hermes, Codex, framtida GitHub Copilot) är undantagna
från detta migrationsmönster per ADR-019.** De är permanenta routingval i
Cortxts kodningspolicy, jämte Cortxts egen Coding Agent (Fas 3 och framåt).
Ersättningskriterierna i 24.2 gäller inte längre kodningsmotorer.

Ingen extern agentruntime ska vara ett dolt beroende i Cortxt Agent Core.

## 23. Implementationstrappa

Trappans numrering är en planeringsordning, inte ett bevisat byggförlopp.
Enligt ADR-017 landade delar av Reasoning Kernel, RLM Engine och Geometric
Engine i main redan före Fas 2 (PR #113, 2026-08-14), med stubbad inference.
Detta ändrar inte målbilden men läsaren ska inte anta att fasnumret speglar
faktisk landningsordning i koden.

Från och med Fas 4 och framåt gäller: ett exit-kriterium räknas som uppfyllt
först vid minst tre (N=3) konsekutiva gröna körningar av dess bevis, inte ett
engångsbevis. Detta gäller inte retroaktivt Fas 0–3.

### Fas 0 — Arkitektur och baseline

Leverabler:

- godkänd begreppsmodell;
- beslut om package boundary;
- en fixturekorpus dimensionerad mot en strategi×mått-täckningsmatris (inte
  ett fast intervall) — minimum per cell eller en motiverad tom-cell-policy
  ska framgå av matrisen, inte antas från "10–20 fixtures";
- baseline från dagens Hermes/Pi-väg;
- initiala schemas för Agent State och Model Invocation.

Exit:

- vi kan mäta kvalitet, kostnad, ledtid och reviewfynd för dagens väg;
- målarkitekturen motsäger inte normativa säkerhetskontrakt;
- strategi×mått-täckningsmatrisen existerar och är godkänd.

### Fas 1 — Inference Gateway

Leverabler:

- internt `InferencePort`;
- en extern provideradapter;
- structured output;
- usage, cost och timeout;
- fixtures och contract tests.

Exit:

- samma agentkod kan byta mellan minst två godkända endpoints utan ändring i
  reasoning-kärnan.

### Fas 2 — Agent Runtime v0.1

Leverabler:

- sessionsstate;
- enkel agentloop;
- tool admission;
- persistence och resume;
- result envelope;
- read-only research profile.

Exit:

- en researchfixture kan lösas utan Hermes.

### Fas 3 — Coding Agent v0.1

Leverabler:

- repository discovery;
- read/search/patch/test/diff tools;
- Tool Gateway v0.1: schema-, permission- och effektklassvalidering (§32.1)
  före varje tool-anrop — ersätter direkta funktionsanrop (t.ex. dagens
  `apply_patch`-anrop direkt från Supervisor);
- execution sandbox;
- bounded write policy;
- kodspecifika operatorer.

Exit:

- en enkel kodfixture kan lösas och verifieras utan Pi eller Hermes;
- workspace-, nätverks- och budgettak är maskinellt bevisade;
- ingen tool-exekvering sker utan att passera Tool Gateway.

Detta exit-kriterium bevisar kapacitet, inte en avsikt att göra Pi eller
Hermes onödiga — de förblir permanenta routingval per ADR-019.

### Fas 4 — Supervisor v0.1

Leverabler:

- root och child sessions;
- querybar status;
- heartbeat;
- cancellation;
- budgetallokering;
- recovery;
- dependency joins.

Exit:

- två avgränsade child runs kan genomföras och integreras utan Hermes.

v0.1 exponerar status och kontroll via CLI/query (operator-CLI, querybar
status); integration mot operatörens faktiska ytor (Hermes desktop primärt,
Buzz som komplement, per current-operating-model) är inte bevisad och krävs
innan Supervisor kan ta huvudvägsansvar (jfr §24.1). Live heartbeat till en
mänsklig operatör i UI/dashboard-form är explicit out of scope för v0.1.

### Fas 5 — RLM v1

Leverabler:

- extern context store;
- bounded recursion;
- context slicing;
- branch budget;
- structured synthesis;
- RLM-specifika evals;
- skalning av Supervisor från Fas 4:s v0.1-tak (2 barn, djup 1, se §25) till
  det djup och den branch-budget RLM kräver (jfr §19.1: max_depth 2,
  max_total_children 6) — detta är en egen leverabel, inte ett antagande.

Exit:

- RLM slår enklare baseline med en i förväg definierad marginal på minst en
  långkontextklass inom godkänd total kostnad.
- Om detta inte uppnås efter tre (N=3) oberoende utvärderingsrundor: RLM-
  spåret nedgraderas, genom operatörsbeslut, till experimentell/diagnostisk
  strategi bakom Reasoning Kernel med enklare baseline som default. Se
  "Nedtrappningsvägar" nedan för konsekvensen för Fas 6.

### Fas 6 — Geometric Reasoning v1

Leverabler:

- Problem State schema;
- reasoning graph;
- embeddings (källa: se §27, öppet och blockerande beslut);
- första operatoruppsättningen;
- contradiction- och attractor-detektering;
- path scoring;
- trajectory viewer eller rapport.

Exit:

- vilket/vilka mått i §12.2 som är beslutande (till skillnad från
  diagnostiska) är avgjort innan detta exit-kriterium utvärderas (§27 #8);
- strategin ger mätbar förbättring på det/de beslutande måtten utan
  regression över säkerhetsfixtures;
- om Fas 5 nedtrappats enligt ovan: `recursive_geometric` (§10.1) får
  fortsätta utvecklas men blir inte default-strategi förrän RLM-spåret är
  återupprättat.

### Fas 7 — Egenhostad inference

Leverabler:

- en öppen modell på lokal eller hyrd GPU;
- liveness och capacity metrics;
- samma InferencePort;
- jämförbar cost/quality telemetry.

Exit:

- minst en godkänd task class kan köras utan extern inferenceprovider.

### Fas 8 — Kontrollerad learning loop

Leverabler:

- versionerade förbättringskandidater;
- offline eval och promotion flow;
- rollback;
- eventuellt tränad operator- eller routingpolicy;
- Skill Platform-promotion (§31) och Tool Platform-evolution (§32.3) som
  fungerande byggd pipeline, inte bara en beskriven modell.

Exit:

- ingen automatisk ändring kan nå produktion utan verifierad promotion.

### Nedtrappningsvägar

Denna sektion beskriver konsekvensen om ett fas-experiment inte levererar
mätbar nytta — §28-invarianten ("Ett misslyckat experiment får inte förstöra
den verifierade operativa vägen") skyddar produktionen men säger inget om
själva fasens eller de beroende fasernas öde. Konkret:

- Fas 5 (RLM): se nedtrappningsvillkoret i Fas 5-exit ovan.
- Fas 6 (Geometric Reasoning): om Fas 6:s eget exit-kriterium inte uppnås
  efter tre oberoende utvärderingsrundor, beslutar operatören om Geometric
  Reasoning nedgraderas till diagnostiskt lager (mätvärden loggas, men
  påverkar inte routing) eller pausas helt. §2:s tes om reasoning som
  transformationer i ett problemrum kvarstår som produktvision oavsett utfall
  — plattformens övriga lager (Supervisor, Agent Runtime, RLM, Inference
  Gateway) är inte beroende av att Geometric Reasoning lyckas.
- Nedtrappning är alltid ett operatörsbeslut, aldrig automatik — i linje med
  §28 ("Modellen föreslår; auktoritativ kod validerar och verkställer").

## 24. Ersättningskriterier

### 24.1 Hermes kan lämna huvudvägen när

- Supervisor kan skapa, pausa, återuppta och avbryta sessions;
- child runs har querybar status och heartbeat;
- budget, timeout och recursion ceilings upprätthålls;
- beroenden och integration fungerar efter processrestart;
- operatörsgrindar och result envelope är kompletta;
- evalresultat är minst likvärdiga för migrerade task classes.

### 24.2 Historisk: Pi som huvudväg (upphävd av ADR-019)

Denna sektion beskrev tidigare villkor för att Pi skulle lämna huvudvägen.
Per ADR-019 (2026-08-16) ersätts inte Pi — Pi, Hermes och Codex är permanenta
routingval jämte Cortxts egen Coding Agent. Villkoren nedan står kvar som
kvalitetsgolv för när Cortxts Coding Agent är ett **giltigt routingval** för
en uppgiftsklass, inte som ersättningskriterier:

- Coding Agent kan orientera sig i repositoryt;
- Execution Runtime upprätthåller skriv- och nätverksgränser;
- patch, test och diff fungerar reproducerbart;
- scope expansion upptäcks och stoppar körningen;
- artifacts, cost och cleanup är verifierade;
- säkerhets- och kodfixtures passerar.

### 24.3 Extern inference kan lämna en task class när

- en egenhostad modell uppfyller dess quality floor;
- latency, tillgänglighet och total kostnad är accepterade;
- dataskydd och drift är verifierade;
- fallback fortfarande finns för kontrollerad återhämtning.

## 25. Första produktinkrementet

Cortxt Agent Platform v0.1 bör vara medvetet litet:

```text
En användare skickar en avgränsad research- eller koduppgift
  -> Control Plane skapar godkänd dispatch
  -> Cortxt Agent Runtime skapar Problem State
  -> Reasoning Kernel väljer direct eller bounded recursive
  -> Agenten använder godkända read/search/tool operations
  -> Codingprofilen kan göra en begränsad patch och köra tester
  -> Verification skapar verdict
  -> Result envelope och trajectory reference returneras
  -> operatören beslutar eventuell merge/Done
```

Begränsningar:

- högst rekursionsdjup 1;
- högst två child runs;
- en skrivbar workspace;
- inga deployments eller publiceringar;
- en extern inferenceadapter;
- en enkel persistent databas;
- ingen automatisk harness refinement.

## 26. Initial package boundary

**Historisk:** Denna paketgräns ersattes av §33 (ADR-016, Decision 1). Den
behålls här för spårbarhet, inte som aktuell auktoritet.

Den nya koden introduceras utan omedelbar flytt av befintliga filer:

```text
agent-platform/
|- supervisor/
|- runtime/
|- reasoning/
|  |- kernel/
|  |- recursive/
|  `- geometric/
|- state/
|- memory/
|- tools/
|- inference/
`- profiles/

adapters/
|- inference/
|- hermes/
|- pi/
`- prime-agent/

harness/
|- execution/
`- evaluation/
```

Packagegränsen ska provas i en vertikal implementation innan större
repositoryomstrukturering beslutas.

## 27. Öppna beslut

Följande ska avgöras innan respektive implementation:

1. Implementationsspråk för Supervisor och Agent Runtime.
2. Processmodell för root och child sessions.
3. Första persistensformatet för Problem State och trajectories.
4. ~~Första execution sandbox på Windows och Linux.~~ Delvis löst (verifierat
   2026-08-16, Kimi K2.7-code-review av Fas 3 mot main: hela `docker_required`-
   sviten kördes live på Windows med Docker Desktop, alla 8 boundary-tester
   gröna, inklusive nätverksisolering/DNS/timeout-proberna). Docker-baserad
   execution sandbox (`agent-platform/runtime/execution/subprocess_sandbox.py`)
   fungerar på Windows och Linux och är CI-gated (`docker_required`-jobbet i
   `.github/workflows/ci.yml`) — OS-isoleringsfrågan A4 avsåg är löst. Kvarstår
   öppet: ingen subprocess-only-fallback finns när Docker saknas (Fas 4:s
   `sandbox_degraded`-fält förutsätter en sådan väg, men den måste byggas från
   grunden), och portabla minnes-/CPU-tak för sandboxen är fortfarande out of
   scope (assumption A10 i Fas 3-specen).
5. Vilken extern provideradapter som används som bootstrap.
6. Vilka fixtures som utgör quality floor för (a) Hermes koordinerande roll
   som ersätts av Supervisor (§24.1), och (b) Cortxt Coding Agent som giltigt
   routingval jämte Pi/Hermes/Codex (§24.2) — Pi, Hermes och Codex som
   kodningsmotorer ersätts inte per ADR-019, så "ersättning" gäller bara (a).
7. Om Agent Platform initialt ligger i detta repo eller i ett eget package med
   separat releasecykel.
8. ~~Vilka geometric metrics som är beslutande respektive endast diagnostiska.~~
   Löst (ADR-025, `docs/adr/025-geometric-reasoning-decisive-vs-diagnostic-
   metrics.md`, 2026-08-19): fem mått är beslutande (redan konsumerade av
   `score_path`/`guidance`/`AttractorDetector` — graf-avstånd till mål,
   evidenstäckning, motsägelsegrad, novelty, stability); fem förblir
   diagnostiska (semantic_closeness, centrality, revisit_ratio,
   path_diversity, information_gain) tills en ny, explicit versionerad
   policy promoverar dem. `information_gain` fick en riktig call site
   (`reasoning.geometric.apply_confidence_update`) för första gången.
9. När egenhostad inference har affärsvärde jämfört med hyrd kapacitet.
10. Embeddings-provider för Fas 6 (§12.2 semantisk närhet). InferencePort
    (§14.1) normaliserar idag inte embeddings, och ingen fas levererar det.
    Blockerande för Fas 6-start.
11. Realtidsaggregering av kostnad/token-budget över detacherade
    processgränser (§20.3) — v0.1 verkställer bara via disjunkt
    förallokering plus post-hoc rollover, inte löpande aggregering.

## 28. Arkitektoniska invariants

Följande ska förbli sant genom hela migrationen:

- Control Plane äger mandat; agenten äger inte sitt eget scope.
- Problem State och trajectories ägs av Cortxt och är portabla.
- Agent Core importerar inte Hermes, Pi, Prime Agent eller en specifik provider.
- Externa implementationer beror på Cortxts portar och kontrakt, inte tvärtom.
- Reasoning och execution är separata trust boundaries.
- Modellen föreslår; auktoritativ kod validerar och verkställer.
- Varje run och child run har stabil identitet och budget.
- Verification är skild från produktion och self-approval är förbjudet.
- Learning sker genom versionsstyrda kandidater och verifierad promotion.
- Ett misslyckat experiment får inte förstöra den verifierade operativa vägen.

## 29. Beslut som denna målbild föreslår

Följande är förslag tills de godkänts genom repositoryts beslutsprocess:

1. Cortxt bygger en egen Agent Platform inom det befintliga kontrollplanet.
2. Cortxt Agent Runtime blir på sikt primärt agent harness.
3. Cortxt Supervisor ersätter på sikt Hermes koordinerande huvudroll.
4. Cortxt Coding Agent är ett permanent tillägg till routingpolicyn för
   kodningsuppgifter, inte en ersättning för Pi/Hermes/Codex (upphävd och
   ersatt av ADR-019, 2026-08-16 — se §22.3/§24.2).
5. RLM och geometric reasoning ägs av Cortxt Agent Core.
6. Inference är en utbytbar port; egenhostad inference införs stegvis.
7. Hermes koordinerande roll och Prime Agent används under migrationen som
   adapters, fallback eller benchmark och ersätts stegvis, aldrig som dolda
   kärnberoenden. Hermes, Pi och Codex som kodningsmotorer är permanenta
   routingval (ADR-019) och migreras inte bort.
8. Dagens kontroll-, säkerhets- och evalfundament behålls.

## 30. Nästa planeringssteg

Klart (verifierat mot ADR-registret och koden):

- ADR för Agent Platform som ny bounded context (ADR-016);
- ADR för `InferencePort` och leverantörsoberoende modellgräns (ADR-016);
- ett första vertikalt slice (ADR-017);
- v0.1-schemas för Agent State, Model Invocation och Trajectory Event
  (`contracts/`, `agent-platform/state/`, `agent-platform/inference/`).

Fortfarande öppet innan nästa större beslutspaket:

- en fixturematris med dagens Hermes/Pi-baseline (fixtures finns spridda i
  repot, men ingen sammanställd matris);
- threat model för Agent Runtime, Tool Gateway och Execution Runtime (inget
  sådant dokument finns i `docs/` ännu);
- beslut om vilka befintliga backlog-items som ska ersättas eller
  omformuleras;
- ADR-016:s öppna Validation-punkt om `docs/authority-map` (se noten under
  "Dokumentets roll" ovan) är fortfarande ogjord.

Implementationen ska börja med ett vertikalt, körbart flöde och inte med en
omfattande repositoryflytt eller fullständig plattformsinfrastruktur — det
har den redan gjort (ADR-017).

## 31. Skill Platform

Skills är förstaklassobjekt i Cortxt Agent Platform. De beskriver
återanvändbara arbetsmönster och kan komponera reasoning-operatorer och tools.

En skill ska kunna innehålla:

- manifest, identitet och semantisk version;
- instruktioner och exempel;
- input- och outputschemas;
- beroenden och kompatibla agentprofiler;
- fixtures, tester och evals;
- deklarerade tools och högsta tillåtna effektklass;
- provenance, changelog och rollbackinformation;
- valfria granskade executable helpers.

### 31.1 Skill Evolution

Agenten får identifiera återkommande framgångar, misslyckanden och
reviewkorrigeringar i verifierade trajectories. Systemet kan därefter skapa en
ny skill-kandidat eller föreslå en avgränsad förbättring.

```text
trajectory observation
  -> pattern detection
  -> skill candidate
  -> sandboxed evaluation
  -> regression and safety comparison
  -> promotion decision
  -> canary/active or rejected
```

Självförbättring betyder inte att agenten själv får ge kandidaten nya
behörigheter eller tyst aktivera den. Promotion styrs av förändringens risk,
fixtures, verifierad förbättring och rollbackmöjlighet.

| Förändring | Minsta promotionregel |
| --- | --- |
| Instruktion, exempel eller källa | Eval mot fixtures och regressioner. |
| Workflow eller reasoning-operator | Jämförelse mot baseline och säkerhetsfixtures. |
| Executable helper | Sandbox, dependency review och contract tests. Om helpern är agentförfattad krävs dessutom en namngiven mänsklig operatörsgrind innan promotion. |
| Nytt tool eller ny behörighet | Separat toolgranskning och operatörsbeslut. |
| Credential, extern effekt eller policy | Alltid operatörsgrind. |

## 32. Tool Platform

Tools är typade, versionsstyrda operationer som observerar eller påverkar en
miljö. Agent Runtime anropar dem genom Tool Gateway; den anropar inte shell,
MCP, providers eller externa API:er direkt.

### 32.1 Tool contract

Ett tool ska minst deklarera:

```yaml
id: repository.run_tests
version: 1.0.0
input_schema: contract-ref
output_schema: contract-ref
effect_class: bounded_execution
filesystem: current-run-workspace
network: none
credentials: []
timeout_seconds: 600
idempotency: repeatable
artifact_policy: result-and-summary
```

Tool Gateway validerar schema, profile permission, dataklass, deklarerade
effekter, budget och runtime eligibility före exekvering.

### 32.2 Effektklasser

| Klass | Exempel | Kontroll |
| --- | --- | --- |
| `observe` | Läsa fil eller söka kod. | Read scope och dataklass. |
| `local_mutation` | Applicera patch i run workspace. | Writable scope och diffkontroll. |
| `bounded_execution` | Köra test eller build i sandbox. | Allowlist, resurser och timeout. |
| `external_mutation` | Skapa issue eller skicka meddelande. | Explicit mandat och read-back. |
| `irreversible` | Merge, deploy eller delete. | Operatörsgrind. |
| `credential` | Skapa eller rotera secret. | Separat trust-boundary-beslut. |

### 32.3 Tool Evolution

Agenten får skapa tool-kandidater med implementation, manifest, schemas,
dokumentation, tester och fixtures. Kandidaten körs i isolering och måste visa:

- korrekt schema- och felbeteende;
- permission denial för otillåtna actions;
- timeout och cancellation;
- credential- och nätverksisolering;
- output sanitization;
- deterministic cleanup;
- dependency- och säkerhetskontroll;
- regression mot aktiv toolversion.

En kandidat kan aldrig ge sig själv nya rättigheter. Nya nätverksmål,
credentials, externa mutationer och irreversibla effekter kräver uttrycklig
promotion enligt Control Plane policy.

### 32.4 Transportneutralitet

MCP, CLI, REST och browser automation är tool-adaptrar. Skills och reasoning
ska bero på Cortxts stabila tool-ID och schemas, inte på transportens eller
leverantörens egna namn.

## 33. Initial repositorystruktur

Den första icke-produktiva scaffolden är:

```text
agent-platform/
|- supervisor/
|- runtime/
|- reasoning/
|- state/
|- memory/
|- skills/
|- tools/
|- inference/
|- portability/            (byggd; motsvaras inte i §26 - historisk)
`- profiles/

adapters/
|- inference/
|- agent-runtime/
|- tools/
`- storage/

harness/                   (planerad, inte byggd ännu)
|- runtime/                (jfr §26:s "execution" - namnet i denna sektion
|                          följer runtime-and-evaluation-harness.md, rad 68)
`- evaluation/
```

Repositoryts befintliga `skills/` och `tools/` fortsätter innehålla dagens
konkreta inventory. `agent-platform/skills` och `agent-platform/tools` ska
innehålla plattformskod för registry, gateway, policy, evolution och promotion.
Ingen befintlig exekveringsväg flyttas in i scaffolden innan ett vertikalt slice
och dess kontrakt är verifierade.

`harness/runtime/` är den normativa promotion-path som
`runtime-and-evaluation-harness.md` (rad 68) beskriver — namnet ersätter §26:s
äldre `harness/execution/`.
