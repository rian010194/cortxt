# Handoff: minimal real Vertical 01 package and evaluations

Snapshot: 2026-08-02  
Ticket: <https://github.com/rian010194/ai-workspace-control-plane/issues/9>  
Map: <https://github.com/rian010194/ai-workspace-control-plane/issues/7>

Operational update: ticket 09 was not implemented during the 2026-08-02 Buzz
workflow session. Read `2026-08-02-buzz-workflow-session.md` before
redispatching. Buzz trigger-text rendering was verified, but automatic workflow
mentions and Builder terminal output remain blocked.

Read `shared-context.md` first.

## Decision question

What is the smallest versioned AI Act package, workflow, schema, synthetic
fixture set, and evaluation set required for the first run to be real and
reusable rather than a disposable smoke test?

## Verified repository state

- `verticals/` currently contains only documentation and `_template/`; the
  actual `vertical-01-ai-act` package has not been created.
- A vertical owns domain workflows, schemas, instructions, templates, and
  approved domain eval fixtures.
- A vertical must not own dispatch, containers, credentials, platform-wide
  approval policy, or global runtime infrastructure.
- The harness owns isolation, runtime routing, timeout, concurrency, usage,
  cost, artifacts, logs, cleanup, and generic evaluation reporting.
- Early runs use synthetic cases. Real customer or municipal documents must
  not be committed.

## Already selected first-run shape

- Domain: EU AI Act applicability and obligations.
- The first package should produce validated structured JSON, a short Swedish
  decision brief, and domain evaluations.
- Research and implementation remain separate stages with human approval
  before Builder work and independent review after completion.

## Locked v0.1 package boundary

- Decision basis: Articles 2–3, Article 5, Article 6 including 6.3–6.4,
  Annex I, and Annex III.
- Requirements assessed in v0.1: Articles 9–12, with Annex IV supporting
  Article 11.
- Articles 14–15 are deferred to v0.2.
- Every unverified legal constraint and expected conclusion remains
  `Needs primary-source research` until verified against the primary EUR-Lex
  source.

## Instructions for ChatGPT

Act as a decision interviewer and rough package-design partner, not an
implementer.

- Ask exactly one question at a time and provide your recommended answer.
- Distinguish domain requirements from runtime/harness responsibilities.
- Prefer the smallest package that can be rerun and evaluated honestly.
- Require synthetic positive, negative, boundary, and uncertainty cases.
- Do not invent legal conclusions or current EU law; mark required legal facts
  `Needs primary-source research`.
- Do not invent repository files or claim that anything has been implemented.

When shared understanding is reached, produce:

1. package purpose and explicit non-goals;
2. proposed directory/file responsibilities without implementation code;
3. workflow stages and approval points;
4. input and output schema requirements;
5. minimal synthetic fixture matrix;
6. deterministic, model-assisted, and human evaluation responsibilities;
7. acceptance criteria for the first real run; and
8. a concise proposed GitHub resolution comment.

Start with the single decision that most strongly determines the package
boundary and include your recommendation.
