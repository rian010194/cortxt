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

## Vad som kräver §27 #10 (embeddings-provider) — ej i denna v1

- Ersätta `hash_embedding` med en riktig provider via `EmbeddingFn`-ytan (drop-in på
  `CandidatePathScore.embedder` och `GraphMetrics.semantic_closeness`).
- **Verifierat 2026-08-17:** InferX exponerar INGEN `/embeddings`-route (HTTP 404) på den
  konfigurerade bas-URL:en — så **Alternativ A (InferX /embeddings) är uteslutet** på befintlig
  bas. Kvarvarande val: B (behåll deterministisk stub — kärnan är grön) eller C (lokal/
  open-source embedding via ny BD-adapter, kräver TDD + ADR-granskning). Se
  `2026-08-17-fas6-embeddings-provider-decision.md`.

## Vad som kräver inference-budget (det empiriska exit-stegest) — ej i denna v1

- Fas 6-exit-kriteriet (§23): "strategin ger mätbar förbättring på de beslutande måtten utan
  regression över säkerhetsfixtures" mot en **riktig modell** (analogt Fas 5). Kräver riktiga
  runs-data och budget (systemhanterat). Detta är det enda återstående steget för ett fullt
  empiriskt exit-bevis; det deterministiska lagret är färdigt för "levande" use.
- §27 #8 (beslutande vs diagnostiska mått): specen föreslår startpunkt (goal_relevance,
  evidence_coverage, contradiction_risk beslutande); formellt beslut ska fattas före
  exit-utvärdering.

## Sammanfattning

Fas 6:s deterministiska kärna är komplett, TDD-testad (36 geometric-tester), 0 regressioner,
0 modellanrop. De enda återstående delarna blockerar inte strukturen: ① provider-bytet (§27
#10, operatörsbeslut, drop-in-redo) och ② det empiriska exit-stegest mot riktig modell
(budgetstyrt). GUI-viewer är deferred (operatörsbeslut 2026-08-17) på ny bas, inte legacy `web/`.
