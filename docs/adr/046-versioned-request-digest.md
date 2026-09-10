# ADR-046: Versioned request digest (dispatch.request.v2)

**Status:** Accepted (2026-09-10)  
**Date:** 2026-09-10  
**Deciders:** Rikard (operator; approved 2026-09-10 via the W-series orchestrator under the standing mandate)  
**Technical Story:** operator decision 2 of the W-series plan; unblocks W10 and W11

## Context

`_request_id` hashes a fixed 17-name allowlist
(`agent-platform/widget_contract/dispatch_request.py:132-138`, `:274-283`).
`execution_profile_id` and `charge_policy_id` are strings that *name* records;
the records are mutable in the repository and, for the halves supplied by
configuration, in `os.environ`. `hermes-free`'s provider and model are resolved
from `CORTXT_FREE_PROVIDER` / `CORTXT_FREE_MODEL` at call time
(`agent-platform/runtime/adapters/hermes_free_adapter.py:46-47`), and
`HermesFreeAdapter._call` re-reads exactly those variables at invoke time
(`scripts/worker_adapters.py:723-724`).

An identifier therefore survives every change to what it identifies. An operator
who confirms a Run against `request_id` is confirming a name, not the execution
configuration that name resolves to. A change to `cost_class`, a repointed
`model_env`, or a moved binding source can all occur without moving the digest,
so a confirmation can bind a mandate that no longer describes what will run.

ADR-045 establishes execution policy profiles and evidence contracts but does
not cover the request digest. This ADR adopts the versioned request digest
(`dispatch.request.v2`) as the contract direction.

## Decision

Cortxt will bind the confirmation to the **semantic content and immutable
revision** of the execution configuration, not to identifiers. The digest is
computed over a fixed, versioned field set that includes the material
configuration, the effective provider/model binding, the charging regime, and
the fallback conditions, in addition to the existing 17 fields.

### The bound field set

The digest is computed over exactly the existing 17 fields plus the following.

**Contract version**

- `request_contract_version` — integer, constant for the contract in force.
  Today `schema_version: 1` is emitted at `dispatch_request.py:358` and is
  absent from the allowlist at `:132-138`. It goes in.

**Execution identity and material configuration.** The **material** subset of
the execution profile (the `ExecutionProfile` type that W10/W11 introduce; the
fields that change what runs or what it may do) is bound:

- `execution.runtime_id`
- `execution.execution_profile_id`
- `execution.execution_profile_revision` — **new.** `"sha256:" + sha256` over
  the canonical form (§Canonicalisation) of the profile's material fields:
  `execution_profile_id`, `runtime_id`, `cost_class`, `reliability_class`,
  `task_shapes` (sorted), `provider`, `model`, `required_env` (sorted),
  `provider_env`, `model_env`, `tool_policy` (sorted), `checkpoint_required`,
  and the `report_channel`. This is the field that makes an unchanged ID
  insufficient: change `cost_class` from `free` to `metered`, or repoint
  `model_env`, and the revision moves.
- `execution.report_channel` — bound separately as well as inside the revision,
  because it determines whether a completion report is owed.

**Model and provider — the effective binding, not the profile's declaration**

- `execution.provider_id` — the profile's pinned `provider` if set, else the
  current value of the variable named by `provider_env`. A semantic id
  (`"nous"`), never a URL, never a key.
- `execution.model_id` — the profile's pinned `model` if set, else the current
  value of the variable named by `model_env`. The full route string as the
  runtime will receive it.
- `execution.binding_source` — `{"provider": "pinned" | "<ENV_VAR_NAME>",
  "model": "pinned" | "<ENV_VAR_NAME>"}`. The **name** of the variable, never
  its value beyond `provider_id` / `model_id` themselves. Binding the source
  means moving a binding from a pinned profile to an environment variable
  invalidates the confirmation even when the resulting strings are identical.

**Charging and fallback conditions**

- `charge_policy.charge_policy_id` and `charge_policy.charge_policy_revision` —
  the digest of the declared per-`(provider_id, model_id)` charging record: its
  `charging` verdict (`zero_charge` | `metered`), its official source, the date
  it was read, and its expiry.
- `charge_policy.route` — `"zero_charge"` | `"metered"`. The operator confirms
  which regime they are launching under.
- `fallback.routing_fallback_engine_id` — the value passed as `route()`'s
  `fallback`, `DEFAULT_FALLBACK_ENGINE = "claude"`.
- `fallback.paid_fallback_reachable` — boolean, server-computed: `True` when the
  request's routing could resolve to an engine whose `cost_class` is not in the
  approved zero-charge set.
- `fallback.engine_policy_pinned` — boolean: whether the mandate's `Engine
  policy` section named an explicit engine, in which case `route_for_issue`
  bypasses `route()` entirely (`dispatch_request.py:255-268`).
- `fallback.engine_manifest_matched` — boolean. The lenience at
  `dispatch_request.py:266-268` returns a mandate-approved engine even with no
  manifest match, and therefore with no `cost_class` and no `reliability_class`
  to check. Binding this makes the operator see when the safety properties were
  unavailable.

**Already bound; not duplicated.** `engine`, `max_cost_usd`,
`max_runtime_seconds`, `max_parallel_workers`, `delegation_depth`,
`artifact_policy`, `isolation`, `worker_role`, `workflow_id`, `routing_reason`,
`routable_task_tags`, `engine_policy`, `scope`, `acceptance_criteria`,
`approval_reference`, `issue_id`, `workflow` are already in
`REQUEST_DIGEST_FIELDS` and stay unchanged.

### What must NOT be bound

Binding any of the following converts a cosmetic or environmental change into a
spurious re-confirmation, which trains operators to re-confirm without reading.

- **Display strings.** `label` and `notes` on `ExecutionProfile`,
  `RUNTIME_LABELS`, and everything derived from them: `runtime_label`,
  `profile_label`, `display_label`. Renaming "Free" to "Free tier" must not
  invalidate a confirmation.
- **Every secret.** API keys, tokens, endpoints, carrier paths, credential file
  locations. None is read, printed, digested, or persisted. Only the **names** of
  the non-secret routing variables cross into `binding_source`.
- **Environment-derived volatile fields.** Concretely: `eligible`, `missing`,
  `errors`, `engine_registered`, `engine_unavailable_reason`, and every preflight
  reason string, including `_dsh_carrier_preflight`'s carrier-mode sentence.
- **Timestamps, run identity, and anything post-hoc.** `claimed_at`,
  `finished_at`, `run_id`, elapsed seconds, `estimated_cost_usd`, token counts,
  `cost_status`. These are observations and cannot participate in an approval
  computed before the run.
- **`agent_role` and `orchestration_mode`**, already implied by the digested
  `worker_role` and `delegation_depth`.
- **`ExecutionIdentity.provider` / `.model` as projected**, which are
  observation-influenced. The approval binds `execution.provider_id` /
  `.model_id` as resolved at preview, not as projected after a run.

### Canonicalisation rule

The current rule is `json.dumps({key: payload.get(key) for key in
REQUEST_DIGEST_FIELDS}, sort_keys=True, separators=(",", ":"), default=str)` over
`sha256`, prefixed `"sha256:"`. The successor keeps its shape and closes three
gaps.

1. **Fixed key tuple, retained.** The hashed object is built by comprehension
   over a constant tuple, so its key set never varies with the payload.
2. **`sort_keys=True`, `separators=(",", ":")`, UTF-8.** Nested objects are
   ordinary JSON objects canonicalised by the same `sort_keys`; sequences are
   **sorted before insertion**, so declaration order is not load-bearing.
3. **`default=str` is removed and replaced by a raise.** A value the
   canonicaliser cannot represent losslessly is a server error that **denies the
   launch**, not a value it guesses at. Numeric limits are normalised to a
   declared type before hashing (`max_cost_usd` to `float`, the integer limits to
   `int`).
4. **Model and provider strings are hashed verbatim** — no case folding, no alias
   resolution, no whitespace trimming beyond rejecting leading or trailing
   whitespace outright as `invalid`.
5. **The contract version participates as a first-class hashed field**, giving
   domain separation between contract versions. It is not a prefix on the digest
   string, because a prefix can be stripped by a caller and a hashed field
   cannot.
6. **`None` and absent are the same input**, and both are legitimate for optional
   fields. A field *required* by the contract that resolves to `None` is not
   hashed as `null` — it **denies the launch**, with `execution_binding_unresolved`
   in `missing` and the field named in the recovery text.

### The test that demonstrates it

`test_material_profile_change_invalidates_prior_confirmation` — in-process,
injected environment and injected profile catalog. No provider call, no process
start, no GitHub call.

1. Build the request through the production builder and record `R1`. Assert
   `eligible is True`, `provider_id == "nous"`, `model_id ==
   "vendor/model-a:free"`.
2. **Negative control — cosmetic change.** Replace the `hermes-free` entry with
   one identical except `label="Free tier"`, `notes="reworded"`. Rebuild.
   **Assert `R2 == R1`**, and that a confirmation carrying `R1` still binds.
3. **Material change, ID unchanged.** Replace the entry with one identical except
   `cost_class="metered"` — same `execution_profile_id`, `runtime_id`,
   `provider_env`, `model_env`, `required_env`. Rebuild. **Assert `R3 != R1`**,
   and that `execution_profile_revision` differs while `execution_profile_id` is
   byte-identical. Repeat, parameterised, for every other material field, so a
   future field added to `ExecutionProfile` without being classified material or
   cosmetic **fails the test** rather than silently escaping the revision.
4. **Material change, profile unchanged.** Restore the original catalog and
   change only `CORTXT_FREE_MODEL` to `"vendor/model-b:free"`. Rebuild. **Assert
   `R4 != R1`.** This is the case that today produces a byte-identical
   `request_id`.
5. **Refusal at the boundary, both entry points.** Feed the stale `R1` into
   `WidgetActionHost._bind_claim_run` and into `gh_claim_run_resume` under each
   of the environments from steps 3 and 4. Assert both raise the staleness
   refusal, that the refusal names the field that moved, and — the load-bearing
   half — that **no claim was created**: `runs.json` byte-identical, the
   execution-map claim store empty, no `workflow:*` label moved.
6. **Forgery control.** Supply a well-formed confirmation whose `execution` block
   asserts `model_id == "vendor/model-a:free"` while the injected environment
   holds `model-b`. Assert refusal, and that the refusal comes from server
   re-derivation rather than from comparing the payload against itself — verified
   by asserting the server never reads the `execution` block from the request
   body at all, only the digest string.

A run that passes step 2 and fails any part of step 3 or 4 means the digest is
binding a name and not its content, which is the defect this correction exists
to close.

## Consequences

### Positive

- A confirmation binds what will actually run, not a name that may have moved.
- A material change to the execution configuration invalidates a prior
  confirmation, so an operator is never silently moved onto a different
  configuration.
- The operator sees the charging regime and fallback conditions they are
  launching under.
- Cosmetic and environmental changes do not force spurious re-confirmations.

### Negative

- The digest is more expensive to compute and to present, because it requires
  resolving the effective binding and the profile revision at preview time.
- The bound field set is larger, so the confirmation surface must present more
  fields.

### Risks

- A field added to `ExecutionProfile` without being classified material or
  cosmetic silently escapes the revision. The parameterised test in §The test
  that demonstrates it is the guard against this.
- The `default=str` removal means a value the canonicaliser cannot represent
  losslessly denies the launch. This is intended, but it is a behaviour change
  from the predecessor.

## Alternatives Considered

1. **Keep the identifier-only digest** — Rejected because an identifier survives
   every change to what it identifies, which is the defect this ADR closes.
2. **Bind the full profile object** — Rejected because it would bind display
   strings and volatile fields, converting cosmetic changes into spurious
   re-confirmations.
3. **Bind the profile revision only, not the effective binding** — Rejected
   because the effective provider/model binding can change via environment
   variables without the profile changing, which is the case that today produces
   a byte-identical `request_id`.

## Validation

- [ ] Implementation matches decision
- [ ] Tests cover decision boundaries
- [ ] Documentation updated

## Expiry/Review Trigger

- Review by: 2026-12-10
- Trigger: a change to the execution configuration model, the charging model, or
  the fallback model that alters the material field set.
