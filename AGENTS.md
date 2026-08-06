# Agent instructions

## Required orientation

Before evaluating the architecture, proposing a new execution path, or
dispatching work, read these files in order:

1. `docs/agents/current-operating-model.md`
2. `docs/architecture/dispatch-contract.md`
3. `docs/architecture/runtime-and-evaluation-harness.md`
4. the GitHub issue and its current Project workflow state

Do not infer the operating model from one experiment, one Buzz limitation, or
one runtime README. In particular, a limitation in Buzz-native delegation does
not mean that Hermes routing is unverified or should be bypassed.

## Agent skills

### Issue tracker

Work for this repository is tracked in GitHub Issues and Projects. See `docs/agents/issue-tracker.md`.

### Domain docs

This repository uses a single-context domain-document layout. See `docs/agents/domain.md`.

## Control-plane boundaries

- GitHub Issues/Projects are the source of truth for scope, workflow status, evidence, review, and approval.
- Runtime task lists, including Hermes Kanban, are execution ledgers only and must correlate to a GitHub issue.
- Do not dispatch a worker before the issue has approved scope, acceptance criteria, runtime limits, and `Ready` status.
- Do not place secrets, customer documents, prompts, or model reasoning in GitHub or committed artifacts.
- Workers may not approve, merge, deploy, publish, or close their own work.
