"""Evaluator — multi-candidate EvidenceMatrix (Phase 8, Decision 2 / 9.2; P1.2).

Computes, per candidate, a baseline-relative evidence row over a shared fixture set:
- ``baseline_delta`` = candidate score - baseline score (positive = strictly better, 0 = tie, negative = worse).
- ``no_regression`` = candidate is NOT worse than baseline (delta >= 0) on a complete run.
- ``complete`` = every fixture was evaluated (any fixture failure -> incomplete, fail-closed).
- ``fixture_coverage`` = fraction of fixtures successfully evaluated.

Kimi P1.2: ``cached_embedder()`` wraps any ``EmbeddingFn`` in a per-unique-text lookup, so geometric
``score_path`` treats the embedder as a lookup during eval (not an API call per path node), reusing the
per-unique-text cache discipline proven in Phase 6. The pre-cache is applied by the candidate adapters (Task 8)
when they build a ``CandidatePathScore``; the generic Evaluator stays transport-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

FixtureId = str
Scorer = Callable[[Any, FixtureId], float]  # (candidate, fixture_id) -> score in [0,1]
EmbeddingFn = Callable[[str], list[float]]


@dataclass(frozen=True)
class EvidenceRow:
    candidate_id: str
    baseline_delta: float | None  # None when nothing could be evaluated (not a tie, Kimi F-04)
    no_regression: bool
    complete: bool
    fixture_coverage: float


def cached_embedder(embedder: EmbeddingFn) -> EmbeddingFn:
    """Pre-cache wrapper (P1.2): underlying embedder called at most once per unique text."""
    cache: dict[str, list[float]] = {}

    def fn(text: str) -> list[float]:
        if text not in cache:
            cache[text] = list(embedder(text))
        return cache[text]

    fn.unique_calls = lambda: len(cache)  # introspection for tests
    return fn


class Evaluator:
    """Deterministic multi-candidate evaluator producing one EvidenceRow per candidate."""

    def evaluate_matrix(
        self,
        candidates: list[Any],
        baseline: Any,
        fixtures: list[str],
        scorer: Scorer,
    ) -> list[EvidenceRow]:
        cand_scores: dict[str, dict[str, float]] = {}
        complete_by_cand: dict[str, bool] = {}
        for cand in candidates:
            scores: dict[str, float] = {}
            complete = True
            for f in fixtures:
                try:
                    scores[f] = scorer(cand, f)
                except Exception:
                    complete = False  # fixture failure -> row incomplete (fail-closed)
            cand_scores[cand.id] = scores
            complete_by_cand[cand.id] = complete

        baseline_scores: dict[str, float] = {}
        baseline_complete = True
        for f in fixtures:
            try:
                baseline_scores[f] = scorer(baseline, f)
            except Exception:
                baseline_complete = False

        rows: list[EvidenceRow] = []
        for cand in candidates:
            cs = cand_scores[cand.id]
            evaluated = [f for f in fixtures if f in cs and f in baseline_scores]
            coverage = len(evaluated) / len(fixtures) if fixtures else 1.0
            if evaluated:
                cand_avg = sum(cs[f] for f in evaluated) / len(evaluated)
                base_avg = sum(baseline_scores[f] for f in evaluated) / len(evaluated)
                delta = cand_avg - base_avg
            else:
                delta = None  # Kimi F-04: nothing evaluated is NOT a tie
            complete = complete_by_cand[cand.id] and baseline_complete
            rows.append(EvidenceRow(
                candidate_id=cand.id,
                baseline_delta=delta,
                no_regression=(delta is not None and delta >= 0 and complete),
                complete=complete,
                fixture_coverage=coverage,
            ))
        return rows
