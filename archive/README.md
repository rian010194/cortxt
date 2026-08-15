# Archive

Historical material with no code coupling to the current baseline: earlier
control-plane runtime/provenance work, abandoned experiments, and internal
session handoffs. None of it defines current architecture or operating
authority — see the root [`README.md`](../README.md) and
[`docs/agents/current-operating-model.md`](../docs/agents/current-operating-model.md)
for that.

| Path | What it was |
| --- | --- |
| [`harness/`](harness/README.md) | Provenance and evaluation work from the earlier control-plane baseline. |
| [`experiments/`](experiments/) | Runtime candidates that were never promoted into the product baseline. |
| `pi/` | Config for a runtime candidate evaluated under `experiments/runtime-pi-builder/`. |
| [`docs/operations/`](docs/operations/) | Operational runbooks for the frozen control-plane backlog (Buzz, Kanban, swarm dispatch). |
| [`docs/wayfinder/handoffs/`](docs/wayfinder/handoffs/) | Point-in-time session snapshots used for context handoff outside the repo-aware session. Frozen when written; not maintained. |
| [`docs/agents/DAY1-OPERATIONS.md`](docs/agents/DAY1-OPERATIONS.md), [`docs/agents/domain.md`](docs/agents/domain.md) | Self-declared legacy operational snapshot and architecture inventory, superseded by `docs/agents/current-operating-model.md`. |
| [`docs/architecture/AGENT_ARCHITECTURE.md`](docs/architecture/AGENT_ARCHITECTURE.md) + `SKILL_PROFILE_MAPPING.md` + `audit-iteration-{1,2,3}.md` | The pre-Cortxt "AI Workspace Control Plane" agent-architecture plan and its structural/deep/artifact audits. |
| [`skills/`](skills/) | Generated interface/schema/stub scaffolding for the old Hermes receptionist skill system (~100 skills). No current code imports it. |

Paths inside these files may reference their old pre-move locations (e.g.
`harness/scripts/...` instead of `archive/harness/scripts/...`) — they are
frozen snapshots and are not rewritten after the fact.
