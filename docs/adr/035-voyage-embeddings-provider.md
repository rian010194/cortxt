# ADR-035: Embeddings provider for Phase 6 — Voyage via EmbeddingPort (§27 #10)

**Status:** Proposed
**Date:** 2026-08-22
**Deciders:** Rikard Andersson (operator); draft by DSH session (workspace-local, `lab/voyage-embeddings/`)
**Technical Story:** target-architecture.md §27 open decision #10 — "Embeddings
provider for Phase 6 (§12.2 semantic closeness)... Blocking for Phase 6 start";
resolves the missing durable record for a provider choice that is already
implemented and empirically demonstrated

## Context

The geometric reasoning layer defines a provider-neutral embedding surface,
`EmbeddingFn = Callable[[str], list[float]]`, in
`agent-platform/reasoning/geometric/embeddings.py`, with a deterministic
`hash_embedding` stub explicitly documented as a test harness to be replaced
"later via the same EmbeddingFn surface". The two consumers are
`reasoning.geometric.path_scoring.CandidatePathScore.embedder` (the only
production call site; its `w1` = expected information gain, a cosine-to-goal
over node content, is a decisive term in `score_path` per ADR-025) and
`GraphMetrics.semantic_closeness(..., embedder=...)` (diagnostic only per
ADR-025).

target-architecture.md §27 #10 marks the embeddings-provider choice as open
and "Blocking for Phase 6 start". The choice was in fact made and exercised
in code: `agent-platform/runtime/embedding_port.py` (`EmbeddingPort`, added in
commit `14c2d56`, on main) is a real, fail-closed, budget- and
provider-policy-gated caller of an OpenAI-compatible `/embeddings` route, and
is itself an `EmbeddingFn` drop-in for `hash_embedding`. The Phase 6 empirical
exit criterion (`agent-platform/tests/harness/eval/test_fas6_exit_criterion.py`,
locked fixture seed 3) ran its live Voyage arm and PASSED on 2026-08-17
(commit `3c3d5c5`; Kimi review GODKAND, commit `ebfe041`): the real embedder
corrected the hash baseline's semantic mis-ranking on a graph-wise equal
tie-break fixture. No ADR records any of this; the decision exists only as
code and commit history, and target-architecture.md still lists the decision
as open.

## Decision

**Voyage AI is the selected embeddings provider for Phase 6 geometric
reasoning.** This ADR formalizes what is already built and demonstrated; it is
a decision record, not a new implementation.

1. **Provider interface.** Embeddings are consumed through an OpenAI-
   compatible `POST {base_url}/embeddings` endpoint
   (`https://api.voyageai.com/v1`), bearer-token auth, input as an array of
   strings. Credentials and configuration come ONLY from environment
   variables — `CORTXT_EMBEDDING_URL`, `CORTXT_EMBEDDING_API_KEY`,
   `CORTXT_EMBEDDING_MODEL` — never hardcoded and never committed, matching
   the `TextInferencePort`/`ResilientInferencePort` credential discipline.
2. **Implementation.** `runtime.embedding_port.EmbeddingPort` is the
   provider adapter. It is itself an `EmbeddingFn`, so it drops into
   `CandidatePathScore.embedder=` and `semantic_closeness(embedder=)` in
   place of `hash_embedding` without interface changes. It is fail-closed:
   provider-policy denial, missing config, invalid response, dimension
   mismatch (`expected_dim`), and non-success envelopes raise
   `EmbeddingError`; redirects are blocked; responses are size-capped;
   calls are L0 read-only and idempotent through the same
   `cortxt-resilient-inference` runner contract as chat calls.
3. **Model family.** The existing exit fixture defaults to `voyage-4-lite`
   with `expected_dim=1024`. The exact model id is operator-selected at run
   time (env `CORTXT_EMBEDDING_MODEL`); the fixture default is the reference
   until a catalog check confirms it. Pricing is not web-verified this
   session; embeddings tokens are fractions of a cent per million, so the
   Phase 6 live arm (~6-10 unique calls) costs fractions of a cent.
4. **Status relative to ADR-025.** `semantic_closeness` remains diagnostic.
   The decisive composite already includes the embedding-dependent `w1`
   term, so swapping the embedder in production reasoning changes scoring
   behavior and is therefore a versioned policy change
   (`CandidatePathScore.version` bump) gated on the Phase 6 exit evidence,
   which already exists as a PASS.
5. **Default remains `hash_embedding`.** Production reasoning keeps the
   deterministic stub by default. Real embeddings are used where a run,
   evaluation, or tool explicitly selects `EmbeddingPort` (configured via
   env), so the verified operational path never depends on a live provider.

## Consequences

### Positive

- Closes §27 #10, formally unblocking Phase 6 start, with the provider
  choice recorded as a reviewable decision instead of implicit code.
- The Phase 6 exit evidence becomes reproducible: the locked fixture's live
  arm can be re-run (`pytest -m real_inference` with `CORTXT_EMBEDDING_*`
  set) and posted as issue evidence.
- A real embedder is available as a drop-in for every future consumer
  (reasoning runs, docs query, review-evidence similarity) without new
  adapter work.

### Negative

- `agent-platform/runtime/` remains untracked in the ADR index sense until
  its own vertical slice; this ADR records the provider choice, not a
  package acceptance.
- Real embeddings add a live-provider dependency wherever they are enabled;
  the fail-closed behavior means an unconfigured or denied environment
  raises instead of degrading silently.

### Risks

- Voyage model availability, dimension, or pricing changes over time —
  mitigated by env-selected model id and `expected_dim` enforcement.
- Promoting `semantic_closeness` to decisive without a new versioned policy
  would violate ADR-025 — the promotion rule is restated here deliberately.
- The live arm's PASS is recorded only in commit history until re-run as
  issue evidence in the current baseline.

## Alternatives Considered

1. **Keep `hash_embedding` only.** Rejected: it provides no semantic
   closeness, and the exit proof shows a real embedder measurably improves
   path selection on a graph-wise equal fixture.
2. **Local embedding model (e.g. sentence-transformers).** Deferred: Phase 7
   (self-hosted inference) is a separate track; Voyage is cheap, drop-in,
   and already exercised. Revisit if provider cost or data-residency policy
   later demands local embeddings.
3. **Defer the decision.** Rejected: the code and evidence already exist on
   main; leaving §27 #10 open misrepresents the system's state and blocks
   Phase 6 formally for no reason.

## Validation

- [ ] ADR index row added and §27 #10 updated/closed in target-architecture.md.
- [ ] Re-running the locked fixture's live arm with `CORTXT_EMBEDDING_*` set
      reproduces the PASS (voyage scores the semantically-relevant branch
      above the lure; skipped real arm is NOT a pass).
- [ ] `EmbeddingPort` drop-in compatibility remains covered by
      `tests/runtime/test_embedding_port.py` (network-free).
- [ ] Any production use of real embeddings names `EmbeddingPort` explicitly
      and keeps `hash_embedding` as the default; any change to the decisive
      composite from the swap bumps `CandidatePathScore.version`.

## Open Questions

- Exact Voyage model id and dimension for production use (fixture default
  `voyage-4-lite` / 1024; confirm against the current Voyage catalog).
- Whether the Voyage key lives in CredentialBroker (`cortxt credentials`) or
  only as env vars for the eval arm — the eval arm requires only env.
- Which consumer slice ships first (reasoning-run wiring vs docs query vs
  review-evidence similarity) and whether `semantic_closeness` should be
  promoted to decisive in a later versioned policy once production reasoning
  consumes real embeddings.

## Expiry/Review Trigger

- Review before production reasoning uses a real embedder by default.
- Revisit on Phase 6 re-evaluation, on Voyage model/API changes, or when a
  consumer slice proposes promoting `semantic_closeness` per ADR-025's
  trigger.
