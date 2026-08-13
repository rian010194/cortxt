# Handoff: readiness gates from local run to production

Snapshot: 2026-08-02  
Ticket: <https://github.com/rian010194/ai-workspace-control-plane/issues/8>  
Map: <https://github.com/rian010194/ai-workspace-control-plane/issues/7>

Read `shared-context.md` first.

## Decision question

Which verifiable gates distinguish:

1. a local Vertical 01 run;
2. an automated pilot;
3. unattended operation; and
4. approved use of real cases?

## Existing non-negotiable constraints

- Every dispatch starts from an approved GitHub issue in `Ready`.
- A valid claim establishes one active attempt, an externally generated
  `run_id`, the selected runtime/profile, and a timeout/lease.
- Status must be queryable and include start time, latest update/heartbeat,
  elapsed time, terminal state, and structured result or blocker.
- Cost must be bounded or explicitly treated as unknown-not-allowed; unknown
  provider cost must never silently become zero.
- Retries receive new run/attempt identity and preserve earlier evidence.
- Workers cannot approve, merge, deploy, publish, or close their own work.
- Real customer inputs stay outside Git history in explicitly approved,
  isolated run workspaces.

## Known open areas

- The general dispatcher does not yet exist.
- Pi Builder has not been promoted from experiment to production harness.
- Retry, recovery, cancellation, backup, monitoring, and data-readiness gates
  have not yet been decided.
- Exact production SLO, operating budget, and operator on-call expectations are
  intentionally still fog on the Wayfinder map.

## Instructions for ChatGPT

Act as a decision interviewer, not an implementer.

- Ask exactly one question at a time and wait for Rikard's answer.
- For every question, give your recommended answer and explain the trade-off.
- Separate verified facts above from assumptions and Rikard's decisions.
- Do not invent repository state, runtime capabilities, costs, or legal rules.
- If a new technical fact is required, label it `Needs Codex verification` and
  continue only if the remaining decision can still be made safely.
- Work breadth-first across gate purpose, entry evidence, exit evidence,
  failure handling, human approval, and rollback.
- Do not design implementation details beyond what is needed to make a gate
  testable.

When shared understanding is reached, produce:

1. a named sequence of readiness levels;
2. mandatory entry and exit evidence for each level;
3. explicit prohibited actions at each level;
4. rollback or demotion triggers;
5. unresolved facts requiring Codex verification; and
6. a concise proposed GitHub resolution comment.

Start with the single highest-leverage decision and include your recommendation.

