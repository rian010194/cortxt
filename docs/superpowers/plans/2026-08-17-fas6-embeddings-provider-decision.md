# Fas 6 — §27 #10 Embeddings-provider — beslutspaket (för operatörsbeslut)

Status: **BESLUTSPAKET — förslag för operatör att ta ställning till.** 2026-08-17, branch
`ci/adr-doc-currency-gate-clean`. Detta dokument äger inga credentials och gör inga riktiga
anrop; det ger dig ett genomtänkt val. Kärnan är redan drop-in-redo — ingen av dessa
konsekvenser kräver ändring av den byggda/verifierade Fas 6-koden.

## Kontext
`reasoning/geometric/embeddings.py` definierar `EmbeddingFn = Callable[[str], list[float]]` med
`hash_embedding` som deterministisk default. En riktig provider byts in via samma yta — på två
ställen: `CandidatePathScore.embedder` (path scoring) och `GraphMetrics.semantic_closeness`
(diagnostisk närhet). §27 #10 (target-architecture) kräver att denna provider beslutas; det är
den enda kvarvarande "strukturellt blockerande" öppna punkten för ett fullt levande Fas 6.

## Befintlig infrastruktur som återanvänds
`agent-platform/runtime/text_inference_port.py` gör text/structured-JSON-anrop via
`cortxt_resilient_inference` (OpenAI-kompatibel `HTTPAdapter`) mot InferX, fail-closed på
**två oberoende grindar** innan något nätverksanrop:
- **BudgetGate** (`adapters/inference/budget_gate.py`) — systemhanterad budget, fail-closed.
- **Provider-policy** (`inference/provider_policy.py`, ADR-016) — dataklass->gate-regeln (L0/L…).
Och den körs under Python312 (enda interp med `cortxt_resilient_inference`).

Detta betyder att en embeddings-väg **inte behöver uppfinna ny fail-closed-infrastruktur** — den
ärver budget + policy + credentials + Python312 från `TextInferencePort`.

## Alternativ (att välja bland)

### A. InferX /embeddings via befintlig infrastruktur (rekommenderat som första steg)
- Bygg `embedding_port` ovanpå `cortxt_resilient_inference` + samma BudgetGate/provider-policy,
  exponera en OpenAI-kompatibel `/embeddings`-anropsväg, koppla svaret → `EmbeddingFn`.
- **Pro:** återanvänder all fail-closed-infra (budget, policy, credentials, Python312); mest
  koherent med ADR-016/ADR-017. Tid- och risklägsta om InferX exponerar `/embeddings`.
- **Con:** kräver att InferX har en embeddings-modell tillgänglig; varje nod-embedding blir ett
  riktigt API-anrop (kostnad + latency); kräver providerbeslut (vilken embedding-modell).

### B. Bibehållen deterministisk hash-stub som v1-embeddings (fallback / diagnostisk)
- Håll `hash_embedding` som default för Fas 6:s struktur + path scoring (redan byggt och grönt).
- **Pro:** 0 kostnad, 0 modellanrop, fullt deterministiskt och testbart.
- **Con:** uppfyller inte "riktig" semantisk närhet (§12.2); exit-kriteriets *semantiska*
  förbättring kan inte bevisas mot en riktig embedding.

### C. Lokal/open-source embedding i processen (t.ex. sentence-transformers) — senare alternativ
- En lokal embeddings-modell körs som `EmbeddingFn` (inget API-anrop).
- **Pro:** riktiga semantiska embeddings, offline, ingen provider-latens/kostnad.
- **Con:** ny tung dependency; **avviker från InferencePort-vägen (ADR-016)** — kräver en ny
  policy-granskad provider-adapter; lägst koherens med existerande arkitektur intill.

## Rekommendation (att granskas av Kimi; producer tar rekommendation, du beslutar)
1. **Prioritera A** — det koherenta, fail-closed-ärvande spåret; bevisa att InferX exponerar
   `/embeddings` och att en embeddings-modell finns, innan implementering.
2. **Behåll B som default** tills A är bevisat — kärnan är redan grön med B, så inget tryck.
3. **C endast** om InferX saknar en tillräcklig embeddings-modell (då ny BD-adapter krävs och
   granskas enligt ADR-016-processen).

## VERIFIERINGSRESULTAT (2026-08-17, 1 begränsat fail-closed-anrop) — PROVISORISKT
- InferX `https://model.inferx.net/endpoints/v1/embeddings` svarade **HTTP 404** (tom kropp)
  med den konfigurerade modellen (`INFERX_MODEL`).
- **PROVISORISKT utfall — inte "uteslutet":** operatören håller på att konfigurera InferX
  `/embeddings` (2026-08-17). 404 beror sannolikt på (a) att embeddings-sidan ännu inte är
  konfigurerad, och/eller (b) fel modell — en **chat-modell (`Qwen3…`) är inte nödvändigtvis en
  embeddings-modell**; OpenAI-kompatibelt `/embeddings` kräver ett `text-embedding-*`-modellnamn.
- **Behövs från operatören när konfigureringen är klar:** (1) bekräftad bas-URL, (2) ev. annan
  route-path om inte standard `/v1/embeddings`, (3) **rätt embeddings-modellnamn**, (4) att
  verifiering tillåts. Då görs en ny, begränsad fail-closed-probe innan implementering.
- **Innebörd just nu:** kärnan förblir grön med **B** (`hash_embedding`) — inget tryck att
  byta. **C** (lokal/open-source) kvarstår som alternativ om InferX-/embedding-vägen inte
  realiseras. Inga credentials skrevs ut/committades; anropet var read-only/idempotent och
  fail-closed.

## Konsekvenser (vilka som är mänskliga grindar — inte delegeras)
- **Provider-/endpoint-beslut** = operatörsgrind (vilken embedding-källa + modell).
- **Credentials-konfiguration** (`CORTXT_INFERENCE_*` / Embeddings-key) = operatörsgrind (skrivs
  aldrig ut/committas).
- **Faktisk implementering av A/C** = normal TDD-kod som kan göras autonomt NÄR providerbeslutet
  är taget; inga nya credentials hämtas av agenten.
- **Empiriskt Fas 6-exit-steg** mot riktig modell = budgetstyrt (systemhanterat), en separat
  operatörs-nods-godkänd aktivitet.

## Frågor att bekräfta från dig
1. Vill du att vi går på **A** (InferX /embeddings, om tillgång finns), **B** (stub, ingen riktig
  embedding för nu), eller **C** (lokal modell)?
2. Om A: vilken embedding-modell/endpoint ska användas (eller ska jag verifiera tillgång först,
  utan att röra credentials)?
3. Godkänner du att ett **begränsat riktigt anrop** görs för att verifiera /embeddings-tillgång
  (inom systemhanterad budget, fail-closed), som underlag till beslutet?
