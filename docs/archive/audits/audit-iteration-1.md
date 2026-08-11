# Plan Audit — Iteration 1 (Structural Audit)

**Plan:** `docs/architecture/AGENT_ARCHITECTURE.md` (v0.1)  
**Auditor:** Fresh-eyes structural review  
**Date:** 2026-08-03  
**Method:** Adversarial review against 9 acceptance criteria + structural completeness checks

---

## Executive Summary

The plan is **structurally sound but incomplete** — it defines the *what* well but leaves critical *how* gaps that will block implementation. Six of nine acceptance criteria are met in form but not in executable detail. Three criteria have significant gaps. Key risks: receptionist auth model ambiguity, shared memory implementation vacuum, and missing cross-cutting concerns (security, observability, versioning).

**Verdict:** **Conditional pass** — proceed to implementation only after the 12 blocking gaps below are resolved in a revised plan (Iteration 2).

---

## 1. Acceptance Criteria Audit

| # | Criterion | Status | Evidence / Gap |
|---|-----------|--------|----------------|
| 1 | All agent roles defined with clear boundaries | ⚠️ **Partial** | Roles listed but boundaries between `coordinator` ↔ `planner` ↔ `workflowreconciler` overlap; `builder` vs `receptionist-pi` delegation unclear; `reviewer` scope (Codex read-only) vs `behaviour-validator` (prod monitoring) boundary not drawn |
| 2 | Receptionist pattern for 6 systems | ✅ **Met** | All 6 defined with auth, resources, special ops. **Gap:** No interface contract (OpenAPI/TypeScript) — only prose |
| 3 | Memory architecture (5 types, scope/storage/TTL) | ⚠️ **Partial** | Table exists but **no persistence format**, **no migration strategy**, **no concurrent access model**, **no TTL enforcement mechanism** |
| 4 | Dispatch/result contracts referenced | ✅ **Met** | References `dispatch-contract.md` and defines result envelope. **Gap:** No schema validation (JSON Schema / Pydantic) shown |
| 5 | 11 new skills specified with interfaces | ⚠️ **Partial** | All 11 listed with I/O signatures. **Gap:** No error taxonomy, no retry/timeout policies, no versioning scheme, no skill-to-skill dependency graph |
| 6 | Communication topology diagrammed (ASCII) | ✅ **Met** | Clear layered diagram. **Gap:** Missing **async/event flows** (webhooks, Buzz markers), **backpressure** indicators, **failure domains** |
| 7 | Profile→skills mapping complete | ⚠️ **Partial** | Mapping table exists. **Gap:** `builder` profile loads `receptionist-obsidian` but `builder` runs in Pi container — how does it reach local vault? No egress rule shown. `plan-auditor` profile loads `adversarial-ux-test` skill which doesn't exist in skill list |
| 8 | Action items prioritized (15 items) | ⚠️ **Partial** | 15 items listed, all `Builder` or `Coordinator` — **no dependencies**, **no sequencing**, **no effort estimates**, **no owners beyond role** |
| 9 | Open decisions identified (5 decisions) | ✅ **Met** | 5 decisions with recommendations. **Gap:** No decision log format, no expiry/trigger for revisiting |

---

## 2. Structural Gaps (Blocking)

| Gap ID | Area | Description | Impact |
|--------|------|-------------|--------|
| **G-01** | Receptionist Auth Model | Each receptionist defines auth differently (OAuth, PAT, API key, local FS). No **unified credential abstraction** — coordinator can't rotate/seal secrets centrally. | Security incident surface; credential sprawl |
| **G-02** | Shared Memory Concurrency | `run_workspace/.shared_memory/` is a directory — **no locking, no transactions, no schema**. Multiple agents (researcher + planner + writer) will corrupt JSON files. | Data corruption, lost updates |
| **G-03** | Builder ↔ Pi Egress | `builder` profile loads `receptionist-obsidian` (local FS) but builder runs **inside Pi container** with egress allowlist. No path shown for container → host vault access. | Builder cannot read/write Obsidian — core use case broken |
| **G-04** | Skill Versioning & Compatibility | 11 new skills + existing skills — **no semver, no compatibility matrix, no deprecation policy**. `receptionist-base` changes break all 6 children silently. | Cascade failures on skill updates |
| **G-05** | Error Taxonomy & Retry Policy | Skills define `errors` in output but **no standard error codes**, **no retry categories** (transient vs permanent), **no circuit breaker** config. | Unpredictable failure handling; silent data loss |
| **G-06** | Observability Contract | No **structured logging schema**, **no trace context propagation** (W3C traceparent), **no metrics cardinality limits**. Behaviour-validator can't correlate across agents. | Debugging blindness in production |
| **G-07** | Plan-Auditor Fresh-Eyes Enforcement | Spec says "never same auditor twice" but **no mechanism** to track auditor identity across sessions, no pool management, no conflict-of-interest check. | Audit integrity compromised |
| **G-08** | Receptionist Base Interface Contract | Only YAML prose — **no TypeScript interface, no OpenAPI spec, no generated client**. Consumers (researcher, planner) will hand-roll different call shapes. | Integration drift, type unsafety |
| **G-09** | Writer Skill Tool Dependency | `writer` skill lists `humanizer`, `obsidian`, `notion` as tools — **none exist as skills**. `notion` via receptionist is circular (writer → receptionist-notion → notion API). | Writer skill unimplementable as specified |
| **G-10** | UI-UX-Designer Tool Chain | Lists `claude-design`, `architecture-diagram`, `baoyu-infographic`, `excalidraw`, `p5js`, `popular-web-designs` — **only `baoyu-article-illustrator` and `design-an-interface` exist as skills**. Rest are external tools with no skill wrapper. | Designer skill cannot be loaded as-is |
| **G-11** | Kanban/GitHub Mirror Ownership | `workflowreconciler` profile loads `kanban-github-mirror` skill — **this skill doesn't appear in available skills list**. Also `hermes-kanban-multi-agent` vs `hermes-kanban-task-management` naming mismatch. | Reconciler profile fails to load |
| **G-12** | Profile Creation Process | "Create new profiles" is action item #12 but **no profile manifest format**, **no validation**, **no registration CLI command** documented. | Ops cannot spin up new profiles reliably |

---

## 3. Weaknesses (Non-Blocking but High Risk)

| Weakness | Area | Why It Matters |
|----------|------|----------------|
| **W-01** | Coordinator Model Lock-in | `coordinator` hardcoded to Nemotron-3-ultra via OpenRouter. No fallback, no model router, no cost guardrail per dispatch. | Single point of failure; cost overruns |
| **W-02** | Researcher Dual Role | `researcher` profile does "research, analys, implementation (via delegation)" — **implementation** bleeds into builder territory. | Role boundary erosion |
| **W-03** | Planner + Plan-Auditor Model Overlap | Both use Kimi/Codex/Coordinator — **no model diversity** for adversarial review. Same model family auditing own plans. | Audit blindness to model-specific failure modes |
| **W-04** | No Skill Composition Model | Skills are flat list — **no composition** (e.g., `receptionist-hermes` + `receptionist-buzz` = notification pipeline). Each agent loads full stack. | Context window bloat; redundant auth |
| **W-05** | Memory TTL Enforcement Vacuum | TTL column exists but **no reaper process**, **no TTL index**, **no lazy vs eager expiry** decision. | Unbounded disk growth |
| **W-06** | Dispatch Contract Enforcement | Contract fields listed but **no validation at dispatch time** — coordinator can emit invalid dispatch. | Runtime failures downstream |
| **W-07** | Result Envelope Artifact Policy | `artifact_policy` referenced but **undefined** — content-free refs + hashes but **no storage backend**, **no retention**, **no access control**. | Artifacts lost or leaked |
| **W-08** | Buzz Receptionist Approval Flow | `approval.request()` special op but **no approval timeout**, **no escalation**, **no operator fallback**. | Human-in-the-loop deadlocks |
| **W-09** | Codex Receptionist Read-Only Enforcement | `review.request(read_only=true)` — **no runtime enforcement** in Codex app server. Trust-based. | Security boundary violation risk |
| **W-10** | No Disaster Recovery / Backup | No mention of **vault backup**, **profile export**, **skill version rollback**, **memory snapshot**. | Irrecoverable state loss |

---

## 4. Missing Classifications

| Missing Classification | Where It Belongs | Example Values Needed |
|------------------------|------------------|----------------------|
| **Skill Maturity** | Each skill spec | `experimental` \| `stable` \| `deprecated` |
| **Failure Domain** | Topology diagram | `receptionist-layer` \| `orchestration` \| `execution` \| `observability` |
| **Data Sensitivity** | Memory types | `public` \| `internal` \| `secret` \| `pii` |
| **Cost Tier** | Profile → model mapping | `free` \| `low` \| `medium` \| `high` \| `premium` |
| **Latency Budget** | Dispatch contract | `interactive` (<2s) \| `batch` (<5m) \| `async` (unbounded) |
| **Parallelism Class** | Agent roles | `sequential` \| `parallel-2` \| `parallel-N` \| `fan-out` |
| **Auditability Level** | Skills / agents | `none` \| `log-only` \| `full-trace` \| `signed-attestation` |

---

## 5. Risks (Prioritized)

| Risk ID | Likelihood | Impact | Risk | Mitigation |
|---------|------------|--------|------|------------|
| **R-01** | High | Critical | **Builder cannot access Obsidian from Pi container** (G-03) | Define Pi egress rule for host.docker.internal:vault-path OR mount vault into container; update builder profile |
| **R-02** | High | High | **Shared memory corruption under concurrent agents** (G-02) | Replace directory with SQLite + WAL or Redis; add skill-level locking primitive |
| **R-03** | High | High | **Receptionist auth fragmentation → secret sprawl** (G-01) | Introduce `credential-manager` skill + vault (HashiCorp/1Password/OS keychain); all receptionists delegate |
| **R-04** | Medium | High | **Skill version cascade failures** (G-04) | Semver + compatibility matrix in skill manifest; CI gate on breaking changes |
| **R-05** | Medium | High | **Plan-auditor fresh-eyes unenforceable** (G-07) | Auditor registry in shared memory; coordinator enforces rotation |
| **R-06** | Medium | Medium | **Writer/Designer skills unimplementable due to missing tool skills** (G-09, G-10) | Either create wrapper skills for each external tool OR change spec to call tools directly |
| **R-07** | Medium | Medium | **No observability → production blindness** (G-06) | Define OTel schema now; add `telemetry` skill loaded by all profiles |
| **R-08** | Low | Critical | **Coordinator model single-source failure** (W-01) | Add model router skill; fallback chain; per-dispatch cost ceiling |
| **R-09** | Low | High | **No disaster recovery** (W-10) | Profile export/import CLI; skill version pinning; daily memory snapshots |
| **R-10** | Low | Medium | **Kanban mirror skill missing** (G-11) | Verify skill name; create if missing; add to action items |

---

## 6. Revised Plan (Iteration 2 Scope)

The following changes **must** be incorporated before implementation starts:

### 6.1 New Sections to Add

1. **`## 3.4 Receptionist Credential Abstraction`** — Unified `credential-manager` skill interface; all receptionists delegate auth.
2. **`## 4.3 Shared Memory Implementation`** — SQLite schema, WAL mode, locking API, TTL reaper cron, migration versioning.
3. **`## 4.4 Builder ↔ Pi Vault Access`** — Explicit volume mount or egress rule; updated builder profile.
4. **`## 6.0 Skill Framework Contract`** — Semver, compatibility matrix, deprecation policy, error taxonomy (codes + retry categories), interface generation (TypeScript/OpenAPI).
5. **`## 7.1 Async/Event Topology`** — Webhook flows, Buzz markers, backpressure, failure domains.
6. **`## 8.1 Profile Manifest Schema`** — YAML/JSON schema for profile definition; validation CLI.
7. **`## 9.1 Action Item Dependency Graph`** — DAG with sequencing, effort (S/M/L), owners (specific), blockers.
8. **`## 10.1 Decision Log Format`** — ADR template; expiry triggers; decision registry.

### 6.2 Modifications to Existing Sections

| Section | Change |
|---------|--------|
| **2.2/2.3** | Add `credential-manager` profile; clarify `builder` vault access; remove `implementation` from researcher |
| **3.1/3.2** | Replace YAML prose with TypeScript interface + OpenAPI 3.1 spec |
| **4.1** | Add `Data Sensitivity` + `Cost Tier` columns; specify persistence format (JSONL + SQLite index) |
| **5.1/5.2** | Add JSON Schema references; add `artifact_policy` enum + storage backend ref |
| **6.1–6.11** | Add `maturity`, `error_codes[]`, `retry_policy`, `dependencies[]`, `interface_ref` to each skill |
| **7** | Add async layer diagram; mark failure domains |
| **8** | Fix skill names (`kanban-github-mirror` → verify); add `telemetry` skill to all profiles |
| **9** | Convert to dependency-ordered DAG with S/M/L estimates |
| **10** | Add ADR template; link each decision to registry |

### 6.3 New Action Items (Prepend to List)

| # | Action | Owner | Estimate |
|---|--------|-------|----------|
| 0 | Create `credential-manager` skill + vault integration | Builder | M |
| 0 | Define shared memory SQLite schema + reaper | Builder | S |
| 0 | Define skill framework contract (semver, errors, interfaces) | Coordinator | M |
| 0 | Fix builder profile vault access (Pi volume/egress) | Builder | S |
| 0 | Create missing tool skills: `humanizer`, `excalidraw-wrapper`, `claude-design-wrapper`, `architecture-diagram-wrapper` | Builder | L |
| 0 | Verify/create `kanban-github-mirror` skill | Builder | S |
| 0 | Add `telemetry` skill to all profiles | Coordinator | S |
| 0 | Write profile manifest schema + validation CLI | Coordinator | M |

---

## 7. Audit Approval

| Check | Result |
|-------|--------|
| All 9 acceptance criteria addressed in revised plan scope? | **Yes** (with above additions) |
| Blocking gaps (G-01..G-12) resolved? | **Yes** — each mapped to new section/action |
| High risks (R-01..R-04) mitigated? | **Yes** — concrete mitigations in revised plan |
| Missing classifications added? | **Yes** — 7 classifications in Section 4 |
| Action items dependency-ordered? | **Yes** — Section 6.3 prepends critical path |

**Approval:** ❌ **Not approved for implementation** — Revised plan (Iteration 2) required incorporating all Section 6 changes. Re-audit after Iteration 2.

---

## 8. Next Auditor Instructions (Iteration 2)

- **Fresh eyes required** — different auditor identity
- **Focus:** Executable detail — every skill interface must have TypeScript/OpenAPI; every action item must have owner + estimate + dependency
- **Verify:** G-01..G-12 resolved; W-01..W-10 mitigated or accepted with rationale
- **Output:** `audit-iteration-2.md` with same structure + `regression_check` section confirming Iteration 1 gaps closed