# Fas 2A — Riktig inference (opt-in) Runbook

Syfte: koppla reasoning-kärnans mockade `InferencePort` till RIKTIG, providerneutral inference
(via `cortxt-resilient-inference`) på en L0-fixtur, för att bryta "fixture-gap"-risken.
Detta är **opt-in** och **dataklass L0 enbart**.

## Grundläggande princip
- Default-sviten är alltid **mockad** och grön (0 modell-anrop): `pytest -m "not real_inference"`.
- Riktiga anrop körs ENDAST när du uttryckligen väljer `-m real_inference` OCH miljön är konfigurerad.
- Budgeten är **systemhanterad** (ingen siffra behöver sättas manuellt av operatören): env
  `FAS2A_INFERENCE_BUDGET_MAX`. Saknas → **0 = fail-closed** (inga riktiga anrop sker).

## Krävs för att köra riktig inference (env)
```bash
export CORTXT_INFERENCE_URL="https://<l0-endpoint>/v1"     # OpenAI-kompatibel, HTTPS
export CORTXT_INFERENCE_API_KEY="<key>"
export CORTXT_INFERENCE_MODEL="<model>"
export FAS2A_INFERENCE_BUDGET_MAX=3                        # litet tak; systemet äger siffran
```
> Kräver att `cortxt-resilient-inference` är installerat (se `requirements`/editable-install).

## Köra
```bash
# från agent-platform/
# 1) Hermetisk default-svit (inga riktiga anrop):
pytest -m "not real_inference"

# 2) Opt-in: riktiga L0-anrop (respekterar budget-taket):
pytest -m real_inference
```

## Budget- och kostnadskontroll
- Varje riktigt anrop loggas till SQLite-tabellen `fas2a_inference_spend` (timestamp, task_id,
  cost_status, latency_ms, route_id, selected_route_id) för senare analys.
- `BudgetGate` nekar (fail-closed) allt före HTTP när taket är nått; ett misslyckat anrop räknas
  också (ingen budget-kringgång via retries).
- Konstantt: alla icke-`real_inference`-tester är hermetiska.

## L0-fixtur
`fixtures/l0_synthetic_rlm.json` — endast syntetiska heltal/vektorer (Fibonaccital, enhetsvektorer),
uppenbart offentliga/syntetiska, dokumenterat ursprung. INGA personuppgifter/hemligheter/riktiga
dokument.

## Varför
Verifierar att RLM/Geometric-strategierna fungerar mot GENUIN model-inference bakom porten, utan att
`reasoning/` någonsin importerar en provider (ADR-016-invarianten skyddas av `test_no_external_deps`).
