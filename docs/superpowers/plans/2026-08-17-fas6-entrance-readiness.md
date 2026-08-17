# Fas 6 — Geometric Reasoning v1 — entrance readiness note

Status: **PRE-SPEC ANALYSIS — not an implementation.** Written 2026-08-17 on
branch `ci/adr-doc-currency-gate-clean` after Fas 5 (RLM v1) implementation
completed (17/17 tasks, 308 passed structural suite). This note documents what
must be true before a Fas 6 design spec and implementation plan can be
entered, grounded in the actual verified code state — not in fabrication.

## Fas 6 leverables (target-architecture §23)

- Problem State schema;
- reasoning graph;
- embeddings (source: §27, open and blocking decision);
- first operator set;
- contradiction- and attractor-detection;
- path scoring;
- trajectory viewer or report.

## Verified current state (what already exists)

`agent-platform/reasoning/geometric/` is a **DM3 vertical slice** (landed
earlier via ADR-017) — deterministic, 0 model calls, 13 green tests:

| Component | Status |
|---|---|
| `graph_space.py` — `ReasoningNode`, `ProblemSpace` (directed graph, shortest_path) | ✅ exists |
| `embeddings.py` — `EmbeddingFn` surface + `hash_embedding` stub, `cosine` | ✅ stub only (deterministic hash, id→vec) |
| `metrics.py` — `GraphMetrics`: semantic_closeness, graph_distance_to_goal, evidence_coverage, contradiction_degree, centrality, novelty, stability | ✅ normalized [0,1] |
| `attractor_detector.py` — `AttractorDetector` (k_threshold, stability_threshold) | ✅ exists |
| `escape_attractor.py` — `escape_attractor()` | ✅ exists |
| `explorer.py` — `Explorer`, `bfs_path`, `exploration_cost` | ✅ exists |
| Real model embedding | ❌ NOT present — `hash_embedding` is explicitly a stub ("a real model embedding would replace this later via the same EmbeddingFn surface") |

## Why Fas 6 implementation cannot be entered cleanly yet

### 1. Blocking open decision §27 #10 — embeddings provider
Target-architecture §27 #10 is explicit:
> "Embeddings-provider för Fas 6 (§12.2 semantisk närhet). InferencePort
> (§14.1) normaliserar idag inte embeddings, och ingen fas levererar det.
> **Blockerande för Fas 6-start.**"

The only embedding today is the deterministic hash stub. A real embeddings
provider requires an actual inference/embedding source (credentials + a
model/embedding endpoint), which is not configured in this environment (no
`CORTXT_INFERENCE_*` credentials). This is not a code-writing problem I can
solve speculatively — it is an environment + open-decision dependency.

### 2. Fas 5 exit evidence is not yet empirical
§23 ties Fas 6's cost-multiplier policy to measurable RLM evidence:
> "Kostnadsmultiplikatorn ... blir en uppgiftsberoende, versionsstyrd
> policyparameter istället för en fast konstant" — only when Fas 5 produces
> measurable cost-per-successful-run evidence.

Fas 5's exit proofs (Task 13/17) are written but SKIPPED — they need a live
model. Without real RLM cost data, Fas 6's path-scoring cost policy would be
built on an unverified baseline.

### 3. No Fas 6 design spec exists
Fas 2-5 each follow: spec → Kimi review → plan (TDD tasks) → execute. There is
no Fas 6 spec yet (`docs/superpowers/specs/` has fas2-fas5 only). Writing
implementation directly without the spec/review cycle would break the
established, reviewed process.

## What unblocks Fas 6 start (concrete, verifiable prerequisites)

1. **Decide §27 #10 embeddings provider** — which embedding/endpoint + how
   `InferencePort` normalizes embeddings (the deferral from Fas 5 spec, beslut
   4). This is the hard gate; nothing else in Fas 6 implementation can proceed
   on a real basis until embeddings exist as more than a hash stub.
2. **Run Fas 5 exit proofs against a live model** (Coding + research classes)
   — produce actual RLM vs baseline cost per round, verify the 5× cap and 2-of-3
   pass rule. This yields (a) confirmation RLM beats baseline, or a
   de-escalation decision (operator), and (b) real cost numbers that make the
   Fas 6 cost-multiplier a data-driven policy instead of a guess.
3. **Write a Fas 6 design spec** (using the existing `reasoning/geometric/`
   DM3 slice as the starting skeleton): first operator set, path scoring that
   consumes real embeddings, trajectory report. Review with Kimi, then plan.

## What CAN be done now, without unblocking (deterministic, verifiable)

Only the non-embeddings, non-evidence-dependent pieces of the Fas 6 skeleton
could be hardened — but doing so before the spec/review cycle risks rework and
is NOT recommended. The disciplined move is to fix the two blockers above
first; they are environment/decision gates, not code gaps I should paper over
with speculative implementation.

— Prepared autonomously as the correct entry step for Fas 6: document the
verified current state and the exact unblock path, rather than fabricating an
implementation on an unproven foundation.
