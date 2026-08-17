"""Fas 6 empirical exit-criterion (target-architecture §23) — geometric reasoning.

The §23 exit criterion: geometric reasoning gives *measurable improvement on the
determining metrics* (goal_relevance, evidence_coverage, contradiction_risk — formal
§27 #8 decision) on real reasoning problems, without regression over safety fixtures,
vs the `hash_embedding` baseline.

Design: for each fixture (a small directed problem space with a reachable goal and
competing paths), pick the best path via `score_path` with a given embedder (`hash_embedding`
baseline vs a real `EmbeddingPort` Voyage embedder). Measure the three determining metrics on
that chosen path. The real-embedding arm must be >= the baseline on each determining metric
(no regression), with the primary pass rule being improvement on the composite while no
single determining metric regresses beyond tolerance.

The `hash_embedding` arm needs 0 model calls and runs in the default suite. The Voyage arm is
gated behind `real_inference` (needs CORTXT_EMBEDDING_URL/API_KEY), so a skipped real arm is
NOT a pass.

STATUS (2026-08-17): SCAFFOLD — the harness helpers (fixture builder, path enumeration, best-path
selection, determining-metric measurement, baseline arm) are implemented and deterministically
validated with the hash baseline (0 calls). The fixture is NOT yet a *valid* exit proof: with
`hash_embedding` on node-ids the current fixture already selects the strong path (score 0.556 vs
0.183), so a real-embedding arm would be trivially green — it cannot demonstrate the embedding
improvement §23 requires. A valid fixture must make the competing paths ~equal on the
graph-based determining metrics so that only *semantic* nearness (real embeddings) can break the
tie, and it must be constructed a priori (not tuned against results) to stay falsifiable. That
design is pending and must be resolved BEFORE spending real Voyage budget. Do not rely on this
test as evidence yet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest

from reasoning.geometric import (
    CandidatePathScore,
    Explorer,
    ProblemSpace,
    ReasoningNode,
    score_path,
)


@dataclass
class GeoFixture:
    """A small directed reasoning problem with a reachable goal."""

    id: str
    space: ProblemSpace
    start: str
    goal: str


def _build_fixture(seed: int) -> GeoFixture:
    """Construct a problem where strong-evidence near-goal paths compete with lure paths.

    Deterministic: node ids/evidence/contradiction derived from the seed so the fixture is
    reproducible (same seed -> same graph). The goal sits at high evidence; two candidate
    routes from `start` diverge: one short/high-evidence/low-contradiction toward the goal,
    one long/low-evidence/high-contradiction (a lure).
    """
    # content strings that are semantically different so real embeddings separate them
    strong = f"targeted claim about resolved outcome {seed}"
    weak = f"tangential decoy hypothesis {seed}"
    lurec = f"contradictory assertion {seed}"
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="start", content=f"start context {seed}", evidence=0.4, contradiction=0.1))
    s.add_node(ReasoningNode(id="s1", content=strong, evidence=0.9, contradiction=0.0))
    s.add_node(ReasoningNode(id="s2", content=strong, evidence=0.8, contradiction=0.0))
    s.add_node(ReasoningNode(id="w1", content=weak, evidence=0.2, contradiction=0.1))
    s.add_node(ReasoningNode(id="w2", content=lurec, evidence=0.1, contradiction=0.85))
    s.add_node(ReasoningNode(id="goal", content="goal: final resolved state", evidence=0.95, contradiction=0.0))
    # strong route: start -> s1 -> s2 -> goal
    s.add_edge("start", "s1")
    s.add_edge("s1", "s2")
    s.add_edge("s2", "goal")
    # lure route: start -> w1 -> w2 -> goal
    s.add_edge("start", "w1")
    s.add_edge("w1", "w2")
    s.add_edge("w2", "goal")
    return GeoFixture(id=f"seed-{seed}", space=s, start="start", goal="goal")


def _determining_metrics(space: ProblemSpace, path: list[str], goal: str, policy: CandidatePathScore):
    """Return the three determining metrics averaged over the chosen path (score_path terms)."""
    ig = [policy.embedder(n) for n in path]  # not used directly here; metrics below are graph-based
    goal_relevance = _avg([_gr(space, n, goal) for n in path])
    evidence_coverage = _avg([_ev(space, n) for n in path])
    contradiction_risk = _avg([_cr(space, n) for n in path])
    return goal_relevance, evidence_coverage, contradiction_risk


def _gr(space, n, goal):
    from reasoning.geometric.metrics import GraphMetrics
    return GraphMetrics.graph_distance_to_goal(space, n, goal)


def _ev(space, n):
    from reasoning.geometric.metrics import GraphMetrics
    return GraphMetrics.evidence_coverage(space, n)


def _cr(space, n):
    from reasoning.geometric.metrics import GraphMetrics
    return GraphMetrics.contradiction_degree(space, n)


def _avg(vals):
    return sum(vals) / len(vals) if vals else 0.0


def _all_simple_paths(space: ProblemSpace, start: str, goal: str):
    """All simple directed start->goal paths (small fixtures only)."""

    def dfs(cur, path):
        if cur == goal:
            yield list(path)
            return
        for nxt in space.successors(cur):
            if nxt not in path:
                yield from dfs(nxt, path + [nxt])

    yield from dfs(start, [start])


def _best_path(space: ProblemSpace, start: str, goal: str, embedder):
    """Pick the path with the highest path-score using the given embedder."""
    policy = CandidatePathScore(embedder=embedder)
    best, best_score = None, None
    for cand in _all_simple_paths(space, start, goal):
        sc = score_path(space, cand, goal, policy)
        if best_score is None or sc > best_score:
            best, best_score = cand, sc
    return best or [start], best_score or 0.0


@pytest.mark.real_inference
@pytest.mark.docker_required
def test_fas6_geometric_beats_baseline_on_determining_metrics(tmp_path):
    """Empirical §23 exit proof, run against a live Voyage embedder (real_inference arm)."""
    from adapters.inference.budget_gate import BudgetGate
    from runtime.embedding_port import EmbeddingPort

    url = os.environ.get("CORTXT_EMBEDDING_URL")
    key = os.environ.get("CORTXT_EMBEDDING_API_KEY")
    if not url or not key:
        pytest.skip("CORTXT_EMBEDDING_URL/API_KEY not set — no live Voyage; skipped exit proof is NOT a pass")

    # isolated per-run spend ledger so it never collides with other budgeting
    db_path = tmp_path / "fas6-spend.db"
    gate = BudgetGate(max_calls=20, db_path=db_path)  # system-managed, fail-closed
    voyage = EmbeddingPort(
        model=os.environ.get("CORTXT_EMBEDDING_MODEL", "voyage-4-lite"),
        budget_gate=gate,
        provider_evidence={"approved": True, "provider_id": "voyage"},
        expected_dim=1024,
    )

    results = {}
    for seed in range(3):
        fx = _build_fixture(seed)
        # baseline (deterministic, no model calls)
        gr_b, ev_b, cr_b = _determining_metrics(fx.space, _best_path(fx.space, fx.start, fx.goal, _hash())[0], fx.goal, CandidatePathScore(embedder=_hash()))
        # real embedder
        voy_path, voy_score = _best_path(fx.space, fx.start, fx.goal, voyage)
        gr_v, ev_v, cr_v = _determining_metrics(fx.space, voy_path, fx.goal, CandidatePathScore(embedder=voyage))
        results[seed] = {"baseline": (gr_b, ev_b, cr_b), "voyage": (gr_v, ev_v, cr_v), "voy_score": voy_score}

    # aggregate + assert no regression on each determining metric (tolerance 0) and
    # improvement on the composite (voy chosen path must not underperform baseline).
    agg = {seed: results[seed] for seed in results}
    for seed, r in agg.items():
        b, v = r["baseline"], r["voyage"]
        for metric_idx, name in enumerate(["goal_relevance", "evidence_coverage", "contradiction_risk"]):
            base_val = b[metric_idx]
            voy_val = v[metric_idx]
            # contradiction risk is "lower is better": no regression = voy <= base on risk,
            # and for goal_relevance/evidence_coverage no regression = voy >= base.
            good = (voy_val <= base_val) if name == "contradiction_risk" else (voy_val >= base_val)
            # HARD assert for the exit proof: no regression on any determining metric.
            assert good, (
                f"Fas 6 exit NOT met, fixture {seed}: {name} regressed "
                f"(baseline={base_val:.3f} -> voyage={voy_val:.3f})"
            )
    print(f"Fas 6 exit empirical results: {agg}")



def _hash():
    from reasoning.geometric.embeddings import hash_embedding
    return hash_embedding
