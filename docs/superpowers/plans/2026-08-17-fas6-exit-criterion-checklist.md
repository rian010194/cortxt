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

## Vad som kräver inference-budget (det empiriska exit-stegest) — ej i denna v1

- Fas 6-exit-kriteriet (§23): "strategin ger mätbar förbättring på de beslutande måtten utan
  regression över säkerhetsfixtures" mot en **riktig modell** (analogt Fas 5). Kräver riktiga
  runs-data och budget (systemhanterat). Detta är det enda återstående steget för ett fullt
  empiriskt exit-bevis; det deterministiska lagret är färdigt för "levande" use.
- §27 #8 (beslutande vs diagnostiska mått): **FORMELT BESLUTAT 2026-08-17** — se specen.

**Exit-körningsstatus (2026-08-17, steg C):** fixturen är låst + deterministiskt validerad, och
`embedding_port`→Voyage-kopplingen är verifierad korrekt (adapter `succeeded`, dim 1024;
`EmbeddingPort`-plumbing bevisad via isolerad mock). Exit-körningen **blockeras av en extern
rate-limit**: Voyage svarar **HTTP 429 `rate_limited`** även på enstaka, spridda anrop (verifierat
inkl. per-attempt-outcome). Cache per unik text (6 unika istället för 10+ raw) + sleep-spread
är inbyggt och deterministiskt bevisat, men **räckte inte** — 429 inträffar på även ett enskilt,
spritt anrop → det är ett **kontobaserat/nyckelbaserat driftstak hos Voyage**, inte en frekvens-
eller kodbugg. Kräver justering på Voyage-kontot (högre rate-limit/nivå) innan exit-steget kan
köras som avgörande bevis. Ingen nyckel i docs/commits; kostnad hittills minimal (mest 429-fail-closed).

## Sammanfattning

Fas 6:s deterministiska kärna är komplett, TDD-testad (36 geometric-tester), 0 regressioner,
0 modellanrop. De enda återstående delarna blockerar inte strukturen: ① provider-bytet (§27
#10, operatörsbeslut, drop-in-redo) och ② det empiriska exit-stegest mot riktig modell
(budgetstyrt). GUI-viewer är deferred (operatörsbeslut 2026-08-17) på ny bas, inte legacy `web/`.
