# Repository cleanup reconciliation — 2026-08-11

Status: active review packet
Authority: issue #91 / operator approval reference in the initiating Codex task
Last verified: 2026-08-11
Supersedes: the three untracked `mutations-matrix-backlog-recon-001*` drafts

This is the single canonical mutation matrix. Evidence is live GitHub data plus
the cleanup branch, not the older drafts. `Gate` is `NO` for reversible changes
already represented by this PR and `BATCH` for the one consolidated destructive
operator decision. Rollback is `git revert <cleanup commit>` for PR changes and
the captured pre-image for GitHub mutations.

## Live pre-image

- 76 issues: 49 open, 27 closed; 72 Project 4 items.
- Project 4 fields: 14, including generic `Status` and `Workflow Status`.
- Project 4 views: one table named `View 1`, empty filter.
- Labels: 21. Milestones: `Vertical 01 v0.1`, open, 0 open/7 closed issues.
- Open PRs: draft #83 and draft #85. PR #93 is merged at `b8564c2`.
- Remote branches: 22. Integration base: `agent/separate-harness-verticals`
  at `d9cd333` after the post-#93 live fix.
- Checkout pre-image: eight untracked user documents; all remain unstaged.
- Protected #92 lineage is reachable from integration base; scripts
  `codex-artifact-roundtrip.sh` and `codex-artifact-roundtrip-verify.py` are unchanged.

## Open issues

Each row includes current state, evidence, disposition, canonical destination,
dependencies, impact, risk, rollback, gate, and verification.

| ID | Current state / evidence | Disposition | Destination | Dependencies / impact | Risk | Rollback | Gate | Verify |
|---|---|---|---|---|---|---|---|---|
| #6 | Open; cost telemetry overlaps #58/#71 | MERGE | #71 | Preserve Pi-specific residual AC | Medium | Reopen + restore body | BATCH | Issue/PR evidence |
| #7 | Open Wayfinder map | KEEP | #7 | Canonical decision map | Low | N/A | NO | Native children |
| #8 | Open; readiness decisions recorded | KEEP | #8 | Governs Ready | Low | N/A | NO | Body/comments |
| #14 | Open skill/runtime contract | KEEP | #14 | Parent candidate for #15/#68 | Low | N/A | NO | Scope review |
| #15 | Open profile/skill activation | KEEP | #15 | Coordinate with #14/#68 | Low | N/A | NO | Scope review |
| #16 | Open; stale blockers in historical evidence | REVIEW_REQUIRED | #16 | Remove only verified stale dependencies | Medium | Restore relation | BATCH | Native dependency read-back |
| #17 | Open n8n/VPS decision | SUPERSEDE | #63 | Future dispatcher option, not baseline | Medium | Reopen + restore hierarchy | BATCH | Body and operating model |
| #18 | Open recovery/idempotency | KEEP | #18 | Depends on dispatcher contract | Low | N/A | NO | Scope review |
| #19 | Open production-data security gate | KEEP | #19 | Blocks real cases | High | N/A | NO | Scope review |
| #22 | Open operator cockpit | KEEP | #22 | Active planning explicitly protected | High | N/A | NO | Issue/working-tree diff |
| #23 | Open; title says consolidated under #22 | CLOSE_NOT_PLANNED | #22 | Preserve feature detail in #22 | Low | Reopen | BATCH | Cross-link read-back |
| #35 | Open; parallel dispatch verified in operating model | CLOSE_NOT_PLANNED | current operating model | Delivered historical validation | Low | Reopen | BATCH | Evidence paragraph |
| #37 | Open vertical v0.2 parent | KEEP | #37 | Parent of #38-#40 | Low | N/A | NO | Native hierarchy |
| #38 | Open; implementation evidence but prior review finding | REVIEW_REQUIRED | #37 | Do not close without final evidence | Medium | N/A | NO | Comments/commits |
| #39 | Open deterministic eval | KEEP | #37 | Blocks #40 | Low | N/A | NO | AC review |
| #40 | Open routing/cost fixture work | MERGE | #67 | Preserve vertical-specific AC as child | Medium | Restore scope | BATCH | Body diff |
| #41 | Open review-log parent | CLOSE_NOT_PLANNED | #37 | Findings live in executable children | Low | Reopen | BATCH | Child coverage |
| #42 | Open review-log parent | CLOSE_NOT_PLANNED | #48-#52 | Findings live in executable children | Low | Reopen | BATCH | Child coverage |
| #43 | Open review-log parent | MERGE | #54 | Preserve any uncovered UI findings | Medium | Reopen | BATCH | Body comparison |
| #44 | Open review-log parent | CLOSE_NOT_PLANNED | #55-#62 | Findings live in executable children | Medium | Reopen | BATCH | Child coverage |
| #47 | Open prompt policy | KEEP | #47 | Vertical boundary | Medium | N/A | NO | AC review |
| #48 | Open dispatch fail-closed guards | KEEP | #48 | Related #66 | High | N/A | NO | AC review |
| #49 | Open portability/envelope | KEEP | #49 | Related #52/#71 | Medium | N/A | NO | AC review |
| #50 | Open; PR #76 merged | CLOSE_NOT_PLANNED | PR #76 | Delivered, operator closure required | Low | Reopen | BATCH | Tests + PR |
| #51 | Open; PR #78 merged/reviewed | CLOSE_NOT_PLANNED | PR #78 | Delivered | Low | Reopen | BATCH | Tests + PR |
| #52 | Open portability/tooling | KEEP | #52 | Repository tools move is partial evidence | Medium | N/A | NO | AC review |
| #54 | Open Assess display bug | KEEP | #54 | Absorb uncovered #43 findings | Medium | Restore body | BATCH | UI tests |
| #55 | Open Pi workspace security | KEEP | #55 | Config remains unsafe experiment evidence | High | N/A | NO | Security AC |
| #56 | Open; draft PR #85 | KEEP | #56/#85 | Active work protected | High | N/A | NO | PR diff |
| #57 | Open contract constraints | KEEP | #57 | Contracts relocation only | High | N/A | NO | Schema tests |
| #58 | Open; PR #80 merged | CLOSE_NOT_PLANNED | PR #80/#71 | Delivered portion | Low | Reopen | BATCH | PR evidence |
| #59 | Open; PR #79 merged; broader cleanup now #91 | CLOSE_NOT_PLANNED | #91 | Delivered/superseded | Low | Reopen | BATCH | PR evidence |
| #60 | Open manifest links | KEEP | #60 | Validate after moves | Medium | N/A | NO | Governance check |
| #61 | Open skill interfaces | KEEP | #61 | No delivery evidence | Medium | N/A | NO | AC review |
| #62 | Open attribution | KEEP | #62 | Legal verification pending | High | N/A | NO | License evidence |
| #63 | Open routing epic | KEEP | #63 | Canonical provider-neutral epic | Low | N/A | NO | Native hierarchy |
| #64 | Open credential migration | KEEP | #64 | External secret action; no secret inspection | High | N/A | NO | Operator evidence only |
| #65 | Open Pi adapter | KEEP | #63 | Depends #55 | High | N/A | NO | AC review |
| #66 | Open Pi RPC adapter | KEEP | #63 | Depends #65/#48/#49 | High | N/A | NO | AC review |
| #67 | Open routing policy | KEEP | #63 | Canonical for #40 | High | N/A | NO | AC review |
| #68 | Open profile consolidation | KEEP | #63 | Blocked until #65/#66 | Medium | N/A | NO | Comments |
| #69 | Open independent review chain | KEEP | #63 | Parent/policy for #70 | High | N/A | NO | AC review |
| #70 | Open review environment; PR #81 partial | KEEP | #69 | Residual scope remains | High | N/A | NO | Comments/PR |
| #71 | Open reporting | KEEP | #63 | Absorb #6/#58 residual scope | Medium | Restore body | BATCH | AC reconciliation |
| #72 | Open, Todo; pilot not delivered | REVIEW_REQUIRED | #63 | Depends #65/#66 | Medium | Restore status | BATCH | Evidence/AC |
| #73 | Open vendor review | REVIEW_REQUIRED | #63 or archive | No execution evidence | Medium | Reopen/restore | BATCH | Operator decision |
| #74 | Open synthetic vendor pilot | REVIEW_REQUIRED | #63 | Depends policy/vendor decision | Medium | Restore status | BATCH | AC review |
| #91 | Open, Todo; cleanup umbrella | KEEP | #91 | Move to Review only after evidence | High | Restore status | NO | Comment read-back |
| #92 | Open, Workflow Review; PR #93 merged | KEEP | #92 | Protected active review chain | High | N/A | NO | Hash/ancestry/tests |

## Project 4

| Object | Current state / evidence | Disposition | Destination | Dependencies / impact | Risk | Rollback | Gate | Verify |
|---|---|---|---|---|---|---|---|---|
| View `View 1` | Single unfiltered table | RENAME | `Inbox` | Add `Active`, `Blocked`, `Archive` | Low | Rename back/delete new views | NO | GraphQL read-back |
| Field `Workflow Status` | Six required options | KEEP | Sole operational status | All views filter this field | Low | N/A | NO | Field read-back |
| Field `Status` | Todo/In Progress/Done | SUPERSEDE | Hidden/ignored | Cannot be API-deleted safely | Medium | Re-show field | BATCH | View configuration |
| Other 12 fields | Built-in metadata | KEEP | Project 4 | No duplicate semantics found | Low | N/A | NO | Field list |
| 72 items | Four issues absent from live Project query may vary | REVIEW_REQUIRED | One item per issue | Add missing, remove no content | Medium | Remove added item | NO | Issue/project join |

Target filters: `Inbox = Workflow Status:Inbox`; `Active = Ready OR In progress OR Review`;
`Blocked = Blocked`; `Archive = Done`. Generic `Status` is ignored in every view.

## Labels and milestone

| Objects | Current state / evidence | Disposition | Destination | Dependencies / impact | Risk | Rollback | Gate | Verify |
|---|---|---|---|---|---|---|---|---|
| `bug` | Used type label | RENAME | `type:bug` | Map before rename | Low | Rename back | BATCH | Label counts |
| `documentation`,`enhancement`,`question` | Generic types | REVIEW_REQUIRED | `type:task/research/decision` | Per-issue mapping needed | Medium | Restore labels | BATCH | Issue label join |
| `wayfinder:map` | Canonical map type | RENAME | `type:epic` | Preserve #7/#63 distinction in hierarchy | Medium | Rename back | BATCH | Native parents |
| `wayfinder:task/prototype/research/grilling` | Workflow-era types | MERGE | `type:task/research/decision` | Map every use first | Medium | Recreate labels | BATCH | Pre-image JSON |
| `status:blocked`,`status:ready` | Duplicate workflow | DELETE_AFTER_VERIFICATION | Workflow Status | Remove only after mapping | Medium | Recreate labels | BATCH | Zero semantic loss |
| `agent:researcher`,`agent:builder` | Duplicate worker routing | DELETE_AFTER_VERIFICATION | Dispatch request body | Require complete bodies first | High | Recreate labels | BATCH | Dispatch audit |
| `review:codex`,`review_pending`,`integration_review_pending` | Review state/provider labels | MERGE | issue evidence + Workflow Review | Preserve warnings in comments | High | Recreate labels | BATCH | Comment read-back |
| `duplicate`,`good first issue`,`help wanted`,`invalid`,`wontfix` | Unused/unstable generic set | DELETE_AFTER_VERIFICATION | type model or closure reason | Confirm zero use | Low | Recreate labels | BATCH | Search count zero |
| New stable set | Absent | REVIEW_REQUIRED | `type:epic/task/bug/research/decision`, `risk:security` | Create only with mapped usage | Low | Delete new labels | NO | Label list |
| Milestone `Vertical 01 v0.1` | Open; 0 open/7 closed | ARCHIVE | Closed milestone | Release already complete by membership | Low | Reopen | BATCH | Milestone read-back |

## Pull requests and remote branches

| Object | Current state / evidence | Disposition | Destination | Dependencies / impact | Risk | Rollback | Gate | Verify |
|---|---|---|---|---|---|---|---|---|
| PR #83 | Open draft; superseded by merged #84 | CLOSE_NOT_PLANNED | #84 | No unique desired scope after diff verification | Medium | Reopen | BATCH | Patch/reachability |
| PR #85 | Open draft for #56 | KEEP | #85 | Active worktree and unique commits | High | N/A | NO | `git cherry` + PR diff |
| `main` | Stable root branch | KEEP | `main` | Behind integration base by design | High | N/A | NO | Branch protection |
| `agent/separate-harness-verticals` | Current integration base (`d9cd333`) | KEEP | same | Cleanup base | High | N/A | NO | SHA/read-back |
| `agent/fix-56-day1-ops` | Active PR #85 | KEEP | same | Unique active commits | High | N/A | NO | PR head |
| `agent/roundtrip-82-codex-orchestrator` | Head of superseded #83 | DELETE_AFTER_VERIFICATION | merged #84 clean branch | Verify unique commits irrelevant | Medium | Recreate ref at pre-image SHA | BATCH | Reachability/cherry |
| `agent/roundtrip-artifact-92` | PR #93 merged; protected by prompt | ARCHIVE | retain until #92 closed | Do not delete in this batch | High | N/A | NO | SHA ancestry |
| `agent/add-agent-task-issue-form`,`agent/version-pi-builder-poc` | Merged legacy branches | DELETE_AFTER_VERIFICATION | merge commits #2/#4 | Reachability required | Low | Recreate refs | BATCH | `merge-base --is-ancestor` |
| `agent/fix-45-eval-json-semantics*`,`agent/fix-46-bnd001-premise*`,`agent/fix-50-shared-memory*`,`agent/fix-51-59-dryrun-docs`,`agent/fix-51-kanban-buzz-dryrun-clean`,`agent/fix-53-assess-result`,`agent/fix-58-71-envelope-cost*`,`agent/fix-59-docs-clean`,`agent/fix-70-codex-adapter-clean`,`agent/fix-85-utf8-runner`,`agent/roundtrip-82-orchestrator-clean`,`feature/fix-89-roundtrip-artifact` | Merged/superseded branch set | DELETE_AFTER_VERIFICATION | integration base merge history | Preserve exact SHA pre-image | Medium | Recreate each ref | BATCH | Per-ref ancestry/cherry |

Before any deletion, record `refs/heads/<name> <sha>` and prove commits reachable
from a merged branch or merge commit. Recommend repository setting “delete head
branches automatically” only after the operator approves policy change.

## Local files and documentation

| Object(s) | Current state / evidence | Disposition | Destination | Dependencies / impact | Risk | Rollback | Gate | Verify |
|---|---|---|---|---|---|---|---|---|
| `.hermes/dispatch/RUNBOOK.md` | Only tracked runtime-dir file | MOVE | `docs/operations/hermes-dispatch-runbook.md` | Removes runtime/source mixing | Low | Git revert | NO | `git ls-files` |
| `schemas/*.schema.json` | Platform contracts | MOVE | `contracts/` | Update references | Low | Git revert | NO | schema/tests |
| `schemas/*.py` | Executable trace code | MOVE | `harness/adapters/` | No executable code under contracts | Medium | Git revert | NO | Python compile/tests |
| `scripts/shared_memory.py`,`trace_*` + tests | Harness runtime code | MOVE | `harness/adapters/`, `harness/tests/` | Update launch paths | Medium | Git revert | NO | deterministic tests |
| Other `scripts/*.py` | Repository maintenance tools | MOVE | `tools/` | Update docs/workflows | Medium | Git revert | NO | compile/tests |
| `pi/config/workspace.yaml` | Singleton Pi experiment config | MOVE | `experiments/runtime-pi-builder/config/` | Unsafe writable-vault proposal remains historical/blocked by #55 | High | Git revert | NO | #55 + path checks |
| `docs/adr/*` | Decisions mixed with docs layout | MOVE | `docs/decisions/` | Proposed remains clearly proposed | Low | Git revert | NO | docs index |
| Audit iterations 1–3 | Historical audits | ARCHIVE | `docs/archive/audits/` | No authority | Low | Git revert | NO | links |
| Nine tracked handoff files | Historical session evidence | ARCHIVE | `docs/archive/handoffs/` | No authority; untracked revision 3 untouched | Low | Git revert | NO | links/status |
| `docs/agents/domain.md` v0.2 | Mixed claims | ARCHIVE | `docs/archive/domain-model-2026-08-03.md` | Preserve all information | Medium | Git revert | NO | byte/history check |
| New domain wayfinder/glossary/index | Missing authority separation | KEEP | active docs/reference | Establishes terminology and authority | Low | Git revert | NO | link checker |
| Remaining active docs (operating model, contracts, operations, architecture references, style guide) | 20 files | KEEP | Indexed category | Add metadata incrementally where absent | Medium | Git revert | NO | governance report |
| `worker1-evidensmatris.md` | Untracked historical evidence at root | REVIEW_REQUIRED | `docs/archive/audits/` or delete | User-owned, never staged | Medium | File remains local | BATCH | status read-back |
| Three old mutation matrices | Untracked competing drafts | DELETE_AFTER_VERIFICATION | this matrix | User-owned, never staged | Medium | File remains local until approval | BATCH | content comparison |
| Untracked routing decision packet | Historical/proposed evidence | REVIEW_REQUIRED | proposed ADR or archive | User-owned, never staged | High | File remains local | BATCH | operator decision |
| Two untracked operator-cockpit plans | Active #22 work | KEEP | current local paths | Explicitly protected | High | N/A | NO | status/diff |
| Untracked `CODEX_REVIEW_PACKET_REVISION_3.md` | Review handoff evidence | REVIEW_REQUIRED | archive after chain completion | Explicitly not staged | High | File remains local | BATCH | #22/#92 chain |
| Ignored `.hermes/`,`.trace/`,`.kanban/`,`.codex-tmp/`, dependencies/build output | Runtime/generated data | KEEP | ignored local state | Never publish content | High | N/A | NO | ignore + staged-file scan |

Every tracked document is covered by the directory rows above or by the
“remaining active docs” row; the exact tracked-doc manifest is verified by the
governance checker and cleanup diff. No local file deletion occurs before the
batch gate.

## Consolidated irreversible batch (not executed)

One approval must cover: issue closures/merges and hierarchy edits above;
hide/ignore generic Project `Status`; label deletion/mapping; milestone closure;
PR #83 closure; verified remote-branch deletion; disposition of the six
non-protected untracked evidence/draft files; and any content-reducing docs merge.
The pre-image is the live JSON/SHA list plus this matrix. Rollback is reopen,
recreate labels/refs from recorded metadata, restore Project values, and recover
local files from their still-present copies. Merge and `Done` remain separate,
operator-only actions after review.
