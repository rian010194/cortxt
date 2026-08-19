# ADR-025: Geometric Reasoning's decisive vs. diagnostic metrics (§27 #8)

**Status:** Accepted
**Date:** 2026-08-19
**Deciders:** Rikard (operator, direct dialogue this session); Claude Code (draft)
**Technical Story:** target-architecture.md §27 open decision #8; blocks Fas 6
(Geometric Reasoning v1)'s own exit criterion, which requires this decision
before evaluation (§23, Fas 6 Exit)

## Context

`target-architecture.md` §12.2 lists ten geometric metrics for Fas 6
(semantic closeness, graph distance to goal, evidence coverage, contradiction
degree, centrality, novelty, stability, revisit ratio, path diversity,
information gain), but never says which of them actually drive a decision
versus which are informational. §27 #8 names this gap explicitly, and Fas 6's
own exit criterion (§23) cannot be evaluated until it is resolved: "vilket/
vilka mått i §12.2 som är beslutande... är avgjort innan detta exitkriterium
utvärderas."

Reading the actual v1 implementation
(`agent-platform/reasoning/geometric/{metrics,path_scoring,attractor_detector}.py`)
rather than guessing from the spec text shows the ten metrics already split
cleanly by whether any decision-making code calls them:

**Already decisive** (feed `CandidatePathScore`/`score_path`,
`GraphMetrics.guidance`, or `AttractorDetector`):
- `graph_distance_to_goal` — `score_path` w2=0.40, `guidance` 0.4
- `evidence_coverage` — `score_path` w3=0.30, `guidance` 0.3
- `contradiction_degree` — `score_path` w5=0.50 (largest subtractive weight),
  `guidance` -0.1, and the `policy_risk` threshold
- `novelty` (per-node) — `guidance` 0.2
- `stability` — `guidance` -0.1, and the sole trigger for
  `AttractorDetector`'s attractor classification → `escape_attractor`

**Computed but never consumed by any decision path** (present in
`GraphMetrics`, called only from their own tests):
- `semantic_closeness`
- `centrality`
- `revisit_ratio`
- `path_diversity`
- `information_gain`

A related naming collision surfaced while checking `information_gain`:
`CandidatePathScore.w1` is commented `expected_information_gain` and is
computed as cosine similarity between a candidate node's content and the
goal — it never calls `GraphMetrics.information_gain(space, nid, before,
after)`, which measures a realized confidence delta and requires a "before"
value `ReasoningNode` does not retain any history of. These are two distinct
metrics that happen to share a name in the spec text: `score_path` scores a
*candidate* path that has not been walked yet, so only a prospective
estimate is possible there; `information_gain` is inherently retrospective
and can only be computed once a node's confidence has actually changed.

## Decision

**§27 #8 is resolved by formalizing what the code already does, not by
inventing new weightings:**

1. The five metrics already consumed by `score_path`/`guidance`/
   `AttractorDetector` — `graph_distance_to_goal`, `evidence_coverage`,
   `contradiction_degree`, `novelty`, `stability` — are the **decisive**
   metrics for Fas 6 v1. They may change ranking, path selection, or trigger
   `escape_attractor`.
2. The remaining five — `semantic_closeness`, `centrality`, `revisit_ratio`,
   `path_diversity`, `information_gain` — are **diagnostic only**. They may
   be reported (e.g. via `TrajectoryReport`) but must not silently start
   influencing `score_path`, `guidance`, or attractor detection without a
   new, explicitly versioned policy (`CandidatePathScore.version` bump or
   equivalent).
3. `information_gain` moves from uncalled to a real diagnostic call site:
   `reasoning.geometric.apply_confidence_update(space, nid, new_confidence)`
   computes the realized before/after delta via `GraphMetrics.
   information_gain`, mutates the node's confidence, and returns the gain
   for the caller to record on `TrajectoryReport.information_gains` (new
   field). `CandidatePathScore.w1` keeps its existing cosine-to-goal
   computation as the *expected* (prospective) proxy — its docstring/comment
   now says so explicitly, so the two are not mistaken for one implementation
   again.

## Consequences

### Positive
- Unblocks Fas 6's exit-criterion evaluation, which was explicitly gated on
  this decision.
- No behavior change to `score_path`/`guidance`/`AttractorDetector` — the
  decisive set is exactly what already runs today, so this is a
  documentation-and-contract change plus one new, additive call site
  (`apply_confidence_update`), not a scoring-policy change.
- `information_gain` gets a genuine caller for the first time; the four
  other diagnostic metrics remain honestly labeled as such rather than
  silently dead code presented as if decisive.
- Removes the `w1`/`information_gain` naming collision as a source of future
  confusion (e.g. someone "fixing" `w1` to call the wrong function, silently
  fabricating an `after` value for an unwalked path).

### Negative
- Four of the ten §12.2 metrics (`semantic_closeness`, `centrality`,
  `revisit_ratio`, `path_diversity`) still have no call site anywhere in
  production code, even after this ADR — they remain computed-only until a
  future decision promotes them or removes them. This ADR does not resolve
  that; it only stops mischaracterizing them as decisive.

### Risks
- If a future change adds a real verification step that updates node
  confidence, it must call `apply_confidence_update` (not set
  `node.confidence` directly) to keep `information_gain` reachable and
  `TrajectoryReport` accurate — this is a convention, not something the type
  system enforces.

## Alternatives Considered
1. **Treat all ten metrics as decisive, add the missing five to `score_path`
   with new weights.** Rejected: would require inventing weights with no
   evaluation evidence behind them (violates §12.4's own "vikter och
   trösklar är policydata och ska utvärderas mot fixtures, inte döljas i
   prompttext"), and changes live scoring behavior as a side effect of
   answering a documentation question.
2. **Fabricate a synthetic "before" value so `information_gain` could be
   called from `score_path`.** Rejected: `score_path` evaluates paths that
   have not been walked; any "after" confidence for an unwalked node is
   invented, not measured, defeating the point of a realized-gain metric.
3. **Leave §27 #8 unresolved and evaluate Fas 6's exit criterion anyway.**
   Rejected: the exit criterion (§23) explicitly requires this decision
   first; skipping it would make "measurable improvement without
   regression" ungrounded — improvement against which mix of metrics would
   be unclear.

## Validation
- [ ] Fas 6's exit-criterion evaluation, when it runs, states explicitly
      which of the five decisive metrics moved and by how much — not an
      aggregate score alone.
- [ ] Any future change to `CandidatePathScore`'s weights or to `guidance`'s
      formula that adds one of the four still-diagnostic metrics bumps
      `CandidatePathScore.version` and references this ADR.
- [ ] `apply_confidence_update` remains the only place `ReasoningNode.
      confidence` is mutated after node creation in the geometric-reasoning
      package, so `information_gain` stays measurable rather than
      approximated.

## Expiry/Review Trigger
- Review by: 2026-09-18 (aligned with ADR-022's own review date, since this
  decision feeds directly into whether `route()` can hand off to Geometric
  Reasoning per ADR-022's Context note on target-architecture.md §29.5)
- Trigger: Fas 6's exit-criterion evaluation actually runs and finds one of
  the five decisive metrics insufficient on its own, OR one of the four
  still-diagnostic metrics gets a concrete proposed use that would promote
  it to decisive.
