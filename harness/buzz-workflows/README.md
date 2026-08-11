# Buzz workflow reconciliation

Issue: [#21](https://github.com/rian010194/ai-workspace-control-plane/issues/21)

This directory contains channel-routing workflows for Buzz. Definitions are
version controlled and disabled by default. They do not replace GitHub as the
task source of truth or the dispatch contract.

## Safety model

- A `[BUILD_READY]` message may only be emitted after the referenced GitHub
  issue is approved and `Ready` with a complete dispatch request.
- Workflow definitions only route channel messages. They do not claim that an
  agent run is pollable, recoverable, or approved for unattended execution.
- No Buzz private key or auth tag belongs in this repository.
- Applying definitions and enabling them are separate operations.

## Validate and plan

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/Sync-BuzzWorkflows.ps1 `
  -ChannelId '<vertical-01-channel-uuid>'
```

This is a local dry run. It validates the repository definitions and reports
what would be reconciled without contacting or changing Buzz.

## Reconcile disabled definitions

Supply `BUZZ_PRIVATE_KEY` and, when required, `BUZZ_AUTH_TAG` through the
operator's approved secret-injection mechanism. Then run:

```powershell
$env:BUZZ_WORKFLOW_APPLY_APPROVED = 'true'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/Sync-BuzzWorkflows.ps1 `
  -ChannelId '<vertical-01-channel-uuid>' `
  -Apply
```

## Enable definitions

Enabling is a distinct operator action:

```powershell
$env:BUZZ_WORKFLOW_APPLY_APPROVED = 'true'
$env:BUZZ_WORKFLOW_ENABLE_APPROVED = 'true'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/Sync-BuzzWorkflows.ps1 `
  -ChannelId '<vertical-01-channel-uuid>' `
  -Apply `
  -Enable
```

Adding another `*.yaml` file to `definitions/` makes it part of the next
reconciliation automatically. Continuous or scheduled reconciliation remains
disabled until a pollable dispatcher satisfies the repository dispatch
contract.

## Hosted Vertical 01 status on 2026-08-02

The definitions were entered through Buzz Desktop for hosted channel
`265caa75-334c-4075-8363-be88ef4077f9`. Trigger rendering worked, but a
workflow-generated textual `@Builder` did not wake Builder without a manual
interactive mention. Builder terminal output was also unavailable after manual
wake. These definitions must therefore remain a supervised routing experiment,
not an unattended dispatcher.

All marker filters use `str_starts_with`, and every agent outcome marker must
be the first text in its message. Do not change them back to `str_contains`:
later marker names appear inside workflow instructions and would otherwise
trigger downstream workflows prematurely.

See
`docs/archive/handoffs/2026-08-02-buzz-workflow-session.md` for the complete
evidence, environment distinction, security note, and resume order.
