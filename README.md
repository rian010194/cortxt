# Cortxt

> A provider-neutral platform for creating, steering, resuming, and verifying
> long-running AI work under human mandate — built solo, in the open, as a
> working portfolio of the approach. Licensed under the
> [Apache License 2.0](LICENSE) (open source).

> **Foundation phase.** The repository name `ai-workspace-control-plane` and
> much of its backlog describe an earlier system. They are retained for history,
> but they do not define Cortxt's current roadmap.

Cortxt is a provider-neutral platform for creating, steering, resuming, and
verifying long-running intelligent work under human mandate. Users own the
work's state, memory, tools, evidence, and evolution; models, inference
providers, and external agent engines remain replaceable resources behind
Cortxt-owned contracts.

Rikard is the first real user. The current product wedge is long-running
research and analysis governed by data-class and provider policy. This phase is
validating that direction with synthetic inputs before committing to a larger
platform build.

## Current status

- GitHub Issues remain durable records for approved scope, evidence, review,
  and decisions.
- GitHub Project 4 and the older control-plane backlog are frozen legacy.
- Worker dispatch's workflow-state carrier is GitHub Issue labels `workflow:inbox`/`ready`/`in-progress`/`review`/`blocked`/`done` (ADR-018). Dispatch execution itself remains gated by the dispatcher work tracked in issue #122.
- The Operator Cockpit, Buzz/Hermes automation, Pi runtime, vertical packages,
  and broader Agent Platform remain historical implementations, experiments,
  or proposals unless an accepted ADR says otherwise.
- Real customer inputs and run outputs must remain outside Git history in an
  explicitly approved, isolated workspace.

The current product decisions are:

- [ADR-014: Cortxt product vision and first user](docs/adr/014-cortxt-f0-vision-and-first-user.md)
- [ADR-015: first wedge and product surface](docs/adr/015-cortxt-f1-first-wedge-and-product-surface.md)
- [ADR-016: Agent Platform boundary and InferencePort](docs/adr/016-agent-platform-bounded-context-and-inference-port.md)
- [ADR-018: Workflow-state carrier (GitHub Issue labels)](docs/adr/018-workflow-state-carrier.md)

## Repository map

| Path | Role today |
| --- | --- |
| `agent-platform/` | Cortxt-owned platform boundary implemented in Fas 2-4 (PR #150, `agent/fas2a-inference-port`, `agent/fas2b-agent-platform-tracked`, `agent/fas3-coding-agent-plan`, `agent/fas3-task8`). `agent-platform/reasoning/` is accepted per ADR-017. Fas 5-8 (learning loop, geometric reasoning, self-hosted inference, controlled learning) exist on `spec/fas8-controlled-learning-loop` branch and are not yet merged to main. |
| `adapters/` | Proposed future provider and runtime adapters behind Cortxt-owned ports; not yet part of this branch. Exercised by `agent-platform/tests/adapters/` in CI, so it stays in place even though untracked. |
| [`verticals/`](verticals/README.md) | Domain packages loaded by the harness — live, not historical (e.g. `provider-resilient-execution`, `vertical-01-ai-act`). |
| [`web/`](web/README.md) | Operator Cockpit prototype — **paused legacy** per ADR-015/021 (CLI is the product surface; `cortxt widget` is the sanctioned thin mirror). Resolved 2026-08-21 in issue #186. |
| [`contracts/`](contracts/README.md) | Existing interface schemas and contract experiments. |
| [`docs/`](docs/) | Architecture and decisions for the current baseline (ADRs, operating model, dispatch contract). |

Historical material (earlier control-plane runtime work, abandoned
experiments, frozen session handoffs, and the pre-Cortxt agent-architecture
plan) is kept locally outside this repository and is not published here.

## Start here

Read these before proposing architecture or execution:

1. [`AGENTS.md`](AGENTS.md)
2. [Current operating model](docs/agents/current-operating-model.md)
3. [Goal operating model](docs/agents/goal-operating-model.md)
4. [Dispatch contract](docs/architecture/dispatch-contract.md)
5. [Accepted ADRs](docs/adr/)

Historical files may explain how the repository arrived here. They do not
override the current operating model or accepted ADRs.
