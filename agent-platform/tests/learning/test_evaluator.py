"""Phase 8 Task 6 — Evaluator: multi-candidate EvidenceMatrix + embedding pre-cache (P1.2)."""
from __future__ import annotations

import pytest

from learning.candidate import Candidate
from learning.evaluator import Evaluator, EvidenceRow


class _CountingEmbedder:
    """EmbeddingFn-protocol fake (Kimi P2.6): counts calls, gives semantically-different vectors per text."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> list[float]:
        self.calls.append(text)
        # deterministic hash-based vector so vector dim is stable
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]


def _cand(name, version, w1):
    return Candidate(type="policy", name=name, version=version,
                     payload={"w1": w1, "w2": 0.4, "w5": 0.5})


def test_evaluator_produces_evidence_for_each_candidate():
    ev = Evaluator()
    baseline = _cand("bl", "v1", 0.2)
    cand_a = _cand("cand-a", "v2", 0.3)
    cand_b = _cand("cand-b", "v2", 0.1)  # worse than baseline
    rows = ev.evaluate_matrix([cand_a, cand_b], baseline, fixtures=["f1"],
                              scorer=lambda c, f: c.payload["w1"])
    assert isinstance(rows, list) and len(rows) == 2
    assert isinstance(rows[0], EvidenceRow)
    assert rows[0].candidate_id == "policy@cand-a@v2"
    # baseline_delta = cand w1 - baseline w1
    assert rows[0].baseline_delta == pytest.approx(0.1)  # 0.3 - 0.2
    assert rows[1].baseline_delta == pytest.approx(-0.1)  # 0.1 - 0.2


def test_evaluator_no_regression_flag():
    ev = Evaluator()
    baseline = _cand("bl", "v1", 0.2)
    same = _cand("cand-s", "v2", 0.2)  # equal score -> tie, not regression
    worse = _cand("cand-w", "v2", 0.1)
    rows = ev.evaluate_matrix([same, worse], baseline, fixtures=["f1"], scorer=lambda c, f: c.payload["w1"])
    assert rows[0].no_regression is True
    assert rows[0].baseline_delta == 0.0  # tie
    assert rows[1].no_regression is False


def test_evaluator_precaches_embeddings():
    """Kimi P1.2: cached_embedder collapses duplicate texts to one underlying call (the geometric path-scoring pattern)."""
    from learning.evaluator import cached_embedder
    embedder = _CountingEmbedder()
    cached = cached_embedder(embedder)
    # simulate score_path embedding the same goal text many times (once per path node)
    for _ in range(10):
        cached("goal-content")
    for _ in range(5):
        cached("node-content")
    assert embedder.calls == ["goal-content", "node-content"]  # exactly 2 unique underlying calls
    assert cached.unique_calls() == 2


def test_evaluator_incomplete_when_fixture_missing():
    ev = Evaluator()
    baseline = _cand("bl", "v1", 0.2)
    cand_a = _cand("cand-a", "v2", 0.3)
    # scorer raises for a missing fixture -> matrix incomplete (fail-closed)
    def scorer(c, f):
        if f == "missing":
            raise KeyError(f)
        return 1.0
    rows = ev.evaluate_matrix([cand_a], baseline, fixtures=["f1", "missing"], scorer=scorer)
    assert rows[0].complete is False
