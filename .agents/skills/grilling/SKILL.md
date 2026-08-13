---
name: grilling
description: Interview the operator one decision at a time to sharpen a plan or design. Use for Wayfinder grilling tickets and explicit stress-testing requests.
---

Interview the operator about the decision until shared understanding is reached.

- Ask exactly one question at a time and wait for the answer.
- Give a recommended answer and its trade-off with every question.
- Read discoverable facts from the current repository instead of asking the
  operator to remember them.
- Separate verified facts, assumptions, and operator decisions explicitly.
- If a required fact cannot be verified read-only, mark it `Needs Codex
  verification`; do not invent it.
- Do not delegate, edit files, update GitHub, or implement anything during the
  grilling conversation.
- Do not use `buzz workflows` or Hermes Kanban for a HITL grilling ticket.

When the operator confirms shared understanding, return:

1. the decision;
2. rationale;
3. rejected alternatives;
4. consequences;
5. unresolved facts; and
6. a concise proposed GitHub resolution comment for Codex to verify and post.

## AI Workspace Wayfinder context

For `Fortsätt Wayfinder`, `readiness-grindarna`, or equivalent requests, use
the context below directly. Do not call file, search, Buzz history, GitHub,
terminal, or delegation tools before asking the first question.

Destination: a production-capable AI Workspace where Rikard works from Buzz,
GitHub is the control plane, approved workflows dispatch through n8n/VPS to
observable and recoverable specialist runs, a broad reviewed skill library is
activated per workflow, and results pass evaluations, independent review, and
human approval before real cases are used.

Current ticket: `Definiera verifierbara readiness-grindar från lokal körning
till produktion` asks which verifiable gates distinguish:

1. a local Vertical 01 run;
2. an automated pilot;
3. unattended operation; and
4. approved use of real cases.

Verified constraints:

- Every dispatch starts from an operator-approved GitHub issue in `Ready`.
- Claim establishes one active attempt, external `run_id`, runtime/profile,
  and timeout or lease.
- Status must be queryable with start, heartbeat/update, elapsed time,
  terminal state, and structured result or blocker.
- Cost is bounded or explicitly `unknown-not-allowed`; unknown never means
  zero.
- Retry creates a new attempt identity and preserves earlier evidence.
- Workers cannot approve, merge, deploy, publish, or close their own work.
- Real inputs stay outside Git in approved isolated run workspaces.
- The general dispatcher, production Pi harness, retry/recovery policy,
  monitoring, backup, and real-data gate are not yet complete.

Begin with this recommended first question in Swedish:

> Min rekommendation är att vi först låser fyra namngivna readinessnivåer:
> `Local validated`, `Automated supervised`, `Unattended recoverable` och
> `Real-case approved`. Ska dessa vara de styrande nivåerna, eller vill du
> dela upp någon av dem ytterligare?

After the operator answers, continue one decision at a time using only the
conversation and this verified context. Request Codex verification only when a
new repository fact is essential.
