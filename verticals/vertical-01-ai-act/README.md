# Vertical 01: EU AI Act Assessment Package

> **Package:** `vertical-01-ai-act`  
> **Version:** `0.1.0`  
> **Contract:** `0.1.0`  
> **Issue:** [rian010194/cortxt#9](https://github.com/rian010194/cortxt/issues/9)

---

## Purpose

This is the first production-intent domain package for the Cortxt control plane. It declares the workflows, schemas, instructions, templates, and synthetic evaluation fixtures required to assess EU AI Act applicability and obligations for a given system description.

## What v0.1 decides

For a single system description input, the vertical:

1. Determines whether the described system falls within the material scope of the AI Act (Articles 2-3, Annex I).
2. Classifies whether the system is prohibited (Article 5) or high-risk (Article 6, including 6.3-6.4; Annex III).
3. Identifies the applicable obligations for the classified system (Articles 9-12, with Annex IV supporting Article 11).
4. Produces a validated structured JSON result and a short English decision brief.

## What v0.1 does NOT decide (non-goals)

| # | Non-goal |
|---|---|
| N1 | **Dispatch or orchestration** — Owned by the harness/control plane. |
| N2 | **Container or sandbox policy** — Owned by the harness. |
| N3 | **Credential or API-key management** — No secrets embedded in the package. |
| N4 | **Hard-coded provider selection** — Capabilities are declared; the harness maps them. |
| N5 | **Platform-wide approval state machine** — Owned by the control plane. |
| N6 | **Real customer documents in Git** — Only synthetic or redistributable fixtures are committed. |
| N7 | **Legal advice or current-law guarantee** — Every unverified legal constraint is marked `Needs primary-source research`. |
| N8 | **Articles 14-15 in v0.1** — Human oversight and transparency obligations are deferred to v0.2. |
| N9 | **Post-market monitoring or drift detection** — Out of scope for v0.1. |

## Directory layout

```text
verticals/vertical-01-ai-act/
|-- vertical.yaml                 # Package manifest
|-- README.md                     # This file
|-- workflows/
|   |-- classify.yaml             # Classification workflow
|   `-- assess-obligations.yaml   # Obligations-mapping workflow
|-- schemas/
|   |-- vertical-manifest.schema.json
|   |-- ai-act-assessment-input.schema.json
|   |-- ai-act-assessment-output.schema.json
|   |-- eval-fixture.schema.json
|   `-- artifact-ref.schema.json
|-- instructions/
|   |-- system-prompt-classify.md
|   `-- system-prompt-obligations.md
|-- evals/synthetic/
|   |-- manifest.yaml
|   |-- README.md
|   |-- positive-cases/           # 3 fixtures
|   |-- negative-cases/           # 3 fixtures
|   |-- boundary-cases/           # 3 fixtures
|   `-- uncertainty-cases/        # 3 fixtures
|-- templates/
    `-- decision-brief-en.md      # English decision brief template
```

## Usage

1. The harness loads `vertical.yaml` and validates it against `schemas/vertical-manifest.schema.json`.
2. Input is validated against `schemas/ai-act-assessment-input.schema.json`.
3. The classification stage consumes `instructions/system-prompt-classify.md`.
4. The obligations stage consumes `instructions/system-prompt-obligations.md`.
5. Output is validated against `schemas/ai-act-assessment-output.schema.json`.
6. The harness renders `templates/decision-brief-en.md` into the final result.

## Synthetic evaluation

Twelve synthetic fixtures are provided under `evals/synthetic/`:
- **Positive cases:** Expected to trigger clear, high-confidence classifications.
- **Negative cases:** Expected to fall outside the AI Act material scope.
- **Boundary cases:** Edge cases at scope or risk-class boundaries.
- **Uncertainty cases:** Cases where the model should flag ambiguity or insufficient data.

## Legal disclaimer

This package assists classification; it does not provide binding legal advice. Every unverified legal constraint is marked `Needs primary-source research` until verified against EUR-Lex.

## Acceptance criteria

1. Package loads cleanly (`vertical.yaml` + all schemas valid).
2. At least one fixture per category exists.
3. All output JSON schemas are syntactically valid.
4. English brief template is non-empty and in English.
5. Deterministic structural checks are expressible in the schemas.
6. Uncertainty cases can be represented.
7. No secrets or real documents in any file.
