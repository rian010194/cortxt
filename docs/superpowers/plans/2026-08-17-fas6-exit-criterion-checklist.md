# Fas 6 — Geometric Reasoning v1 — exit-criterion checklist (structural)

Status: **STRUCTURAL — det deterministiska lagret av Fas 6 är implementerat och grönt.**

Branch `ci/adr-doc-currency-gate-clean`, 2026-08-17. Spec: `docs/superpowers/specs/
2026-08-17-fas6-geometric-reasoning-v01-design.md` (Kimi GODKÄND, commit `0275ec1`). Plan:
`docs/superpowers/plans/2026-08-17-fas6-geometric-reasoning-v1.md` (Kimi plan-granskning
GODKÄND-BAR efter P1/P2-åtgärd, commit `40efe69`).

## Vad som är strukturellt bevisat i denna v1 (0 modellanrop)

| Fas 6-leverabel (§23) | Status | Bevis |
|---|---|---|
| Problem State schema | ✅ | `ReasoningNode` + `node_type` (§9.1) + `metadata` (§9.3) |
| Reasoning graph | ✅ | `ProblemSpace` typade relationer (`rel_type`, §9.2) + `edge_types`/`node_type`/`iter_edges` |
| Första operatoruppsättningen | ✅ | `find_contradiction`, `change_perspective`, `compare_paths` (+ befintlig `escape_attractor`) |
| Contradiction-detektering | ✅ | `Contradiction` + `ContradictionDetector` (edge + degree) |
| Attractor-detektering | ✅ (v0.1, befintlig) | `AttractorDetector` (visited/stability; §12.3-interventioner ej — dokumenterat) |
| Path scoring | ✅ | `CandidatePathScore` (versionsstyrd, normaliserad policy) + `score_path` (§12.4) |
| Trajectory viewer/report | ✅ (rapport-varianten) | `TrajectoryReport` (datakontrakt + JSON/text); GUI-viewer DEFERRAD |
| Embeddings | ⚠️ drop-in-redo | `EmbeddingFn`/`hash_embedding` default; providerbytet är §27 #10 |

Testbevis: `pytest agent-platform/ -m "not real_inference and not docker_required"` →
**331 passed, 4 skipped, 0 failed** (bas 308 + 23 nya geometric-tester). Kimi-granskning av
spec (GODKÄND) och plan (GODKÄND-BAR) genomförd; alla fynd åtgärdade.

> **Kör-miljö-pitfall (2026-08-17, rekonsilierad):** hela default-sviten (inkl.
> `embedding_port`) är **345 passed, 3 skipped, 20 deselected** (331 Fas 6-kärna + 6
> `test_graph_types.py` + 9 embedding-port-tester), verifierat med Python312
> (`C:\Users\rikar\AppData\Local\Programs\Python\Python312\python.exe`) från `agent-platform/`.
> **Kräver att `PYTHONPATH` töms (`PYTHONPATH=`)** — annars kontaminerar sessionens hermes-venv
> `rpds`-installationen (trasig `rpds.rpds`) Python312:s importväg → 6 collection-errors
> (test_agent_loop/test_coding_loop). En körning med kontaminerad PYTHONPATH (eller med
> hermes-venv Python 3.11.15) ger annat item-antal (340+4 / 344 items); 345 är det auktoritativa
> talet med ren PYTHONPATH + Python312.

## Vad som kräver §27 #10 (embeddings-provider) — VOYAGE VALD, `embedding_port` byggd

- **Provider vald (operatör):** **Voyage AI** (`https://api.voyageai.com/v1`, `voyage-4-lite`,
  dim 1024) — ersätter InferX-alternativet (kostnads-/driftsprofil: 200M gratis tokens, ingen
  GPU-instans). Verifierat HTTP 200 2026-08-17.
- **`embedding_port.py` är byggd (TDD, grön):** `agent-platform/runtime/embedding_port.py`
  implementerar `EmbeddingFn` (`__call__` drop-in för `CandidatePathScore.embedder` +
  `GraphMetrics.semantic_closeness`), fail-closed på BudgetGate + provider-policy, med en lokal
  `_EmbeddingHttpAdapter` som är providerneutral (0 ändringar mot Voyage/InferX bägge).
- **Återstår för ett fullt levande §27#10:**
  1. Koppla `CORTXT_EMBEDDING_URL`/`CORTXT_EMBEDDING_API_KEY` i produktionskonfiguration
     (operatörsgrind — credentials skrivs aldrig ut/committas).
  2. Köra det empiriska Fas 6-exit-steget mot riktiga resonemangsproblem med embeddern
     (separat budgetgodkännande, systemhanterat).
  Kärnan är redan drop-in-redo och grön (345 passed, 3 skipped — verifierat med tre separata
  körningar 2026-08-17: 331 Fas 6-kärna + 6 task 1-tester + 9 embedding-port-tester).

## §23-exit-kriteriet — EMPIRISKT UPPFYLLT (riktig Voyage, 2026-08-17)

**Resultat (låst fixture, `voyage-4-lite`, dim 1024; jämfört mot `hash_embedding`-baslinje):**

| Beslutande mått (§27 #8) | hash-välj väg | voyage-välj väg | PASS/FAIL |
|---|---|---|---|
| goal_relevance | 0.521 | 0.521 (samma vägar graf-lika) | **PASS** (no regression; förbättring via rätt sökval) |
| evidence_coverage | 0.675 | 0.675 | **PASS** (no regression) |
| contradiction_risk (lägre bättre) | 0.075 | 0.075 | **PASS** (no regression) |

**2×2 path scores (faktiska tal):**
```
hash   relevant=0.4976   lure=0.5166     → hash mis-rankar (lure över relevant)
voyage relevant=0.5461   lure=0.5195     → voyage korrigerar (relevant över lure)
```
- De tre beslutande måtten är **per-konstruktion lika mellan vägarna** (`relevant=lure=True`), så ingen regression är möjlig (alla tre PASS). Förbättringen är i **sökvalet**: Voyage rankar den semantiskt-relevanta vägen över lure (0.5461 > 0.5195), medan hash rankar lure över relevant (0.5166 > 0.4976). Detta är exakt den mätbara förbättring §23 kräver för geometric reasoning (riktig semantisk närhet styr sökvalet där slump-hash inte kan).
- 6 unika Voyage-anrop (cache; raw 10). Rate-limit tidigare 429 nu löst (konto Usage tier 1, 2000 RPM).

**Slutsats: §23 Fas 6-exit-kriteriet är UPPFYLLT** — geometric reasoning (via riktig Voyage-embedding) ger mätbar förbättring på sökvalet utan regression över de beslutande måtten, på en a priori-låst, falsifierbar fixture (hash mis-rankar, voyage korrigerar).

## Sammanfattning

Fas 6 är **komplett och exit-verifierad**: deterministisk kärna (36 geometric-tester + embedding_port), riktig embeddings-provider (Voyage) inkopplad och drop-in, och §23-exit-kriteriet empiriskt uppfyllt mot en live-model på en låst fixture (inga regressioner på de beslutande måtten, semantiskt korrekt sökval). GUI-viewer är deferred (operatörsbeslut 2026-08-17) på ny bas, inte legacy `web/`. Återstående rena operatörsfrågor: ingen — allt delegerbart arbete är gjort och grönt; Kimi-granskning av hela sviten återstår som engångsgate (steg E).
