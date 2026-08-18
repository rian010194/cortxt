# Fas 6 — Geometric Reasoning v1 — handoff

Status: **HANDOFF / arbetsprompt.** Beständig kopia av uppdragsbeskrivningen till
nästa Hermes-session, skriven 2026-08-17 på branch
`ci/adr-doc-currency-gate-clean`. Oroa dig inte över att denna är en kopia av en
chattprompt — den är skriven för att en session utan konversationskontext ska kunna
orientera sig och fortsätta korrekt.

---

Vi fortsätter arbetet i repot `C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane`
(branch `ci/adr-doc-currency-gate-clean`). Du har ingen konversationskontext — orientera
dig i kodbasen och docs innan du agerar.

## KONTEXT — vad som är KLART

- **Fas 5 (RLM v1)** är fullt implementerad: 17/17 tasks, hela recursiva
  `Coordinator.run_node`-motorn + båda eval-harnessarna. Structural suite:
  **308 passed, 0 regressioner**. Commits `5841150..d37f802`.
- **Fas 5:s exit-kriterium ÄR empiriskt bevisat** mot riktig InferX-modell
  (`Qwen3-Coder-Next-FP8`, Python312): `test_exit_criterion_coding.py` +
  `test_exit_criterion_research.py` båda PASSED. Evidens i state.db
  `fas2a_inference_spend` (9 `attempt_started`).
- **Checkpoint #1 (Stage A)** är Kimi-reviewad och grön. Fullständig lägesbild:
  `docs/superpowers/plans/2026-08-17-fas5-exit-criterion-checklist.md`.

## KRITISKT — dina säkerhets-/processregler (personliga)

- **Autonom, ingen bollning:** vid tekniska vägval, fråga Kimi
  (kimi-k2.6, provider kimi-coding, ENDAST L0-dataklass, INGESTION-citat +
  state.db-provenance) vad den rekommenderar och kör på det.
- **'Stoppa vid varje checkpoint'** = stoppa för oberoende (Kimi) review, INTE för
  att fråga operatören.
- **Hårda mänskliga gatear som INTE delegeras:** självapproval,
  credential/providerändring, irreversibel/extern skrivning, deploy/publish,
  destruktiv cleanup (kräver inventering först). MERGE-gaten är delegerad till
  Kimi (godkänd om Kimi-reviewer GODKÄND). Riktiga inference-anrops BUDGET
  systemhanterat (litet internt tak, ingen siffra från operatören).
- **Producer äger rework:** KRÄVER → hash-bind → re-review tills GODKÄND.

## INFERX-CREDENTIALS (för riktiga inference-anrop)

- Finns i `C:\Users\rikar\Cortxt\projects\ticket-triage\.env` under
  `INFERX_BASE_URL`/`INFERX_API_KEY`/`INFERX_MODEL`. Mappa `INFERX_BASE_URL`→
  `CORTXT_INFERENCE_URL`, `INFERX_API_KEY`→`CORTXT_INFERENCE_API_KEY`, men sätt
  `CORTXT_INFERENCE_MODEL=Qwen3-Coder-Next-FP8` (`INFERX_MODEL`-värdet ger 404).
- Måste köras under Python312:
  `C:\Users\rikar\AppData\Local\Programs\Python\Python312\python.exe` (enda interp
  med `cortxt_resilient_inference`; `sys.executable` ärvs till
  `rlm_child_cli`-subprocesser). Notera Bash, inte PowerShell. Skriv aldrig ut
  eller commita API-nyckeln.
- BudgetGate mot delad state.db fail-closedar om `FAS2A_INFERENCE_BUDGET_MAX` inte
  överstiger historisk spend (9 rader nu); använd isolerad `db_path` per-run.

## DITT UPPDRAG — Fas 6 (Geometric Reasoning v1)

- Fas 6-entrén är dokumenterad i
  `docs/superpowers/plans/2026-08-17-fas6-entrance-readiness.md`. Två saker
  blockerar ren start och kräver operatörsbefattning, dokumentera och lyft dem,
  men det FINNS deterministiskt arbete som inte är blockerat:
  1. Granska target-architecture §23 Fas 6-leveranser (Problem State schema,
     reasoning graph, första operatoruppsättningen, contradiction-/
     attractor-detektering, path scoring, trajectory viewer/report) mot det
     redan-existerande `reasoning/geometric/`-paketet (DM3-slice, 13 gröna
     tester, deterministiskt hash-embedding-stub).
  2. Identifiera vilka Fas 6-delar som KAN implementeras deterministiskt
     (0 modellanrop) utan embeddings-providern §27#10, och vilka som är
     blockerade. Skriv en Fas 6-design-spec (`docs/superpowers/specs/`) för de
     oblockerade delarna, följ den etablerade
     spec → Kimi-review → plan → TDD-exekvering-processen.
  3. Lyft tydligt vilka beslut som kräver operatören (embeddings-provider §27#10,
     och om riktiga inference-anrop för Fas 6-kostnadsdata behöver mer budget).
- Bekräfta först att du kan köra hela default-sviten grönt
  (`pytest agent-platform/ -m "not real_inference and not docker_required"` =
  308 passed) och att du har Fas 5-exit-checklistan som sanningskälla innan du
  börjar.

## Processregler för denna fas (etablerade genom Fas 2–5)

- **spec → Kimi review → plan (TDD) → exekvering.** Ingen implementationskod
  innan specen är godkänd och en plan (TDD-tasks) existerar.
- **TDD** enligt `test-driven-development`-skillen: RED → verifiera fail → GREEN →
  verifiera pass, vertikala skivor, inga regressioner (308 + nya gröna).
- **Kimi-review** via `hermes -p coordinator -z <prompt> --provider kimi-coding
  -m kimi-k2.6` (se skill `codex-review-gate` → `kimi-headless-fallback-review`).
  Kör som background-process (2–4 min), spara utdata till `runs/<name>.out`,
  verifiera INGESTION-citat + state.db-provenance (billing_provider kimi-coding,
  model kimi-k2.6), ENDAST L0.
