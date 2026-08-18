# Fas 7 — Egenhostad inference — design

Status: **v8 — FAS 7 AVSLUTAD. §23-exit-kriteriet empiriskt uppfyllt** (riktig N=3-körning mot
en riktig Vast.ai-deployment, 3/3 lyckades, noll externa providers — se
`docs/superpowers/plans/2026-08-17-fas7-exit-criterion-checklist.md`). Instansen stoppad,
~$0.16 av $10-taket förbrukat. Fyra öppna produktionshärdningspunkter kvarstår ärligt
dokumenterade (viktigast: Cloudflare Quick Tunnels är inte stabila nog för obevakad drift).
Writer: Claude (orchestrator session), 2026-08-17, branch `spec/fas7-self-hosted-inference`
(grenad från `ci/adr-doc-currency-gate-clean`, senaste commit `3eda624`). **Revideringshistorik
2026-08-17:** (v1) InferX som förslag → avvisat av operatören (opak GPU-prissättning). (v2) Ett
lokal-RTX-4060-först-plus-Vast.ai-fallback-förslag → **operatören avvisade det lokala steget
explicit** ("vill inte använda min egen GPU"). (v3) **Vast.ai som enda deployment-väg**, konkret
modell (Qwen3-8B-Instruct) + ett kostnadstak på 25–30 USD föreslaget. (v4) Kostnadstaket
korrigerat till ~10 USD och en faktafel om InferX rättad (auto-decommission fungerade faktiskt —
den verkliga Fas 6-kostnaden var överdimensionering, inte ett trasigt idle-shutdown). (v5) Beslut
8 tillagt: operatörsförslag om automatiskt idle-stopp + Vast.ai:s inbyggda Max Duration som
backstop, verifierat mot Vast.ai:s dokumentation. (v6) Kimi-granskning genomförd på operatörens
explicita begäran (`hermes -p coordinator --provider kimi-coding -m kimi-k2.6`) →
**GODKÄND MED ANMÄRKNINGAR**; P1 åtgärdad (Beslut 7:s "noll ändringar"-påstående var fel,
`route_id` var hårdkodat — rättat till en minimal parametrisering); 5×P2 som öppna punkter.
**(v7, denna version) Operatören:** (a) bekräftade explicit att den mindre, kvantiserade modellen
+ svagare (≥16GB) GPU:n är tillräcklig — löser Kimi P2 #2, se Beslut 2; (b) godkände gate 0 +
kostnadstaket (~10 USD, redan laddat på operatörens Vast.ai-konto); (c) **auktoriserade explicit
att Claude tar kontroll över operatörens inloggade Vast.ai-session (webbläsare) för de admin-steg
Hermes byggarbete når fram till** (instansprovisionering, vLLM-deploy, Max Duration-inställning,
stop/start) — se "Autonomt exekveringsmandat" nedan för exakt scope. (d) instruerade att resten av
Fas 7 nu ska skötas autonomt, utan ytterligare avstämningsfrågor utöver genuina blockerare/
destruktiva avvikelser.
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

Den centrala observationen som formar hela denna spec: **leverabel (3) är i grunden redan uppfylld
av existerande kod, inte något som ska byggas om från grunden.** `TextInferencePort`
(`agent-platform/runtime/text_inference_port.py`) är redan providerneutral — den pratar med
*vilken* OpenAI-kompatibel `/chat/completions`-endpoint som helst via `CORTXT_INFERENCE_URL`/
`CORTXT_INFERENCE_API_KEY` (konfigurerbara env-namn via konstruktorn), fail-closed på två oberoende
grindar (BudgetGate + `inference/provider_policy.py`, ADR-016) innan något nätverksanrop. En
egenhostad modell blir därmed **en tredje instans av samma port-instansiering** — exakt samma
mönster som `embedding_port.py` (Fas 6) redan bevisade för `/embeddings`. Fas 7 introducerar därför
**ingen ny arkitektur och ingen ny portklass**; den introducerar en ny *deployment* (en självvald,
självhostad modell bakom en OpenAI-kompatibel endpoint), en ny *provider-evidence*-rad för den
routen, och **en minimal parametrisering** av porten (Beslut 7, rättat efter Kimi-granskning: ett
hårdkodat `route_id`-fält behöver bli en konstruktörsparameter — se Beslut 7 för detaljer). Den
sistnämnda är en enradsändring i linje med portens befintliga parametriseringsmönster, inte ett
avsteg från "ingen ny arkitektur".

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

## Varför inte OpenRouter/en annan aggregator? (operatörsfråga, besvarad 2026-08-17)

Operatören ifrågasatte explicit om detta arbete alls är motiverat jämfört med att bara använda
OpenRouter eller en annan API-aggregator (Together, Groq, Fireworks m.fl.) — rimlig fråga, eftersom
en aggregator sannolikt är **billigare och enklare** för låg volym som enstaka evals. Ärligt svar:
**detta byggs inte för kostnadseffektivitet.** OpenRouter *är* en extern inferenceprovider — bara
en aggregator av andra externa providers — så att köra en task class genom OpenRouter skulle
uppfylla **noll** av §23:s exit-kriterium ("...kan köras **utan extern inferenceprovider**").
Skälen som faktiskt motiverar detta:

1. **Leverantörsoberoende, inte kostnad.** Om OpenRouter höjer priser, ändrar villkor, får
   driftstopp eller stänger ett konto försvinner hela den vägen. Fas 7 bevisar att minst en
   uppgiftsklass kan köras även om alla externa providers är otillgängliga samtidigt.
2. **Datasuveränitet-vägen.** En riktigt egenhostad modell (i förlängningen på egen hårdvara) kan
   nå L1-dataklass utan någon tredje parts DPA/assurance-process (jfr Beslut 3). En aggregator
   ärver alltid sina underliggande providers assurance-nivå — den vägen finns inte där.
3. **§14.3 — vägen mot en egen inferensprodukt.** Målbilden är att Cortxt på sikt äger sin egen
   serveringsstack, inte bara konsumerar andras API:er. Den operativa muskeln (deployment,
   liveness, capacity, modellops) byggs bara genom att faktiskt göra det en gång.
4. **Avgränsat experiment, inte en ersättning av Fas 5/6:s providers.** Fas 5 (InferX) och Fas 6
   (Voyage) fortsätter oförändrade för det mesta arbetet; Fas 7 bevisar bara att *ett* spår kan stå
   på egna ben.

Om dessa skäl inte väger tyngre än kostnaden/besväret för operatören är rätt beslut att nedgradera
Fas 7 till diagnostisk/lågprioriterad (samma nedtrappningsmönster §23 redan definierar för andra
faser) snarare än att bygga den — detta är därför ett explicit, inte underförstått, godkännande
(se "Blockerade delar", punkt 0 nedan).

## Scope decisions

### 1. Deployment-väg: Vast.ai (hyrd), inte operatörens egen GPU (operatörsbeslut 2026-08-17)

**Beslut (operatörsgodkänt, ersätter tidigare InferX-rekommendation och det tidigare
lokal-först-utkastet):** operatören vill uttryckligen **inte** använda sin egen maskin (RTX 4060)
för detta — inget lokalt steg. En marknadsjämförelse (RunPod, Vast.ai, Lambda Cloud, Together.ai,
Fireworks.ai, Modal, InferX; se research-underlag 2026-08-17) visade att InferX **inte** har
transparent $/hr-prissättning för GPU-hyra (bara per-token för katalogmodeller, ingen
självbetjänad sida för dedikerad GPU-hyra hittades). Mellan de återstående alternativen valde
operatören **Vast.ai** framför **RunPod**: RunPod:s Serverless är bekvämare (färdig vLLM-mall,
äkta scale-to-zero) men dyrare per GPU-timme; Vast.ai är billigare ($0.20/hr för en L4-klass GPU,
källa: research-underlaget) men kräver manuell vLLM/Docker-konfiguration — operatören har
uttryckligen prioriterat pris över bekvämlighet och bekräftat att det manuella arbetet inte är
ett hinder.

**Varför inte InferX (rättad motivering, v4):** ett tidigare utkast av denna spec påstod att en
InferX-instans "inte auto-decommissionerades snabbt nog" under Fas 6 — det var **fel**, rättat
efter operatörens fråga. Sessionsloggen visar tvärtom att InferX **auto-decommissionerade en
instans efter 15–20 minuters idle**, vilket fungerade. Den faktiska kostnaden där kom från att en
**35B-modell** deployades för en uppgift (embeddings) som bara behövde en **0.6B**-modell —
överdimensionering, inte ett trasigt idle-shutdown — plus en duplicerad instans som manuellt
städades bort för **$0.28** (trivialt belopp). Skälet att undvika InferX här är därför enbart den
**opaka $/hr-prissättningen för GPU-hyra**, inte ett (obekräftat) påstått
idle-avstängningsproblem. Detta betyder också att InferX:s bevisade fungerande
auto-decommissioning är en verklig fördel InferX har som Vast.ai (Beslut 2) saknar — vägt mot
priset, väger operatören ändå Vast.ai högre.

**Varför inte lokal RTX 4060:** ett tidigare utkast av denna spec föreslog lokal körning som ett
gratis första steg (tekniskt fullt möjligt — Q4-kvantiserad 7–8B ryms på 8 GB vRAM). Operatören
avvisade det explicit: Vast.ai är den enda deployment-vägen i denna spec, inte en fallback efter
ett lokalt steg.

**Hård gräns (icke-delegerbar, se "Blockerade delar"):** den faktiska GPU-provisioneringen på
Vast.ai kräver operatörens explicita godkännande av kostnadsram innan den sker — detta beslut
fastställer *vilken* leverantör, inte att pengar spenderas nu.

### 2. Modellval + konkret kostnadsram (SLUTGILTIGT BESLUTAT 2026-08-17, löser Kimi P2 #2)

**Beslut (operatörsstyrt, ersätter v6:s öppna bf16/24GB-rekommendation):** **Qwen3-8B-Instruct,
kvantiserad (AWQ eller GPTQ int4 — inte GGUF/Q4_K_M, som var den lokala RTX 4060-vägens format;
vLLM stödjer AWQ/GPTQ nativt och moget, till skillnad från dess omogna GGUF-stöd)**, på en
**16 GB-klass Vast.ai-GPU** snarare än 24 GB. Operatören frågade explicit om den mindre
modellen + svagare GPU:n räcker — svaret är **ja**: §23-exit-kriteriet handlar om att bevisa
leverantörsoberoende arkitektur (Beslut 7) för en avgränsad, lågkomplex L0-task class (Beslut 4),
inte om att maximera modellkvalitet. En kvantiserad 8B (~5–6 GB vikter + KV-cache-marginal på
16 GB) är gott och väl tillräcklig för det, och billigare 16GB-kort finns typiskt till lägre
$/hr än 24GB-klassen (L4/4090). Qwen-familjen är redan bevisad i detta projekt (Qwen3-Coder-
Next-FP8 via InferX i Fas 5, Qwen3-Embedding-0.6B/Qwen3-35B testade i Fas 6).

**Exakt GPU-modell/erbjudande väljs vid provisionering** (marknadsplatsutbudet varierar) — kravet
är: **≥16 GB vRAM, billigast tillgängliga sådana på Vast.ai vid det tillfället**, inte ett specifikt
kortnamn fastlåst i förväg.

**Konkret kostnadsram (rättad i v4 efter operatörens fråga om taket var rimligt — förslag att
godkänna, inte en pågående provisionering):**
- **GPU:** Vast.ai on-demand, ≥16 GB-klass (billigast tillgängliga vid provisionering — typiskt
  billigare än L4:s ~$0.20/hr; L4/24GB som reserv endast om inget 16GB-alternativ finns till
  rimligt pris).
- **Uppskattad total körtid:** setup/felsökning (vLLM-container, modellnedladdning) + N=3-
  eval-rundor + liveness-probe-verifiering — grovt **5–10 timmar** sammanlagt, inte kontinuerlig
  drift.
- **Faktisk kostnad vid avsedd användning:** 5–10h × $0.20–0.29/hr ≈ **$1–3**. (Föregående version
  av denna spec föreslog ett tak på $25–30 här — en omotiverad ~10× marginal utan förklaring;
  operatören ifrågasatte den, med rätta.)
- **Kostnadstak att godkänna: ~10 USD.** Fortfarande ~35–50 timmars marginal mot den uppskattade
  faktiska användningen (5–10h) — täcker upprepade felsökningsförsök utan att vara ett
  slentrianmässigt högt tak.
- **Risken om instansen glöms igång — nu automatiserad bort, se Beslut 8 (reviderat efter
  operatörsförslag):** Vast.ai on-demand-instanser har **ingen inbyggd scale-to-zero** (till
  skillnad från RunPod Serverless, som avvisades i Beslut 1) — obevakade kostar de per minut tills
  de stoppas. Utan skydd, om en instans lämnas igång en hel månad (730h): $0.20/hr →
  **~146 USD/månad**, $0.29/hr → **~212 USD/månad**. Operatören föreslog att bygga automatik
  istället för att lita på ett manuellt "kom ihåg"-krav — se **Beslut 8** för det fulla designet
  (mjukt idle-stopp via Vast.ai:s `stop_instance`-API + Vast.ai:s inbyggda hårda Max
  Duration-backstop). Med Beslut 8 på plats sjunker worst-case till lagringskostnaden för en
  korrekt *stoppad* (inte igångvarande) instans (~$3–7.50/månad, se Beslut 8) plus Max
  Duration som absolut yttergräns om även watchern skulle fela.

**Varför liten och kvantiserad, inte stor/okvantiserad:** en mindre, kvantiserad modell (a) håller
GPU-hyran låg under bevisfasen (16GB-klass är billigare än 24GB), (b) räcker gott för en
avgränsad, lågkomplex task class (Beslut 4) — exit-kriteriet mäter portoberoende, inte
modellkvalitet, (c) kan skalas upp senare (större modell, mindre kvantisering, större GPU) om ett
framtida exit-kriterium för en svårare task class visar att kvalitet är den begränsande faktorn.

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

### 7. Samma InferencePort — återanvänds nästan oförändrad; en minimal parametrisering krävs (rättat efter Kimi P1)

**Beslut:** `TextInferencePort.__init__` accepterar redan `model`, `base_url_env`, `api_key_env`
som konstruktorparametrar. Den självhostade routen instansieras som **en andra
`TextInferencePort`-instans** pekad på nya env-namn (t.ex. `CORTXT_SELFHOSTED_URL`/
`CORTXT_SELFHOSTED_API_KEY`), fail-closed på samma BudgetGate + samma `provider_policy`-modul.

**Kimi-granskning (2026-08-17) fann P1: påståendet "noll ändringar krävs" var felaktigt.**
`text_inference_port.py:88` har `route_id` **hårdkodat** till `"l0-default"` inuti
`_call_backend`s request-dict — verifierat i koden. Det motsäger Beslut 6, som kräver ett
distinkt `route_id` (t.ex. `"selfhosted-qwen3-8b"`) per route för `BudgetGate`s
kostnadsjämförelse (`GROUP BY route_id`). **Rättat beslut:** en minimal, bakåtkompatibel ändring
krävs — `route_id` görs till en konstruktörsparameter på `TextInferencePort` (default
`"l0-default"` så befintliga anrop/tester är oförändrade), och `_call_backend` använder
`self._route_id` istället för den hårdkodade strängen. Detta är fortfarande **inte en ny
portklass eller ett nytt kontrakt** — bara en parametrisering av ett värde som redan fanns i
requesten, i linje med hur `model`/`base_url_env`/`api_key_env` redan är parametriserade.

**Varför detta fortfarande är samma leverabel, bara mer ärligt beskriven:** §23:s krav är "samma
InferencePort" — det handlar om att inte bygga en ny port eller ett nytt kontrakt, inte om
bokstavligen noll diff. En enradsparametrisering av ett redan konfigurerbart mönster är
kvalitativt samma sak som Fas 6:s `embedding_port.py` bevisade (generalisering utan
omarkitektur), inte ett avsteg från det. Detta är fortfarande den tredje instansen av samma
mönster (text via InferX, embeddings via Voyage, text via egenhostad Vast.ai-serving).

**TDD-konsekvens:** denna ändring (och dess test — verifiera att `route_id` propagerar till
`fas2a_inference_spend`-raden) blir en explicit, liten TDD-task i planen, inte något som antas
"redan fungera".

### 8. Automatiskt idle-stopp + Max Duration-backstop + snabb återstart (tillagt efter operatörsförslag 2026-08-17)

**Beslut:** operatören föreslog att ersätta det manuella "kom ihåg att stänga av"-kravet (Beslut 2)
med automatik, och bygga för snabb återstart från kallstart snarare än att låta instansen stå igång
i onödan. Detta byggs som **två oberoende, samverkande skyddslager** (defense-in-depth, samma
princip som `BudgetGate`s fail-closed-design):

1. **Mjukt idle-stopp (business-logik, vår kod):** en liten watcher-process läser samma
   aktivitetssignal `selfhosted_liveness.py` redan samlar in (Beslut 5) — senaste lyckade anrops-
   tidsstämpel mot den självhostade routen (härledbar ur `fas2a_inference_spend` eller
   `fas2a_selfhosted_liveness`). Efter en konfigurerbar idle-tröskel (t.ex. 10–15 min, exakt värde
   avgörs i planen) anropas Vast.ai:s `stop_instance`-API — **inte** `destroy` — vilket stoppar
   GPU-fakturering men **bevarar disken**, så modellvikterna inte behöver laddas ner igen vid nästa
   start (verifierat mot Vast.ai:s dokumentation, se källor i konversationen 2026-08-17).
2. **Hård backstop (plattformsenforcerad, oberoende av vår kod):** Vast.ai:s inbyggda **Max
   Duration** sätts vid provisionering (en hyreskontrakt-gräns som stoppar instansen automatiskt
   när den nås, oavsett om vår watcher körs eller kraschat). Detta är den verkliga garantin mot "vår
   egen kod glömde stänga av" — samma roll som `BudgetGate`s DB-baserade fail-closed-räkning spelar
   för inferenskostnad. **Konkret värde (Kimi P2 #4, tidigare saknat):** rekommendation **2–4
   timmar** för bevisfasen — gott om marginal mot den uppskattade 5–10h totala körtiden fördelat
   över flera sessioner, samtidigt som det håller backstoppet meningsfullt tight snarare än
   slappt. Exakt värde bekräftas vid provisionering, inte fastlåst här.

**Snabb återstart:** en tunn `ensure_running()`-wrapper runt `TextInferencePort`-anropet (plan-
nivå-detalj var exakt den läggs) kollar instansstatus före anrop; om stoppad, anropas
`start_instance` och en poll mot `/health` (Beslut 5) tills servern svarar, sedan fortsätter
anropet. Kallstartslatensen syns bara på det första anropet efter en paus, inte på varje anrop.

**Öppen verifieringspunkt (Kimi P2 #3, inte löst av denna spec):** resonemanget "disk bevaras vid
stop" förutsätter att Vast.ai garanterar **samma värd** för en stoppad instans. På en
marknadsplats kan `start_instance` i princip omallokera till en annan värd — om disken är
värdlokal (inte nätverkslagring) följer den inte med, och "snabb återstart" blir då i praktiken en
ny nedladdning + omprovisionering. Detta **måste verifieras mot Vast.ai:s faktiska
instansmodell/dokumentation vid provisioneringstillfället**, inte antas. Om värdstabilitet inte
kan garanteras är fallbacken enkel: acceptera den långsammare kallstarten (fortfarande fungerande,
bara inte "snabb") eller höj idle-tröskeln så stopp sker mer sällan.

**Varför detta sänker risken rejält (rättad siffra, inte gissad):** eftersom `stop` bevarar disken
men stänger av GPU-fakturering, och Vast.ai:s lagringspris typiskt är $0.10–0.15/GB/månad, blir
worst-case för en **glömd men korrekt stoppad** instans (~30–50 GB modell-disk) **~$3–7.50/månad**
i lagring — inte de ~$146–212/månad som gällde om GPU:n stod igång kontinuerligt (Beslut 2). Med
Max Duration som backstop begränsas även scenariot "watchern kraschade" till en hård bortre gräns.
**Öppen punkt (Kimi P2 #5):** ~$3–7.50/månad-golvet förutsätter att endast lagring debiteras för
en stoppad instans — bekräfta vid provisionering att Vast.ai inte tar ut någon separat
"stoppad instans"- eller IP-reservationsavgift som skulle höja golvet.

**Kallstartstid — INTE verifierad, ska mätas, inte antas:** eftersom disken bevaras behöver
omstarten bara göra container-boot + vLLM-motorinitiering + vikt-laddning till GPU-minne, inte en
ny modellnedladdning — rimligen sekunder-till-några-minuter för en 8B-modell, men ingen konkret
siffra hittades i research-underlaget. Detta mäts empiriskt under TDD-implementeringen (första
verkliga `ensure_running()`-anrop loggar och rapporterar faktisk tid) — se
[[feedback_verify_before_writing_claims]]-disciplinen: siffran skrivs inte som fakta förrän den är
mätt.

**Precedent:** mönstret (egen idle-shutoff-watcher ovanpå Vast.ai:s API) är redan beprövat i
communityn (ett öppet källkods-exempel gör exakt detta) — inte ett experimentellt
egenutvecklat protokoll.

**Konsekvens för Beslut 2:** "Operativ disciplin"-stycket i Beslut 2 ersätts av detta — kravet är
inte längre "kom ihåg att stänga av manuellt" utan "watchern + Max Duration måste faktiskt vara
konfigurerade och verifierade innan instansen lämnas obevakad", ett TDD-verifierbart krav snarare
än en mänsklig vana.

## Components (nya/ändrade moduler)

**Ändrad (minimal, Beslut 7):** `agent-platform/runtime/text_inference_port.py` —
`route_id` blir en konstruktörsparameter (default `"l0-default"`, bakåtkompatibelt) istället för
hårdkodad i `_call_backend`. Inga ändringar i `agent-platform/inference/provider_policy.py`.
Nya moduler:

- `agent-platform/runtime/selfhosted_liveness.py` — `parse_liveness(metrics_payload) ->
  LivenessSample` (ren funktion) + en tunn `_LivenessHttpProbe`-I/O-wrapper (samma split som
  `_EmbeddingHttpAdapter`).
- `agent-platform/runtime/selfhosted_lifecycle.py` (Beslut 8) — idle-detektering (ren funktion mot
  `LivenessSample`-historik) + en tunn `_VastAiControlAdapter`-I/O-wrapper (`stop_instance`/
  `start_instance`, samma split-mönster) + `ensure_running()`-wrappern.
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
- **Idle-detektering och lifecycle-beslut (Beslut 8), deterministisk del:** ren funktion som tar
  en `LivenessSample`-historik + idle-tröskel → beslutar `should_stop: bool`, testad mot
  fixture-tidsstämplar (ingen riktig Vast.ai-anrop). `ensure_running()`s tillståndslogik
  (kollad/stoppad/startande/redo) testas mot mockade `_VastAiControlAdapter`-svar, samma
  felklassificeringsmönster som `_EmbeddingHttpAdapter`.
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

## Kimi-granskning (2026-08-17, kimi-k2.6 via `hermes -p coordinator --provider kimi-coding`)

**Verdikt: GODKÄND MED ANMÄRKNINGAR.** Begärd explicit av operatören (kostnadskänsligt, körs
sparsamt per operatörsinstruktion). Full utdata i sessionens temp-loggar.

**P1 (åtgärdad, se Beslut 7):** `route_id` hårdkodat i `text_inference_port.py:88` motsade
Beslut 7:s "noll ändringar"-påstående — verifierat i koden, rättat till en minimal
konstruktörsparametrisering.

**P2 (öppna, inte blockerande — för operatören/plan-fasen att ta ställning till):**
1. Kostnadsräkningen är aritmetiskt korrekt (Kimi räknade om själv) men saknar en direkt
   fotnot/länk till research-underlaget i slutversionen — kosmetiskt, inte substantiellt.
2. **LÖST (v7):** kvantiseringsvalet gjordes till ett aktivt, operatörsstyrt beslut i Beslut 2 —
   Qwen3-8B-Instruct AWQ/GPTQ int4 på ≥16GB, inte bf16/24GB. Operatören bekräftade explicit att
   den mindre modellen/svagare GPU:n är tillräcklig för exit-kriteriets syfte.
3. **Beslut 8:s "disk bevaras vid stop" förutsätter värdstabilitet som inte är verifierad.** På en
   marknadsplats kan `start_instance` omallokera till en annan värd — om disken är värdlokal
   (inte nätverkslagring) följer den då inte med, och "snabb återstart" blir i praktiken en ny
   nedladdning. Måste verifieras mot Vast.ai:s faktiska instansmodell innan Beslut 8 implementeras.
4. **Max Duration saknar ett konkret rekommenderat värde.** Kimi föreslår 2–4 timmar för
   bevisfasen som utgångspunkt — tvålagersskyddet (Beslut 8) är arkitektoniskt sunt men behöver
   ett faktiskt tal, inte bara principen.
5. Bekräfta att en stoppad instans inte har dolda avgifter (t.ex. IP-reservation) utöver ren
   lagring — golvet ~$3–7.50/månad (Beslut 8) förutsätter att endast lagring debiteras.

**Hantering:** P1 är åtgärdad i denna version (v6). P2 #2–5 kräver verifiering mot Vast.ai:s
faktiska plattformsbeteende vid provisioneringstillfället (inte något som kan avgöras från denna
spec i isolation) — de läggs till som explicita plan-nivå-verifieringssteg, inte antaganden. P2 #1
är en enkel dokumentationsjustering.

## Autonomt exekveringsmandat (operatörsauktoriserat 2026-08-17, v7)

Följande **var** operatörsgrindar (se historiken nedan för vad de krävde) och är nu **avklarade
eller explicit delegerade** — dokumenterat här som register (vad operatören faktiskt beslutade,
vid detta tillfälle), inte som en levande status som kan bli inaktuell:

0. **Gate 0 (bygga Fas 7 alls, leverantörsoberoende-motivet):** **GODKÄNT.**
1. **Val av GPU-leverantör/hosting (Beslut 1):** **GODKÄNT.** Vast.ai. Operatören är inloggad på
   Vast.ai med ~10 USD saldo redan laddat.
2. **Modellval + instansstorlek (Beslut 2):** **GODKÄNT, SLUTGILTIGT.** Qwen3-8B-Instruct,
   AWQ/GPTQ int4, ≥16 GB Vast.ai-GPU (billigast tillgängliga vid provisionering). Operatören
   bekräftade explicit att detta räcker för exit-kriteriets syfte.
3. **Kostnadstak (Beslut 2):** **GODKÄNT.** ~10 USD för hela bevisfasen.
4. **Faktisk GPU-provisionering, credential-/providerkonfiguration och admin-steg inne på
   Vast.ai (instansskapande, vLLM-deploy, Max Duration-inställning, stop/start):**
   **DELEGERAT MED SPECIFIK MEKANISM.** Operatören auktoriserade explicit att **Claude tar
   kontroll över operatörens redan inloggade Vast.ai-webbläsarsession** (via
   `claude-in-chrome`-verktygen) för de admin-steg som Hermes byggarbete inte kan göra själv
   (Hermes kodar/testar; Claude utför UI-handlingar i operatörens konto när Hermes arbete når en
   sådan punkt). `CORTXT_SELFHOSTED_URL`/`CORTXT_SELFHOSTED_API_KEY` sätts av Claude i den miljö
   som gör riktiga anrop under detta mandat — **skrivs aldrig ut i chatt eller committas**, i
   linje med det generella credential-förbudet.
5. **Inference-budget för det empiriska exit-beviset:** täcks av samma ~10 USD-tak (punkt 3);
   `FAS2A_INFERENCE_BUDGET_MAX` sätts som en del av exekveringen, inte en separat väntande grind.
6. **Merge/deploy av denna spec till en godkänd plan:** planen (`2026-08-17-fas7-self-hosted-
   inference-v1.md`) är redan skriven och operatörsgodkänd att exekvera — självgodkännande av
   *kod* (§28) gäller fortfarande normalt (verifiering/tester, inte Claudes egen bekräftelse), men
   ytterligare avstämningsfrågor om att *starta* exekveringen är inte längre nödvändiga.
7. **Idle-tröskel + Max Duration-värden (Beslut 8):** sätts av Claude vid provisionering inom
   specens rekommenderade intervall (10–15 min idle, 2–4h Max Duration) som en del av mandatet,
   inte en väntande fråga.

**Vad som INTE är delegerat (kvarstår som genuina stopp-villkor, per operatörens egen instruktion
"sköts autonomt... [utom] genuina blockerare"):** att spendera utöver ~10 USD-taket utan att
fråga; att radera/förstöra data eller andra resurser utanför denna specs scope; att upptäcka ett
last-bärande designfel i planen (inte bara ett justeringsbehov); eller något som kräver ett nytt,
separat kostnads- eller leverantörsbeslut som inte redan täcks av Beslut 1–2 ovan (t.ex. att byta
GPU-leverantör igen, eller höja kostnadstaket).

## Deferred decisions

| Decision | Revisit when |
|---|---|
| RunPod istället för Vast.ai | Om Vast.ai:s manuella konfiguration/marketplace-variabilitet visar sig vara ett verkligt driftsproblem i praktiken — RunPod:s färdiga vLLM-mall + äkta scale-to-zero är den kända, dyrare reservvägen. |
| Uppskalning till större öppen modell | Om exit-kriteriets kvalitetsjämförelse (Beslut 6) visar att en liten modell är den begränsande faktorn, inte kostnad. |
| L1/L2-dataklasstöd på den självhostade routen | Avslutad oberoende assurance för den specifika Vast.ai-infrastrukturen — ingen väg dit finns ännu. |
| Fler task classes utan extern provider | Efter att den första (Beslut 4) är exit-bevisad — §24.3:s villkor ("quality floor uppfylld, latency/kostnad accepterad, dataskydd verifierat, fallback finns") avgör per klass. |
| Caching/batching/modellpool/lastbalansering (§14.3 steg 4–5) | När v1:s enkla en-modell-en-route-bevis är klart och ett verkligt behov (kostnad eller genomströmning) motiverar det. |
| Exakt kallstartstid (Beslut 8) | Mäts empiriskt vid första verkliga `ensure_running()`-anropet under TDD-implementeringen — inte antagen i specen. Om den visar sig oacceptabelt lång (t.ex. flera minuter) kan idle-tröskeln höjas eller idle-stoppet stängas av för aktiva evalsessioner. |
| §27 #9 (affärsvärde egenhostad vs hyrd) fullt besvarad | När cost/quality-jämförelsen (Beslut 6) ger faktiska tal från en riktig deployment — denna spec besvarar bara "vilken väg vi provar först", inte den ekonomiska slutsatsen. |
