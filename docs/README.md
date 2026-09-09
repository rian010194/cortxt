# Documentation map

Status: active navigation map
Authority: navigation only — it points at authority, it never creates any
Last verified: 2026-09-10 against `main` `7e5a243`

This page is a **description**: it asserts what is true now and must change in
the same pull request as the thing it describes. It routes you to the document
that owns each question. When a document here disagrees with an Accepted ADR,
the ADR wins and the document is wrong.

## Where authority lives

| Question | Authority | Not authority |
| --- | --- | --- |
| What is the scope, evidence, review and approval of a piece of work? | The GitHub issue, plus exactly one `workflow:*` label (ADR-018) | Any map, ledger, plan or runtime queue |
| What was decided, and does it bind me? | Accepted ADRs in [`adr/`](adr/README.md) | A Proposed ADR, a plan, or a summary of one |
| What can the system actually do today? | [`agents/current-operating-model.md`](agents/current-operating-model.md) | A merged UI change, a registered adapter, a green fixture |
| Where is this going? | [`agents/goal-operating-model.md`](agents/goal-operating-model.md) | Anything that reads as a schedule or a commitment |
| What must a dispatch satisfy? | [`architecture/dispatch-contract.md`](architecture/dispatch-contract.md) | A worker's own success message |
| How do goals, areas, dependencies and progress relate? | [`agents/atlas.md`](agents/atlas.md) — derived views over Issues | Atlas is never a second backlog |

Issues remain the single durable record. Atlas maps, the local run registry and
any runtime task list are derived views or execution ledgers that must
correlate to an issue.

## What to read for the work you have

Read what your task needs. No worker has to load the whole roadmap.

**A bounded fix** — a defect, a test, a documentation correction, one file or
one contract you already know:

1. The GitHub issue: scope, acceptance criteria and limits.
2. [`../CLAUDE.md`](../CLAUDE.md) non-negotiable rules and the build/test
   section.
3. The contract or guide the change touches — see *Contracts and guides* below.

**Architecture, planning or dispatch** — proposing an execution path,
evaluating the architecture, or starting work for someone else:

1. [`agents/current-operating-model.md`](agents/current-operating-model.md)
2. [`architecture/dispatch-contract.md`](architecture/dispatch-contract.md)
3. [`architecture/runtime-and-evaluation-harness.md`](architecture/runtime-and-evaluation-harness.md)
4. [`agents/atlas.md`](agents/atlas.md) and
   [`agents/issue-tracker.md`](agents/issue-tracker.md)
5. The GitHub issue and its current evidence.

[`../AGENTS.md`](../AGENTS.md) carries the operating boundaries that apply to
both routes. [`../CONTEXT.md`](../CONTEXT.md) is the controlled vocabulary; read
it when a term's exact meaning decides the answer.

## Contracts and guides

| Document | What it settles |
| --- | --- |
| [`architecture/dispatch-contract.md`](architecture/dispatch-contract.md) | Required identity, limits, evidence and lifecycle of a dispatch |
| [`architecture/run-authority.md`](architecture/run-authority.md) | What a Run may claim about itself |
| [`architecture/label-dispatch.md`](architecture/label-dispatch.md) | The `workflow:*` label mechanics |
| [`architecture/event-surface.md`](architecture/event-surface.md) | The event surface contract |
| [`architecture/vertical-package-contract.md`](architecture/vertical-package-contract.md) | What a vertical package must provide |
| [`agents/work-launcher.md`](agents/work-launcher.md) | `cortxt work` — starting and observing runs |
| [`agents/running-cortxt-os.md`](agents/running-cortxt-os.md) | Starting the action host and Cortxt OS locally |
| [`design/global-design-system.md`](design/global-design-system.md) | UI tokens, roles and the consumer contract (ADR-043) |
| [`style-guide.md`](style-guide.md) | Writing rules for everything in this directory |
| [`security/credential-broker-threat-model.md`](security/credential-broker-threat-model.md) | Credential isolation threat model (Proposed, not implemented) |

## Historical evidence and registers

These are **registers**: they record why something was decided or what was
observed at one moment. They are never edited to match the present. A register
that turns out to be wrong is superseded by a new one, not rewritten.

| Register | What it holds |
| --- | --- |
| [`adr/`](adr/README.md) | Every architecture decision, with its status |
| [`architecture/REVIEW_LOG.md`](architecture/REVIEW_LOG.md) | Append-only log of changes to Accepted ADRs |
| [`daemon-proof-log.md`](daemon-proof-log.md) | Recorded daemon proof runs |
| [`design/os-app-boundary-operator-decision-20260828.md`](design/os-app-boundary-operator-decision-20260828.md) | The operator decision behind ADR-044 |
| [`architecture/cortxt-agent-platform-target-architecture.md`](architecture/cortxt-agent-platform-target-architecture.md) | A proposed long-term target, partially superseded by later ADRs — read its reconciliation notice first |

Per-issue evidence lives on the issue and its pull request, not in this
directory. Session handoffs and working notes are kept outside the repository
and are supplemental: nothing required to do the work depends on having them.

## The public site

[`../site/`](../site/) publishes a subset of this material to
[cortxt.io/docs](https://cortxt.io/docs/). One page is generated and must not be
hand-edited (`site/src/content/docs/docs/adrs.md`, from `docs/adr/` via
`scripts/docs_currency.py`); the rest are hand-maintained summaries that name
their repository source. `site/README.md` records which is which. When you
change a source here, check whether a site page repeats the claim.
