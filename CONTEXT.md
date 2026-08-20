# Cortxt Control Plane

Cortxt coordinates durable work across replaceable agent runtimes while keeping operator mandate, state, and evidence under Cortxt ownership.

## Language

**Workstream**:
The operator-visible unit of work, normally correlated to one GitHub issue and one branch/worktree. A workstream may exist without a Git workspace for research-only work.
_Avoid_: Branch session, task session

**Run**:
One attempt to advance a workstream, identified by a durable `run_id`. A retry creates a new run and never overwrites earlier evidence.
_Avoid_: Retry session, execution

**Agent Session**:
The event-sourced lifecycle of one agent or runtime participant within a run.
_Avoid_: Workstream, branch session

**Lane**:
The timeline row assigned to one agent role or control-plane participant within a workstream view.
_Avoid_: Agent, session

**Segment**:
A contiguous state interval on a lane, such as running, waiting, review, blocked, or done.
_Avoid_: Event

**Workspace**:
The optional Git branch and worktree attached to a workstream. It is execution metadata, not the workstream's identity.
_Avoid_: Workstream
