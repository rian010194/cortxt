# Cortxt

> A provider-neutral platform for creating, steering, resuming, and verifying
> long-running AI work under human mandate — built solo, in the open, as a
> working portfolio of the approach. Licensed under the
> [Apache License 2.0](LICENSE).

Cortxt is a provider-neutral platform for creating, steering, resuming, and
verifying long-running intelligent work under human mandate. Users own the
work's state, memory, tools, evidence, and evolution; models, inference
providers, and external agent engines remain replaceable resources behind
Cortxt-owned contracts.

The current product wedge is long-running research and analysis governed by
data-class and provider policy, delivered through a repository-native CLI
(`cortxt`), with a thin widget complement and an MCP server as the external
integration surface (see [ADR-015](docs/adr/015-cortxt-f1-first-wedge-and-product-surface.md),
[ADR-021](docs/adr/021-reopen-adr-015-for-v02-admin-surface-and-widget-ui.md),
and [ADR-024](docs/adr/024-external-integration-surface-form.md)).

## Current status

- GitHub Issues are the durable records for approved scope, evidence, review,
  and decisions.
- GitHub Project 4 and the older control-plane backlog are frozen legacy.
- Worker dispatch's workflow-state carrier is GitHub Issue labels
  `workflow:inbox`/`ready`/`in-progress`/`review`/`blocked`/`done`
  ([ADR-018](docs/adr/018-workflow-state-carrier.md)).
- Real customer inputs and run outputs must remain outside Git history in an
  explicitly approved, isolated workspace.

The current product decisions are recorded as
[Architecture Decision Records](docs/adr/README.md).

## Repository map

| Path | Role today |
| --- | --- |
| [`agent-platform/`](agent-platform/) | Cortxt-owned platform boundary (reasoning, runtimes, CLI, MCP server, state, adapters). `agent-platform/reasoning/` is accepted per ADR-017; `agent-platform/adapters/inference/` holds the live provider-neutral inference adapters. |
| [`verticals/`](verticals/README.md) | Domain packages loaded by the harness — live, not historical. |
| [`web/`](web/README.md) | Operator Cockpit prototype — **paused legacy** per ADR-015/021 (the CLI is the product surface; `cortxt widget` is the sanctioned thin mirror). |
| [`contracts/`](contracts/README.md) | Interface schemas and contract experiments. |
| [`schemas/`](schemas/) | Machine-readable schema definitions. |
| [`scripts/`](scripts/) | Dispatcher, worker adapters, and profile tooling used by the platform. |
| [`docs/`](docs/) | Architecture and decisions for the current baseline (ADRs, operating model, dispatch contract, security). |

Internal working documents (agent session plans, handoffs, assessments) are
kept out of the repository and archived locally.

## Start here

Read these before proposing architecture or execution:

1. [`AGENTS.md`](AGENTS.md)
2. [Current operating model](docs/agents/current-operating-model.md)
3. [Goal operating model](docs/agents/goal-operating-model.md)
4. [Dispatch contract](docs/architecture/dispatch-contract.md)
5. [Accepted ADRs](docs/adr/)

## Contributing and security

- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
