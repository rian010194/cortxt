# ADR-032: MCP Tier-1+ tool calls require a signed, nonce-bound mandate envelope, verified before execution

**Status:** Proposed
**Date:** 2026-08-22
**Deciders:** Rikard Andersson (operator), scope approved 2026-08-22 (session); design/adversarial analysis by Claude Code and the coordinator
**Technical Story:** issue #206 step 2b; design documents `artifacts/mandate-envelope-proposal.md`, `lab/mandate-206-scope-block.md`, `lab/mandate-206-adversarial-review.md`, `lab/issue-206-approved-scope.md` (workspace-local, not tracked in this repo)

## Context

ADR-023/024 accepted external MCP consumption of Cortxt and chose MCP as
the surface, but both explicitly flagged auth/mandate verification as an
open gap that needed specifying before the server is exposed beyond
loopback. Verified directly against the code (2026-08-22, prior to this
change):

- `cortxt_mcp.tools.unlocked_tiers()` / `call_tool()` gate Tier-1+ tools
  (`cortxt_dispatch`, `cortxt_addons_submit`, `cortxt_daemon_status`) with
  a process-wide boolean (`allow_dispatch`), threaded in from a CLI flag
  at server startup. Nothing in the call path distinguishes *which*
  caller is asking -- any stdio client that can reach a server started
  with `--allow-dispatch` gets full Tier-1 access.
- The only audit was post-hoc: `cortxt_mcp.protocol.handle_request`
  called `audit.record(...)` only *after* `tools.call_tool` had already
  returned a successful result, and only on that success path. A
  `ToolTierLockedError` rejection was never logged at all.
- No signature check, nonce check, scope check, or budget check existed
  anywhere between receiving a `tools/call` JSON-RPC request and
  executing the handler.

This invalidates Cortxt's core product claim -- that work runs only under
a verifiable human mandate (ADR-014/015) -- for its first external write
path. This ADR is step 1 of the MCP research-lifecycle work; step 2
(`create_run`/`resume_run`/`submit_for_review`) depends on this slice
being in place first, since every future Tier-1+ mutation inherits the
same protection by construction (verification lives inside `call_tool`,
not duplicated per handler).

## Decision

**(a) Envelope schema v1.** A mandate envelope is a JSON object with
exactly these fields: `schema_version`, `mandate_id`, `granted_by`,
`issue_ref`, `allowed_tools`, `data_class_max`, `budget_usd_max`,
`max_runtime_seconds`, `expires_at`, `nonce`, `scope_fingerprint`,
`signature`. An envelope missing, adding, or renaming any field is
rejected as malformed (fail closed), not partially interpreted.
`max_runtime_seconds` is an enforced v1 authorization bound, not
informational metadata. A call whose declared `estimated_runtime_seconds`
exceeds that maximum is rejected before its handler runs. Equality is
allowed, an omitted estimate remains backward compatible, and malformed
or negative envelope values fail closed as `malformed_envelope`.

**(b) Fail-closed verification inside `call_tool`, before the handler.**
`cortxt_mcp.tools.call_tool()` gains a keyword-only `mandate: dict | None`
parameter. For every tool at `TIER_DISPATCH` or above, verification runs
immediately after the existing tier-lock check and before the handler is
invoked; a `None` mandate, a malformed mandate, or one that fails any
check raises `MandateRejectedError` (a `PermissionError` subclass,
distinct from `ToolTierLockedError`) and the handler never runs. Tier-0
tools are exempt by construction (the check only runs for
`spec.tier >= TIER_DISPATCH`) and silently ignore a stray `mandate` key
if one is present.

Verification (`mandate.verify_mandate`) is a pure function: envelope dict
in, `MandateDecision` out, with only a nonce-store, a budget-store, and a
clock injected (no hidden I/O). Checks run in this fixed order: schema
version known -> signature present and valid (Ed25519, over the
envelope's canonical-JSON serialization with `signature` excluded,
reusing `runtime.session_state.canonical_json` rather than a second
serialization scheme) -> nonce not already consumed -> `expires_at`
parses and is in the future -> tool is in `allowed_tools` -> requested
data class is at or below `data_class_max` -> declared requested runtime
is at or below `max_runtime_seconds` -> cumulative spend for this
`mandate_id` (this call's estimated cost plus everything already debited
against it) is at or below `budget_usd_max` -> `issue_ref` matches the
call's expected scope -> `scope_fingerprint` matches the call's expected
fingerprint. Runtime excess is reported as `runtime_exceeded`; malformed
runtime bounds are reported as `malformed_envelope`. The nonce and the
budget debit are both applied as soon as their check runs, regardless of
whether a later check goes on to reject the call -- otherwise an attacker
could re-probe a consumed nonce against a different tool name, or fire
several parallel calls each individually under the budget cap before any
of them is recorded (adversarial review HIGH-1, MED-2).

**(c) Asymmetric signing; the server never holds the private key.**
Signing is Ed25519 via the `cryptography` package
(`cryptography.hazmat.primitives.asymmetric.ed25519`), added as a new
required dependency of `agent-platform` (`pyproject.toml`). Python's
stdlib has no asymmetric-signature primitive, and a shared-secret scheme
(HMAC) would let a compromised server process mint its own accepted
envelopes -- directly against this design's core property and against
ADR-029's credential-isolation principle, which treats the
longer-running, more-exposed process (there: the daemon; here: the MCP
server) as the less-trusted side. `cortxt_mcp.mandate.issue_mandate()`
(operator/CLI-side only) holds or generates the private key;
`cortxt_mcp.mandate.verify_mandate()` and `MandateVerifier` (server-side)
take only a `public_keys: dict[granted_by -> hex-encoded public key]`
mapping. `cortxt_mcp.server.serve()` builds this mapping from an
environment variable (`CORTXT_MCP_MANDATE_PUBLIC_KEYS`, a JSON object) at
startup -- mirroring how `--allow-dispatch`/`--allow-credentials` are
already explicit startup configuration -- never from a file committed to
the repo and never derived from a credential-broker read inside
`cortxt_mcp/`. A standing test (`test_mandate.py`, AC 8) asserts that
`cortxt_mcp`'s server-side source files (`tools.py`, `protocol.py`,
`server.py`, `audit.py`, `nonce_store.py`) contain no reference to
`mandate.MANDATE_SIGNING_KEY_CREDENTIAL_ID`, the private-key credential
id used only by the issuing-side helper.

**(d) Durable nonce replay-rejection.** `cortxt_mcp.nonce_store.NonceStore`
is a small file-backed store (`{"nonces": [...]}` under a JSON file,
default `agent-platform/.mandate/used_nonces.json`), written atomically
(tempfile + `os.replace`, the same primitive `runtime.session_state`
already uses) so a nonce consumed by one server process is still consumed
after a restart -- an in-memory-only register would re-arm every issued
envelope on every restart (adversarial review HIGH-1). A companion
`BudgetStore` in the same module tracks cumulative spend per
`mandate_id` the same way. Storage-form rationale and limits are in Open
Questions below.

**(e) Ledger gains `mandate_id` + `mandate_decision`, including
rejections.** `cortxt_mcp.audit.AuditLog.record()` gains optional
`mandate_id: str | None` and `mandate_decision: str | None` keyword
arguments, always written into the `mcp.tool_call` event (as `null` for
Tier-0 calls, which carry no mandate at all, rather than the keys being
omitted). `cortxt_mcp.protocol.handle_request`'s `tools/call` branch now
calls `audit.record(...)` on the `ToolTierLockedError` and
`MandateRejectedError` paths too, not only on success -- today's
rejection-is-never-logged gap is closed as part of this same change
(operator-approved as an explicit behavior change, not an incidental
side effect).

**(f) Key handling follows ADR-029's credential-isolation principle.**
Private-key generation and storage are entirely on the operator/CLI side:
`mandate.issue_mandate()` builds and signs an envelope (generating a
fresh Ed25519 keypair if none is injected); `mandate
.store_signing_key_in_broker()` and `mandate.load_signing_key_from_broker()`
are thin, explicitly-named wrappers around
`security.credential_broker.CredentialBroker` (`.with_dpapi(...)` in
production), reusing ADR-029/Phase-1's existing encryption-at-rest and
operator-confirmed-write machinery rather than inventing a second
credential-storage convention. None of these three functions is ever
called from `cortxt_mcp`'s server-side runtime path -- the server process
only ever sees a public key, which is not secret by construction.

## Consequences

### Positive
- Closes the concrete, verified gap ADR-023/024 flagged: Tier-1+ MCP
  calls now require a specific, scoped, replay-protected, expiring
  mandate rather than "whatever tier the server process happens to have
  been started with."
- Every current and future caller of `call_tool` (not just
  `protocol.py`'s stdio shim -- also any future SDK-based or REST-facade
  entry point) inherits the protection by construction, because
  verification lives inside `call_tool` itself rather than duplicated
  per transport or per handler.
- The rejection-is-never-logged gap (found while implementing this ADR,
  not merely hypothesized) is closed as a side effect: every decision,
  accepted or rejected, is now in the ledger.

### Negative
- A new required dependency (`cryptography`) is added to
  `agent-platform`, the first place this repo's "no new framework
  without a decision" discipline is actually spent for this package.
- The ledger schema change is additive but permanent: any future reader
  of `mcp.tool_call` events that does strict-schema validation must
  tolerate the two new keys. No such reader exists inside `cortxt_mcp/`
  today; not verified beyond this package.
- The nonce/budget stores are single-process-safe (a `threading.Lock`
  guards concurrent access within one server process) but not
  multi-process-safe. A future deployment running more than one MCP
  server process against the same state directory concurrently would
  need real file locking, not just an in-process lock -- flagged, not
  built, since v1's server is a single stdio process per connection.

### Risks
- The public-key delivery mechanism (an environment variable read at
  server startup) has no rotation story: rotating a compromised or
  retired key means restarting the server with new environment
  configuration, with no in-flight revocation of envelopes already
  issued under the old key before its `expires_at`. Deferred to a later
  key-rotation ADR per the approved scope.
- `issue_ref`/`scope_fingerprint` verification in this v1 checks only
  against what the *caller* declares in `mandate_context` (a
  `CallContext` built from an optional, client-supplied
  `arguments.mandate_context` object) -- there is no live GitHub lookup
  confirming the issue is still `workflow:ready` at call time. This
  keeps the hot path local and avoids a TOCTOU race against the GitHub
  API (adversarial review MED-1), but means a caller who simply omits
  `mandate_context.issue_ref`/`scope_text`/`expected_scope_fingerprint`
  gets those specific checks skipped rather than failed -- by design
  (empty context = no claim to verify against), but worth flagging
  explicitly: this is not equivalent to a live, continuously-revalidated
  scope check.

## Alternatives Considered
1. **HMAC (shared secret) instead of asymmetric signing** -- rejected: the
   verifying process (the MCP server) would hold the same secret used to
   issue mandates, so a compromised server could forge its own accepted
   envelopes, defeating the entire point of a mandate.
2. **Reuse `runtime.session_state`'s per-session ledger as the nonce
   register** -- rejected: that ledger is deliberately scoped per
   connection/session, while the nonce and budget registers need to be
   global and durable across every session and every server restart;
   bolting a global concern onto a per-session store would need a
   synthetic well-known session id and mix two different lifetimes in one
   file. A small dedicated JSON file per concern (`nonce_store.py`) keeps
   each independently inspectable.
3. **Live GitHub lookup of `issue_ref`/scope on every call** -- rejected
   for v1: adds a slow, network-dependent, TOCTOU-prone check to the hot
   path and requires `gh` credentials inside the MCP server process,
   itself a credential-isolation concern under ADR-029. Left as a
   documented v2 option once the server is exposed beyond loopback.

## Validation
- [ ] Implementation matches decision -- builder runs the focused mandate
      and protocol tests plus the full `tests/cortxt_mcp/` suite locally;
      coordinator will independently run and confirm CI before acceptance.
- [ ] Tests cover decision boundaries -- runtime below, equal to, and above
      the maximum; omitted requested runtime; malformed envelope runtime;
      and pre-handler rejection are covered, pending coordinator CI run.

## Open Questions (deferred, not blocking this ADR)
- **Operator issuance UX.** `issue_mandate()` is a CLI-callable function
  today; there is no interactive command, widget, or approval-UI
  affordance yet for an operator to issue a mandate. Deferred, per the
  approved scope (CLI-only for this slice).
- **Nonce-store exact storage form.** Resolved for v1 as a plain
  JSON file per store (`nonce_store.py`'s `NonceStore`/`BudgetStore`),
  atomic-write, single-process-safe. Whether this needs to become a real
  multi-writer-safe store (proper file locking, or a small embedded DB)
  is open, pending a deployment shape with more than one concurrent MCP
  server process against the same state directory.
- **REST facade.** Whether a future REST facade (ADR-024's Alternatives
  #2) needs the identical mandate mechanism or an adapted one (e.g.
  bearer-token-carried envelope vs. a request-body field) is undecided.
- **Key rotation policy.** Not needed for the first verifiable slice; a
  single long-lived keypair per `granted_by` identity is sufficient for
  v1. No rotation or revocation-before-expiry mechanism exists yet.

## Expiry/Review Trigger
- Review by: next MCP research-lifecycle step (step 2:
  `create_run`/`resume_run`/`submit_for_review`) that depends on this
  slice, or before the MCP server is exposed beyond loopback, whichever
  comes first.
