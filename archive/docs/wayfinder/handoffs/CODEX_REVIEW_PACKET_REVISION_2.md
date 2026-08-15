---
attachment_id: 3d1e24cb-0d32-4cee-aff8-561741c519f5
sha_256_expected: 6993573D493E56085E92F3F4CC8BE23365724EEAEAAFD5E5C911B013EEF586B6
revision: 2
verified_by_coordinator: 2026-08-11
---

# REVISION 2 — FINAL FOR CODEX VERIFICATION

**Reviewer instruction (mandatory):**
1. Bekräfta att detta paket börjar med exakt rubriken `PLANNING RESULT: READY_FOR_CODEX_REVIEW (second revision)`.
2. Bekräfta att `attachment_id` ovan är `3d1e24cb-0d32-4cee-aff8-561741c519f5`.
3. Om rubrik eller ID inte stämmer: returnera `UNVERIFIABLE` och stoppa.
4. Om de stämmer: granska ENDAST denna revision. Ignorera alla tidigare revisioner och tidigare Codex-utlåtanden.

---

PLANNING RESULT: READY_FOR_CODEX_REVIEW (second revision)

---

## Objective
Prepare an implementation-ready, provider-neutral UI/UX specification for the existing `web/` prototype and a bounded Release 1 plan for a deployed, read-only operator cockpit preview.

## Hard constraints
- Stage 1 is planning only: zero repository edits, zero GitHub mutations, zero deployment.
- Release 1 is read-only preview: no browser-side credentials, no dispatch/approval/merge/close/Done/deploy mutations.
- Preserve useful prototype work; replace product-bound IA, false liveness, unsafe future assumptions.
- Coordinator proposes; Codex reviews; operator approves.

## Authoritative sources and freshness
- `AGENTS.md` — read 2026-08-11
- `docs/agents/current-operating-model.md` — read 2026-08-11
- `docs/architecture/dispatch-contract.md` — read 2026-08-11
- `docs/architecture/runtime-and-evaluation-harness.md` — read 2026-08-11
- `docs/agents/issue-tracker.md` — read 2026-08-11
- `C:/Users/rikar/Cortxt/leverantorsneutral-dynamisk-routing-malarkitektur-v2.md` — read 2026-08-11
- `docs/architecture/operator-cockpit-ui-ux-plan-2026-08-11.md` — read 2026-08-11
- `docs/agents/domain.md` — read 2026-08-11
- `web/README.md`, `web/PHASE2_PLAN.md`, `web/package.json`, `web/vite.config.ts` — read 2026-08-11
- All `web/src/` source files — read 2026-08-11
- GitHub issue #54 body — fresh read-back 2026-08-11 (body: "Codex-U3. Assess.tsx:127 — allt utom prohibited/high_risk får badge-green, inkl. uncertain (missvisande positivt). Fix: använd riskStyles-mappning; uncertain egen (neutral/gul) stil. AC: uncertain visas inte som grön.")
- GitHub Project 4 items — fresh read-back 2026-08-11 (#22, #54, #57, #58, #71 in Inbox)

## Current-state inventory
- Vite/React/TypeScript/Tailwind prototype; 9 routes; BrowserRouter; no live data integration.
- `web/dist/` exists but stale; no SPA fallback on server.
- Lint passes with 2 warnings.
- **False liveness:** `Layout.tsx:50-54` — pulsing green dot + hard-coded "Coordinator: kimi-k2.6".
- **#54 — two green-badge bugs:**
  1. `Assess.tsx:122` — `uncertain` risk class → `badge-green` (covered by existing #54 body).
  2. `Assess.tsx:215` — `ai_act_applies: false` always → `badge-green`, **ignoring confidence** (NOT covered by existing #54 body; planning finding).
- **Both cost functions return 0 for unknown:**
  - `systemData.ts:445` — `calculateCost` returns `{ amount: 0, ... }` for unknown profile.
  - `systemData.ts:459` — `estimateRunCost` returns `{ amount: 0, ... }` for unknown profile.
- **Responsive broken:** `Layout.tsx:23` fixed `w-64` sidebar + `ml-64` main, zero breakpoints.
- **Visual verification:** Desktop partially verified at 1264×569; tablet and mobile **VISUALLY_UNVERIFIED**.

## Proposed information architecture and page decisions
- Remove: Overview, Flow, Agents, Kanban, Dispatch.
- Keep/rename: Skills → Capabilities; Telemetry → Economics; Verticals → keep; Assess → keep under Verticals, fix #54 (both badges).
- Add: Decision Queue, Work, Runs, Routes, Evidence, Policy.
- Navigation: 9 items reflecting operator jobs, not products.

## Bounded Release 1 — Builder Run 1 (single coupled code package)

| Field | Value |
|---|---|
| Scope | UI-002 (responsive shell + design system) + #54 fixes + false liveness removal |
| Files | `Layout.tsx`, `Assess.tsx`, `systemData.ts` (cost functions only) |
| Worker | Builder (Kimi) |
| Runtime | Pi Builder container or local `web/` workspace |
| Max runtime | 1800 seconds |
| Max cost | $1.00 USD |
| Dependencies | None (self-contained) |

**AC for Builder Run 1:**
1. Sidebar false liveness removed; explicit `Preview / static data` banner + last-updated timestamp.
2. #54 risk-class badge: `uncertain` → warning amber (not green).
3. #54 applicability badge: `uncertain`/`needs_more_info` → warning amber + `AlertTriangle` icon (not green).
4. Both `calculateCost` and `estimateRunCost` return `null`/`unknown` for unknown profiles; UI renders `—`.
5. Deterministic test: fixture `v01-syn-unc-001` produces amber badges for both risk and applicability.
6. Lint passes with zero new warnings.

**UI-004, UI-005, UI-006 remain in Inbox** until backend contracts (#57, #58, #71) are ready.

## Hosting comparison (revised with verified facts)

| Criterion | GitHub Pages | Vercel Hobby/Standard | Vercel Pro/Enterprise | Cloudflare Pages |
|---|---|---|---|---|
| SPA deep-link | Requires `404.html` = `index.html` hack or HashRouter switch | Native via config | Native via config | Native (`not_found_handling = single-page-application`) |
| Preview URL protection | N/A (public) | Vercel Authentication — password/SSO on preview and deployment URLs | Advanced SSO options | Cloudflare Access (separate Zero Trust org, up to 50 users free) |
| Production domain protection | **Public only** on free repos; private requires GitHub Enterprise Cloud | **Public** — production domain not protected on Hobby/Standard | Deployment Protection available — can restrict production domain | Public default; Access can restrict production |
| Custom domain / TLS | Supported | Supported | Supported | Supported |
| Account requirement | Existing GitHub | New Vercel account | Paid plan | New Cloudflare account |

**Audience/auth (private vs public) is a preceding operator gate.** No hosting selection before this is decided.

## Exact proposed issue mutations matrix (revised)

**Total mutations: 0**

| # | Target | Before | After | Rationale | Dependency | Worker | Runtime | Cost | Risk | Rollback | Gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | #22 title | `Operator cockpit: visualisering och integration` | `Operator cockpit: provider-neutral read-only preview (epic)` | Align with V2 | #91 | Coordinator | Kimi | $0 | Low | Restore exact pre-image from `docs/wayfinder/handoffs/pre-image-#22-<timestamp>.md` | Operator |
| 2 | #22 body | Phase 2 Sessions A/B/C | New body: Release 1 non-goals, canonical IA, AC, child list | Remove unapproved steps | #91 | Coordinator | Kimi | $0 | Low | Restore exact pre-image | Operator |
| 3 | #22 labels | none | `wayfinder:task` | Align convention | — | Operator | — | $0 | Low | Remove label | Operator |
| 4 | #23 state | `OPEN` | `CLOSED` as `not_planned` | Consolidate into #22 | #22 rescoped | Coordinator | — | $0 | Low | Reopen and restore original state | Operator |
| 5 | #23 comment | none | "Closed: consolidated into #22 / UI-005" | Record decision | — | Coordinator | — | $0 | Low | Delete comment | Operator |
| 6 | #43 state | `OPEN` | `OPEN` (retain) | #54 not yet reconciled | #54 resolved | — | — | $0 | Low | — | Operator closes after evidence |
| 7 | **#54 body** | `Codex-U3. Assess.tsx:127 — allt utom prohibited/high_risk får badge-green... AC: uncertain visas inte som grön.` | **Append:** `AC-2: applicability badge (Assess.tsx:215) uses confidence-aware colouring; uncertain/needs_more_info → warning amber + AlertTriangle icon, never green. AC-3: deterministic test fixture v01-syn-unc-001 produces amber for both risk-class and applicability badges.` | Extend AC to cover second bug found in planning | — | Coordinator | Kimi | $0 | Low | Restore exact pre-image of body | Operator |
| 8 | #54 state | `OPEN` | `OPEN` (retain until Builder Run 1 completes) | Fix both bugs in Run 1, then close with evidence | — | Builder | Kimi | <$0.50 | Low | Revert code | Operator approves fix |
| 9 | Create UI-001 | — | Child of #22: `Information architecture and canonical domain model` | Define new nav, routes | #22 | Coordinator | Kimi | $0 | Low | Close as `not_planned`, remove from Project 4 | Operator |
| 10 | Create UI-002 | — | Child of #22: `Accessible responsive shell and design system` | Sidebar, responsive, focus | UI-001 | Builder | Kimi | <$1 | Low | Close as `not_planned`, remove from Project 4 | Operator |
| 11 | Create UI-003 | — | Child of #22: `Deploy read-only preview` | Build, hosting, rollback | UI-001, UI-002 | Builder | Kimi | <$1 | Low | Close as `not_planned`, remove from Project 4 | Operator |
| 12 | Create UI-004 | — | Child of #22: `Server-side GitHub read model` | GitHub integration | UI-001 | Builder | Kimi | <$1 | Low | Close as `not_planned`, remove from Project 4 | Operator |
| 13 | Create UI-005 | — | Child of #22: `Runs, routes, evidence views` | Contract-backed views | UI-001, #57, #58, #71 | Builder | Kimi | <$1 | Low | Close as `not_planned`, remove from Project 4 | Operator |
| 14 | Create UI-006 | — | Child of #22: `Operator decision queue` | Gate UX | UI-001, #8, #19 | Builder | Kimi | <$1 | Low | Close as `not_planned`, remove from Project 4 | Operator |

**Rollback rule:** Capture exact pre-image (title, body, labels, state, Project 4 status) to `docs/wayfinder/handoffs/pre-image-<issue>-<timestamp>.md` before mutation. Restore exact values on rollback. New issues rolled back by closing as `not_planned` and removing from Project 4.

## Unresolved conflicts, risks and operator decisions
1. **Audience/auth gate:** Private preview (auth required) or public? Must be decided before hosting selection.
2. `domain.md` vs `current-operating-model.md`: profile count, primary surface, coordinator model.
3. **Hosting:** Cloudflare Pages + Access (private) vs GitHub Pages (public, zero new accounts).
4. **#54 scope extension:** Operator must approve extending #54 AC to include applicability badge (or create separate issue).
5. **Builder Run 1 scope:** Operator must approve bounded run (UI-002 + #54 + false liveness) vs. broader scope.
6. **Approval required for #22 rescope and child creation.**

## Relevant file paths and minimal excerpts
- `web/src/components/Layout.tsx:50-54` — false liveness:
  ```tsx
  <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
  Coordinator: kimi-k2.6
  ```
- `web/src/pages/Assess.tsx:122` — #54 risk-class bug:
  ```tsx
  <span className={`badge text-xs ${r.classification.system_risk_class === 'prohibited' || r.classification.system_risk_class === 'high_risk' ? 'badge-red' : 'badge-green'}`}>
  ```
- `web/src/pages/Assess.tsx:215` — #54 applicability bug (planning finding, NOT in original #54 body):
  ```tsx
  <span className={`badge text-xs ${r.applicability.ai_act_applies ? 'badge-red' : 'badge-green'}`}>
    {r.applicability.ai_act_applies ? 'AI-förordningen tillämpas' : 'Tillämpas inte'}
  </span>
  ```
- `web/src/data/systemData.ts:445` — `calculateCost` unknown → 0:
  ```ts
  return { amount: 0, currency: 'USD', breakdown: { input: 0, output: 0 } };
  ```
- `web/src/data/systemData.ts:459` — `estimateRunCost` unknown → 0:
  ```ts
  return { amount: 0, currency: 'USD', profile: workerRole };
  ```
- `web/src/components/Layout.tsx:23` — fixed sidebar breaking responsive:
  ```tsx
  <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col fixed h-screen">
  ```

---

## Reviewer instructions

Act as an independent read-only reviewer. Verify the plan against fresh repository and GitHub evidence. Do not rewrite the plan, edit files, mutate GitHub, deploy or approve an operator action. Return exactly one verdict: GODKÄND or KRÄVER ÄNDRINGAR. Report only actionable P0/P1/P2 findings, each with evidence, impact and the smallest correction. Check provider neutrality, source authority, contract fidelity, security boundaries, accessibility, visual-verification completeness, hosting assumptions, issue duplication and whether Release 1 is genuinely bounded.
