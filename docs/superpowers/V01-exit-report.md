# V01 — Exit Report (template)

Status: **DRAFT — skapad som del av Fas 8 close-out (Kimi V01-rekommendation).** Fylls i vid V01-slutet.
Mall enligt Kimis rekommendation (2026-08-18): lista varje fas, dess exit-kriterium, bevis (commit-hash +
testresultat + N=3-körningar) och caveats — så att V01 läses som en sammanhållen helhet, inte sju isolerade PR:ar.

Instruktion: för varje fas, fyll i raden med (a) exit-kriterium, (b) commit-hash(ar) som bevisar det,
(c) test-/evalresultat, (d) eventuella caveats. Den "samlar säcken" och är vad V01:s slutgranskning mäter mot.

| Fas | Exit-kriterium | Bevis (commit + testresultat) | Caveats |
|---|---|---|---|
| Fas 2 — Agent Runtime v0.1 | Verifierad vertical runtime | (fyll) | |
| Fas 3 — Coding Agent | Bounded write-slice | (fyll) | |
| Fas 4 — Supervisor | sessions/child-run-kontroll | (fyll) | |
| Fas 5 — RLM v1 | N=3-bevis mot riktig InferX-modell | (fyll: commits 5841150..d37f802; test_exit_criterion_{coding,research} PASS) | Python312 + INFERX_MODEL 404-fixa |
| Fas 6 — Geometric Reasoning v1 | §23-exit mot riktig Voyage | (fyll: 36 geometric-tester; exit PASS, relevant 0.5461 > lure 0.5195) | Voyage 429-risk; embeddings-budget |
| Fas 7 — Egenhostad inference v1 | §23-exit: task class utan extern provider | (fyll: N=3 mot Vast.ai, 3/3 OK, ~$0.16/$10) | Cloudflare-tunnel ej stabil för obevakad drift (Fas 7 v2) |
| **Fas 8 — Kontrollerad learning loop** | **Ingen automatisk ändring når produktion utan verifierad promotion** | **(fyll: `tests/learning/` 64 passed; exit-criterion N=3 grön; spec/plan GODKÄND) — se 2026-08-18-fas8-closeout notes** | skill/tool djup = v1.x; rollback depth-1; live-Voyage-eval budgetgated |

## Från specens "V01-close-out" (Kimi-rekommendationer adopterade)

1. **Evidens-continuitet Fas 5/6/7 → 8:** en enda evidence-registry-vy (denna fil) visar alla fasers
   N=3-exit-bevis.
2. **Integrationspunkt Supervisor → aktiv policy (Fas 4):** Supervisor bör läsa aktiv policy via
   `learning.resolve_active_policy()` vid session-start — dokumenterat, implementation v1.x.
3. **Integrationspunkt ToolGate → tool-kandidat (Fas 3):** en framtida promotad tool-version ersätter
   `ToolGate`-logik — dokumenterat, implementation v1.x (tool-kandidaten är operator-gated).
4. **N=3-gröna exit-körningar:** exit-beviset körs tre konsekutiva gröna omgångar (gjort för Fas 8 i
   `tests/learning/test_exit_criterion.py`).
