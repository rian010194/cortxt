# Buzz Boundaries: What Buzz Is and Is Not Today

**Status:** operational baseline  
**Last updated:** 2026-08-03  
**Authority:** `docs/agents/current-operating-model.md`

## One-sentence summary

Buzz is the **operator dialog and approval surface**. It is **not** the durable
task registry, the execution runtime, or an automated dispatch hub.

---

## Verified capabilities

| Capability | Evidence | Date |
|---|---|---|
| Operator chat and status display | Daily use | ongoing |
| Create GitHub issues from dialog | Verified | 2026-08-02 |
| Display workflow output with trigger text | Verified | 2026-08-02 |
| Render `{{trigger.message_id}}` and `{{trigger.text}}` | Verified | 2026-08-02 |
| Manual operator mention of an agent | Verified | 2026-08-02 |

---

## Known limitations (do not treat as temporary glitches)

| Limitation | Impact | Recovery |
|---|---|---|
| `delegate_task` returns handles but **cannot poll status** | Unattended delegation is impossible | Use Hermes Kanban or manual dispatch |
| Textual `@Builder` in workflow output **does not wake agent** | No automatic handoff | Operator must add structured mention manually |
| Builder terminal **echoes command, returns no output** | Agent cannot execute tools | Builder profile is stopped until repaired |
| Buzz cannot complete human edit-approval round trip | No closed-loop writing | Use Pi Builder or Hermes manual dispatch |
| ACP text not reliably published back into Buzz channel | No automatic status back-feed | ✅ **Resolved 2026-08-05:** `harness/scripts/buzz-return.py` posts verified to hosted Vertical 01 channel (event `f44d6e1c…`). Use it or the Kanban→GitHub cron. |

---

## What Buzz should be used for today

1. **Scope clarification** — discuss requirements with the operator.
2. **Approval gating** — explicit operator sign-off before dispatch.
3. **Status display** — read-only view of runtime state (via Kanban mirror or GitHub).
4. **Emergency stop** — operator can interrupt or block a run.

## What Buzz must not be used for today

1. **Durable task registry** — GitHub Issues/Projects owns this.
2. **Execution ledger** — Hermes Kanban owns this.
3. **Unattended dispatch** — no polling means no observability.
4. **Secrets or prompts** — never paste private keys, auth tags, or model reasoning.
5. **Independent backlog** — do not create Buzz-native tasks outside GitHub.

---

## The six version-controlled workflows

The repository contains six Buzz workflow definitions under
`harness/buzz-workflows/definitions/`. They are:

- Disabled by default (`enabled: false`).
- Stored as policy-gated assets, not live automation.
- Activated only as an explicit operator action.
- Enabled **one link at a time** after each adjacent handoff is verified.

Definitions exist for:

| Marker | Destination |
|---|---|
| `[BUILD_READY]` | Builder |
| `[BUILD_COMPLETE]` | Codex Reviewer |
| `[REVIEW_CHANGES_REQUIRED]` | Coordinator |
| `[RESEARCH_REQUEST]` | Researcher |
| `[RESEARCH_COMPLETE]` | Coordinator |
| `[REVIEW_APPROVED]` | Coordinator/operator gate |

---

## Recovery paths (preferred order)

1. **Hermes Kanban gateway** — proven for scratch workspaces; use for all
   unattended execution today.
2. **Manual Hermes dispatch** — operator opens correct profile, pastes issue
   context, generates `run_id` outside the model.
3. **Pi Builder** — containerized bounded writes when Hermes Builder is stopped.
4. **Buzz workflows** — enable only after Builder runtime is repaired and
   workflow mention-to-`p`-tag support is verified on the hosted relay.

---

## Common misreading guardrails

- Do **not** remove Hermes because Buzz lacks polling.
- Do **not** treat Pi as a replacement for Hermes Coordinator or Researcher.
- Do **not** invent a second backlog outside GitHub.
- Do **not** abandon Buzz as the operator surface merely because it is not the
  writing runtime.
- Do **not** describe a smoke test as a finished production workflow.
- Do **not** use Codex for routine planning, research, or implementation.

---

## Reconciliation

If this document conflicts with `docs/agents/current-operating-model.md` or the
live Wayfinder map, stop and reconcile before proceeding.
