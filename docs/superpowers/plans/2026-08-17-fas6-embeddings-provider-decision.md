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

## UPPDATERAT VERIFIERINGSRESULTAT (2026-08-17, operatör konfigurerade InferX-bundle) — **A BEKRÄFTAD**
Operatören deployade InferX-katalogbundlen `Qwen3.6-35B-A3B-FP8 + Qwen3-Embedding-0.6B +
Qwen3-Reranker-0.6B` och godkände ett nytt, begränsat verifieringsanrop mot den. Resultat:
**HTTP 200**, `model=Qwen/Qwen3-Embedding-0.6B`, `embedding_dim=1024`, `prompt_tokens=5`.
Anropet gjordes med API-nyckeln hämtad direkt från urklipp in i anropet — nyckeln skrevs aldrig
ut eller committades.

- **Stabil bas-URL (modell-nivå, ingen instans-ID inbakad):**
  `https://model.inferx.net/funccall/tn-1bbbzbamb8/default/Qwen3.6-35B-A3B-FP8/m3/v1`
  (`/v1` = LLM, `/m2/v1` = rerank, `/m3/v1` = embeddings — per katalogens routing)
- **Modell:** `Qwen/Qwen3-Embedding-0.6B`
- **Tidigare 404 var provisorisk, nu förklarad:** berodde på fel modellnamn (chatt-modellen
  `INFERX_MODEL`, inte en embeddings-modell) — inte på att InferX saknar embeddings-stöd.

Den tidigare öppna frågan 3 (godkänn ett begränsat riktigt anrop) är därmed besvarad: **ja,
godkänt och genomfört.** Fråga 1/2 besvaras: **A**, med modell/endpoint enligt ovan.

### Ny upptäckt under implementering: adapter-inkompatibilitet
`cortxt_resilient_inference.http_adapter.OpenAICompatibleAdapter` är hårdkodad mot
`/chat/completions` och en chatt-meddelande-svarsform (`payload["choices"][0]["message"]`) —
den kan **inte** återanvändas oförändrad för embeddings (annat endpoint, annat svarsschema:
`payload["data"][0]["embedding"]`). Löst genom en ny, lokal adapter (`_EmbeddingHttpAdapter` i
`runtime/embedding_port.py`) som implementerar samma `Adapter`-protokoll
(`(route, timeout_ms) -> Mapping`) som `cortxt_resilient_inference.runner.execute` förväntar —
utan att ändra det externa paketet. Skillnad mot `OpenAICompatibleAdapter`: timeout hanteras
in-process (urllib-timeout) i denna första version, inte via en terminerbar barnprocess;
processisolering kan läggas till senare om embeddings-anrop behöver samma hård-kill-garanti.

### Status: `embedding_port.py`-kontraktet är förberett (TDD, inga riktiga anrop i testerna)
- `agent-platform/runtime/embedding_port.py` — `EmbeddingPort`, fail-closed på samma två
  grindar som `TextInferencePort` (BudgetGate + provider_policy), instansen är själv en
  `EmbeddingFn` (`__call__(text) -> list[float]`) — drop-in för
  `CandidatePathScore.embedder`/`GraphMetrics.semantic_closeness`.
- `agent-platform/tests/runtime/test_embedding_port.py` — 9 tester, alla gröna, inklusive ett
  drop-in-kompatibilitetstest som anropar `GraphMetrics.semantic_closeness` med en
  `EmbeddingPort`-instans som `embedder=` (mockad backend, inget riktigt nätverksanrop).
- Full default-svit efter tillägget: **340 passed, 4 skipped, 20 deselected** (0 regressions —
  verifierat färskt 2026-08-17; 331 Fas 6-kärna + 9 embedding-port-tester). Tidigare textsiffra
  "345" var felaktig; 340 är det verifierade värdet.
- **Ej gjort än:** `CORTXT_EMBEDDING_URL`/`CORTXT_EMBEDDING_API_KEY` är inte kopplade in i någon
  produktionskonfiguration, och det empiriska Fas 6-exit-steget (RLM mot riktiga
  resonemangsproblem med denna embedder) är inte kört — det kräver separat budgetgodkännande.

## SLUTLIGT PROVIDERVAL (2026-08-17): Voyage AI, inte InferX
Efter kostnadsgenomgång (InferX GPU-instanser: instans-kostnad även vid vila/kallstart,
dubbletter kan uppstå av misstag och kosta pengar) bytte operatören mål till **Voyage AI**
(Anthropics egen rekommenderade embeddings-partner):
- **200 miljoner gratis tokens** (de flesta modeller) — vårt verifieringsanrop kostade 4 tokens;
  ett fullt Fas 6-exit-steg ryms sannolikt inom gratisnivån.
- **Ren hostad API — inga GPU-instanser att hantera.** Inget Standby/Ready-läge, ingen
  kallstart, ingen risk för kostsamma dubbletter av det slag InferX visade sig ha.
- **Samma svarsform som InferX** (`{"object": "list", "data": [{"embedding": [...]}], ...}`) —
  `_EmbeddingHttpAdapter` i `embedding_port.py` behövde **noll kodändringar** för att fungera
  mot Voyage; bara ny `base_url`/`model`/`api_key_env`. Detta bekräftar att kontraktet verkligen
  är providerneutralt, inte bara InferX-format i förklädnad.

**Verifierat (2026-08-17, konto skapat av operatör, ett nytt begränsat anrop):**
```
HTTP 200 OK
model: voyage-4-lite
object: list
embedding_dim: 1024
total_tokens: 4
```
API-nyckeln (`cortxt-embedding-verify`, Voyage-projekt "default project") hämtades från
urklipp direkt in i anropet — aldrig skriven ut eller committad.

**Uppdaterat §27#10-underlag:**
```json
{
  "base_url": "https://api.voyageai.com/v1",
  "model": "voyage-4-lite",
  "api_key_env": "CORTXT_EMBEDDING_API_KEY",
  "embedding_dim": 1024,
  "verified": "2026-08-17, HTTP 200, 4 total_tokens, Voyage AI (ersätter InferX-alternativet)"
}
```
InferX-spåret ovan kvarstår som ett verifierat, fungerande alternativ (samma kontrakt, andra
env-värden) om Voyage av någon anledning behöver bytas ut senare — men Voyage är nu det
rekommenderade förstahandsvalet givet kostnads- och driftsprofilen.
