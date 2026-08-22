# ADR-033: MCP mandate envelopes identify versioned signing keys and support overlap and revocation

**Status:** Proposed
**Date:** 2026-08-22
**Deciders:** Rikard Andersson (operator), design approved 2026-08-22 (session); not yet implemented
**Technical Story:** Follow-up to ADR-032 key-rotation risk and open question; filed as ADR-033 (Proposed) after operator approval of the parallel-session draft (`lab/parallel-key-rotation/`)

## Context

ADR-032 introduced Ed25519-signed mandate envelopes and deliberately left key rotation unresolved. The implemented envelope schema v1 has no key identifier. `verify_mandate()` receives `public_keys: Mapping[str, str]`, so each `granted_by` identity resolves to exactly one public key. `server._build_mandate_verifier_from_env()` reads `CORTXT_MCP_MANDATE_PUBLIC_KEYS` once at startup as a JSON object of `granted_by` to hex public key. Replacing that value therefore requires a server restart and immediately makes every still-valid envelope signed by the replaced key unverifiable.

The issuing side has the same single-key assumption. `issue_mandate()` accepts one optional private key and returns an `IssuedMandate` containing the envelope, unencrypted private-key PEM, and public-key hex. `store_signing_key_in_broker()` and `load_signing_key_from_broker()` use one fixed credential id, `mcp-mandate-signing-key`. This cannot represent two keys for one issuer during a transition.

Rotation is required for routine retirement, cryptoperiod limits, and rotate-on-suspicion response. Long-lived signing keys increase the number and lifetime of envelopes an exposed key can forge. Normal rotation must not invalidate legitimate envelopes that have not reached their signed `expires_at`. Compromise response has the opposite requirement: the operator must be able to reject a key and every envelope signed by it before expiry.

The existing `NonceStore` and `BudgetStore` show a durable, injected-store pattern, but they are single-process-safe only and treat malformed files as defaults. Revocation is security configuration, not replay or accounting state: a missing, malformed, unreadable, or stale revocation source must not silently mean "nothing is revoked."

This decision preserves ADR-032's asymmetric trust boundary and ADR-029's credential-isolation principle: the MCP server receives public verification material and revocation status only. It never receives, loads, or derives a mandate private key.

## Decision

### 1. Key identity is `(granted_by, kid)`

Mandate envelope schema v2 adds a required `kid` string. `kid` is an opaque, operator-assigned identifier that is unique within one `granted_by` identity. It is not secret, is covered by the envelope signature, and must not be derived from mutable labels such as `active` or `current`. A recommended form is a stable random or time-sortable identifier; key fingerprints may be displayed for operator comparison but are not the sole identity contract.

Verification keys become a nested keyring:

```json
{
  "operator-demo": {
    "01J...OLD": "<old Ed25519 public key as hex>",
    "01J...NEW": "<new Ed25519 public key as hex>"
  }
}
```

`verify_mandate()` resolves exactly `public_keys[granted_by][kid]`. It never tries every key and never falls back to another `kid`. Unknown or empty `kid` fails closed with a distinct `unknown_kid` decision; an unknown `granted_by` remains `unknown_granted_by`. A duplicate `(granted_by, kid)` with different key material makes the complete keyring configuration invalid and leaves the verifier unconfigured, rather than accepting an arbitrary value.

Adding `kid` changes the exact envelope field set, so it is schema v2 rather than a silent extension of v1. Whether a bounded v1 compatibility window is required is an operator decision in Open Questions. If enabled, v1 uses a separately configured legacy key per `granted_by`; v1 must never guess among multiple v2 keys and issuance must stop producing v1 before the overlap begins.

### 2. Normal rotation uses an overlap bounded by envelope expiry

Rotation has four explicit phases:

1. Generate and store a new private key on the operator/CLI side, assign its `kid`, and publish the matching public key alongside the old public key.
2. Confirm every verifier has the new public key before selecting it for issuance.
3. Switch issuance atomically to the new `kid`. Keep the old public key available while any envelope signed by it can remain valid.
4. Remove the old public key only after `last_old_key_issuance_at + maximum_envelope_ttl + clock_skew_margin`, or after a later recorded `not_after` bound if the key registry records one.

During the overlap, both keys verify, but all newly issued envelopes use only the selected active key. Existing `expires_at` remains the authority for individual envelope expiry. Rotation does not extend an envelope and does not make an expired envelope valid.

A configured maximum envelope TTL is required for bounded retirement. `issue_mandate()` must reject an `expires_at` later than `now + maximum_envelope_ttl`; the clock is injected for deterministic tests. Without this bound, one envelope could force indefinite retention of an old public key. The exact TTL and skew margin require operator approval.

### 3. Revocation-before-expiry is an explicit denylist checked before signature work

The verifier receives an injected `KeyRevocationStore` with a fail-closed query equivalent to `is_revoked(granted_by, kid, at) -> bool`. Entries identify `(granted_by, kid)` and contain at least `revoked_at`, plus an optional non-secret reason or incident reference. Once effective, revocation rejects every envelope naming that key, even if its signature and `expires_at` are otherwise valid. The decision reason is `key_revoked` and is carried into the existing mandate decision audit field.

The first implementation uses an operator-managed JSON file in the mandate state directory, loaded through a refreshable snapshot rather than only at server construction. The server checks file metadata at a short configured interval and atomically replaces its last verified in-memory snapshot after a complete parse and validation. An operator can therefore publish a revocation with atomic file replacement without restarting the server. Revocations are monotonic in v1: removing or backdating an entry is rejected unless an explicit administrative recovery procedure is later designed.

This store must not reuse or extend `NonceStore`. Nonces are high-volume consumed facts with permissive recovery behavior for malformed storage; revocations are low-volume security policy and require different failure semantics. The revocation store must fail closed if it has never loaded a valid snapshot, if a newer snapshot is malformed, unreadable, or rolls back its generation, or if its freshness exceeds a configured maximum. It may continue using the last valid snapshot only within that bounded freshness window. A monotonically increasing `generation` field detects rollback within the running process. Durable rollback resistance across host restart requires a stronger signed or transactional control plane and remains an open question.

Revocation is evaluated after schema and key-identity parsing but before signature verification, nonce consumption, and budget debit. A revoked attempt therefore cannot consume a legitimate nonce or budget. The revocation list is public security configuration; it contains no private key.

Environment-only deployment remains supported for the public keyring, but startup-only environment configuration cannot provide emergency no-restart key publication. For v1 of this ADR, no-restart behavior is guaranteed for revocation through the refreshable file, not for adding keys. A restart may still be required to publish the new public key for routine rotation. A fully refreshable public-key registry is deferred unless the operator selects it in Open Questions.

### 4. Issuance selects an explicit key version and keeps private keys in CredentialBroker

`issue_mandate()` gains required `kid` and continues to accept the selected `Ed25519PrivateKey`. The function writes `kid` into the signed v2 body. It does not discover the active key, read environment configuration, or query CredentialBroker. This preserves the current pure, explicit issuing boundary.

Operator/CLI orchestration selects the active `(granted_by, kid)`, loads that exact private key, and passes both to `issue_mandate()`. Before returning an envelope, issuance verifies that the loaded key's derived public key matches the registered public key for that tuple. Missing selection, unknown `kid`, mismatch, expired key metadata, or an `expires_at` beyond the maximum TTL fails closed.

CredentialBroker stores one private key per tuple under a versioned credential id such as `mcp-mandate-signing-key/<granted_by>/<kid>`. Components must encode or validate segments so identities cannot collide or traverse storage paths. `store_signing_key_in_broker()` and `load_signing_key_from_broker()` therefore accept `granted_by` and `kid`; stores remain operator-confirmed, and loads keep an explicit issuance purpose and `requesting_runtime="mandate-cli"`. The active-key pointer and public metadata are non-secret operator-side configuration, separate from private-key bytes. Old private keys remain broker-held during overlap only if re-issuance or recovery requires them; normal issuance cannot select a retired key.

`IssuedMandate` may continue returning public-key hex for enrollment and diagnostics, but returning unencrypted `private_key_pem` is unsafe as the normal multi-key lifecycle API. Key generation and broker persistence should become an explicit operator command that minimizes PEM lifetime. Removal of that return field is an API migration question, not silently included in this decision.

ADR-032 AC8 remains invariant and is expanded: server-side modules must contain no versioned signing credential id construction and no import of CredentialBroker or issuing-side key-selection code.

### 5. Security boundary

Routine rotation limits future use of a retired key and permits cryptoperiod policy without breaking unexpired mandates. Emergency revocation stops server acceptance of all envelopes under a known compromised `kid` after the revocation snapshot reaches the verifier.

Rotation does not invalidate envelopes already issued under a still-trusted old key, shorten their `expires_at`, undo calls already executed, recover a leaked private key, or prove that an issuer host was clean. Revoking one key cannot distinguish legitimate envelopes from forged envelopes made with that key. An attacker may exploit a compromised key until revocation propagates, so the refresh and freshness bounds are part of the incident-response objective. Short maximum envelope TTL remains defense in depth.

## Consequences

### Positive

- Multiple public keys can coexist for one `granted_by`, so routine rotation preserves valid in-flight envelopes.
- Every envelope selects one auditable key version without trial verification or ambiguous fallback.
- A compromised key can be denied before envelope expiry without placing private material in the MCP server or requiring a server restart for the revocation update.
- Explicit TTL bounds make overlap duration and key retirement finite and testable.
- The injected clock and store boundaries preserve the pure-verifier testing style established by ADR-032.

### Negative

- Envelope schema v2 and nested public-key configuration require coordinated issuer and verifier rollout.
- Operators must maintain key lifecycle metadata, an active selection, overlap timing, and a revocation source.
- Routine addition or removal of public keys may still require server restart in the first implementation.
- Revoking a key rejects legitimate outstanding envelopes under that key; this is deliberate during compromise response.
- The file-backed design inherits the current single-process deployment limit and cannot provide durable rollback resistance against a host-level attacker.

### Risks

- A long maximum envelope TTL creates a correspondingly long overlap and compromise blast radius.
- If the issuer switches before all verifiers receive the new public key, valid new envelopes fail closed.
- A stale or unavailable revocation source creates an availability-versus-security choice. This decision chooses bounded last-known-good operation followed by fail-closed rejection.
- A compromised operator host or broker-authorized issuance process can select and use any key it is authorized to load; server-side rotation does not solve issuing-side compromise.
- Reusing a `kid` for different key bytes creates ambiguity and must be rejected permanently.

## Alternatives Considered

1. **Map `granted_by` to a list and try every public key.** Rejected: it hides key identity, makes revocation and audit correlation ambiguous, increases verification work, and gives no deterministic way to distinguish retired from active keys.
2. **Replace the single key and accept that old envelopes fail.** Rejected for routine rotation: it violates the requirement that unexpired valid envelopes survive planned rotation. It remains equivalent to emergency revocation when compromise demands immediate denial.
3. **Encode the version into `granted_by`.** Rejected: it conflates human or system authority identity with cryptographic key lifecycle and fragments audit history for one grantor.
4. **Use only short `expires_at` and omit revocation.** Rejected: it bounds but does not eliminate the window in which a known compromised key can authorize calls.
5. **Put revocations in an environment variable.** Rejected as the sole mechanism: it has the same startup-only update limitation as the current public-key map. It may be accepted as a static bootstrap denylist, not as emergency propagation.
6. **Extend `NonceStore` with revoked keys.** Rejected: nonce consumption and security-policy distribution have different data shape, scale, update authority, and fail-closed requirements.
7. **Query CredentialBroker from the MCP server.** Rejected under ADR-029 and ADR-032: the less-trusted verification side must never gain access to mandate signing private keys.
8. **Use an online key-management or authorization service immediately.** Deferred: it can provide signed, centrally refreshed key and revocation state, but adds network availability, authentication, and operational dependencies beyond the current single-host stdio deployment.

## Validation

- [ ] **AC10 - Key identity is signed and deterministic.** A v2 envelope issued with `(granted_by, kid)` verifies only against that exact nested keyring entry. Tampering with `kid`, an unknown `kid`, an empty `kid`, or a duplicate tuple with different public bytes fails closed with the specified reason and does not try another key.
- [ ] **AC11 - Planned overlap preserves unexpired envelopes.** With old and new keys registered, fake-clock tests show an old-key envelope and a new-key envelope both verify before their respective `expires_at`; after the old envelope expires, it is rejected even while the old public key remains loaded.
- [ ] **AC12 - Issuance switches without verifier ambiguity.** Fake issuer metadata selects the new `kid`; every new envelope names it, a retired key cannot be selected, and a private/public mismatch is rejected before an envelope is returned.
- [ ] **AC13 - TTL bounds retirement.** With an injected fake clock, issuance accepts `expires_at` at the configured maximum plus allowed skew and rejects a later value. Retirement calculation retains the old public key through the last possible valid envelope and permits removal only after the bound.
- [ ] **AC14 - Revocation beats expiry.** A valid, unexpired envelope is accepted before its tuple is revoked and rejected as `key_revoked` after an atomic fake-store update. The rejected call does not invoke the handler, consume the nonce, or debit the budget.
- [ ] **AC15 - Revocation refresh survives process behavior.** Fake clock and fake revocation snapshots cover refresh interval, last-known-good freshness, malformed/unreadable update, generation rollback, and stale-source fail-closed behavior. A real temporary-file test covers atomic replacement without server restart.
- [ ] **AC16 - Rotation does not weaken existing checks.** Existing AC1-AC9 and adversarial tests remain green for supported schemas; signature, nonce replay, expiry, tool, data class, budget, issue reference, scope fingerprint, ledger, and Tier-0 behavior are unchanged.
- [ ] **AC17 - Configuration fails closed.** Invalid nested JSON, non-string key material, invalid Ed25519 bytes, duplicate logical tuples, and a missing initial revocation snapshot produce an unconfigured verifier or explicit rejection, never partial acceptance.
- [ ] **AC18 - Credential isolation survives multi-key storage.** Fake CredentialBroker tests show separate tuple-specific credentials, operator-confirmed stores, exact-key loads, collision-safe identifiers, and explicit purpose. The standing source test proves server-side files contain neither private-key credential ids nor broker/issuer imports.
- [ ] **AC19 - Schema transition is explicit.** If v1 compatibility is approved, tests prove v1 uses only its configured legacy key and cannot select among v2 keys; issuance no longer emits v1. If compatibility is not approved, v1 fails as unknown schema after the coordinated cutover.
- [ ] **AC20 - Audit identifies rotation decisions.** Accepted and rejected Tier-1 ledger rows include `granted_by` and `kid` or an equivalent non-secret key reference, and revoked attempts record `rejected:key_revoked` without logging key material.
- [ ] Implementation matches this decision and is reviewed against ADR-029 and ADR-032 trust boundaries.
- [ ] Tests use injected fake clocks and fake key, revocation, nonce, budget, and broker stores; file-backed behavior is covered separately with temporary directories.

## Open Questions

- Must existing schema v1 envelopes remain valid during migration, and if so, what is the hard end date for the single legacy key per `granted_by`?
- What maximum envelope TTL, clock-skew margin, key cryptoperiod, revocation refresh interval, and last-known-good freshness window should production use?
- Is restart-based public-key publication acceptable for the first slice, or must the keyring use the same live-refresh mechanism as revocation?
- Who is authorized to create, activate, retire, revoke, and destroy a key, and what operator evidence records each transition?
- Should revocation state be a local unsigned file, an operator-signed file, or a stronger transactional control plane before any deployment beyond one host and one MCP process?
- Is permanent monotonic revocation sufficient, or is an exceptional un-revoke procedure required for operator error?
- Should `IssuedMandate.private_key_pem` be removed or deprecated once broker-backed generation exists?
- Should audit rows add explicit `granted_by` and `kid`, or is a composite non-secret key reference sufficient?
- Should key retirement delete old private key bytes immediately after the issuance switch, after overlap, or only after a separately approved recovery period?

## Expiry/Review Trigger

- Review before implementing schema v2, before the first planned mandate-signing key rotation, immediately on suspected signing-key compromise, or before the MCP server is exposed beyond loopback, whichever comes first.
- Revisit when deployment uses more than one MCP process or host, because the proposed local refresh and rollback model is not sufficient for distributed verification.
