---
finding: acp-primary-source-review
date: 2026-09-11
issue: "#561"
status: partial — the RunRegistry claim is verified, the additive seam is sound,
        the ADR-047 numbering collision is confirmed, and four of six primary-source
        clusters pass; the exact v1/v2 release-status pin and the remote transport
        standing remain open (v1/v2 pin not closable without a version-locked source)
---

# Independent review of ADR-047 (the three ACPs) — record

## Context

Issue #561 is the decision record proposing the three ACPs (client protocol,
communication contract, and coordination plane) under ADR-047. This document is
the independent review of that ADR, delivered for the operator's accept/reject.
It is a **finding**: it records what was verified and what remains open at one
point in time, and is not edited in place.

## What was verified

### (a) ACP primary-source facts — four of six clusters pass, one qualified, one open

| ACP claim in ADR-047 | Verdict | Basis |
| --- | --- | --- |
| Local JSON-RPC over stdio transport | PASS | agentclientprotocol.com/protocol/v1/transports (JSON-RPC over stdio, newline-delimited) |
| Python SDK exists | PASS | agentclientprotocol.com/libraries/python, package `agent-client-protocol` (earlier "no Python SDK" concern resolved) |
| sessionId issuer | CORRECTED in D4 | client requests `session/new`; the agent responds with the unique sessionId (agentclientprotocol.com/protocol/v1/session-setup) |
| Elicitation first-class, capability-gated | PASS | `elicitation/create` + `elicitation/complete`; form/URL modes require capability advertisement (agentclientprotocol.com/protocol/v1/elicitation) |
| Remote HTTP/WebSocket transport | QUALIFIED | Streamable HTTP is a version-1 draft proposal in progress; Python SDK has experimental HTTP/WS; not a stable guarantee — do not implement remote transport now |
| v1 stable / v2 draft | OPEN | rendered v2 doc page does not by itself establish release status; must pin the targeted schema/release against a version-locked source before recording this as passed |

### (b) RunRegistry claim — CONFIRMED (accurate)

`scripts/dispatcher.py` reads the whole JSON store once in `__init__`
(`json.loads(path.read_text())`, no lock/re-read); `_flush()` writes the whole
dict via `Path.write_text` (no `os.replace`, no lock). Two processes race: the
second flush writes a stale snapshot and silently erases the first process's
runs. This is consistent with the 2026-09-10 `dispatcher.in_progress` observation
but is not claimed to be its root cause.

### (c) Additive seam — SOUND

`agent-platform/runtime/engine_adapter.py` is a structural Protocol. Adding a
keyword-only `on_event` (D3) mirrors the existing `session_id` addition and is
additive. `supports_events` fail-explicit is a forward, test-asserted
requirement, not yet implemented. The ADR's Risk section names the structural
limit (a capability flag can be decorative without asserted observation). Net:
contract preserved, contingent on Validation tests being written.

### (d) ADR-047 numbering collision — CONFIRMED

Two distinct documents both carry the number ADR-047 and both Status: Proposed:
1. Branch `docs/adr-047-three-acps` -> `047-agent-client-protocol-communication-contract-and-coordination-plane.md` (#561)
2. Branch `docs/reconcile-operator-direction` -> `047-surface-operation-contract-parity-and-coordinator-boundary.md` (#554/#556)

Reconciled by operator decision: keep 047 for #561; reassign #554/#556's
document to ADR-048 (verified free). Neither is Accepted by renaming.

## Overall verdict

Sound enough to accept provided two conditions are met:
1. The v1/v2 release-status pin is closed against a version-locked source (the
   one fully open cluster above) — it is kept open here rather than asserted.
2. The 047 numbering collision reconciliation is carried in the delivery PR.

The engineering (atomic CAS for the RunRegistry claim owner = D7; additive
seam = D3; transport-vs-judgement separation in D5/D6) is strong and internally
consistent. The ACP client role is preserved; no A2A delegation, no new Run
state, no new event schema, and no new Evidence Gate correlation-chain
requirement is introduced.
