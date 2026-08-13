# Issue tracker: GitHub

Status: active normative
Authority: repository governance
Last verified: 2026-08-13

GitHub Issues remain the durable task records for this repository. Project 4,
now named `Legacy AI Workspace Delivery — frozen`, is a frozen legacy planning
layer and is not Cortxt's active roadmap. Do not add, reclassify, or dispatch
work from it without a separate operator decision. Use the repository remote to
resolve `rian010194/ai-workspace-control-plane` and use `gh` for tracker
operations.

## Current workflow-state availability

No planning-state carrier is currently designated. Project 4 is frozen and
GitHub Issue state alone does not encode `Inbox`, `Ready`, `In progress`,
`Review`, `Blocked`, and `Done`. Worker dispatch is therefore suspended until
the operator explicitly designates a replacement carrier and its state mapping.

The state names below define the required lifecycle contract; they do not prove
that a current carrier exists.

## Conventions

- Create an issue with a descriptive title and structured Markdown body.
- Read the issue, labels, assignees, dependencies, comments, and any explicitly
  designated current planning state before acting.
- Use these workflow states after a current carrier is designated: `Inbox`,
  `Ready`, `In progress`, `Review`, `Blocked`, and `Done`.
- Treat authoritative `Ready` as execution approval only when scope, acceptance
  criteria, worker role, time limit, cost limit, and human approval are present.
- Record runtime identity and evidence using the repository's `docs/architecture/dispatch-contract.md`.
- Pull requests are not a request or triage surface.

## Wayfinding operations

Wayfinder uses one issue labelled `wayfinder:map` as the canonical map and child issues as decision tickets.

- Map body sections: `Destination`, `Notes`, `Decisions so far`, `Not yet specified`, and `Out of scope`.
- Child labels: `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`.
- Prefer native GitHub sub-issues. If unavailable, add the child to a task list in the map and put `Part of #<map>` at the start of the child.
- Prefer native issue dependencies for blocking. If unavailable, put `Blocked by: #<issue>` at the start of the blocked ticket.
- Claim a frontier ticket by assigning it before work begins. An open unassigned child without open blockers is available.
- Resolve a ticket by posting the decision or findings, closing it, and adding a short linked pointer under the map's `Decisions so far`.
- Research tickets may run in parallel. HITL grilling and prototype tickets require live human participation.

## Safety

- Creating or dispatching child work requires the operator-approved map and ticket.
- A runtime card or delegation handle is never a second backlog item.
- Do not copy secrets, private documents, full prompts, or model reasoning into issues or comments.
