# Manual Dispatch Routine

## Purpose

Until the general automated dispatcher exists, this is the repeatable routine for moving an approved GitHub issue into a Hermes or Pi runtime run, and returning the result to GitHub.

> **2026-08-06 — automated wrapper added:** the steps below are codified and
> verified in `harness/scripts/dispatch-manual.sh` (minimal contract-compliant
> manual dispatch adapter, proven end-to-end on issue #25). It enforces the
> same fail-closed guard (no dispatching a blocked ticket, acceptance criteria
> present, workflow status `Ready`), generates `run_id` in the shell, transitions
> `Ready → In progress → Review`, posts the result envelope, and pushes status to
> Buzz. `Done` remains operator-only. Run it from the repo root:
> `OPENROUTER_API_KEY=... bash harness/scripts/dispatch-manual.sh "<owner/repo#N>" researcher`
> See the script header for the contract mapping.

## Prerequisites

- [ ] Issue is in GitHub Project column **Ready**.
- [ ] Issue has complete acceptance criteria.
- [ ] Issue has `Max runtime` and `Max budget` fields filled.
- [ ] Issue has `Suggested route` selected.
- [ ] No active `run_id` already claims this issue.
- [ ] Operator has reviewed the issue and approves dispatch.

## Step 1: Generate run identity

Generate a `run_id` now, outside any model:

```bash
# Bash / Git Bash
export RUN_ID="$(date -u +%Y%m%d_%H%M%S)_$(openssl rand -hex 4)"
echo "$RUN_ID"
```

Or in PowerShell:

```powershell
$RunId = (Get-Date -Format "yyyyMMdd_HHmmss") + "_" + (-join ((1..8) | ForEach-Object { "{0:X}" -f (Get-Random -Max 16) }))
Write-Host $RunId
```

## Step 2: Select runtime and profile

| Suggested route | Runtime | Command / Action |
|-----------------|---------|------------------|
| Coordinator | Hermes CLI, coordinator profile | `hermes -p coordinator` |
| Researcher | Hermes CLI, researcher profile | `hermes -p researcher` |
| Builder | Pi Builder Docker or Hermes builder profile | See Pi runtime docs or `hermes -p builder` |
| Codex Reviewer | Codex CLI, read-only mode | `codex --mode ask` or `codex review <pr>` |
| Operator decides | Operator selects after reading issue | — |

## Step 3: Open Hermes with the correct profile

```bash
# Example: dispatching to researcher
hermes -p researcher
```

Inside the Hermes session, give the agent:

- The exact GitHub issue URL or `owner/repo#issue_number`.
- The acceptance criteria from the issue.
- The `run_id` you generated.
- The runtime limits (`max_runtime_seconds`, `max_cost_usd`).

Example opening prompt:

```
Issue: rian010194/ai-workspace-control-plane#7
run_id: 20260802_143052_a1b2c3d4
Max runtime: 600 seconds
Max budget: USD 0.50
Acceptance criteria:
- [ ] Skill gap analysis completed
- [ ] Hermes skills mapped to workflow requirements
- [ ] Result written to docs/agents/skills-inventory.md

Execute this task. Return a complete result envelope with status, evidence, model, usage, and cost.
```

## Step 4: Worker execution

Hermes will:

1. Read the issue via `web_extract` or `terminal(gh issue view …)`.
2. Plan steps and optionally use `delegate_task` for parallel subtasks.
3. Execute within the runtime and budget limits.
4. Return a result envelope as a GitHub comment or local file.

## Step 5: Record the result

The worker must produce a result comment on the GitHub issue with this structure:

```markdown
## Run result: `RUN_ID`

| Field | Value |
|---|---|
| Status | `succeeded` / `failed` / `timed_out` / `budget_exceeded` / `blocked` / `cancelled` |
| Runtime | Hermes / Pi / Codex |
| Worker role | coordinator / researcher / builder / reviewer |
| Model | provider/model identifier |
| Started at | UTC timestamp |
| Finished at | UTC timestamp |
| Usage | input / output / cache / reasoning tokens |
| Cost | amount and confidence (`unknown` if unavailable) |
| Artifacts | paths or PR links (no secrets) |
| Evidence | tests, sources, assertions |
| Error | category and recovery suggestion (if not succeeded) |
```

If the worker cannot post to GitHub, the operator copies the result from the session and posts it.

## Step 6: Move the issue

- If result is `succeeded` with evidence → move to **Review**.
- If result is `failed` / `timed_out` / `budget_exceeded` → move to **Blocked**.
- If retry is approved → generate new `run_id`, go to Step 3.

## Step 7: Independent review (when required)

If the issue workflow requires review:

1. Dispatch Codex or a second Hermes profile in **read-only** mode.
2. Provide: issue, acceptance criteria, diff/artifact, test evidence.
3. Record review result as a separate comment.
4. Only operator approval moves the issue to **Done**.

## Quick reference: One-liner dispatch

```bash
# Read issue, generate run_id, open Hermes with context
ISSUE="rian010194/ai-workspace-control-plane#7"
RUN_ID="$(date -u +%Y%m%d_%H%M%S)_$(openssl rand -hex 4)"
gh issue view "$ISSUE" --json title,body,labels > /tmp/issue.json
hermes -p researcher -q "Run $RUN_ID for $ISSUE. Read /tmp/issue.json. Execute within 10 min / USD 0.50. Post result envelope as comment."
```

## Fail-closed rules

- If any prerequisite is missing → do not dispatch.
- If runtime limit is exceeded → worker must stop, report `timed_out`.
- If budget is unknown and `unknown-not-allowed` is set → report `budget_exceeded`.
- If result envelope is incomplete → treat as `blocked` until operator resolves.
