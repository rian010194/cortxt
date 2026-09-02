# ADR-045: Execution policy profiles and evidence contracts

**Status:** Proposed  
**Date:** 2026-09-02  
**Deciders:** Operator approval required  
**Technical Story:** issue #495; follow-up to the S7 execution proof and issues #489, #490, and #493

## Context

ADR-018 makes `workflow:*` labels the sole workflow-state carrier, while
ADR-040 distinguishes delivery paths and Atlas records an optional `Work kind`.
Those classifications answer where work is in its lifecycle and how it is
presented; they do not determine whether an Issue is safe to dispatch or what
constitutes acceptable evidence.

A `bug` may ask for diagnosis, a code fix, or documentation. Research may
legitimately finish with a durable report and no commit. An Atlas map or epic is
a planning record and should not launch a worker at all. Treating labels as an
implicit execution policy would therefore either over-authorize unknown work or
force every kind of work through the mutating-code evidence contract.

The S7 proof intentionally covers one bounded mutating-delivery shape. Cortxt
needs to permit that proven shape without claiming that every combination of
labels, work kinds, effects, and evidence has already earned execution.

## Decision

Cortxt will resolve every dispatch to one named, versioned **execution policy
profile** before a claim is acquired. A profile binds an eligible work shape to
its permitted effects, isolation, artifact scope, runtime/provider limits, and
**evidence contract**. Profile resolution is part of pre-flight authorization;
it is not inferred after execution.

The following classifications remain separate:

- `workflow:*` is lifecycle state only.
- `Work kind` describes the intended outcome for planning and rendering. Its
  current vocabularies are not sufficiently reconciled to serve as policy
  input or authority.
- descriptive labels such as `bug`, area labels, and `atlas:map` are metadata
  and constraints, never sufficient dispatch authority.
- task-shape tags select a compatible engine capability; they do not select an
  evidence policy or authorize execution.
- a risk modifier strengthens gates for effects such as authority/workflow
  mutation, security-sensitive code, secrets or customer data, schema changes,
  deployment, publication, and destructive or irreversible operations.
- the approved Issue mandate supplies one explicit `Execution profile:
  <profile-id>/<version>` together with concrete scope, limits, artifact
  policy, worker role, risk modifiers, and human approval.
- the execution policy profile is the versioned platform rule that combines
  those inputs into permitted execution and required evidence.

Resolution must fail closed when the work kind is absent where required,
unknown, contradictory, unsupported by the requested effect, or lacks a named
profile. A generic agent or generic evidence fallback is forbidden. Multiple
labels do not create profiles through combinatorial matching: labels may narrow
or deny an explicitly selected profile, but may never silently widen it.

Profile parsing is a strict, versioned authorization boundary and must not reuse
Atlas's presentation parser or its default-to-`delivery` behavior. Missing or
invalid values, unknown versions, multiple profile declarations, a task-shape/
worker-role mismatch, and a mutation request that conflicts with the profile
all deny dispatch before claim acquisition.

The server-side resolver constructs the effective policy as the intersection of
the base profile, mandate constraints, and risk modifiers. Constraints may
remove capabilities or strengthen gates; they never add a capability absent
from the base profile. Any requested effect outside that intersection, parse
failure, or conflict denies dispatch. Legacy isolation waivers are unsupported
for profiles that require isolation.

The profile identifier/version, risk modifiers, and canonical effective-policy
fingerprint are included in the immutable dispatch request and its `request_id`
digest. Pre-flight receipt, claim, and durable Run all carry the same binding.
Any policy change after confirmation produces a new request and requires new
operator confirmation; recording policy only after launch is forbidden.

The initial profile catalog is deliberately bounded:

| Profile family | Eligible outcome | Minimum execution/evidence rule |
| --- | --- | --- |
| `code-change/v1` | Bounded code or configuration change | Isolated worktree; concrete allowed paths; new correlated commit on the Run branch/worktree; DCO; profile-required tests; Evidence Gate; durable review submission |
| `docs-change/v1` | Bounded tracked-document change | Isolated worktree; docs-only allowed paths; new correlated commit on the Run branch/worktree; documentation checks; Evidence Gate; durable review submission |
| `research-report/v1` | Research or diagnosis without workspace, repository, or arbitrary external mutation | One profile-named append-only evidence-output port; durable structured report with declared sources/assertions, schema, redaction/data-class, and retention enforcement; no fabricated commit requirement |
| `controlled-proof/v1` | Explicit platform/CI proof | Named fixture environment, assertions, cleanup and correlation requirements; never inferred from a general Issue label |

Only a profile that has its own positive, negative, replay, cleanup, and
end-to-end proof may be enabled for real dispatch. S7 may enable its proven
mutating-delivery profile first. Other families remain unavailable until their
contracts and proofs exist.

`research-report/v1` remains disabled until its authoritative evidence-output
port and storage are selected. The port is the only permitted write capability:
it accepts the versioned report schema and enforces redaction, data class, and
retention. It does not grant filesystem, repository, Issue-edit, comment, or
other general external mutation rights.

Atlas maps, epics, decision-only Issues, and unknown combinations are
non-dispatchable by default. They must be decomposed into or explicitly
reclassified as an eligible bounded work item; graph position, `workflow:ready`,
or a `bug` label alone does not grant execution authority.

`bug` is a constraint modifier, not a profile. For a mutating fix its evidence
contract additionally requires a pre-fix reproduction or explicitly justified
non-reproduction, plus post-fix regression evidence. A `bug` combined with
documentation or research still uses the explicitly selected base profile and
cannot gain mutation rights from the label.

Risk modifiers may require stronger isolation, provider/data-class assurance,
tests, reviewers, or reserved operator decisions. Neither Issue text nor labels
may lower the base profile's risk requirements. A conflict denies dispatch.

## Consequences

### Positive

- Cortxt can begin with a narrow proven execution shape without pretending to
  support every Issue form.
- Evidence is judged against the requested outcome: mutating work cannot pass
  without a commit, while legitimate evidence-only work is not forced to invent
  one.
- New work shapes are added as explicit, testable policy profiles rather than
  fragile label combinations.
- The UI can explain both why a Workstream is or is not runnable and exactly
  what evidence its Run must produce.

### Negative

- Existing Issue metadata is not yet sufficient to resolve every profile;
  templates and validation need an explicit versioned profile reference and
  typed mandate constraints.
- Research, diagnosis, Atlas, and specialized CI work remain unavailable from
  the general launcher until their profiles are implemented and proven.
- Profile versioning and migration become part of the durable Run contract.

### Risks

- Treating `Work kind` or `bug` as authority would recreate an implicit generic
  fallback. Resolution tests must prove that descriptive metadata can only
  constrain a profile.
- A large profile catalog could become another workflow taxonomy. Profiles
  should be added for materially different effect/evidence contracts, not for
  every label or team convention.
- Re-evaluating an old Run against the newest profile could rewrite history.
  Review must use the profile identifier and version recorded at dispatch.

## Alternatives Considered

1. **One universal execution and evidence policy.** Rejected because mutating
   delivery and evidence-only inquiry have incompatible valid outcomes.
2. **Map every GitHub label combination to policy.** Rejected because labels
   are open-ended metadata, combinations grow without bound, and descriptive
   labels are not authorization.
3. **Let the agent choose its evidence contract at runtime.** Rejected because
   the worker cannot define the gate used to judge its own success.
4. **Delay all real use until every work kind is supported.** Rejected because
   independently proven profiles can be enabled safely while unsupported work
   continues to fail closed.

## Validation

- [ ] A versioned schema represents profile identity, permitted effects,
      isolation, artifact constraints, limits, and evidence requirements.
- [ ] Pre-flight rejects absent, unknown, contradictory, and unsupported
      profile inputs before acquiring a claim or invoking a worker.
- [ ] Durable Run records contain the resolved profile identifier and version.
- [ ] Dispatch request, `request_id`, pre-flight receipt, claim, and Run bind
      the same profile/version, risk modifiers, and effective-policy fingerprint;
      any change requires operator reconfirmation.
- [ ] Mutating-delivery tests cover a `bug` fix and prove that the `bug` label
      alone grants no authority.
- [ ] Documentation tests reject changes outside the approved docs paths.
- [ ] Evidence-only tests accept a valid durable report without a commit and
      reject every write except the named evidence-output port.
- [ ] Atlas maps, epics, decision-only Issues, and unknown combinations expose
      no launch action.
- [ ] Each enabled profile has positive, negative, replay, cleanup, and real
      end-to-end evidence before production enablement.

## Expiry/Review Trigger

Review on the first proposed non-mutating real Run, the first attempt to launch
an Atlas map or epic, the first new profile family, or any request to derive
execution authority directly from a GitHub label.
