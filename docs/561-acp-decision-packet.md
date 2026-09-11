# #561 decision packet — corrected (three ACPs, ADR-047)

Status: LOCAL decision packet for operator accept/reject on issue #561. NOT
Accepted, NOT an implementation mandate. No worker/aggregate budget. The ADR and
this packet are Proposed; accept/reject is the operator's on the issue.

Date/UTC: 2026-09-11.

## A. What decision #561 decides

Issue #561 is a **decision point**, not an implementation order. It proposes
ADR-047 (the three ACPs) with eight decisions, D1-D8. On accept, the delivery
PR carries the ADR amendments to ADR-026/027/028 (Status lines only) plus the
review-log rows in the same PR. No product code is written by #561 itself; ACP
implementation (a future `AcpAdapter`) is a separate, scoped delivery after
acceptance.

The three ACP levels are kept distinct and are not one decision:

| Level | Name | Decided by | Nature |
| --- | --- | --- | --- |
| Level 1 | Client-to-agent | D1/D3/D4 | Adopted (ACP v1 as client; agent role deferred) |
| Level 2 | Result channel | D5/D6 | Derived (attestation retained for non-ACP; six states judge both paths) |
| Level 3 | Coordination plane | D7 | Built (atomic claim owner; no scheduling policy) |

## B. Criterion 4 — primary-source review status (corrected)

| Claim | Status |
| --- | --- |
| Local JSON-RPC stdio transport | PASS |
| Python SDK exists | PASS (earlier "no Python SDK" concern resolved) |
| sessionId issuer | CORRECTED in D4 (agent issues the ACP sessionId in response to `session/new`) |
| Elicitation first-class | PASS (capability-gated) |
| Remote HTTP/WebSocket transport | QUALIFIED (draft; do not implement now) |
| v1 stable / v2 draft | **OPEN** — must be pinned against a version-locked source before recorded as passed; rendered v2 page != stable release |

Four of six primary-source clusters pass, one is qualified (remote transport),
one stays open (v1/v2 release-status pin). The open pin is explicitly held open
in this packet and in the finding; it is not asserted.

## C. Adopted vs rejected in #561 (from the complementary protocol review)

Adopted (sharpens and corroborates #561):
- ACP scope boundary: ACP standardizes the interactive session; it does NOT
  standardize Run/Request/Workstream identity, Evidence Gate, mandate controls,
  request digest, claim ownership, or role-based approval — Cortxt owns all of
  these.
- Cortxt heartbeat/timeout is necessary now: ACP v1 defers reconnect/replay/
  keepalive to v2, so F-6/F-7/F-8 compensation stays on main and is not removed.
- Cortxt ACP client role is preserved: editors/IDEs act as clients driving
  agents; Cortxt-as-ACP-client matches.

Rejected for #561 (not introduced merely on the report's recommendation):
- A2A delegation for the coordinator agent.
- New Run state "ORPHANED".
- New structured event schema (WorkerEvent).
- New Evidence Gate correlation-chain requirement.

These remain out of scope of this decision and would need their own scoped
decisions if they are ever adopted.

## D. D4 correction — session identity

- ACP `sessionId`: issued by the agent in response to `session/new`; lives in
  the ACP namespace.
- engine-native `session_id`: Cortxt's opaque per-adapter resume token (ADR-028).
- Cortxt Run/request identity: owned by RunRegistry / dispatch.request, above both.

Three separate namespaces that never meet (unchanged from the ADR); the issuer
detail is corrected (agent issues the ACP sessionId, not the client).

## E. D7 — storage/ownership (see decision basis in this PR)

#561 D7 replaces RunRegistry's read-once/write-all store with an atomic
compare-and-swap claim owner, with NO scheduling policy. Atomic file replacement
alone prevents partial files, not lost updates from a stale read-modify-write;
the decision compares SQLite-transaction/CAS, correctly-locked file handling, and
single-writer against the same correctness/failure tests. The "no scheduling
policy" boundary stands.

## F. Status for operator

- Recommended: ACCEPT the #561 decision (D1-D8) with (i) the D4
  sessionId-issuer correction, (ii) D7 owning a compared storage/ownership
  choice, and (iii) the residual v1/v2 version pin noted as the one
  criterion-4 item still to close.
- Not accepted in this packet; no merge, no implementation.
- The numbering collision is reconciled in this PR: 047 stays with #561;
  #554/#556 reassign to ADR-048 (verified free).

## G. Separate track: M2

The minimum v2 wiring (M2) does not depend on #561 acceptance (verified: the v2
machinery exists on main independently of any ACP work). ACP (#561) and M2 are
separate tracks with no manufactured serial dependency. The only explicit gate
before M2 is decision (c) (bounded read-only evidence reconstruction), not #561.
