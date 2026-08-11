# Control-plane glossary

Status: active reference
Authority: repository governance
Last verified: 2026-08-11

**Control plane**: GitHub Issues and Project 4, which hold canonical scope,
workflow state, evidence, review, and approval. _Avoid_: Hermes board, backlog.

**Execution ledger**: Runtime-local records used to execute an approved work
unit and correlated by `issue_id` and `run_id`. _Avoid_: backlog, source of truth.

**Dispatch request**: An approved, immutable description of one work attempt
with scope, acceptance criteria, limits, artifact policy, and approval reference.

**Run**: One claimed execution attempt with a unique `run_id`. A retry is a new
run and does not overwrite earlier evidence.

**Result envelope**: The structured terminal record that correlates a run with
status, runtime, model, usage, cost, artifacts, evidence, and errors.

**Runtime adapter**: A provider-neutral boundary that makes an execution runtime
conform to the dispatch contract. _Avoid_: dispatcher when only adaptation is meant.

**Vertical package**: A versioned domain package containing workflows, schemas,
instructions, evaluations, and templates without control-plane responsibilities.

**Operator**: The human authority for irreversible effects, approval, merge,
publication, deployment, closure, and final completion.
