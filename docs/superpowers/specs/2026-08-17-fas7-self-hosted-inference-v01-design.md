# Fas 7 — Egenhostad inference — design

Status: **DRAFT v3 — väntar på operatörsgranskning.** Writer: Claude (orchestrator session),
2026-08-17, branch `spec/fas7-self-hosted-inference` (grenad från `ci/adr-doc-currency-gate-clean`,
senaste commit `3eda624`). **Revideringshistorik 2026-08-17:** (v1) InferX som förslag →
avvisat av operatören (opak GPU-prissättning + Fas 6:s idle-kostnadsincident). (v2) Ett
lokal-RTX-4060-först-plus-Vast.ai-fallback-förslag → **operatören avvisade det lokala steget
explicit** ("vill inte använda min egen GPU"). (v3, denna version) **Vast.ai är den enda
deployment-vägen**, valt över RunPod eftersom operatören prioriterar pris ($0.20/hr L4-klass)
över RunPod:s bekvämare färdigmall och accepterar det manuella vLLM/Docker-konfigurationsarbetet.
Beslut 2, 3 och 5 justerade i konsekvens. Ingen Kimi-granskning begärd ännu (kostnadskänsligt per
operatörsinstruktion — begärs bara om operatören explicit ber om det). Inga kodändringar i
produktionsvägar; bara denna spec.
Authority: architectural proposal for one bounded vertical slice; does not override
`docs/agents/current-operating-model.md`.
Related: `docs/architecture/cortxt-agent-platform-target-architecture.md` §14.1–14.3 (Inference
Gateway, providers, väg till egen inferenceprodukt), §23 (Fas 7 — Egenhostad inference, leverabler
+ exit), §24.3 (när extern inference kan lämna en task class), §27 öppen fråga **#9** (när
egenhostad inference har affärsvärde jämfört med hyrd kapacitet — denna spec besvarar den för v1:s
scope), §28 (arkitektoniska invariants); `docs/adr/016-agent-platform-bounded-context-and-inference-port.md`
(InferencePort-kontraktet, provider-assurance-principen, InferX-restriktionen till L0);
`agent-platform/runtime/text_inference_port.py` och `agent-platform/runtime/embedding_port.py`
(de två existerande instanserna av samma fail-closed-mönster som denna spec återanvänder som
tredje instans); `docs/superpowers/specs/2026-08-17-fas6-geometric-reasoning-v01-design.md` och
`docs/superpowers/plans/2026-08-17-fas6-exit-criterion-checklist.md` (föregående fas, format-mall
och den InferX/Voyage-baslinje denna spec jämför mot).

## Why this spec is scoped the way it is

§23 kräver fyra leverabler för Fas 7: (1) en öppen modell på lokal eller hyrd GPU, (2) liveness- och
capacity-metrics, (3) samma `InferencePort`, (4) jämförbar cost/quality-telemetri mot befintliga
externa providers. Exit: minst en godkänd task class kan köras helt utan extern inferenceprovider.

Den centrala observationen som formar hela denna spec: **leverabel (3) är redan uppfylld av
existerande kod, inte något som ska byggas.** `TextInferencePort`
(`agent-platform/runtime/text_inference_port.py`) är redan providerneutral — den pratar med
*vilken* OpenAI-kompatibel `/chat/completions`-endpoint som helst via `CORTXT_INFERENCE_URL`/
`CORTXT_INFERENCE_API_KEY` (konfigurerbara env-namn via konstruktorn), fail-closed på två oberoende
grindar (BudgetGate + `inference/provider_policy.py`, ADR-016) innan något nätverksanrop. En
egenhostad modell blir därmed **en tredje instans av samma port-instansiering** — exakt samma
mönster som `embedding_port.py` (Fas 6) redan bevisade för `/embeddings`. Fas 7 introducerar därför
**ingen ny arkitektur och ingen ny portklass**; den introducerar en ny *deployment* (en självvald,
självhostad modell bakom en OpenAI-kompatibel endpoint) och en ny *provider-evidence*-rad för den
routen.

Detta håller specen liten och i linje med `docs/architecture`:s invariant "Inference är en
utbytbar port; egenhostad inference införs stegvis" (§29.6) och §14.3:s väg ("En lokal eller hyrd
GPU med öppen modell" är steg 3 av 7, inte en omskrivning av gatewayn).

## Verified current state

| Komponent | Nuläge | Relevans för Fas 7 |
|---|---|---|
| `TextInferencePort` | Providerneutral, konfigurerbara env-namn, fail-closed på BudgetGate + provider_policy. Används idag mot InferX. | Återanvänds oförändrad — pekas om mot en ny route via en andra instans (nya env-namn), inte en ny klass. |
| `EmbeddingPort` | Samma mönster för `/embeddings`. Fas 6: Voyage AI vald (extern), InferX-embeddings 404:ade. | Bevisar mönstret redan generaliserar till en andra endpoint-typ — precedent för att generalisera till en tredje deployment (egenhostad chat). |
| `BudgetGate` | Systemhanterad SQLite-spend-tabell (`fas2a_inference_spend`), `route_id`/`selected_route_id`-kolumner redan finns. Fail-closed: attempt-rad skrivs FÖRE nätverksanrop. | Redan route-medveten — kräver ingen ny kolumn eller tabell för grundläggande cost-jämförelse (Beslut 6). |
| `inference/provider_policy.py` (ADR-016) | Deterministisk dataklass→gate. L0 kräver bara `approved`. L1 kräver + ZDR + kryptering. L2 kräver + DPA/subprocessors/hosting-region/incident + **avslutad** oberoende assurance. | Avgör vilken task class som är laglig att köra på den nya routen (Beslut 3). |
| ADR-016 Decision 4 | InferX är **experimentell, inte godkänd för konfidentiellt material**; endast dataklass **L0** tillåten hos InferX tills avslutad assurance. | Samma logik (assurance-gate per infrastruktur, inte per modell) appliceras i Beslut 3 på Vast.ai — leverantörsbyte ändrar inte principen. |
| Fas 6-precedent (hyrd GPU, eget modellval) | 2026-08-17: Cortxt deployade **Qwen3-Embedding-0.6B** som en dedikerad InferX-instans (`/m3/v1`, egen modellval, inte InferX:s färdiga katalogmodell) innan Voyage valdes av kostnadsskäl. | Bevisar att "hyr en GPU, deploya din egen öppna modell"-mönstret redan är prövat i detta projekt — bara leverantören byts (InferX → Vast.ai, Beslut 1). |
| §27 #9 (öppen fråga: affärsvärde egenhostad vs hyrd) | Obesvarad i arkitekturdokumentet. | Besvaras av denna spec för v1:s scope (Beslut 1): hyrd GPU via Vast.ai, inte lokal hårdvara (operatören avvisade det) och inte InferX (opak prissättning). |
| Marknadsjämförelse GPU-hyra (research 2026-08-17) | InferX saknar transparent $/hr för GPU-hyra (bara per-token för katalogmodeller); RunPod har billigast bekvämlighet (färdig vLLM-mall, äkta scale-to-zero) men högre pris; Vast.ai billigast rakt av ($0.20/hr L4-klass) men manuell vLLM/Docker-konfiguration. | Operatören valde Vast.ai (pris > bekvämlighet, manuellt arbete inget hinder) framför både InferX och RunPod (Beslut 1). |

## Purpose

Leverera Fas 7:s fyra §23-leverabler som en **liten, avgränsad vertikal slice** som återanvänder
befintlig fail-closed-infrastruktur maximalt: en egenhostad öppen modell bakom en OpenAI-kompatibel
endpoint, konsumerad av en andra `TextInferencePort`-instans (ingen ny portkod); en enkel
liveness/capacity-probe; en task-class-eval som bevisar att minst en L0-klassad uppgift kan köras
utan extern provider; och en cost/quality-jämförelse mot den befintliga InferX-baslinjen från Fas
5, återanvänd via samma harness-mönster (N=3, binär success-jämförelse).

Detta följer samma process som Fas 2–6: spec → (valfri) oberoende review → plan (TDD) → exekvering.
Ingen implementationskod, ingen GPU-provisionering och inga riktiga inferensanrop görs innan
operatören godkänt den specifika planen och kostnaden (hård grind, se "Blockerade delar").

## Scope decisions

### 1. Deployment-väg: Vast.ai (hyrd), inte operatörens egen GPU (operatörsbeslut 2026-08-17)

**Beslut (operatörsgodkänt, ersätter tidigare InferX-rekommendation och det tidigare
lokal-först-utkastet):** operatören vill uttryckligen **inte** använda sin egen maskin (RTX 4060)
för detta — inget lokalt steg. En marknadsjämförelse (RunPod, Vast.ai, Lambda Cloud, Together.ai,
Fireworks.ai, Modal, InferX; se research-underlag 2026-08-17) visade att InferX **inte** har
transparent $/hr-prissättning för GPU-hyra (bara per-token för katalogmodeller) och att Fas 6
redan fick ett konkret idle-kostnadsproblem där en InferX-instans inte auto-decommissionerades
snabbt nog. Mellan de återstående alternativen valde operatören **Vast.ai** framför **RunPod**:
RunPod:s Serverless är bekvämare (färdig vLLM-mall, äkta scale-to-zero) men dyrare per GPU-timme;
Vast.ai är billigare ($0.20/hr för en L4-klass GPU, källa: research-underlaget) men kräver manuell
vLLM/Docker-konfiguration — operatören har uttryckligen prioriterat pris över bekvämlighet och
bekräftat att det manuella arbetet inte är ett hinder.

**Varför inte InferX:** InferX:s prissättning för GPU-hyra är opak (ingen självbetjänad
$/hr-sida hittades), och Fas 6:s idle-kostnadsincident visar att auto-decommissioning där inte kan
litas på. Att fortsätta på samma leverantör "för att det redan finns credentials" vore att
optimera för bekvämlighet över kostnadskontroll.

**Varför inte lokal RTX 4060:** ett tidigare utkast av denna spec föreslog lokal körning som ett
gratis första steg (tekniskt fullt möjligt — Q4-kvantiserad 7–8B ryms på 8 GB vRAM). Operatören
avvisade det explicit: Vast.ai är den enda deployment-vägen i denna spec, inte en fallback efter
ett lokalt steg.

**Hård gräns (icke-delegerbar, se "Blockerade delar"):** den faktiska GPU-provisioneringen på
Vast.ai kräver operatörens explicita godkännande av kostnadsram innan den sker — detta beslut
fastställer *vilken* leverantör, inte att pengar spenderas nu.

### 2. Modellval: liten öppen instruct-modell, budgetmedveten

**Rekommendation:** en öppen instruct-modell i 7–8B-klassen (t.ex. Qwen3-8B-Instruct) — ryms
bekvämt på en L4-klass GPU (Beslut 1) utan aggressiv kvantisering, vilket ger bättre kvalitet än
en lokal Q4-begränsad körning skulle gjort. Qwen-familjen är redan bevisad i detta projekt
(Qwen3-Coder-Next-FP8 via InferX i Fas 5, Qwen3-Embedding-0.6B/Qwen3-35B testade i Fas 6) — att
stanna i samma familj minskar operativ nyhet, oavsett att serveringsvägen nu är Vast.ai istället
för InferX.

**Varför liten, inte stor:** Fas 6 fick ett konkret kostnadsvarningsincident (35B-instansen kostade
$0.066/min och auto-decommissionerades inte snabbt nog, "onödig kostnad" enligt sessionsloggen).
En mindre modell (a) håller GPU-hyran låg under bevisfasen, (b) räcker för en avgränsad,
lågkomplex task class (Beslut 4), (c) kan skalas upp senare om exit-kriteriet visar att kvalitet
är den begränsande faktorn, inte kostnad.

**Hård gräns:** exakt modell + instansstorlek + faktisk provisionering är ett operatörsgodkänt
kostnadsbeslut (se "Blockerade delar"), inte fastlåst av denna spec. Operatören har låg
förkunskap om modellval — denna rekommendation är en startpunkt att godkänna eller justera, inte
ett fastslaget faktum.

### 3. Dataklass-tak: L0, ärvt av ADR-016 Decision 4:s princip — inte "trivialt ZDR"

**Beslut:** eftersom Vast.ai är en tredje parts marketplace-infrastruktur (data lämnar
operatörens maskin och transiterar en Vast.ai-värd) är `zero_data_retention` **inte** trivialt
sant — samma princip som redan begränsade InferX (ADR-016 Decision 4: experimentell
infrastruktur, ej godkänd för konfidentiellt material, endast dataklass **L0** tills avslutad
oberoende assurance) appliceras nu på Vast.ai. Utan publicerad DPA/subprocessors/hosting-region/
incident-process/avslutad oberoende assurance för den specifika Vast.ai-värden som vinner budet
är `inference/provider_policy.py`s `_REQUIREMENTS[DataClass.L1]` (`zero_data_retention` +
`encryption` som explicita, verifierade flaggor) inte uppfyllt.

En `ProviderEvidence`-rad konstrueras per anrop (samma mönster som `TextInferencePort`/
`EmbeddingPort` redan använder — ingen central registry existerar, se `provider_policy_cli.py`):
`provider_id="cortxt-selfhosted-vastai-<host>-<model>"`, `approved=True` (operatören godkänner
deploymenten), `zero_data_retention=False` tills verifierat annorlunda, övriga L1+-flaggor
`False`.

**Varför detta är rätt, inte en genväg:** ADR-016:s dataklass→gate-princip appliceras ärligt per
faktisk infrastruktur — en marketplace-GPU har inte automatiskt samma assurance-egenskaper bara
för att Cortxt äger modellvalet. Policyn kringgås inte bara för att leverantören bytt namn från
InferX till Vast.ai.

**Konsekvens:** detta bestämmer vilken task class som är laglig (Beslut 4) — måste vara L0, direkt
jämförbar med Fas 5/6:s befintliga L0-baserade InferX/Voyage-baslinjer.

### 4. Task class för exit-kriteriet: en avgränsad, L0-klassad, redan existerande fixture-klass

**Rekommendation:** återanvänd en av Fas 5/6:s redan byggda, offentliga/syntetiska fixture-set
(t.ex. Fas 5:s RLM-baseline-eval-fixtures eller en enklare avgränsad summerings-/klassificerings-
task) snarare än att uppfinna en ny task class. Kravet "en godkänd task class" tolkas operativt
som: en **namngiven, avgränsad uppgiftsklass** (inte "allt") som körs end-to-end genom
`TextInferencePort` pekad på den självhostade routen, med en explicit, mätbar success-definition
(binär per instans, N=3-rundor à la Fas 5:s harness-mönster).

**"Utan extern inferenceprovider" — operationell definition:** för en fullständig eval-runda visar
`BudgetGate`s spend-tabell (`fas2a_inference_spend`, `route_id`-kolumnen) **noll**
`attempt_started`-rader mot någon extern-provider-`route_id` (InferX-katalog, Voyage) — 100 % av
anropen i rundan går mot den självhostade routen. Detta är maskinellt verifierbart mot en existerande
tabell, inte en subjektiv bedömning.

**Varför inte en ny task class:** YAGNI — att uppfinna en ny uppgiftsklass för att bevisa
portabilitet vore att testa två saker samtidigt (ny uppgift + ny inferensväg). Att återanvända en
redan verifierad L0-fixture isolerar variabeln till "vilken modell svarar", vilket är exakt vad
cost/quality-jämförelsen (Beslut 6) behöver.

### 5. Liveness och capacity metrics: vLLM:s inbyggda ytor, inget nytt protokoll

**Beslut:**
- **Liveness** = periodisk `GET` mot serverns hälso-endpoint (vLLM exponerar `/health` inbyggt),
  normaliserad till `{alive: bool, checked_at: timestamp}`.
- **Capacity** = GPU-vRAM-utnyttjande (%), kö-djup/inflight-requests, tokens/sekund — skrapat från
  vLLM:s inbyggda Prometheus-`/metrics`-endpoint (ships out of the box).

**Varför vLLM specifikt:** en Vast.ai-hyrd GPU (Beslut 1, typiskt L4/4090-klass) tål vLLM utan
kvantiseringskompromisser, till skillnad från en tänkt lokal 8 GB-körning. vLLM är redan namngiven
i §14.2/§14.3 som målserveringsstack ("Cortxt-hostad vLLM eller SGLang") och är den enda öppna
server-lösning i arkitekturdokumentet med inbyggda liveness+metrics-ytor — minimerar ny kod till
en tunn skrapnings-/normaliseringsfunktion, inte ett eget metrics-system.

**Determinism/testbarhet (samma split-mönster som `embedding_port.py`):** en ren
funktion (`parse_liveness(metrics_payload: dict) -> LivenessSample`) separeras från den enda
I/O-gränsen (HTTP-skrapningen). Den rena funktionen testas deterministiskt mot fixtures av
vLLM:s dokumenterade metrics-svarsform; skrapningen testas separat med samma
felklassificeringsmönster som `_EmbeddingHttpAdapter` (timeout/HTTP-status/ogiltigt-svar →
strukturerade utfall, aldrig tyst fabricerad data).

**Lagring:** ny SQLite-tabell i samma databas som `BudgetGate` redan äger
(`fas2a_selfhosted_liveness`: `timestamp`, `route_id`, `alive`, `vram_pct`, `queue_depth`,
`tokens_per_sec`) — återanvänder existerande DB-anslutningsmönster, ingen ny persistenskälla.

### 6. Cost/quality-telemetri: återanvänd BudgetGate:s befintliga route-kolumner, ingen ny schema

**Beslut:** `BudgetGate.record()` har redan `route_id`/`selected_route_id`-kolumner. Den självhostade
routen får ett eget `route_id` (t.ex. `"selfhosted-qwen3-8b"`), skilt från InferX:s
katalog-`route_id` (`"l0-default"` idag) och Voyage:s embedding-route. Kostnadsjämförelse blir
därmed en ren `SELECT ... GROUP BY route_id`-fråga mot en tabell som redan finns — **ingen ny
kolumn, ingen ny tabell krävs för kostnadssidan.**

**Kvalitetssidan:** återanvänd Fas 5:s N=3-baseline-eval-harness-mönster (binär
success-per-rond-jämförelse, samma fixture-set) — kör **samma** task-class-fixtures (Beslut 4)
genom (a) den självhostade routen och (b) den befintliga InferX/Voyage-baslinjen, jämför
success-rate + latency + $/lyckad-runda. Detta är den äpplen-mot-äpplen-jämförelse
dispatch-uppdraget efterfrågade: samma fixture, samma harness, olika `route_id` — inte en ny
eval-metodik.

**Varför inte en ny telemetriyta:** BudgetGate:s tabell är redan route-medveten av precis den här
anledningen (byggd under Fas 2a för att jämföra kostnad över routes). Att bygga en parallell
telemetriyta vore duplicering utan nytt behov.

### 7. Samma InferencePort — återanvänds oförändrad, ingen ny portklass

**Beslut:** `TextInferencePort.__init__` accepterar redan `model`, `base_url_env`, `api_key_env`
som konstruktorparametrar. Den självhostade routen instansieras som **en andra
`TextInferencePort`-instans** pekad på nya env-namn (t.ex. `CORTXT_SELFHOSTED_URL`/
`CORTXT_SELFHOSTED_API_KEY`), fail-closed på samma BudgetGate + samma `provider_policy`-modul.
**Noll ändringar i `text_inference_port.py` krävs.**

**Varför detta är leverabeln, inte ett hinder för den:** §23:s krav är "samma InferencePort" —
det bevisas precis genom att **inte** skriva ny portkod, samma sätt Fas 6:s `embedding_port.py`
bevisade portmönstrets generaliserbarhet till en ny endpoint-typ utan att röra
`text_inference_port.py`. Detta är den tredje instansen av samma mönster (text via InferX,
embeddings via Voyage, text via egenhostad lokal/Vast.ai-serving) — exakt det §16.1-tesen om en
utbytbar port med många adapters förutsäger.

## Components (nya/ändrade moduler)

Inga ändringar i `agent-platform/runtime/text_inference_port.py` eller
`agent-platform/inference/provider_policy.py`. Nya moduler:

- `agent-platform/runtime/selfhosted_liveness.py` — `parse_liveness(metrics_payload) ->
  LivenessSample` (ren funktion) + en tunn `_LivenessHttpProbe`-I/O-wrapper (samma split som
  `_EmbeddingHttpAdapter`).
- Task-runner/eval-skript (plan-nivå-detalj, exakt plats avgörs i TDD-planen) som återanvänder
  Fas 5:s N=3-baseline-eval-harness pekad på den nya `TextInferencePort`-instansen och en existerande
  L0-fixture-klass (Beslut 4).
- Ny SQLite-tabell `fas2a_selfhosted_liveness` i samma DB som `BudgetGate` (Beslut 5) — skapas via
  samma `_ensure_table`-mönster, ingen ny databasfil.
- Provider-evidence för den nya routen konstrueras inline vid anropsplatsen (samma mönster som
  idag — ingen central config-fil för `ProviderEvidence`, se `provider_policy_cli.py`).

## Data flow

```
Egenhostad modell (vLLM, OpenAI-kompatibel /chat/completions + /health + /metrics)
  på hyrd Vast.ai-GPU (Beslut 1, operatörsgodkänd)
  → TextInferencePort(model=..., base_url_env="CORTXT_SELFHOSTED_URL", ...)   (Beslut 7, oförändrad kod)
      → provider_policy.evaluate_provider("L0", ProviderEvidence(...))         (Beslut 3)
      → BudgetGate(...)                                                        (route_id="selfhosted-...")
  → task-class-eval (Beslut 4) kör N=3-rundor mot L0-fixture
  → cost/quality-jämförelse (Beslut 6): GROUP BY route_id över fas2a_inference_spend
  → selfhosted_liveness.py pollar /health + /metrics parallellt                (Beslut 5)
      → fas2a_selfhosted_liveness-tabell
```

## Error handling

| Fall | Hantering |
|---|---|
| Självhostad endpoint svarar inte (nätverksfel/timeout) | `TextInferenceError` via befintlig `_call_backend`-logik (oförändrad) — fail-closed, ingen tyst fallback till extern provider. |
| Provider-policy nekar (L1+ försök mot en L0-begränsad route) | `TextInferenceError` från `evaluate_provider`-grinden (oförändrad) — samma disciplin som idag. |
| `/health` svarar men `/metrics` är otillgängligt eller har oväntad form | `parse_liveness` returnerar `alive=True` men `capacity=None`/degraderat sample, aldrig fabricerade tal — samma "degradering, inte fel"-princip som Fas 6:s `change_perspective`. |
| Budget uttömd under eval-rundan | `BudgetExhausted` (befintlig `BudgetGate`-logik, oförändrad) — rundan räknas som förlorad i N=3-utvärderingen, samma mönster som Fas 5. |
| Ett externt-provider-anrop läcker in i en "utan extern provider"-runda (bugg i test-setup) | Test-gate: assertion mot `fas2a_inference_spend` att 100 % av `route_id`-raderna för rundan är den självhostade routen — samma "fail via test-gate"-mönster som Fas 6:s no-external-deps-assert. |

## Testing strategy

- **TDD, vertikala skivor** enligt `test-driven-development`-skillen.
- **Deterministisk kärna först (0 GPU-anrop):** `parse_liveness` mot fixture-payloads (vLLM:s
  dokumenterade `/metrics`-svarsform), `TextInferencePort`-instansiering med de nya env-namnen,
  provider-policy-beslutet för den nya `ProviderEvidence` (L0 tillåts, L1 nekas — ren
  policy-logik, redan testad generellt, ny testrad för den specifika evidensen).
- **Route-isoleringstest:** assert att `fas2a_inference_spend`-rader taggade med den självhostade
  `route_id` aldrig blandas med InferX/Voyage-rader inom samma test-DB.
- **Empiriskt exit-bevis (separat, budget-/GPU-styrt steg, kräver operatörsgodkännande):**
  N=3-rundor av den valda task class (Beslut 4) mot den faktiska deployade modellen, jämfört mot
  InferX-baslinjen — samma struktur som Fas 5:s exit-bevis, inte en del av den deterministiska
  kärnans TDD-cykel.
- **Ingen regression:** hela default-sviten (`pytest agent-platform/ -m "not real_inference and
  not docker_required"`) förblir grön (345 passed, 3 skipped, senast verifierat Fas 6-slut) — nya
  tester adderas, inget befintligt rörs (Beslut 7 garanterar detta strukturellt).

## Out of scope for this slice

- **Faktisk GPU-provisionering och riktiga inferensanrop** — kräver operatörsgodkänd plan + budget
  (hård grind, se nedan). Denna spec bygger inte mot en live-deployment.
- **UI/dashboard för liveness/capacity** — CLI/query-status räcker (samma linje som Fas 4–6:
  operatörsdashboard out-of-scope tills levande behov).
- **RLM-generalisering eller ändringar i reasoning-kärnan** — explicit uteslutet av
  dispatch-uppdraget; denna spec rör bara inference-lagret.
- **Multi-tenant-isolering, usage accounting, kundexponerat inference-API** — §14.3 steg 6–7,
  hör inte hemma i Fas 7:s "bevisa att en task class kan köra utan extern provider"-scope.
- **L1/L2-dataklasstöd på den självhostade routen** — blockerat av Beslut 3 tills avslutad
  oberoende assurance för den specifika Vast.ai-infrastrukturen finns. Ingen ny
  assurance-process initieras av denna spec.
- **Caching, batching, modellpool, lastbalansering** (§14.3 steg 4–5) — hör till en senare,
  bevisad-värde-driven iteration, inte v1:s bevis-att-porten-generaliserar-scope.
- **Ny task class uppfunnen för detta ändamål** — Beslut 4 återanvänder befintlig L0-fixture
  medvetet.

## Blockerade delar och operatörsbeslut (att lyfta)

Följande **kräver operatörsbefattning** och blockerar plan/TDD-exekvering av deployment-delen (men
inte den deterministiska kärnans TDD — liveness-parsing, portinstansiering, policy-logik kan
byggas och testas med fixtures innan GPU:n existerar):

1. **Val av GPU-leverantör/hosting (Beslut 1).** **Operatörsgodkänt 2026-08-17:** Vast.ai, inte
   lokal hårdvara (avvisat explicit) och inte InferX/RunPod. Faktisk provisionering kräver ett
   separat godkännande av kostnadsram vid det tillfället.
2. **Modellval + instansstorlek + faktisk kostnad (Beslut 2).** Rekommendation: liten öppen
   Qwen3-instruct-modell (~7–8B). Operatören har låg förkunskap om modellval — denna spec föreslår
   en startpunkt, men exakt modell + Vast.ai-instansstorlek och kostnadsram kräver fortsatt
   explicit godkännande innan provisionering.
3. **Faktisk GPU-provisionering och credential-/providerkonfiguration** (`CORTXT_SELFHOSTED_URL`/
   `CORTXT_SELFHOSTED_API_KEY`) — skrivs aldrig ut/committas, sätts av operatören i miljön som kör
   riktiga anrop.
4. **Inference-/GPU-budget för det empiriska exit-beviset** (analogt Fas 5/6) — systemhanterat via
   `FAS2A_INFERENCE_BUDGET_MAX`, men kräver att operatören faktiskt sätter budgeten vid
   exit-bevisets tidpunkt.
5. **Merge/deploy av denna spec till en godkänd plan** — självgodkännande är förbjudet (§28).

## Deferred decisions

| Decision | Revisit when |
|---|---|
| RunPod istället för Vast.ai | Om Vast.ai:s manuella konfiguration/marketplace-variabilitet visar sig vara ett verkligt driftsproblem i praktiken — RunPod:s färdiga vLLM-mall + äkta scale-to-zero är den kända, dyrare reservvägen. |
| Uppskalning till större öppen modell | Om exit-kriteriets kvalitetsjämförelse (Beslut 6) visar att en liten modell är den begränsande faktorn, inte kostnad. |
| L1/L2-dataklasstöd på den självhostade routen | Avslutad oberoende assurance för den specifika Vast.ai-infrastrukturen — ingen väg dit finns ännu. |
| Fler task classes utan extern provider | Efter att den första (Beslut 4) är exit-bevisad — §24.3:s villkor ("quality floor uppfylld, latency/kostnad accepterad, dataskydd verifierat, fallback finns") avgör per klass. |
| Caching/batching/modellpool/lastbalansering (§14.3 steg 4–5) | När v1:s enkla en-modell-en-route-bevis är klart och ett verkligt behov (kostnad eller genomströmning) motiverar det. |
| §27 #9 (affärsvärde egenhostad vs hyrd) fullt besvarad | När cost/quality-jämförelsen (Beslut 6) ger faktiska tal från en riktig deployment — denna spec besvarar bara "vilken väg vi provar först", inte den ekonomiska slutsatsen. |
