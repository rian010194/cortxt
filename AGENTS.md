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
Parallel operator dispatch is documented in `docs/agents/work-launcher.md`.

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

## Session injection (workspace-local coordination)

Parallel sessions coordinate deliveries through a file-based inbox OUTSIDE
the repository: `lab/inbox/` (workspace-local, never tracked). Conventions:

- Each session has an `out/` and `in/` directory under `lab/inbox/`.
- A session that produces something another session (or the coordinator)
  should see writes a message file to `lab/inbox/<target>/in/` with
  YAML frontmatter: `from`, `to`, `type` (`delivery` | `request` |
  `handoff`), `created`, `artifact`, `affects`.
- The coordinator reads `lab/inbox/*/in/` at the start of each work round
  and presents new messages; consumed messages move to `lab/inbox/done/`.
- Messages are English, zero a/o/u-with-diacritics, and contain no secrets,
  prompts, or model reasoning - only artifact pointers plus a short
  description.
- See `lab/DESIGN-session-injection.md` for the design; this is its v1.

Handoffs live in `lab/` (workspace-local, never tracked) and are the durable
start point for each session; the inbox supplements them with live
deliveries between running sessions.
