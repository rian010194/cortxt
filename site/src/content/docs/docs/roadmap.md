---
title: Status and roadmap
description: Current product status and the live-derived Atlas roadmap page.
---

## Current status

Cortxt is work- and mandate-first (ADR-042): durable Workstream scope and
evidence live in GitHub Issues, workflow state is carried by `workflow:*`
labels, and execution across provider-neutral runtime adapters is
replaceable behind Cortxt-owned contracts. Human approval remains the final
gate. See [current product vs. direction](/docs/product-status/) for what is
verified today versus accepted direction versus experimental.

### Verified baseline

GitHub-backed workflow authority, mandate issuance and verification,
provider-policy gate, dispatch and Run identity, evidence and review
mechanisms, the `cortxt` CLI, `cortxt mcp serve`, engine adapters,
declarative widget contracts, a continuity proof, and accepted ADR-042.

### In active development

Cortxt OS shell, Work (first principal app), Decisions, Evidence, Execution
Inspector integration, Studio and prompt-generated views/apps, and a real
dogfood vertical slice.

### Future or conditional

Hosted synchronization and managed services, broader adapter support,
OpenShell-backed secure execution, and team/private capabilities. None of
these are implemented or foundational today.

## Atlas roadmap

The [visual Atlas graph](/atlas/) shows the roadmap as an interactive graph: issues as nodes, blockers and containment as edges, milestones as groups, and the actionable frontier highlighted. The [text Atlas status page](./atlas-status) lists the same derived data (frontier, blockers, milestone overview, discipline violations, review-evidence presence) as a readable table. Both are generated automatically from the Atlas roadmap maps (GitHub issues remain the single source of truth) and refreshed by the daily Atlas sync.

The [widget prototypes page](/widgets/) renders declarative widget contracts and interactive spec maker tools client-side alongside their CLI counterpart commands.

The full, canonical roadmap with coordinator-owned prose lives in the Atlas map issues ([global map](https://github.com/rian010194/cortxt/issues/214), [MCP lifecycle and dispatch stack](https://github.com/rian010194/cortxt/issues/215)).
