# ADR Index (Architecture Decision Records)

Authoritative index of the architecture decisions in this repo. Status per the decision-state rule in
`docs/style-guide.md` / the ADR pattern: **Accepted** = normative within its scope; **Proposal** = reviewable
proposal, not implementation authority; **Superseded** = historical reference, replaced by newer decisions.

Updated: 2026-08-27 (ADR-043 accepted by operator approval: one global design-system source and explicit consumer contract). Previously updated 2026-08-26 (ADR-042 accepted by operator approval, including the pre-acceptance amendment retaining the Cortxt OS canvas/window/app-shell model and naming the cockpit's role Execution Inspector).

| # | Title | Status | Notes |
| --- | --- | --- | --- |
| 011 | Model Router for Coordinator Fallback | **Superseded** (ADR-017) | Predates F0/F1; static fallback chain replaced by provider-neutral inference (ADR-016) + reasoning (ADR-017) |
| 012 | Disaster Recovery for Profiles, Skills, and Memory | **Superseded** (ADR-017) | Predates F0/F1; portability shifts toward Cortxt-owned ports/state |
| 013 | Skill Composition Model | **Superseded** (ADR-017) | Predates F0/F1; static skill-pack model replaced by provider-neutral architecture |
| 014 | Cortxt Product Vision and First User (F0) | **Accepted** (amended 2026-08-16 for proof-env naming per ADR-020) | Product vision + first user |
| 015 | Cortxt First Wedge and Product Surface (F1) | **Accepted** (amended 2026-08-16 for proof-env naming per ADR-020) | Wedge B: provider-/data-class-driven long-running analysis; repository+CLI |
| 016 | Agent Platform bounded context, InferencePort and provider-assurance | **Accepted** (amended 2026-08-14 for reasoning/ per ADR-017) | Bounded context + InferencePort + data-class→gate; reasoning/ now tracked/Accepted |
| 017 | Agent Platform — reasoning core accepted as tracked architecture | **Accepted** (post-review) | Vertical slice DM1–4 (PR #113, commit `09f1d8a`) proves the need; `agent-platform/reasoning/` → tracked |
| 018 | Workflow-state carrier — GitHub Issue labels | **Accepted** | `workflow:*` labels are the state carrier (ADR-018); Project 4 frozen legacy |
| 019 | Coding execution — permanent multi-engine routing, not Pi/Hermes replacement | **Accepted** | Pi/Hermes/Codex (+ future Copilot) permanent routing choices alongside own Coding Agent; supersedes the §24.2 replacement criteria in target-architecture.md |
| 020 | Proof environment naming — redact product/partner name from public surface | **Accepted** | Terminology redaction: the former internal proof-environment identifier → "proof environment B" going forward; ADR-014/015 substance remains Accepted (2026-08-22: identifier removed from the tracked ADR surface) |
| 021 | Reopen ADR-015 for v.02 admin surface + widget UI (F2 treatment) | **Accepted** | ADR-015 review trigger observed; decides only product-surface additions (widget + admin surface on top of CLI), not wedge, naming, security model, pricing, or add-on review; Phase 2+ in the v.02 wayfinder now authoritative |
| 022 | Phase 3 v0.1 — capability manifest shape and engine-selection criteria | **Accepted** | Engine-agnostic capability manifest + deterministic `route()`; resolves ADR-019's open selection-criteria point |
| 023 | Cortxt supports both bottom-up and top-down integration, not one exclusively | **Accepted** | Top-down permanently internal + deliberately bottom-up-consumable outward; decides the direction, not the surface (deferred to Phase 6) |
| 024 | External integration surface takes the form of an MCP server | **Accepted** | Decides ADR-023's deferred surface form: MCP server, not SDK/REST, for the initial slice |
| 025 | Geometric Reasoning's decisive vs. diagnostic metrics (§27 #8) | **Accepted** | Formalizes which of §12.2's ten metrics drive decisions today (5) versus merely report (5); resolves the `w1`/`information_gain` name collision; resolves Phase 6's blocking exit criterion |
| 026 | Engine adapter-registry (Cordis-inspired DI) kept separate from `route()`'s selection | **Accepted** (amended 2026-08-19 for service-broker pattern per ADR-027) | `route()`/`engine_manifest.py` untouched; new `EngineAdapter`/`EngineContext` layer replaces `unified_cli.py`'s if/elif dispatch, not the selection logic |
| 027 | `EngineContext` adopts the service-broker pattern (Cordis §6.2), not exclusive binding | **Accepted** | `engine_id` becomes a broker key that can carry multiple providers without disturbing consumers; v1 builds only the skeleton (one provider = passthrough), no routing policy until a second provider is actually registered |
| 028 | Orchestrator multi-engine resume via opaque per-adapter `session_id`, CodexAdapter added | **Accepted** | `EngineAdapter.invoke()` gains additive `session_id`; `/engine` command in chat-REPL; implemented and merged 2026-08-20 |
| 029 | Unattended daemon credential isolation — allowlisted subprocess-env, shared launch discipline, broker as read-only caller | **Proposed** | Spec-only, not implemented; closes the env-inheritance gap in `invoke_hermes()`/`CodexAdapter.invoke()` and generalizes the Windows shim fix |
| 030 | Plan-vs-actual divergence tracking — YAML-sidecar + explicit-only correlation, ghost markers on real timeline | **Proposed** (Part 1 implemented) | `plan_task_ref` field exists and flows through the pipeline (Part 1, 2026-08-20); reconciliation/rendering (Part 2) still spec-only |
| 031 | Open-source license — Apache-2.0 | **Accepted** | `LICENSE` → verbatim Apache-2.0 (copyright Rikard Andersson); replaces "viewable, not open source"; basis for product packaging/contributions |
| 032 | MCP Tier-1+ tool calls require a signed, nonce-bound mandate envelope, verified before execution | **Accepted** (2026-08-22) | Ed25519 mandate envelope, fail-closed verification inside `call_tool`, durable nonce/budget stores, `max_runtime_seconds` enforced (PR #227); Proposed until 2026-08-22 |
| 033 | MCP mandate envelopes identify versioned signing keys and support overlap and revocation | **Accepted** (2026-08-22) | Key rotation follow-up to ADR-032: schema v2 `kid`, overlap rotation bounded by envelope expiry, revocation denylist before signature work; implemented (issue #241, PR #242) |
| 034 | MCP run lifecycle tools — mandate-bound create/resume/submit_for_review | **Accepted** (2026-08-22) | Step 2 of the MCP research lifecycle (issue #230): `run_lifecycle.py` service, session_state run store, strict schemas, `-32003` error mapping, idempotent review submission; records the ADR-032 review as a strengthening (PR #231); Proposed until 2026-08-22 |
| 035 | Embeddings provider for Phase 6 — Voyage via EmbeddingPort | **Accepted** (2026-08-22) | Resolves target-architecture §27 #10: `runtime/embedding_port.py` (on main) is the fail-closed, budget/policy-gated OpenAI-compatible `/embeddings` drop-in for `EmbeddingFn`; Phase 6 live exit arm PASSED against Voyage 2026-08-17 and re-run/PASSED 2026-08-22 as issue #233 AC2 evidence; `hash_embedding` stays the default until a versioned policy swap |
| 036 | MCP run lifecycle asynchronous create and status polling | **Accepted** | Step 3 of the MCP research lifecycle (issue #245), accepted after real external stdio dogfood evidence with a deterministic engine (issue #247) |
| 037 | MCP review submission daemon synchronization | **Accepted** (2026-08-22) | Step 4 consumes durable review submissions and mechanically transitions their issues to `workflow:review`; accepted after the live transition proof (issues #249 and #252) |
| 038 | Declarative widget contract and authorized action ports | **Accepted** (2026-08-22) | Widget = named allow-listed reads -> typed data -> platform-owned render primitive tree -> named action requests through `cli`/`mcp`/`github-transition` ports; strict versioned validation, explicit capabilities, typed composition with no widening, action-time authorization (ADR-032 for Tier-1+ MCP, operator gate for irreversible effects); no widget code/raw commands/arbitrary access/self-approval (issue #251/#265) |
| 039 | Execution map concurrency claims and prerequisite ordering | **Accepted** (2026-08-22) | Deterministic prerequisite waves + fail-closed pre-flight claims over issue/run/branch/worktree/label/session/engine-session/writer-domain resources; conditional all-or-nothing acquisition, leases with reconciliation, immutable attempt history, fresh blocker checks; disjoint-resource parallelism, driver/observer separation, receipt is a gate not authority; current JSON/process-local guards insufficient for parallel writers — durable store is an explicit operator decision (issue #251/#265) |
| 040 | Delivery execution paths and workflow-label invariant | **Accepted** (2026-08-22) | Three sanctioned paths (dispatched runtime build / coordinator-direct fast fix / docs-ADR materialization) + hard label invariant: a merged delivery PR never leaves its issue at workflow:inbox; Atlas Work kind records kind for rendering only (issues #259-#262; operator question 2026-08-22) |
| 041 | Backend Service Surface Reopens ADR-015 (Surface Dimension Only) | **Accepted** | Permits opt-in remote state behind the existing MCP external surface while preserving CLI-primary interaction and the loopback widget boundary. |
| 042 | Work- and Mandate-First Product Surface with Replaceable Secure Execution | **Accepted** (2026-08-26) | Product hierarchy: durable Workstream authority above replaceable engines/providers/runtimes, expressed inside the existing Cortxt OS canvas/window/app-shell model; Work Console is the default app; Decisions/Evidence/Policies/Atlas/Connections/Execution Inspector are related apps over shared Workstream state; cockpit reframed as Execution Inspector (not "Run Inspector"); retain CLI/MCP/widgets; evaluate OpenShell as optional execution backend; require a continuity proof before broad UI change. |
| 043 | Global design-system source and consumer contract | **Accepted** (2026-08-27) | Platform-owned preset source, generated web artifact, consumer adapters, shared authority/execution grammar, compatibility, and CI conformance. |

## Decisions and Authority

- **The reasoning core** (`agent-platform/reasoning/`) is **tracked/Accepted** per ADR-017, backed by the vertical
  slice DM1–4 in `main` (PR #113, commit `09f1d8a`; 58 pytest, 93 % cov, `test_no_external_deps`).
- **`agent-platform/adapters/` and other agent-platform packages** remain **Proposal/Untracked** until their own
  vertical slices (ADR-016/017).
- **ADR-016** is **Accepted** after amendment 2026-08-14 (partially lifting the untracked-scaffold decision for
  reasoning/); InferencePort + provider-assurance stand.

## Searchable Status

Use `grep -n "Status:" docs/adr/*.md` for the current status per file. No files outside `docs/adr/`
create architectural authority; `docs/style-guide.md` handles module/writing rules.
