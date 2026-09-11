---
title: Protocols
description: A short orientation to the protocol interfaces Cortxt relates to — ACP, MCP and A2A — and which of them Cortxt has actually adopted.
---

This page is documentation, not research and not a decision. It is an
**orientation, not a specification**: it names the protocol interfaces Cortxt
relates to and states which of them Cortxt has adopted, without restating their
specifications. Where this page and an Accepted ADR disagree, the ADR wins.

## ACP — Agent Client Protocol

[ADR-047](https://github.com/rian010194/cortxt/blob/main/docs/adr/047-agent-client-protocol-communication-contract-and-coordination-plane.md)
adopts the **Agent Client Protocol** (`agentclientprotocol.com`) as an **ACP
client**: Cortxt drives ACP-speaking agents over the protocol instead of over
per-adapter subprocess conventions. Exposing Cortxt *as* an ACP agent is
deferred, not rejected.

As verified by the ADR at the time of adoption: v1 is stable, v2 is in draft,
local transport is JSON-RPC over stdio, and remote transport over
HTTP/WebSocket is stated by the upstream project to be work in progress.

**A naming warning that matters.** "ACP" has referred to two different
protocols. The one Cortxt adopts is the Agent Client Protocol above. A separate
**Agent Communication Protocol** (IBM BeeAI, `i-am-bee/acp`) was previously
conflated under the same label; it is archived and is **not adopted** by
Cortxt. ADR-047 pins the label on that two-distinct-protocol basis.

ADR-047 also separates three levels that had been discussed as one thing: the
client-to-agent protocol (adopted), the result channel carrying a worker's
outcome (derived), and the cross-process coordination plane (built). They are
one gap, but they are not one decision.

## MCP — Model Context Protocol

[ADR-024](https://github.com/rian010194/cortxt/blob/main/docs/adr/024-external-integration-surface-form.md)
decides that Cortxt's external integration surface takes the form of an **MCP
server**, rather than an SDK or a REST API, for the initial slice.

## A2A — Agent2Agent

A2A is the Linux Foundation protocol that the archived Agent Communication
Protocol became part of. It is named here because the "ACP" name collision
makes the lineage necessary to state. **ADR-047 does not adopt A2A**, and no
Cortxt A2A integration is documented.

## What this page does not claim

This page does not describe transports, message schemas or implementation state
for these protocols beyond what the cited ADRs state. It is not a compatibility
statement and not a roadmap.
