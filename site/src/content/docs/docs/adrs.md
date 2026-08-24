---
title: Accepted architecture decisions
description: The Accepted-only ADR index mirrored from the repository authority.
---

<!-- docs-currency:auto:begin -->

This page is generated from the repository ADR files by `scripts/docs_currency.py`; do not hand-edit the generated block. As of 2026-08-24. [Open the authoritative ADR index](https://github.com/rian010194/cortxt/blob/main/docs/adr/README.md).

| ADR | Decision |
| --- | --- |
| [014](https://github.com/rian010194/cortxt/blob/main/docs/adr/014-cortxt-f0-vision-and-first-user.md) | Cortxt Product Vision and First User (F0) |
| [015](https://github.com/rian010194/cortxt/blob/main/docs/adr/015-cortxt-f1-first-wedge-and-product-surface.md) | Cortxt First Wedge and Product Surface (F1) |
| [016](https://github.com/rian010194/cortxt/blob/main/docs/adr/016-agent-platform-bounded-context-and-inference-port.md) | Agent Platform bounded context, InferencePort and provider-assurance principle |
| [017](https://github.com/rian010194/cortxt/blob/main/docs/adr/017-agent-platform-reasoning-acceptance.md) | Agent Platform — reasoning core accepted as tracked architecture |
| [018](https://github.com/rian010194/cortxt/blob/main/docs/adr/018-workflow-state-carrier.md) | Workflow-state carrier — GitHub Issue labels |
| [019](https://github.com/rian010194/cortxt/blob/main/docs/adr/019-coding-engines-permanent-multi-routing.md) | Coding execution — permanent multi-engine routing, not Pi/Hermes replacement |
| [020](https://github.com/rian010194/cortxt/blob/main/docs/adr/020-proof-environment-naming-redaction.md) | Proof environment naming — redact product/partner name from public surface |
| [021](https://github.com/rian010194/cortxt/blob/main/docs/adr/021-reopen-adr-015-for-v02-admin-surface-and-widget-ui.md) | Reopen ADR-015 for v.02 Admin Surface + Widget UI (F2 treatment) |
| [022](https://github.com/rian010194/cortxt/blob/main/docs/adr/022-fas3-capability-manifest-and-engine-selection-criteria.md) | Phase 3 v0.1 — capability manifest shape and engine-selection criteria |
| [023](https://github.com/rian010194/cortxt/blob/main/docs/adr/023-bottom-up-and-top-down-integration-model.md) | Cortxt supports both bottom-up and top-down integration, not one exclusively |
| [024](https://github.com/rian010194/cortxt/blob/main/docs/adr/024-external-integration-surface-form.md) | External integration surface takes the form of an MCP server |
| [025](https://github.com/rian010194/cortxt/blob/main/docs/adr/025-geometric-reasoning-decisive-vs-diagnostic-metrics.md) | Geometric Reasoning's decisive vs. diagnostic metrics (§27 #8) |
| [026](https://github.com/rian010194/cortxt/blob/main/docs/adr/026-engine-adapter-registry-separate-from-route-selection.md) | Engine adapter-registry (cordis-inspired DI) is kept separate from `route()`'s selection |
| [027](https://github.com/rian010194/cortxt/blob/main/docs/adr/027-engine-context-adopts-service-broker-not-exclusive-binding.md) | `EngineContext` adopts the service-broker pattern (Cordis §6.2), not exclusive binding |
| [028](https://github.com/rian010194/cortxt/blob/main/docs/adr/028-orchestrator-multi-engine-resume-and-codex-adapter.md) | Orchestrator multi-engine resume via opaque per-adapter session_id, CodexAdapter added |
| [031](https://github.com/rian010194/cortxt/blob/main/docs/adr/031-open-source-apache-2.0.md) | Open-source license — Apache-2.0 |
| [032](https://github.com/rian010194/cortxt/blob/main/docs/adr/032-mcp-mandate-envelope.md) | MCP Tier-1+ tool calls require a signed, nonce-bound mandate envelope, verified before execution |
| [033](https://github.com/rian010194/cortxt/blob/main/docs/adr/033-mcp-mandate-key-rotation.md) | MCP mandate envelopes identify versioned signing keys and support overlap and revocation |
| [034](https://github.com/rian010194/cortxt/blob/main/docs/adr/034-mcp-run-lifecycle-tools.md) | MCP run lifecycle tools -- mandate-bound create/resume/submit_for_review |
| [035](https://github.com/rian010194/cortxt/blob/main/docs/adr/035-voyage-embeddings-provider.md) | Embeddings provider for Phase 6 — Voyage via EmbeddingPort (§27 #10) |
| [036](https://github.com/rian010194/cortxt/blob/main/docs/adr/036-mcp-run-lifecycle-async.md) | MCP run lifecycle asynchronous create and status polling |
| [037](https://github.com/rian010194/cortxt/blob/main/docs/adr/037-mcp-review-daemon-sync.md) | MCP review submission daemon synchronization |
| [038](https://github.com/rian010194/cortxt/blob/main/docs/adr/038-declarative-widget-contract-and-authorized-action-ports.md) | Declarative Widget Contract and Authorized Action Ports |
| [039](https://github.com/rian010194/cortxt/blob/main/docs/adr/039-execution-map-concurrency-claims-and-prerequisite-ordering.md) | Execution Map Concurrency Claims and Prerequisite Ordering |
| [040](https://github.com/rian010194/cortxt/blob/main/docs/adr/040-delivery-execution-paths-and-label-invariant.md) | Delivery execution paths and workflow-label invariant |
| [041](https://github.com/rian010194/cortxt/blob/main/docs/adr/041-backend-service-surface-reopens-adr-015.md) | Backend Service Surface Reopens ADR-015 (Surface Dimension Only) |

:::note
**Proposed** records ([ADR-029](https://github.com/rian010194/cortxt/blob/main/docs/adr/029-unattended-daemon-credential-isolation.md) (Proposed), [ADR-030](https://github.com/rian010194/cortxt/blob/main/docs/adr/030-plan-vs-actual-divergence-tracking.md) (Proposed (Part 1 implemented; Part 2 spec-only))) are reviewable designs, not Accepted decisions; they are intentionally absent from the Accepted table above. **Superseded** records ([ADR-011](https://github.com/rian010194/cortxt/blob/main/docs/adr/011-model-router.md), [ADR-012](https://github.com/rian010194/cortxt/blob/main/docs/adr/012-disaster-recovery.md), [ADR-013](https://github.com/rian010194/cortxt/blob/main/docs/adr/013-skill-composition.md)) are historical references kept for traceability only.
:::

<!-- docs-currency:auto:end -->
