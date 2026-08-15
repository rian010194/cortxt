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

Paths inside these files may reference their old pre-move locations (e.g.
`harness/scripts/...` instead of `archive/harness/scripts/...`) — they are
frozen snapshots and are not rewritten after the fact.
