# Synthetic Fixtures and Evaluation Matrix

> **Package:** `vertical-01-ai-act`  
> **Version:** `0.1.0`  
> **Target:** `evals/synthetic/`

---

## Fixture inventory

| Category | Count | Fixtures |
|---|---|---|
| `positive-cases` | 3 | `001-high-risk-medical-diagnostic`, `002-prohibited-social-scoring`, `003-high-risk-recruitment` |
| `negative-cases` | 3 | `001-traditional-accounting-software`, `002-simple-calculator-app`, `003-game-ai-npc` |
| `boundary-cases` | 3 | `001-borderline-biometric-counting`, `002-borderline-emotion-safety-exception`, `003-borderline-education-emotion` |
| `uncertainty-cases` | 3 | `001-incomplete-description`, `002-novel-technology`, `003-dual-use-military-civilian` |
| **Total** | **12** | |

Every fixture is a self-contained YAML file conforming to `eval-fixture.schema.json` containing:

- `fixture_id` — stable identifier
- `fixture_type` — category enum
- `input` — synthetic system description (validates against input schema)
- `expected_output` — expected assessment result (validates against output schema)
- `deterministic_assertions` — checks the harness can run without a model
- `model_assisted_assertions` — probabilistic checks requiring a model grader
- `human_review_required` — boundary-line legal conclusions may require human review

## Fixture design principles

1. **Synthetic only** — No real customer data, no proprietary documents, no credentials.
2. **Redistributable** — All text is original and may be committed to version control.
3. **Legally grounded** — Each fixture references specific AI Act articles, annexes, or definitions.
4. **Deterministic assertions** — Every fixture includes assertions that a harness can evaluate programmatically.
5. **Uncertainty propagation** — Fixtures in the `uncertainty` and `boundary` categories expect the model to emit low confidence, `uncertain` classifications, and populated `uncertainties` rather than force a wrong answer.

## Assertion language (v0.1)

Assertions are declarative objects designed to be consumed by the harness. Each assertion has:

| Field | Meaning |
|---|---|
| `path` | JSON Pointer into the actual output (e.g., `/classification/system_risk_class`) |
| `operator` | `equals`, `contains`, `exists`, `type_is` |
| `expected_value` | Expected value (type depends on operator) |

## Expected harness behaviour per category

### Positive cases
The model should produce **high-confidence** classifications that match the expected `applicability` and `classification` values. Obligations should be populated for in-scope, non-prohibited, high-risk systems.

### Negative cases
The model should produce **high-confidence** `applicability.ai_act_applies: false`. `classification.system_risk_class` should be `minimal_risk` with `basis_annex: null`. No obligations should be asserted.

### Boundary cases
The model should **not** force a classification when the legal boundary is genuinely unclear. Instead it should:
- Emit `confidence: uncertain` or `confidence: needs_more_info`
- Populate `uncertainties` with at least one explanation
- Leave `classification.system_risk_class` as `uncertain` when the boundary is unresolved

Exception: `003-borderline-education-emotion` expects the model to **prioritise prohibition** when a prohibited sub-component is present, even if the primary purpose is high-risk.

### Uncertainty cases
The model should recognise **insufficient or ambiguous input** and refuse to classify definitively. Expected outputs:
- `classification.system_risk_class: uncertain`
- `applicability.confidence: uncertain` or `needs_more_info`
- `uncertainties` listing the missing or ambiguous dimensions
- Optionally, a request for additional information

## Cross-dependencies

- **JSON Schema (`schemas/`):** The `path` values in assertions and the structure of `expected_output` are aligned with the final JSON Schema definitions.
- **Package boundary (`README.md`, `vertical.yaml`):** Scope in/out decisions (e.g., Articles 14-15 deferred, GPAI out of scope) are respected in fixture design.

## Future work (v0.2+)

- Add real-world edge cases drawn from published European Commission guidance or EDPB opinions.
- Expand the assertion language with regex, numeric ranges, and semantic similarity thresholds for model-assisted grading.
- Add adversarial fixtures that deliberately mislead (e.g., describing a prohibited system in euphemistic terms).
- Integrate with the harness to produce per-fixture pass/fail reports and cost/usage metrics.
