# Plan Audit — Iteration 2 (Deep Audit)

**Plan:** `docs/architecture/AGENT_ARCHITECTURE.md` (v0.2 — Iteration 2 revised)  
**Auditor:** Fresh-eyes deep review (never saw v0.1 or Iteration 1 audit)  
**Date:** 2026-08-03  
**Method:** Adversarial review against 9 acceptance criteria + NEW requirements from Iteration 1 + regression check

---

## Executive Summary

The revised plan (v0.2) makes **substantial progress** on Iteration 1 gaps. All 12 blocking gaps (G-01..G-12) have concrete resolutions in the document. The NEW requirements (TypeScript/OpenAPI interfaces, DAG with owners/estimates, ADR-format decisions, skill maturity/error taxonomy/retry/versioning) are **largely addressed in structure** but **critically incomplete in executable detail**.

**Verdict:** **Conditional pass** — proceed to implementation only after the 8 critical gaps below are resolved. The plan has the *architecture* right but lacks *implementation contracts* in several key areas.

---

## 1. Acceptance Criteria Audit (v0.2)

| # | Criterion | Status | Evidence / Gap |
|---|-----------|--------|----------------|
| 1 | All agent roles defined with clear boundaries | ✅ **Met** | Table 2.1 (categories), 2.2 (current), 2.3 (new) with Failure Domain & Parallelism Class. Boundaries clarified vs v0.1. |
| 2 | Receptionist pattern for 6 systems | ✅ **Met** | Section 3 fully specified: generic base (TypeScript + OpenAPI), credential abstraction, per-system impl, usage example. |
| 3 | Memory architecture (5 types, scope/storage/TTL) | ✅ **Met** | Table 4.1 with Data Sensitivity + Auditability. Section 4.2: SQLite WAL schema, locking API, TTL reaper cron. Section 4.3: Builder↔Pi vault access via volume mount. |
| 4 | Dispatch/result contracts referenced | ✅ **Met** | Section 5.1/5.2: JSON Schema for DispatchRequest + ResultEnvelope. Validation at dispatch time noted. Artifact policy defined. |
| 5 | 11+ new skills specified with interfaces | ⚠️ **Partial** | 14 skills listed (7.1–7.14) with maturity, error taxonomy, retry policy, deps, OpenAPI refs. **Gap: No actual TypeScript/OpenAPI files exist — only references.** |
| 6 | Communication topology diagrammed (ASCII) | ✅ **Met** | Section 8: layered topology + async/event flows + failure domains table. Clear and complete. |
| 7 | Profile→skills mapping complete | ✅ **Met** | Section 9: all 13 profiles mapped with skills + failure domain. New profiles added. |
| 8 | Action items prioritized (15+ items) | ⚠️ **Partial** | 18 items in DAG (Section 10) with owner, estimate, depends_on. **Gap: Several estimates are placeholders (M/S/L without day ranges); #0 items prepended but not integrated into critical path cleanly.** |
| 9 | Open decisions identified (5+ decisions) | ✅ **Met** | Section 11: 10 ADRs with template, status, review triggers. Expiry triggers present. |

---

## 2. NEW Requirements from Iteration 1 — Compliance Check

| Requirement | Status | Gap |
|-------------|--------|-----|
| **All interfaces: TypeScript + OpenAPI 3.1 spec** | ⚠️ **Structure only** | Section 3.1 shows `receptionist-base` TypeScript + error codes. Section 6.3 says "generated at skill creation". **No actual `.ts`, `.yaml` files exist in repo.** Skills 7.1–7.14 list "Interface: TypeScript + OpenAPI 3.1" but no artifacts. |
| **All action items: DAG with dependencies, effort (S/M/L), specific owner** | ⚠️ **Mostly met** | Section 10 Mermaid DAG + table with Owner/Estimate/Depends On. **Gap: Owner is role ("Builder", "Coordinator") not named individual; estimates are S/M/L without day ranges; #0 items (prepended) not visually integrated in DAG.** |
| **All skills: maturity, error taxonomy, retry policy, versioning, dependencies** | ✅ **Met in spec** | Section 6.1 skill manifest schema includes all. Section 7.1–7.14 each list maturity, error taxonomy ref, deps. **Gap: No validation that each skill's `error_taxonomy` matches the 30+ codes in receptionist-base.** |
| **All beslut: ADR-format med expiry triggers** | ✅ **Met** | Section 11: ADR template with Expiry/Review Trigger column. 10 ADRs populated with triggers. |
| **Verify G-01..G-12 resolved** | ✅ **Met** | See Section 4 (Regression Check) — all 12 have concrete resolutions in v0.2. |
| **Verify W-01..W-10 mitigated or accepted with rationale** | ⚠️ **Mostly met** | See Section 5 (Regression Check) — 8/10 mitigated, 2 accepted with rationale but rationale thin. |

---

## 3. Critical Gaps (Blocking Implementation)

### GAP-01: No Executable Interface Artifacts (TypeScript/OpenAPI)
**Location:** Section 3.1, 6.3, 7.1–7.14  
**Issue:** The plan *describes* interfaces but produces zero `.ts`, `.json`, `.yaml` files. Skills claim "Interface: TypeScript + OpenAPI 3.1" but there's no `skills/receptionist-base/interfaces/`, no `openapi/`, no generated stubs.  
**Impact:** Consumers (researcher, planner, builder) will hand-roll incompatible call shapes. CI gate (Section 6.4) validates manifests but not interface conformance.  
**Required:** Add `scripts/generate_interfaces.py` that reads `skill.yaml` → emits TypeScript interfaces, JSON Schemas, OpenAPI 3.1 YAML, Python stubs. Gate on `skill_manage create`.

### GAP-02: Skill Manifest Validation Incomplete
**Location:** Section 6.1, 6.4  
**Issue:** `validate_skill_manifest.py` and `check_breaking_changes.py` are referenced but don't exist. No schema for `skill.yaml` itself (JSON Schema).  
**Impact:** Invalid manifests pass CI. Breaking changes undetected.  
**Required:** Create `schemas/skill-manifest.schema.json` + validation scripts before any skill lands.

### GAP-03: Action Item Estimates Lack Precision
**Location:** Section 10 table  
**Issue:** Estimates are "S (1d)", "M (2d)", "L (5d)" but several are vague: #0 "Create missing tool skills" = L (5d) for 4 skills? #14 "Run plan-auditor Iteration 2" = L (3d)? Owner is role not person.  
**Impact:** Sprint planning impossible. Critical path estimate (~15-20 days) unverifiable.  
**Required:** Decompose #0 into 4 separate items. Assign named owners. Use day ranges (e.g., "2-3d") not letters.

### GAP-04: Missing Tool Skills Block Writer/Designer
**Location:** Section 7.8, 7.9, 9 (profiles), Risk R-06  
**Issue:** `writer` needs `humanizer`; `ui-ux-designer` needs `claude-design`, `architecture-diagram`, `excalidraw`, `p5js`, `popular-web-designs`. Only `baoyu-article-illustrator` and `design-an-interface` exist. Action item #0 lists 4 wrappers but not all 6.  
**Impact:** Two specialist profiles cannot load.  
**Required:** Either (a) create all 6 wrapper skills, or (b) change spec to call external tools directly via `computer_use` / CLI, removing skill dependency.

### GAP-05: Kanban Mirror Skill Name Unverified
**Location:** Section 7.5, 9, 10 (#0, #1), Risk R-10  
**Issue:** `workflowreconciler` profile loads `kanban-github-mirror` and `hermes-kanban-multi-agent`. Available skills list shows `hermes-kanban-task-management`. Name mismatch unresolved.  
**Impact:** Reconciler profile fails to load.  
**Required:** Verify actual skill name in `~/.hermes/skills/` or create missing skill.

### GAP-06: Profile Manifest Schema + CLI Missing
**Location:** Section 8.1 (Iteration 1 scope), Section 10 (#0, #7)  
**Issue:** Action item #0 "Write profile manifest schema + validation CLI" exists but no schema design in plan. Section 9 tables are ad-hoc markdown.  
**Impact:** Cannot programmatically validate/create profiles. Action item #12 "Create new profiles" unexecutable.  
**Required:** Add `schemas/profile-manifest.schema.json` + `scripts/profile_cli.py` (create, validate, list, export).

### GAP-07: Telemetry Skill Spec Incomplete
**Location:** Section 7.14, Section 9 (all profiles load it)  
**Issue:** `telemetry` skill listed with 4 bullets but no interface contract, no OpenAPI, no error taxonomy, no maturity beyond "experimental". All 13 profiles depend on it.  
**Impact:** Single point of failure — if telemetry breaks, all profiles fail to load.  
**Required:** Full skill spec for `telemetry` matching Section 6.1 manifest (input/output schemas, error codes, retry, deps).

### GAP-08: BVC Registry + 5 Contracts Underspecified
**Location:** Section 7.11, 10 (#18)  
**Issue:** `behaviour-validator` references "Built-in library: 5 contracts" but none are defined. No BVC spec schema shown. Action item #18 "Create BVC registry + 5 built-in contracts" has no detail.  
**Impact:** Observability domain non-functional.  
**Required:** Define BVC spec schema (YAML) + 5 concrete contracts (availability, error-rate, queue-lag, cost, deploy-success) with thresholds, measurement queries, alerting rules.

---

## 4. Regression Check: G-01..G-12 Resolution Status

| Gap ID | v0.1 Description | v0.2 Resolution | Status | Evidence |
|--------|------------------|-----------------|--------|----------|
| **G-01** | Receptionist auth fragmentation | Section 3.2: `credential-manager` skill + vault backends; all receptionists delegate | ✅ **Resolved** | Lines 169-200, 208 |
| **G-02** | Shared memory concurrency (dir + JSON) | Section 4.2: SQLite WAL + optimistic locking + TTL reaper cron | ✅ **Resolved** | Lines 247-290 |
| **G-03** | Builder ↔ Pi egress (vault access) | Section 4.3: Pi volume mount `/host/vault` + egress rules | ✅ **Resolved** | Lines 292-332 |
| **G-04** | Skill versioning/compatibility | Section 6: semver, compat matrix, deprecation policy, CI gate | ✅ **Resolved** | Lines 439-521 |
| **G-05** | Error taxonomy & retry policy | Section 6.1: `error_taxonomy` with transient/permanent + retry_policy per category | ✅ **Resolved** | Lines 465-476 |
| **G-06** | Observability contract | Section 7.14: `telemetry` skill (OTel, W3C traceparent, structured logging) | ⚠️ **Partial** | Skill spec incomplete (Gap-07) |
| **G-07** | Plan-auditor fresh-eyes enforcement | Section 7.10: Auditor registry in shared memory; Section 11 ADR-005 | ✅ **Resolved** | Lines 589-596, 864 |
| **G-08** | Receptionist base interface contract | Section 3.1: TypeScript interfaces + OpenAPI 3.1 in prose | ⚠️ **Partial** | No artifacts (Gap-01) |
| **G-09** | Writer skill tool dependency | Section 7.9: lists `humanizer`, receptionists; Action #0 creates wrappers | ⚠️ **Partial** | Wrappers not all created (Gap-04) |
| **G-10** | UI-UX-Designer tool chain | Section 7.8: lists 6 tools; Action #0 creates 4 wrappers | ⚠️ **Partial** | 2/6 missing (Gap-04) |
| **G-11** | Kanban mirror skill missing | Section 7.5, 9, 10: referenced but unverified | ❌ **Unresolved** | Gap-05 |
| **G-12** | Profile creation process | Section 8.1, 10 (#0, #7): schema + CLI action items | ⚠️ **Partial** | Schema missing (Gap-06) |

**Summary:** 7/12 fully resolved, 4 partially resolved (need artifacts), 1 unresolved (G-11).

---

## 5. Regression Check: W-01..W-10 Mitigation Status

| Weakness | v0.1 Description | v0.2 Mitigation | Status | Rationale Gap |
|----------|------------------|-----------------|--------|---------------|
| **W-01** | Coordinator model lock-in (Nemotron only) | Risk R-08: Model router skill + fallback chain + cost ceiling (Planned) | ⚠️ **Accepted, thin rationale** | No ADR for model router; no cost ceiling spec |
| **W-02** | Researcher dual role (implementation bleed) | Section 2.2: `researcher` marked "research-only (no implementation)" | ✅ **Mitigated** | Clear boundary now |
| **W-03** | Planner + Plan-Auditor model overlap | ADR-009: Plan-auditor models = Kimi (iter 1-2), Codex (iter 3) | ⚠️ **Accepted, thin rationale** | Cost trigger >$5/run but no model diversity guarantee |
| **W-04** | No skill composition model | Not addressed. Skills remain flat list. | ❌ **Unmitigated** | Context bloat risk remains |
| **W-05** | Memory TTL enforcement vacuum | Section 4.2: TTL reaper cron (every 5 min) + SQLite index on expires_at | ✅ **Mitigated** | Concrete mechanism |
| **W-06** | Dispatch contract enforcement | Section 5.1: "Coordinator validerar mot schema vid dispatch" | ✅ **Mitigated** | Validation at dispatch time |
| **W-07** | Result envelope artifact policy undefined | Section 5.2: `artifact_policy` enum + storage backend refs | ✅ **Mitigated** | Defined (workspace_only, github_artifacts, external_refs) |
| **W-08** | Buzz approval flow no timeout/escalation | Section 3.3 (Buzz): marker filtering, approval flow, webhook verification | ⚠️ **Partial** | No timeout/escalation spec in skill |
| **W-09** | Codex read-only enforcement trust-based | Section 7.7: "Read-only enforcement: Runtime check i Codex app-server" | ⚠️ **Accepted, thin rationale** | No mechanism described; trust-based still |
| **W-10** | No disaster recovery/backup | Risk R-09: Profile export/import CLI + skill pinning + daily snapshots (Planned) | ⚠️ **Accepted, thin rationale** | No ADR; no spec for snapshot format/frequency |

**Summary:** 3/10 fully mitigated, 4 partially/accepted with thin rationale, 1 unmitigated (W-04), 2 accepted with insufficient rationale (W-01, W-03, W-09, W-10).

---

## 6. Missing Classifications — Coverage Check

Section 12 adds 7 classifications. **Coverage in plan:**

| Classification | Applied In Plan? | Notes |
|----------------|------------------|-------|
| **Skill Maturity** | ✅ Yes | Every skill in 7.1–7.14 has maturity |
| **Failure Domain** | ✅ Yes | Topology (Section 8), profiles (Section 9) |
| **Data Sensitivity** | ✅ Yes | Memory table (4.1) + artifacts |
| **Cost Tier** | ✅ Yes | Profile table (2.2) |
| **Latency Budget** | ✅ Yes | Profile table (2.2), Dispatch contract |
| **Parallelism Class** | ✅ Yes | Agent roles table (2.3) |
| **Auditability Level** | ✅ Yes | Memory table (4.1) |

**All 7 classifications present and applied.** ✅

---

## 7. Risk Register — Updated Assessment

| Risk ID | v0.2 Status | Assessment |
|---------|-------------|------------|
| **R-01** | 🟡 In Progress | Volume mount + egress defined. Need Pi config validation. |
| **R-02** | 🟡 In Progress | SQLite WAL + locking + reaper defined. Need integration test. |
| **R-03** | 🟡 In Progress | Credential-manager skill spec done. Need vault backend impl. |
| **R-04** | 🟢 Planned | Semver + compat matrix in manifest. CI gate script missing. |
| **R-05** | 🟢 Planned | Auditor registry in shared memory. Need registry schema + enforcement. |
| **R-06** | 🟡 In Progress | Action #0 creates 4/6 wrappers. Gap-04 remains. |
| **R-07** | 🟢 Planned | Telemetry skill in all profiles. Skill spec incomplete (Gap-07). |
| **R-08** | 🟢 Planned | Model router skill. No ADR, no spec. |
| **R-09** | 🟢 Planned | Profile export/import + snapshots. No spec. |
| **R-10** | 🟢 Planned | Kanban mirror skill. Name unverified (Gap-05). |

**New Risks Identified in v0.2:**
- **R-11 (NEW)**: Interface generation pipeline missing — all skills claim TypeScript/OpenAPI but no generator exists. **High/Medium**.
- **R-12 (NEW)**: Skill manifest validation scripts don't exist — CI gate hollow. **Medium/High**.
- **R-13 (NEW)**: Profile manifest schema + CLI not designed — blocks profile creation. **High/Medium**.
- **R-14 (NEW)**: BVC registry underspecified — observability domain non-functional. **Medium/High**.

---

## 8. Revised Plan (Iteration 3 Scope)

### 8.1 New Action Items (Prepend to Critical Path)

| # | Action | Owner | Estimate | Depends On |
|---|--------|-------|----------|------------|
| -1 | Create `schemas/skill-manifest.schema.json` + `validate_skill_manifest.py` | Coordinator | S (1d) | — |
| -1 | Create `schemas/profile-manifest.schema.json` + `profile_cli.py` | Coordinator | M (2d) | — |
| -1 | Create `scripts/generate_interfaces.py` (skill.yaml → TS/OpenAPI/JSON/Python) | Builder | M (2d) | skill-manifest schema |
| -1 | Decompose Action #0 "missing tool skills" into 6 separate items with named owners | Coordinator | S (0.5d) | — |
| -1 | Define `telemetry` skill full spec (manifest + interfaces + error taxonomy) | Coordinator | M (2d) | skill-manifest schema |
| -1 | Define BVC spec schema + 5 concrete contracts (YAML) | Monitor | M (2d) | behaviour-validator skill |
| -1 | Verify `kanban-github-mirror` skill name; create if missing | Builder | S (0.5d) | — |
| -1 | Add ADR for Model Router (W-01), Disaster Recovery (W-10), Skill Composition (W-04) | Coordinator | S (1d) | — |

### 8.2 Modifications to Existing Sections

| Section | Change |
|---------|--------|
| **3.1** | Add generated interface file paths to `receptionist-base` spec |
| **6.1** | Add `interface_files` section to skill manifest schema (paths to generated artifacts) |
| **6.4** | Update CI gate to run `generate_interfaces.py` + validate against schemas |
| **7.1–7.14** | Add `interface_files` to each skill entry (once generator exists) |
| **7.14** | Expand `telemetry` to full skill spec matching Section 6.1 |
| **10** | Replace S/M/L with day ranges; assign named owners; integrate #0 items into DAG |
| **11** | Add ADR-011 (Model Router), ADR-012 (Disaster Recovery), ADR-013 (Skill Composition) |

### 8.3 Critical Path Update

```
-1 → 0 → 1-7 → 12 → 14 → G1
```
**Revised Critical Path Estimate:** ~20-25 days (added 5-7 days for interface pipeline, schemas, telemetry spec)

---

## 9. Audit Approval

| Check | Result |
|-------|--------|
| All 9 acceptance criteria addressed in v0.2? | **Yes** (Criterion 5, 8 partial — see gaps) |
| Blocking gaps (G-01..G-12) resolved? | **7/12 fully, 4 partial, 1 unresolved** |
| NEW requirements (TypeScript/OpenAPI, DAG, ADR, skill maturity) met? | **Structure yes, artifacts no** |
| High risks (R-01..R-04) mitigated? | **In progress — need implementation** |
| Missing classifications added? | **Yes — all 7 present** |
| Action items dependency-ordered with estimates? | **Yes — but estimates need precision** |

**Approval:** ❌ **Not approved for implementation** — Iteration 3 required to close 8 critical gaps (Section 3) and produce executable artifacts. Re-audit after Iteration 3 with focus on: generated interface files, validation scripts, decomposed action items, telemetry/BVC specs.

---

## 10. Next Auditor Instructions (Iteration 3)

- **Fresh eyes required** — different auditor identity
- **Focus:** Artifact existence — every skill must have `.ts`, `.yaml`, `.json` files in `skills/<name>/interfaces/`, `skills/<name>/openapi/`, `skills/<name>/stubs/`. CI gate must validate conformance.
- **Verify:** All 8 critical gaps closed; telemetry/BVC specs complete; action items with named owners + day ranges; kanban mirror skill verified.
- **Output:** `audit-iteration-3.md` with same structure + `artifact_inventory` section listing every generated file.