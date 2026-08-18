⚠️ **ASSESSMENT ONLY — DO NOT MERGE**

This issue provides risk/benefit assessment for merging
(spec/fas8-controlled-learning-loop) to (main).

**Do not merge this branch without explicit operator approval.**

## Current state

| Item | Value |
|---|---|
| Branch | spec/fas8-controlled-learning-loop (current) |
| Base for merge | main |
| Commits ahead | 102 commits |
| Files changed (unique) | ~40+ files in agent-platform/, adapters/, docs/, .github/ |
| Total lines added | ~1500+ |
| Total lines removed | ~150+ |

## Fas 5-8 scope (from branch history)

1. **Learning Loop foundation (Task 1-2)**: Candidate datamodel, CandidateRegistry (SQLite), submit_candidate, EvidenceClassifier, PromotionGate
2. **Evidence processing (Task 3-4)**: EvidenceClassifier phase(a/b), Evaluator, EvidenceMatrix
3. **RLM/Geometric reasoning (Task 5-7)**: geometric reasoning support, Voyage embeddings, self-hosted inference hooks
4. **Supervisor/Controller (Task 8)**: policy-candidate adapter, policy-constraint safety rules

## Conflict analysis (branch vs main)

### High-risk areas (likely conflicts)
- `agent-platform/learning/` — NEW module on spec branch, main has no learning module → **NO CONFLICT**
- `agent-platform/runtime/selfhosted_*.py` — exists on both, different implementations → **CONFLICT LIKELY**
- `agent-platform/supervisor/budget.py` — minor diffs expected
- `agent-platform/reasoning/geometric/` — Fas B changes on spec branch

### No conflicts expected
- `agent-platform/context_store/` — accepted per ADR-017, exists on main
- `agent-platform/supervisor/coordinator.py` — Fas 4 Supervisor, exists on main
- `agent-platform/runtime/rlm_child_cli.py` — Fas 4 state ledger, exists on main

## Risk summary

| Risk | Severity | Notes |
|---|---|---|
| Git merge conflicts | MEDIUM | `agent-platform/runtime/selfhosted_*.py` likely to conflict; `agent-platform/supervisor/budget.py` possible |
| Breaking changes to main | LOW-MEDIUM | spec branch adds new learning module; no breaking changes to existing Fas 2-4 modules |
| CI/test breakage | LOW | All tests pass on spec branch (verified per commit history) |
| Revert difficulty | LOW | Git merge is atomic; can be reverted with `git revert` or `git reset` |

## Recommendation

**Assessment (not execution):**

- **Risk level:** MEDIUM (merge conflicts expected, but resolvable)
- **Impact:** LOW (adds new functionality, no breaking changes)
- **Suggested workflow:**
  1. Operator reviews this assessment
  2. Operator approves merge (explicit approval required per AGENTS.md)
  3. PR created from spec/fas8-controlled-learning-loop → main
  4. Codex review for architectural correctness
  5. Operator merges after Codex sign-off

## Merge procedure (when approved)


**CRITICAL:** This merge is an irreversible decision. It must be approved by the operator (Rikard) and NOT performed by an agent.

**Labels:** workflow:ready, type:risk-assessment, wedge-b
