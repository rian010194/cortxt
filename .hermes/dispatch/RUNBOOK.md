# Dispatch Runbook — next real Vertical 01 run

Consolidated 2026-08-05. Replaces the earlier "Buzz Blockers → Issues → Fix"
three-stream plan, which chased two blockers that are now resolved or by-design.

## Convergence decisions (2026-08-05)

1. **Blocker 2 (Builder terminal-output) — RESOLVED / not reproducible.**
   A Hermes ACP subagent probe on 2026-08-02 returned real output for `pwd`,
   `echo`, `ls` (exit 0). Pi Builder Docker bootstrap returned `0.82.1`.
   The 2026-08-02 failure was specific to the Buzz-delegation transport path,
   not the Builder runtime. Re-verify (fail closed) on the next Buzz-woken
   dispatch; do not treat as a general runtime fault.
   Reflected in `docs/agents/current-operating-model.md` and `web/src/data/systemData.ts`.

2. **Blocker 1 (Buzz-native delegation discovery-only) — BY DESIGN.**
   Buzz is the dialog + approval surface, NOT the dispatcher. GitHub is the
   source of truth. See `docs/agents/current-operating-model.md` and
   `docs/architecture/dispatch-contract.md`. Do not build a pollable Buzz
   adapter; it contradicts the current operating model ("as simple as necessary").

3. **Real gap to make Buzz useful:** a functioning **Hermes↔Buzz return channel**
   so status/approvals flow back into Buzz. This is the work item that makes
   Buzz feel alive.

## Goal of this run

Deliver the smallest real `vertical-01-ai-act` package that satisfies issue #9's
locked v0.1 boundary and acceptance criteria, through the **verified** path:

```
GitHub issue #9 (Ready, approved scope+AC, assigned)
  -> Hermes Coordinator/Builder via Kanban gateway or manual dispatch (run_id)
  -> verticals/vertical-01-ai-act/ package (vertical.yaml, workflows, schemas,
     instructions, synthetic fixtures, eval suite)
  -> evidence posted to issue #9
  -> independent Codex review (read-only)
  -> operator approval (= issue moves to Done)
```

## Preconditions (must all hold before work)

- [ ] Issue #9 body carries approved scope + acceptance criteria (posted as
      comment 2026-08-02; confirm the body/comment is operator-approved).
- [ ] Issue #9 is added to Project **AI Workspace Delivery (#4)** and its
      `Workflow Status` = **Ready**.
- [ ] Explicit **cost ceiling** set (max_cost_usd) before dispatch — last run
      left it as `unknown-not-allowed`.
- [ ] Issue assigned to `builder` (or coordinator for package design).
- [ ] Dispatch fields captured exactly per `docs/architecture/dispatch-contract.md`:
      `issue_id`, `workflow`, `worker_role`, `scope`, `acceptance_criteria`,
      `max_runtime_seconds`, `max_cost_usd`, `max_parallel_workers=1`,
      `delegation_depth=0`, `artifact_policy`, `approval_ref`.
- [ ] A dispatcher-generated `run_id` (never model-invented).

## Execution steps

1. Move issue #9 to `Workflow Status = Ready` in Project #4.
2. Dispatch package building.
   - Preferred: Hermes Kanban gateway (scratch workspace) to one `builder`
     worker; correlate the run to issue #9 with the run_id.
   - Fallback: manual dispatch of a `builder` profile (kimi) bounded to
     `verticals/vertical-01-ai-act/` only.
   - Enforce: schema validation, fail-closed on violations, no real customer
     docs, no harness runtime code inside the vertical.
3. Run the deterministic eval suite + model-assisted rubric on synthetic
   fixtures (positive, negative, boundary, uncertainty).
4. Post a run result + evidence comment to issue #9 (envelope: run_id, status,
   runtime, worker_role, timestamps, model, usage, cost, artifacts, evidence).
5. Request independent Codex read-only review with minimal context (issue,
   criteria, diff/artifact, test evidence).
6. Operator approves → move issue #9 to Done.

## Buzz return channel (follow-on work — DONE 2026-08-05)

To actually "use Buzz more", post run status and approval prompts into Buzz via
`harness/scripts/buzz-return.py` (Hermes→Buzz). Live-verified into the hosted
Vertical 01 channel (event `f44d6e1c…`). Key is read from env or the setx
user-scope fallback and is never printed. This makes Buzz a live operator
surface without re-enabling unattended Buzz workflow dispatch.

## Cost model

- Planning/convergence: free coordinator (nemotron).
- Package build: builder (kimi). Set explicit max_cost_usd before dispatch.
- Review: Codex once, read-only.
