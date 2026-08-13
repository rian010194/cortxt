# Agent State

Status: scaffold

This package owns portable Cortxt data structures rather than model-specific
transcripts:

- Problem State;
- Reasoning Graph nodes and relations;
- reasoning-step records;
- trajectory events;
- verification and termination state.

Private chain-of-thought is not part of the state contract. Persisted records
must be structured, content-minimized where required, and linked to provenance.

