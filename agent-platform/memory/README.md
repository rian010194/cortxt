# Memory

Status: scaffold

Defines policies and ports for turn context, session state, run memory, project
memory, skill memory, and evidence memory.

Memory policy must define scope, retention, data class, provenance, and who may
write. Compaction may summarize conversational context but cannot overwrite
authoritative goals, constraints, budgets, evidence references, or run state.

