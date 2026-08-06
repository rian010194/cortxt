# GitHub Projects Kanban — Setup Guide

## Purpose

One canonical Kanban board for the AI Workspace control plane. GitHub Issues/Projects remain the only durable task registry. Hermes Kanban and Buzz are runtime surfaces only.

## Recommended board: AI Workspace Delivery

If a board named **AI Workspace Delivery** does not yet exist, create it at:
`https://github.com/users/rian010194/projects`

Then link it to repository `rian010194/ai-workspace-control-plane`.

## Columns (status fields)

| Column | Meaning | Who moves |
|--------|---------|-----------|
| **Backlog** | Ideas, unrefined tasks, future work | Operator or Coordinator |
| **Triage** | Needs scoping, acceptance criteria, route selection | Operator |
| **Ready** | Approved scope, acceptance criteria, runtime limits, `Ready` for dispatch | Operator only |
| **In progress** | Active worker run, one or more attempts | Auto on claim, manual if manual dispatch |
| **Review** | Result returned, pending independent review or operator acceptance | Auto on result submission |
| **Blocked** | Non-recoverable failure, needs decision | Auto on structured failure or manual |
| **Done** | Approved, merged, published, or completed | Operator only |

## Custom fields (add to the project)

| Field | Type | Purpose |
|-------|------|---------|
| `Work type` | Single select: Research / Implementation / Review / Planning | Route hint |
| `Suggested route` | Single select: Researcher / Builder / Codex Reviewer / Coordinator / Operator decides | Runtime hint |
| `Write permission` | Single select: Read-only / Sandbox or worktree only / Named files only / None | Security boundary |
| `Max runtime` | Text | Hard stop limit |
| `Max budget` | Text | USD cap or `unknown-not-allowed` |
| `Runtimes` | Text | Attempted runs: `run_id` list |
| `Actual cost` | Text | Observed or `unknown` |
| `Reviewed by` | Text | Profile or tool that did independent review |

## Automation rules (GitHub built-in)

1. When an issue is **closed** → move to **Done**.
2. When a PR is **merged** linked to an issue → move issue to **Done**.
3. When label `blocked` is added → move to **Blocked**.
4. When label `ready` is added → move to **Ready** (only if already in Triage or Backlog).

## Workflow for an issue moving through the board

```
Backlog
  -> Operator reviews, fills acceptance criteria -> Triage
Triage
  -> Operator approves scope, budget, route -> Ready
Ready
  -> Hermes/Pi claim or manual dispatch -> In progress
In progress
  -> Worker returns result with evidence -> Review
Review
  -> Independent review passes + operator approval -> Done
  -> Structured failure -> Blocked
Blocked
  -> Operator decides retry (new run_id) or close -> Ready or Done
```

## What NOT to do

- Do not create a second Kanban in Buzz, Hermes, Notion, or elsewhere.
- Do not let a worker move an issue to Done.
- Do not place runtime-generated cards outside GitHub Issues.
- Do not copy prompts, secrets, or customer data into Project fields.
