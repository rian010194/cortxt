# Agent instructions

## Required orientation

Before evaluating the architecture, proposing a new execution path, or
dispatching work, read these files in order:

1. `docs/agents/current-operating-model.md`
2. `docs/architecture/dispatch-contract.md`
3. `docs/architecture/runtime-and-evaluation-harness.md`
4. `docs/agents/atlas.md` -- roadmap maps derived from GitHub Issues (#210); see also `docs/agents/issue-tracker.md`'s Wayfinding section
5. the GitHub issue and any explicitly designated current planning state

Do not infer the operating model from one experiment, one Buzz limitation, or
one runtime README. In particular, a limitation in Buzz-native delegation does
not mean that Hermes routing is unverified or should be bypassed.

## Agent skills

### Issue tracker

Durable work for this repository is tracked in GitHub Issues. See
`docs/agents/issue-tracker.md` for the current planning-state rules.

### Domain docs

The historical domain inventory is kept locally outside this repository (not
published), but it is not current operating authority. Use the operating
model and accepted ADRs in `docs/adr/` for current boundaries.

## Control-plane boundaries

- GitHub Issues are the durable source of truth for scope, evidence, review,
  and approval. Use a GitHub Project for workflow state only when it is
  explicitly designated current; Project 4 is frozen legacy and must not be
  used for new dispatch.
- Runtime task lists, including Hermes Kanban, are execution ledgers only and must correlate to a GitHub issue.
- Worker dispatch is suspended until a planning-state carrier is explicitly
  designated current. After designation, do not dispatch before the issue has
  approved scope, acceptance criteria, runtime limits, and authoritative
  `Ready` status.
- Do not place secrets, customer documents, prompts, or model reasoning in GitHub or committed artifacts.
- Workers may not approve, merge, deploy, publish, or close their own work.
