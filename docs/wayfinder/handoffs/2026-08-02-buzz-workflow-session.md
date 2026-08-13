# Session handoff: Buzz workflows and Vertical 01 ticket 09

Date: 2026-08-02  
Repository: <https://github.com/rian010194/ai-workspace-control-plane>  
Primary ticket: <https://github.com/rian010194/ai-workspace-control-plane/issues/9>  
Workflow follow-up: <https://github.com/rian010194/ai-workspace-control-plane/issues/21>

## Outcome

Six version-controlled Buzz workflow definitions and a reconciliation script
were prepared under `harness/buzz-workflows/`. The definitions were also added
manually through Buzz Desktop to the existing hosted Vertical 01 channel.

The experiment verified that a channel message can trigger a Buzz workflow and
that `{{trigger.message_id}}` and `{{trigger.text}}` can be rendered into the
workflow output. It did **not** establish an unattended Builder path. Two
runtime blockers remain:

1. a textual `@Builder` emitted by the hosted workflow did not wake Builder
   unless the operator added an interactive mention; and
2. once Builder was woken, its terminal tool only echoed the submitted command
   and returned no command output, after which the agent session timed out.

No `verticals/vertical-01-ai-act/` implementation was completed. Ticket 09 must
therefore resume from the package-schema milestone, not from review.

## Locked ticket 09 boundary

The accepted v0.1 boundary is:

- decision basis: Articles 2–3, Article 5, Article 6 including 6.3–6.4,
  Annex I, and Annex III;
- requirements assessed in v0.1: Articles 9–12, with Annex IV supporting
  Article 11;
- outside v0.1: Articles 14–15, deferred to v0.2; and
- every unverified legal constraint and expected conclusion must be marked
  `Needs primary-source research` until verified against the primary EUR-Lex
  source.

The intended first implementation milestone remains a machine-loadable
`vertical.yaml`, one domain workflow, input/output JSON Schemas, an eval suite,
and at least one valid and one intentionally invalid colocated synthetic case.
Harness-owned retries, timeouts, cancellation, credentials, routing, generic
metrics, and generic reports must not move into the vertical.

## Version-controlled Buzz assets

The repository now contains:

- `harness/buzz-workflows/definitions/01-dispatch-builder.yaml`
- `harness/buzz-workflows/definitions/02-dispatch-review.yaml`
- `harness/buzz-workflows/definitions/03-review-changes.yaml`
- `harness/buzz-workflows/definitions/04-dispatch-research.yaml`
- `harness/buzz-workflows/definitions/05-research-complete.yaml`
- `harness/buzz-workflows/definitions/06-review-approved.yaml`
- `harness/buzz-workflows/scripts/Sync-BuzzWorkflows.ps1`
- `harness/buzz-workflows/tests/Sync-BuzzWorkflows.Tests.ps1`

Routing markers are:

| Marker at start of message | Destination |
|---|---|
| `[BUILD_READY]` | Builder |
| `[BUILD_COMPLETE]` | Codex Reviewer |
| `[REVIEW_CHANGES_REQUIRED]` | Coordinator |
| `[RESEARCH_REQUEST]` | Researcher |
| `[RESEARCH_COMPLETE]` | Coordinator |
| `[REVIEW_APPROVED]` | Coordinator/operator gate |

Filters use `str_starts_with(trigger_text, "[MARKER]")`, not
`str_contains`. This prevents instructional text that merely mentions a later
marker from prematurely firing another workflow. Agent responses must put the
outcome marker first.

Definitions remain disabled by default in Git. Enablement is an explicit
operator action. During recovery, enable only one link at a time.

## Buzz environments discovered

Buzz Desktop uses the hosted relay:

```text
wss://cortxt.communities.buzz.xyz
```

The existing hosted Vertical 01 channel is:

```text
265caa75-334c-4075-8363-be88ef4077f9
```

A separate local relay was built and brought to readiness during diagnosis.
It required Postgres, Redis, and MinIO. A duplicate local channel was created:

```text
e39a2f26-e539-484e-8cec-9a3024fc55c2
```

That local channel and its six local workflows are not visible in the hosted
Desktop workspace and are not the operational Vertical 01 channel. Do not
confuse the two environments. Do not delete the local test state without an
explicit operator decision.

## Reconciliation-script findings

The PowerShell workflow reconciler was corrected to:

- tolerate empty/null remote workflow entries;
- support Windows PowerShell 5 encoding behavior;
- send YAML through standard input using `--yaml -`, because passing a
  temporary filename is parsed as literal YAML; and
- keep apply and enable approvals separate.

PowerShell 7.6.4 was installed, but it may not be on `PATH` in an already-open
shell. Use an absolute path or open a new PowerShell session when necessary.

The hosted CLI could not substitute for the authenticated Desktop session: a
plain private-key invocation reached the hosted relay but returned
`relay_membership_required`. Workflows were therefore entered through Buzz
Desktop's YAML editor. Never commit or paste private keys or auth tags into
repository documentation.

## Verified workflow behavior

- `[BUILD_READY]` triggered `vertical_01_dispatch_builder` when enabled.
- `{{trigger.message_id}}` rendered a real source message ID.
- `{{trigger.text}}` rendered the complete compact dispatch request.
- Definitions pasted from Git may disable themselves because they contain
  `enabled: false`; Desktop enablement must be checked after every edit.
- Long chains must not be enabled all at once until each adjacent handoff is
  verified.

## Blocker 1: workflow mentions do not wake Builder

In the tested hosted environment, workflow output displayed `@Builder`, but
Builder did not start until the operator manually selected and added Builder as
an interactive mention.

Current Buzz source contains relay-side logic and the regression test
`workflow_send_message_p_tags_mentioned_member`, which should resolve an exact,
unambiguous channel-member display name into a Nostr `p` tag. Hosted behavior
shows that this guarantee is not currently available for this channel and
deployment. Only one Builder was reported in the channel, so a simple
duplicate-name explanation was ruled out.

Do not claim autonomous handoff until the emitted event is verified to contain
Builder's `p` tag and Builder wakes without operator intervention. Recovery
options, in preferred order, are:

1. reconcile or upgrade the hosted relay to a build containing the workflow
   mention fix and verify the emitted event;
2. verify that the member has an exact non-empty relay profile display name
   matching the workflow text; or
3. use a narrowly scoped temporary ACP subscription workaround for Builder,
   restricted to this channel and guarded by an explicit dispatch header and
   trigger-message ID.

The third option wakes Builder on more channel traffic and is not the desired
production design.

## Blocker 2: Builder terminal output unavailable

When Builder was manually woken, repository reads sometimes began, but terminal
calls returned only the submitted shell command, for example:

```text
$ cd /c/Users/rikar/Cortxt/projects/ai-workspace-control-plane && pwd
```

No actual working directory or command output followed. Sessions then ended in
`idle_timeout`. The compact dispatch instructed Builder to stop and report a
workflow blocker in this situation, but the agent continued planning and timed
out.

This is a Hermes/ACP tool-transport or profile-runtime blocker, not a ticket 09
schema problem. Before redispatch, verify with one bounded probe that Builder
can execute a working-directory command and receive the actual path. Also
verify that the agent fails closed when tool output is unavailable.

## Dispatch contract correction for the next attempt

The compact request used during the final test included most required fields,
but the dispatch contract also requires explicit `worker_role`,
`max_parallel_workers`, and `delegation_depth`. The next real dispatch must
include every field from `docs/architecture/dispatch-contract.md` and use a
dispatcher-generated `run_id`; a model must not invent one.

Before dispatch, verify GitHub issue #9 has approved scope, acceptance criteria,
and `Ready` state. A valid claim must move it to `In progress`. Buzz marker
routing alone does not implement claim, lease, polling, cost capture, or the
required terminal result envelope.

## Security note

A Desktop private key was exposed during interactive troubleshooting. Its value
is intentionally omitted here and must never be copied into Git, Buzz messages,
logs, or future prompts. Rotate the affected identity through the approved
identity-recovery process when channel ownership and membership migration can
be handled safely. Clear temporary shell variables after diagnosis:

```powershell
Remove-Item Env:BUZZ_PRIVATE_KEY -ErrorAction SilentlyContinue
Remove-Item Env:BUZZ_AUTH_TAG -ErrorAction SilentlyContinue
Remove-Item Env:BUZZ_RELAY_PRIVATE_KEY -ErrorAction SilentlyContinue
```

## Exact resume order

1. Confirm issue #9's live GitHub state and approved scope.
2. Keep all Buzz workflows disabled while repairing Builder runtime.
3. Run one manually mentioned Builder terminal probe. Require real output; do
   not accept command echo as evidence.
4. Verify or deploy hosted workflow mention-to-`p`-tag support.
5. Enable only `vertical_01_dispatch_builder` and send a test-only incomplete
   dispatch. Builder must wake automatically and return `[DISPATCH_BLOCKED]`.
6. Send a complete contract-valid dispatch with a dispatcher-generated
   `run_id`. Confirm the full trigger text appears in the workflow handoff.
7. After a real `[BUILD_COMPLETE]`, enable and test only the review handoff.
8. Add changes, research, and approval links one at a time after the preceding
   link has produced observable evidence.
9. Do not describe ticket 09 as implemented until actual repository artifacts,
   a focused diff, and reproducible validator output exist.

