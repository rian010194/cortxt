# Pending Builder Dispatch: Vertical 01 Implementation

**Status:** awaiting operator approval  
**Issue:** <https://github.com/rian010194/ai-workspace-control-plane/issues/9>  
**Run ID:** `20260803_003321_651528bd`  
**Prepared:** 2026-08-03

---

## What is being requested

Implement the files declared in the synthesized specification
(`vertical-01-package-spec-v0.1.md`, swarm `t_7dcc6947`) into the repository at
`verticals/vertical-01-ai-act/`.

## Files to create

```text
verticals/vertical-01-ai-act/
|-- vertical.yaml
|-- README.md
|-- workflows/
|   |-- classify.yaml
|   `-- assess-obligations.yaml
|-- schemas/
|   |-- vertical-manifest.schema.json
|   |-- ai-act-assessment-input.schema.json
|   |-- ai-act-assessment-output.schema.json
|   |-- eval-fixture.schema.json
|   `-- artifact-ref.schema.json
|-- instructions/
|   |-- system-prompt-classify.md
|   `-- system-prompt-obligations.md
|-- evals/
|   `-- synthetic/
|       |-- manifest.yaml
|       |-- README.md
|       |-- positive-cases/
|       |-- negative-cases/
|       |-- boundary-cases/
|       `-- uncertainty-cases/
|-- templates/
|   `-- decision-brief-sv.md
```

## Source specifications

| Source | Location |
|---|---|
| Boundary and non-goals | `kanban/boards/cortxt-cp/attachments/t_2db8d55c/vertical-01-boundary-and-non-goals.md` |
| Schema requirements | `kanban/boards/cortxt-cp/attachments/t_178c23d5/json-schema-requirements.md` |
| Draft schema files | `kanban/boards/cortxt-cp/attachments/t_178c23d5/*.schema.json` |
| Validated examples | `kanban/boards/cortxt-cp/attachments/t_178c23d5/*-valid.json`, `*-invalid.json` |
| Fixture README | `kanban/boards/cortxt-cp/attachments/t_c44923a0/README.md` |
| Fixture manifest | `kanban/boards/cortxt-cp/attachments/t_c44923a0/manifest.yaml` |
| Final synthesis | `kanban/boards/cortxt-cp/workspaces/t_3b9cae74/vertical-01-package-spec-v0.1.md` |

## Dispatch contract compliance

| Field | Value |
|---|---|
| `issue_id` | `rian010194/ai-workspace-control-plane#9` |
| `workflow` | `vertical-01-ai-act` `v0.1.0` implementation |
| `worker_role` | `builder` |
| `scope` | Implement declared files per synthesized spec. Do not modify scope, non-goals, or acceptance criteria. |
| `acceptance_criteria` | 8 criteria from synthesized spec (see issue #9 comment) |
| `max_runtime_seconds` | `1800` |
| `max_cost_usd` | `unknown-not-allowed` |
| `max_parallel_workers` | `1` |
| `delegation_depth` | `0` |
| `artifact_policy` | Write to `verticals/vertical-01-ai-act/` only. No secrets, no customer docs. |
| `approval_ref` | This document + operator approval below. |

## Runtime options

### Option A: Hermes builder profile (recommended for speed)

```bash
export RUN_ID="20260803_003321_651528bd"
hermes -p builder
```

Inside the session, provide:
- The synthesized spec path.
- The source schema files.
- The acceptance criteria.
- Explicit instruction: "Do not modify scope or non-goals."

### Option B: Pi Builder (recommended for isolation)

See `experiments/runtime-pi-builder/`.

```bash
cd experiments/runtime-pi-builder
docker compose -f compose.write-test.yaml up
```

Requires:
- Docker Desktop running.
- Approved workspace mount.
- Egress restrictions verified.

### Option C: Manual operator implementation

Operator creates files directly using the synthesized spec and source
attachments as reference.

---

## Operator approval

Before dispatch, confirm:

- [ ] Scope is unchanged from synthesized spec.
- [ ] Non-goals (N1–N9) are respected.
- [ ] Runtime limit (`1800s`) is acceptable.
- [ ] Builder option (A/B/C) is selected.
- [ ] Post-build review is scheduled (Codex read-only when required).

**Approved by:** _________________  **Date:** _________________
