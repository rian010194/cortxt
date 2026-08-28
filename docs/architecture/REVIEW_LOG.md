# Architecture Review Log

Append-only register of changes to **Accepted** Architecture Decision Records
(ADRs). Per the repository's documentation-currency rule, any pull request
that modifies an Accepted ADR must add a row here.

| Date | ADR | Change | PR |
| --- | --- | --- | --- |
| 2026-08-28 | ADR-044 | Accepted - operator approved the Cortxt OS system-surface and first-party app boundary; Work replaces Work Console as the first principal app, Workspace retains its execution-resource meaning, and Activity Center remains a shell-owned attention projection | #448 |
| 2026-08-26 | ADR-042 | Accepted - status Proposed -> Accepted by operator approval 2026-08-26, including a pre-acceptance amendment (A-F) that retains the existing Cortxt OS canvas/window/app-shell model, names Work Console the default app, and canonicalizes the cockpit's role as Execution Inspector (superseding the "Run Inspector" working name) | #401 |
| 2026-08-26 | ADR-042 | Added - Work- and Mandate-First Product Surface with Replaceable Secure Execution (Proposed; product-positioning review, no implementation issue assigned) | #401 |
| 2026-08-24 | ADR-041 | Accepted - status Proposed -> Accepted by operator approval 2026-08-24 | #364 |
| 2026-08-24 | ADR-041 | Added - reopens ADR-015 on the state-ownership dimension only; permits backend state-sync capability as a new route family on the MCP server (ADR-024), opt-in per state category | #364 |
| 2026-08-22 | ADR-040 | Accepted - status Proposed -> Accepted by operator approval 2026-08-22 | #273 |
| 2026-08-22 | ADR-040 | Added - Delivery execution paths and workflow-label invariant (Proposed; issues #259-#262; operator question 2026-08-22) | #272 |
| 2026-08-22 | ADR-039 | Accepted - status Proposed -> Accepted by operator approval 2026-08-22; durable multi-writer store choice remains an open operator decision for build #261 | #267 |
| 2026-08-22 | ADR-038 | Accepted - status Proposed -> Accepted by operator approval 2026-08-22; unblocks builds #259 and #260 | #267 |
| 2026-08-22 | ADR-039 | Added - Execution map concurrency claims and prerequisite ordering (Proposed; issue #251/#265) | #266 |
| 2026-08-22 | ADR-038 | Added - Declarative widget contract and authorized action ports (Proposed; issue #251/#265) | #266 |
| 2026-08-22 | ADR-037 | Accepted - live daemon review-sync transitioned a real GitHub fixture issue to workflow:review through the real gh CLI (issue #252); status Proposed -> Accepted | #254 |
| 2026-08-22 | ADR-037 | Added - MCP review submission daemon synchronization (Proposed; issue #249) | #250 |
| 2026-08-22 | ADR-036 | Accepted - MCP run lifecycle async create/status approved after end-to-end dogfood proof over real MCP stdio with a deterministic engine (issue #247); status Proposed -> Accepted | #248 |
| 2026-08-22 | ADR-036 | Added — MCP asynchronous run creation and Tier-0 status polling (Proposed; issue #245) | #246 |
| 2026-08-22 | ADR-033 | Accepted — MCP mandate key rotation (versioned signing keys, overlap, revocation) approved after implementation + focused/full suite green (issue #241); status Proposed → Accepted | #242 |
| 2026-08-22 | ADR-033 | Added — MCP mandate key rotation (Proposed); follow-up to ADR-032 key-rotation risk; not yet implemented | #229 |
| 2026-08-22 | ADR-035 | Accepted — embeddings provider for Phase 6 (Voyage via EmbeddingPort) approved after live Voyage arm re-run PASS posted as issue #233 AC2 evidence; status Proposed → Accepted | #239 |
| 2026-08-22 | ADR-035 | Added — embeddings provider for Phase 6, Voyage via EmbeddingPort (Proposed); resolves target-architecture §27 #10 (issue #233) | #234 |
| 2026-08-22 | ADR-034 | Accepted — run lifecycle tools approved after implementation + CI confirmation (PR #231); status Proposed → Accepted | #231 |
| 2026-08-22 | ADR-034 | Added — MCP run lifecycle tools (Proposed); records the ADR-032 Expiry/Review-Trigger review as a strengthening (issue #230) | #231 |
| 2026-08-22 | ADR-031 | Amended — contribution policy resolved to DCO (Developer Certificate of Origin) | #228 |
| 2026-08-22 | ADR-032 | Accepted — mandate envelope approved after enforcement of `max_runtime_seconds` as a v1 bound (PR #227); status Proposed → Accepted | #227 |
| 2026-08-22 | ADR-018 | Amended — clarification: exactly-one rule scoped to open work issues with `atlas:map` exemption; workflow label is state not authority (ADR-032 mandate dimension); dispatcher atomicity is single-process with multi-process race open | #223 |
| 2026-08-22 | ADR-031 | Amended — license-file representation: `LICENSE` is the verbatim Apache-2.0 text; project copyright notice moved to `NOTICE` | #221 |
| 2026-08-22 | ADR-021 | Amended — proof-environment identifier reference removed from tracked ADR surface (public-readiness; no decision change) | #221 |
| 2026-08-22 | ADR-020 | Amended — decision text updated: former proof-environment identifier removed from the tracked ADR surface (public-readiness cleanup) | #221 |
| 2026-08-22 | ADR-015 | Amended — proof-environment identifier redacted from tracked ADR surface (public-readiness; no decision change) | #221 |
| 2026-08-22 | ADR-014 | Amended — proof-environment identifier redacted from tracked ADR surface (public-readiness; no decision change) | #221 |
| 2026-08-21 | ADR-014 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-015 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-016 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-017 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-018 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-019 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-020 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-021 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-022 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-023 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-024 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-025 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-026 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-027 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-028 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-029 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-030 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-031 | Translated to English (public-readiness; no decision change) | #197 |
| 2026-08-21 | ADR-031 | Added — open-source license (Apache-2.0) | #188 |
| 2026-08-21 | ADR-020 | Added — proof-environment naming redaction | #151 |
| 2026-08-16 | ADR-014 | Amended — proof-environment naming per ADR-020 | #151 |
| 2026-08-16 | ADR-015 | Amended — proof-environment naming per ADR-020 | #151 |
| 2026-08-27 | ADR-043 | Added and accepted — global design-system source, generated artifact ownership, consumer boundaries, and conformance gate | Operator approval |
