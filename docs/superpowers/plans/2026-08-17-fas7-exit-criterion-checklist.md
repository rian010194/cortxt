# Fas 7 — Egenhostad inference — exit-criterion checklist (empirisk)

Status: **§23-EXIT-KRITERIET EMPIRISKT UPPFYLLT.** Branch `spec/fas7-self-hosted-inference`,
2026-08-17. Spec: `docs/superpowers/specs/2026-08-17-fas7-self-hosted-inference-v01-design.md`
(v7, Kimi-granskad GODKÄND MED ANMÄRKNINGAR, P1 åtgärdad). Plan:
`docs/superpowers/plans/2026-08-17-fas7-self-hosted-inference-v1.md` (v3, Task 1–8 gröna,
Fas B genomförd).

## §23-kravet

> minst en godkänd task class kan köras utan extern inferenceprovider.

## Vad som faktiskt kördes (inte antaget)

- **Instans:** Vast.ai instans-ID `47966869`, 1x RTX 3090 (24 GB, över 16 GB-golvet i Beslut 2),
  Tyskland, $0.138/hr (billigare än det uppskattade $0.20/hr-golvet för en 16GB-klass-GPU).
- **Modell:** `Qwen/Qwen3-8B-AWQ` (officiell Qwen-kvantisering, AWQ int4), servad via vLLM 0.27.1
  bakom Vast.ai:s `vastai/vllm`-image, exponerad över en Cloudflare Quick Tunnel (HTTPS, krävs av
  `cortxt_resilient_inference`s säkerhetspolicy — se "Öppna punkter" nedan för varför detta INTE
  är produktionsstabilt).
- **Task class:** en avgränsad L0-klassificeringsuppgift (sentiment: positive/negative över tre
  syntetiska engelska meningar) — se Beslut 4:s YAGNI-motivering (återanvänder mönstret, ingen ny
  uppgiftsklass uppfanns).
- **Väg:** riktig `TextInferencePort` → `inference/provider_policy.py` (L0-beslut) →
  `BudgetGate` → `cortxt_resilient_inference` → riktigt HTTP-anrop → riktig vLLM-instans. Ingen
  mockning i denna körning.

## Resultat

```
fx-cats-1: success=True output={'answer': 'positive'} error=None
fx-cats-2: success=True output={'answer': 'negative'} error=None
fx-cats-3: success=True output={'answer': 'positive'} error=None

N=3 round: 3/3 succeeded

fas2a_inference_spend rows:
  ('selfhosted-qwen3-8b-awq', 'attempt_started', 3)
  ('selfhosted-qwen3-8b-awq', 'success', 3)

Distinct route_ids used: {'selfhosted-qwen3-8b-awq'}
External-provider route_ids used: set() (must be empty for §23 exit)
```

**N=3, 3/3 lyckades. Noll rader mot någon extern-provider-`route_id` i `fas2a_inference_spend`.**
§23:s "utan extern inferenceprovider" är därmed maskinellt verifierat mot en existerande tabell,
inte en subjektiv bedömning (samma operationella definition som Beslut 4 föreskrev).

## Övriga empiriska mätvärden från denna session

| Mätvärde | Resultat | Löser |
|---|---|---|
| Kallstartstid (`ensure_running()`, stoppad → frisk) | **59.2 sekunder** | Ersätter Beslut 8:s "INTE verifierad"-status |
| Värdstabilitet vid stop/start | Samma värd, samma IP/portmappning, disk bevarad | Kimi P2 #3 |
| Total kostnad denna session (provisionering + två stop/start-cykler + N=3-bevis) | **~$0.16** av $10-taket (saldo $9.84 kvar) | Bekräftar Beslut 2:s kostnadsuppskattning ($1–3) var för hög i andra riktningen — verklig användning var ännu billigare |
| Route-isolering (Beslut 6) | Verifierad end-to-end mot riktiga spend-rader | — |

## Buggar hittade och rättade under denna verifiering (inte antaganden — alla TDD-verifierade)

1. **Kimi P1 (Hermes-fixad innan Fas B):** `TextInferencePort`s `route_id` hårdkodat.
2. **`selfhosted_liveness.py`:** fel Prometheus-metriknamn (`gpu_cache_usage_perc` →
   verklig `kv_cache_usage_perc`) + saknad Bearer-auth mot den riktiga endpointen.
3. **`_VastAiControlAdapter.status()`:** parsade inte den riktiga API-svarsformen
   (`{"instances": {...}}`-wrapper).
4. **`_VastAiControlAdapter.start()/stop()`:** antog fel endpoint-form (`/start/`/`/stop/`
   sub-routes); verklig API är en PUT mot instansresursen med `{"state": ...}`-body.
5. **`BudgetGate.__call__`:** den inledande `attempt_started`-raden skickade inte `route_id`,
   så route-isoleringen höll bara delvis innan denna fix.

Alla fem committade (`33b5677`…`dcb0bf7`), inga regressioner (371 passed, 3 skipped efter samtliga
fixar).

## Öppna punkter — INTE löst av denna körning, ärligt kvarstående

**Operatörsbeslut 2026-08-17: samtliga fyra punkter nedan skjuts till Fas 7 v2.** Fas 7 v1 stänger
här — exit-kriteriet är uppfyllt, men ingen produktionsdrift, ingen aktiv routing och ingen
långlevande instans följer av det. v2 tar vid produktionshärdningen när den blir aktuell.

1. **Cloudflare Quick Tunnel är inte produktionsstabilt.** Den första tunneln (etablerad vid
   första provisioneringen) slutade svara i DNS efter en stop/start-cykel (bekräftat:
   `Resolve-DnsName` mot 1.1.1.1 → "Non-existent domain" för samtliga tunnel-subdomäner). En andra
   provisioneringsrunda fick en ny, fungerande tunnel-URL. **Detta är en verklig, bekräftad
   begränsning** — Quick Tunnels är designade för tillfällig felsökning, inte stabil drift.
   Rekommendation för produktionshärdning: en riktig namngiven Cloudflare Tunnel (kräver ett
   Cloudflare-konto/domän), en egen TLS-terminerande reverse proxy på instansen, eller Vast.ai:s
   "Secure Cloud"-erbjudande. Inget av detta är löst här — nästa operatörsbeslut.
2. **`CORTXT_SELFHOSTED_URL` måste inkludera `/v1`-segmentet** (t.ex.
   `https://<tunnel>.trycloudflare.com/v1`), samma konvention som redan gäller för InferX:s
   `base_url` i detta projekt (`cortxt_resilient_inference`s `http_adapter.py` bygger
   `{base_url}/chat/completions`, inte `{base_url}/v1/chat/completions`). Inte en kodbugg —
   en konfigurationsdetalj som måste dokumenteras vid produktionssättning.
3. **Modellvalets kvalitet mot InferX-baslinjen** (Beslut 6:s cost/quality-jämförelse) är INTE
   genomförd — denna körning bevisade bara *att* det fungerar, inte en sida-vid-sida-jämförelse
   mot InferX på samma fixtures. Kvarstår som separat, lågt prioriterat arbete om en sådan
   jämförelse blir relevant.
4. **Max Duration-backstop (Beslut 8)** sattes aldrig på den faktiska instansen — operatören/
   Claude höll själva koll på sessionen och stoppade manuellt vid två tillfällen. Om Fas 7 körs
   obevakat i framtiden krävs antingen ett verkligt Max Duration-värde satt vid provisionering
   eller den byggda `selfhosted_lifecycle.py`-watchern faktiskt kopplad in som en körande process
   (den är byggd och testad, men aldrig driftsatt som en långkörande tjänst i denna session).

## Sammanfattning

**Fas 7:s §23-exit-kriterium är empiriskt uppfyllt** mot en riktig, operatörsgodkänd
Vast.ai-deployment (RTX 3090, Qwen3-8B-AWQ) — en avgränsad L0-task-class kördes N=3 med 3/3
lyckade genom hela produktionskoden (port, policy, budget, route-isolering), med maskinellt
verifierad noll-användning av externa inferensproviders. Fem verkliga buggar hittades och
rättades genom denna live-verifiering, inte genom spekulation. Fyra öppna punkter kvarstår
ärligt dokumenterade för produktionshärdning, framför allt Quick Tunnel-instabiliteten. Instansen
är stoppad; ~$0.16 av $10-budgeten förbrukad.
