# Cortxt Agent Platform — Target Architecture

Status: proposed target architecture  
Authority: architectural proposal; does not override the current operating model  
Date: 2026-08-12 (original)  
Last updated: 2026-08-21  
Owner: Rikard  
Review trigger: before implementation scope is approved and whenever a major platform boundary changes

> **Reconciliation notice (2026-08-21).** This document is a long-term target
> and is partially implemented. Read it together with the current state:
> - `docs/agents/current-operating-model.md` — what is verified today.
> - Accepted ADRs in `docs/adr/` — the normative record of decisions. Several
>   sections of this target document have since been decided or partially
>   built by ADRs: reasoning kernel accepted and tracked (ADR-017), workflow
>   labels as state carrier (ADR-018), permanent multi-engine routing
>   (ADR-019), admin surface + widget complement (ADR-021), capability
>   manifest + selection criteria (ADR-022), bottom-up and top-down
>   integration (ADR-023), MCP server as external surface (ADR-024),
>   geometric-reasoning decisive metrics (ADR-025), engine adapter registry
>   (ADR-026) and service-broker `EngineContext` (ADR-027), orchestrator
>   multi-engine resume (ADR-028), unattended daemon credential isolation
>   (ADR-029), plan-vs-actual divergence tracking (ADR-030), and the
>   Apache-2.0 license (ADR-031).
> - Where a section here contradicts an Accepted ADR, the ADR is authoritative.

> Cortxt is to evolve from a control plane that primarily orchestrates external
> agent engines into its own, vendor-neutral agent platform. The platform is to
> own the agent's state, reasoning, recursion, memory, verification, and
> lifecycle. Models, inference capacity, and external execution engines are to
> remain replaceable resources.

## The document's role

This document describes the long-term target state and a step-by-step path to
it. It is not a description of what is production-verified today.

In case of conflict, the documentation order below governs (ADR-016 planned a
`docs/authority-map` for this, but that item in ADR-016's Validation list is
still undone — `docs/README.md` does not exist in the repo). Most importantly:

- `docs/agents/current-operating-model.md` describes today's verified path;
- `docs/architecture/dispatch-contract.md` remains normative for dispatch,
  run identity, and the result envelope;
- `docs/architecture/runtime-and-evaluation-harness.md` remains normative
  for isolation and evaluation;
- this document describes where the architecture is to evolve.

## 1. Summary

Cortxt should not throw away today's control plane. The system is to be
complemented with the agentic core that has so far been provided mainly by
Hermes, Pi, and other external agent harnesses.

The target product consists of:

1. a control plane for mandate, policy, budget, workflow, and approvals;
2. its own supervisor for goals, session lifecycle, and coordination;
3. its own agent runtime for coding, research, and other agent profiles;
4. a reasoning kernel with several selectable strategies;
5. its own RLM engine for recursive problem solving over external context;
6. a geometric reasoning layer with an explicit problem and relation model;
7. an inference gateway that can use both self-hosted and external models;
8. an isolated execution runtime for tools and code;
9. an independent evaluation and evidence layer;
10. versioned vertical packages for domain-specific capabilities.

Hermes's coordinating role is used during the migration as an adapter, fallback,
and benchmark and is incrementally replaced by the Cortxt Supervisor (§24.1).
Hermes, Pi, and Codex as coding engines, by contrast, are permanent parallel
routing choices per ADR-019 (2026-08-16) — they are not replaced, regardless of
how the Cortxt Agent Platform evolves (see §22.3/§24.2).

## 2. Product vision

The Cortxt Agent Platform is to be an agentic operating system for long-running,
traceable, and verifiable knowledge and coding work.

The platform's differentiating thesis:

> Reasoning can be treated as transformations of an explicit, dynamic
> problem space. Recursive inference explores the problem space, while
> verification and evidence determine which paths hold.

Coding Agent is the first complete application of the platform, not the final
product boundary. The same core should later be able to carry research,
architecture work, document analysis, and vertical business flows.

## 3. Design goals

### 3.1 Functional goals

- Solve bounded coding tasks without Hermes or Pi.
- Run research and analysis tasks over material that exceeds a model's
  context window.
- Create, pause, resume, and cancel long-running agent sessions.
- Split work recursively with hard caps on depth, branches, time, and cost.
- Represent hypotheses, evidence, contradictions, and open questions explicitly.
- Choose the model and inference provider without changing the reasoning core.
- Verify results with deterministic tests, independent models, and
  human decision points.
- Learn from verified trajectories without the production behavior changing
  silently or irreversibly.

### 3.2 Quality goals

- Vendor neutrality.
- Resumability after a process or client interruption.
- Explainable routing and measurable reasoning strategy.
- Fail-closed on policy, budget, or isolation errors.
- No external side effects without explicit mandate.
- No storage of private chain-of-thought.
- Reproducible evals and version-pinned results.
- Least necessary privilege for every agent and tool.

### 3.3 Non-goals for the first product generation

- Training a general foundation model of its own.
- Writing its own CUDA-based inference engine.
- Competing as a global GPU marketplace.
- Unlimited self-modification or recursion.
- Replacing GitHub as today's canonical task record before a separate decision.
- Automating away the operator's mandate over irreversible decisions.

## 4. Stable conceptual model

| Concept | Responsibility |
| --- | --- |
| Control Plane | Owns scope, policy, workflow state, budget framework, evidence, and operator gates. |
| Agent Platform | The entire Cortxt agentic execution system under the control plane. |
| Supervisor | Owns goals, session lifecycle, delegation, dependencies, recovery, and coordination. |
| Agent Runtime | Runs an agent session and manages the agent loop, context, tools, and session state. |
| Agent Profile | Versioned configuration of role, operators, tools, permissions, memory, model policy, and verification. |
| Reasoning Kernel | Selects the reasoning strategy and the next allowed transformation of the Problem State. |
| Problem State | Explicit and persistent state for goals, claims, hypotheses, evidence, contradictions, and open questions. |
| Reasoning Graph | Typed graph representing the objects and relations in the Problem State. |
| Reasoning Strategy | Algorithm for how the problem space is explored, e.g. direct, recursive, or geometric. |
| Reasoning Operator | A bounded transformation, e.g. decompose, challenge, or integrate. |
| RLM Engine | Performs recursive decomposition, context inspection, child calls, and synthesis within budget. |
| Inference Gateway | Vendor-neutral boundary for model invocations, routing, usage, and errors. |
| Inference Provider | Service or local endpoint that runs a model, e.g. InferX or a self-hosted vLLM. |
| Agent Harness | Program layer around a model for tools, context, memory, and the agent loop. The Cortxt Agent Runtime is the target state's primary harness. |
| Execution Runtime | Isolated environment where shell, code, and other tools actually run. |
| Evaluation Harness | Independent layer for assertions, graders, comparisons, and verdicts. |
| Vertical Package | Domain package with workflows, schemas, instructions, fixtures, and evals. |
| Trajectory | Structured sequence of states, decisions, actions, and verified outcomes; not private chain-of-thought. |

## 5. Target architecture

```text
Operator / API / UI
        |
        v
CONTROL PLANE
scope | policy | workflow | budget | approval | evidence
        |
        v
CORTXT SUPERVISOR
goals | sessions | dependencies | child runs | recovery
        |
        v
AGENT RUNTIME
agent loop | context | profiles | tool admission | persistence
        |
        +--------------------+
        |                    |
        v                    v
REASONING KERNEL       EXECUTION RUNTIME
Problem State          sandbox | files | shell
RLM                    browser | external tools
Geometric reasoning
verification planning
        |
        v
INFERENCE GATEWAY
local models | external providers | routing | usage
        |
        v
EVALUATION HARNESS
tests | graders | adversarial verification | evidence
        |
        v
CONTROL PLANE / OPERATOR GATE
```

### 5.1 Responsibility rule

The model may propose the next reasoning step or action. The component that owns
authoritative state must validate and enforce the proposal.

Example:

- the model proposes that a subproblem be created;
- the Reasoning Kernel checks the reasoning budget;
- the Supervisor creates the child run and identity;
- the Execution Runtime enforces permissions and isolation;
- the Control Plane stops external or irreversible effects at the gate.

## 6. Control Plane

The existing control plane is retained. It remains responsible for:

- canonical scope and acceptance criteria;
- data class, risk class, and policy version;
- route eligibility;
- total budget and hard ceilings;
- claim, `run_id`, and workflow state;
- operator approvals;
- evidence and result references;
- decisions about merge, deploy, publishing, and Done.

The control plane must not contain domain reasoning or model-dependent
agent logic.

## 7. Cortxt Supervisor

The Supervisor incrementally replaces Hermes's coordinating responsibility.

### 7.1 Responsibilities

- receive an approved dispatch request;
- create or resume a root session;
- assign the agent profile and reasoning policy;
- create and monitor child sessions;
- allocate sub-budgets without raising the total budget;
- manage dependencies and join points;
- provide queryable status and heartbeat;
- perform cancellation and timeout;
- recover sessions after a process interruption;
- integrate terminal partial results;
- produce a complete result envelope.

### 7.2 Supervisor state machine

```text
ADMITTED
  -> FRAMING
  -> READY_TO_REASON
  -> REASONING
  -> EXECUTING
  -> INTEGRATING
  -> VERIFYING
  -> WAITING_FOR_OPERATOR | SUCCEEDED | BLOCKED | FAILED
```

> Target-state vocabulary. The implemented v0.1 vocabulary is the
> session_state event set (session.created, child.spawned, join.waiting,
> join.satisfied, budget.reclaimed, budget.transferred, session.terminal)
> with terminal statuses succeeded/blocked/failed/cancelled/lost
> (supervisor/coordinator.py).

Every transition must be explicit, version-controlled, and readable back.

### 7.3 Child runs

Every child run must have:

- its own `child_run_id`;
- the same `issue_id` and root `run_id`;
- a bounded purpose and output schema;
- an allocated sub-budget;
- a relevant context reference, not an uncontrolled copy of the entire parent context;
- a maximum recursion depth;
- queryable status;
- a terminal structured result.

### 7.4 Status mapping to the result envelope

The Supervisor's state machine (§7.2) and the dispatch contract's normative
result-envelope statuses do not use the same vocabulary. The mapping:

| Supervisor state / event | Result envelope status |
| --- | --- |
| ADMITTED … VERIFYING, WAITING_FOR_OPERATOR | no envelope yet (non-terminal) |
| SUCCEEDED | `succeeded` |
| BLOCKED | `blocked` |
| FAILED | `failed` |
| timeout | `timed_out` |
| budget cap reached | `budget_exceeded` |
| cancellation | `cancelled` |
| child status `lost` (Phase 4, §27 #4) | root `blocked` with a reason pointing to the lost child |

The envelope in §19.2 is not extended by this table — the dispatch contract is
normative and only changes through separate approval (§19.1). Verified against
the Phase 4 code (final-fix report, Fix 1): Supervisor v0.1 in practice maps
timeout to `blocked` with a reason, not to a dedicated `timed_out` field.
The target state should promote `timed_out` and `budget_exceeded` to
first-class terminal causes in a later phase.

## 8. Agent Runtime

The Agent Runtime is Cortxt's own agent harness. It complements Pi, Hermes, and
Codex as a permanent parallel routing choice for coding tasks (ADR-019,
see §22.3/§24.2) — it does not replace them.

### 8.1 Common runtime

Coding, research, and coordinator must not be separate technical products.
They are profiles on the same runtime:

```yaml
agent_profile:
  id: coding-v1
  reasoning_strategies: [direct, recursive, geometric]
  operator_set: coding-core-v1
  tools: [repository_search, file_read, patch, shell, tests, diff]
  permissions: bounded-workspace-write
  memory_policy: session-plus-run-state
  model_policy: coding-balanced-v1
  verification_policy: tests-plus-independent-review-v1
```

### 8.2 Runtime responsibilities

- agent loop and turn handling;
- prompt and context assembly;
- tool discovery and tool admission;
- model invocation through the Inference Gateway;
- context compaction;
- session persistence and resume;
- structured output;
- trajectory events;
- connection to the Supervisor and the Execution Runtime.

The runtime must not itself approve external side effects or expand the budget.

## 9. Problem State and Reasoning Graph

Problem State is the central domain model for reasoning.

```text
ProblemState
|- goal
|- constraints
|- concepts
|- claims
|- hypotheses
|- evidence
|- assumptions
|- contradictions
|- perspectives
|- unresolved_questions
|- candidate_conclusions
|- reasoning_frontier
|- verification_state
`- termination_state
```

### 9.1 Node types

- `goal`
- `constraint`
- `concept`
- `claim`
- `hypothesis`
- `evidence`
- `assumption`
- `contradiction`
- `question`
- `candidate_conclusion`

### 9.2 Relation types

- `supports`
- `contradicts`
- `depends_on`
- `causes`
- `derived_from`
- `generalizes`
- `specializes`
- `analogous_to`
- `alternative_to`
- `observed_from`

### 9.3 Minimal metadata

Every node and relation must be able to carry:

- stable identity;
- provenance;
- confidence and confidence source;
- evidence references;
- data class;
- the creating `reasoning_step_id`;
- timestamps;
- status and version.

### 9.4 Storage principle

The first implementation should use simple, portable formats and an ordinary
database. A separate graph database is introduced only when measurable query or
scaling needs justify it.

## 10. Reasoning Kernel

The Reasoning Kernel chooses how the Problem State is to evolve. It must not be
reduced to a single large system prompt.

### 10.1 Strategies

- `direct`: a bounded model invocation and verification;
- `retrieval_augmented`: retrieve targeted external context before answering;
- `tool_augmented`: use tools to observe or change the environment;
- `recursive`: decompose, solve, and integrate recursively;
- `geometric`: explore the structure of the problem space and alternative paths;
- `recursive_geometric`: geometric selection of recursive branches;
- `adversarial`: attempt to falsify the current candidate;
- `ensemble`: compare independent solution candidates;
- `human_escalation`: stop and request a material decision.

### 10.2 Operators

| Operator | Purpose |
| --- | --- |
| `inspect` | Read a bounded part of external context. |
| `decompose` | Create dependent or independent subproblems. |
| `abstract` | Search for a common principle behind several observations. |
| `concretize` | Test an abstract idea against a concrete case. |
| `change_perspective` | Model the problem from another position. |
| `find_contradiction` | Search for incompatible claims, constraints, or evidence. |
| `find_missing_dimension` | Search for a variable or relation the problem model lacks. |
| `generate_counterexample` | Attempt to falsify a hypothesis. |
| `compare_paths` | Compare alternative reasoning trajectories. |
| `integrate` | Combine compatible partial results. |
| `escape_attractor` | Force an independent alternative model or path. |
| `verify` | Run appropriate verifiers against a candidate. |

### 10.3 Reasoning step

Private chain-of-thought must not be stored. The system stores structured and
auditable state transitions:

```yaml
reasoning_step_id: step-00042
operator: generate_counterexample
input_refs: [hypothesis-12, evidence-7]
output_refs: [counterexample-3, contradiction-4]
decision_summary: "The hypothesis was tested against a boundary case."
confidence_before: 0.78
confidence_after: 0.51
model_invocation_ref: invocation-81
evidence_refs: [artifact://run/source-14]
```

## 11. RLM Engine

The RLM Engine treats large contexts as external, addressable data and uses
recursive child calls as a programmable operation.

### 11.1 Basic loop

```text
inspect problem and context references
  -> determine whether decomposition adds value
  -> create bounded subproblems
  -> allocate branch budgets
  -> execute child runs
  -> integrate structured results
  -> challenge integrated candidate
  -> stop, recurse or escalate
```

### 11.2 Hard limits

Every RLM run must have:

- `max_depth`;
- `max_branches_per_node`;
- `max_total_children`;
- `max_model_invocations`;
- `max_context_reads`;
- `max_runtime_seconds`;
- `max_cost`;
- `max_output_size`;
- an explicit stop policy.

### 11.3 Stop conditions

- acceptance criteria are verified;
- expected information gain is below the threshold;
- remaining budget is not enough for a meaningful branch;
- all relevant branches are integrated;
- a material contradiction requires an operator or new evidence;
- a policy or security limit stops further work.

### 11.4 Data class at context ingest

Ingested context inherits and retains its data class. Aggregated context in the
Problem State is classed as the highest incoming data class. The class must be
visible to the Tool Gateway and provider eligibility (ADR-016 data class → gate)
at every subsequent call that consumes the aggregated context. This builds on
the data-class metadata already required per node and relation (§9.3).

## 12. Geometric Reasoning Engine

Geometric reasoning v1 is an operational system model, not a claim that
information geometry is an established physical force of nature.

### 12.1 Working definition

Reasoning is treated as paths and transformations in a structured
problem space:

- nodes and relations provide explicit graph structure;
- embeddings provide soft semantic closeness;
- goals and constraints influence which directions are relevant;
- contradictions create measurable tension;
- verification changes confidence and the frontier;
- stable conclusion families can be identified as attractors.

### 12.2 Geometric metrics in the first version

- semantic closeness between nodes;
- graph distance to the goal or acceptance criterion;
- evidence coverage;
- contradiction degree;
- centrality;
- novelty;
- stability under perspective change;
- number of revisits to the same conclusion family;
- path diversity;
- information gain per reasoning step.

### 12.3 Attractor detection

A candidate attractor is present when the system returns to the same
conclusion family despite one or more of the following interventions:

- new evidence;
- perspective change;
- explicit counterexample;
- independent child run;
- changed branch order.

This must trigger `escape_attractor`, stronger adversarial verification, or
human escalation. It must not automatically be interpreted as the conclusion
being true.

### 12.4 First scoring function

A candidate path can be ranked with a version-controlled function based on:

```text
expected_information_gain
+ goal_relevance
+ evidence_coverage
+ path_novelty
- contradiction_risk
- expected_cost
- policy_risk
```

Weights and thresholds are policy data and must be evaluated against fixtures,
not hidden in prompt text.

## 13. Coding Agent

Coding Agent is the first complete vertical on the Agent Runtime.

### 13.1 Capabilities

- read repository instructions;
- map files, symbols, and dependencies;
- formulate and test bug hypotheses;
- read and modify only the approved workspace;
- create minimal patches;
- run tests and static checks;
- inspect the diff against scope;
- detect scope expansion;
- produce artifacts, evidence, and the result envelope;
- resume work after a controlled interruption.

### 13.2 Coding-specific operators

- `locate_ownership`
- `build_dependency_map`
- `form_bug_hypothesis`
- `find_minimal_reproduction`
- `compare_contract_to_implementation`
- `propose_minimal_patch`
- `analyze_blast_radius`
- `generate_regression_test`
- `inspect_diff_against_scope`
- `falsify_fix`

### 13.3 Security boundary

Coding Agent does not run shell or code directly in the agent process. It
requests actions through the Tool Gateway and Execution Runtime, which validate
workspace, command, network, timeout, and artifact policy.

## 14. Inference Gateway and self-hosted inference

### 14.1 Inference Gateway

The Inference Gateway must be built early and owned by Cortxt. It normalizes:

- provider and exact model version;
- messages and structured outputs;
- tool calling;
- reasoning and output settings where they exist;
- input, output, cache, and reasoning tokens;
- latency, timeout, and cancellations;
- cost and cost confidence;
- retries and error classification;
- data class and provider eligibility.

The agent core must depend only on an internal `InferencePort`.

### 14.2 Inference providers

The following can exist in parallel behind the gateway:

- external endpoints (the current bootstrap provider, referenced in the
  adapters; "InferX" appears only as an L0/L2 synthetic fixture:
  `inference/fixtures/l0-inferx-like.json`, `l2-inferx-like.json`);
- OpenAI-compatible gateways;
- local models;
- Cortxt-hosted vLLM or SGLang;
- future self-hosted serving infrastructure.

### 14.3 The path to a self-hosted inference product

1. Own gateway API and own contracts.
2. An external provider adapter for bootstrap.
3. A local or rented GPU with an open model.
4. Model pool, liveness, and load balancing.
5. Caching, batching, and capacity measurement.
6. Multi-tenant isolation and usage accounting.
7. A customer-exposed inference API only after a separate product and security decision.

A self-hosted inference product does not mean Cortxt must write its own
low-level inference engine in the first generation.

## 15. Tool Gateway and Execution Runtime

The Tool Gateway is the only path from the Agent Runtime to external actions.

The Execution Runtime owns:

- sandbox and container policy;
- writable scope;
- network and egress policy;
- process limits;
- command timeout;
- credential injection without persistence;
- artifact capture;
- log and usage limits;
- deterministic cleanup.

Reasoning and execution must be separate failure domains. A persistent
reasoning session must not in itself imply persistent OS-level permissions.

## 16. Memory and context

### 16.1 Memory types

| Memory | Scope | Example |
| --- | --- | --- |
| Turn context | One model turn | Selected input to the next invocation. |
| Session state | One agent session | Problem State, frontier, and active handles. |
| Run memory | Root run and children | Structured partial results and artifacts. |
| Project memory | One repository/project | Approved conventions and verified facts. |
| Skill memory | One capability version | Procedures, schemas, and tool instructions. |
| Evidence memory | Cross-cutting evaluation | Aggregated, content-minimized outcomes. |

### 16.2 Context assembly

The Agent Runtime should assemble the next model input from:

- the current goal;
- the relevant part of the Problem State;
- the selected reasoning operation;
- explicitly retrieved external context;
- tool schemas;
- policy and output constraints.

The entire session history must not be replayed uncontrolled at every
invocation.

### 16.3 Compaction

Compaction may summarize conversation and raw observation, but must not replace
authoritative structures such as:

- goals and constraints;
- open contradictions;
- budget;
- run identity;
- evidence references;
- operator and verification status.

## 17. Verification and Evaluation

Verification is a separate phase and sometimes a separate actor.

Priority order:

1. deterministic assertions and tests;
2. schema and policy validation;
3. property and metamorphic tests;
4. adversarial reasoning and counterexamples;
5. independent model review;
6. domain expert or operator when the decision requires it.

### 17.1 Reasoning metrics

- task success;
- first-attempt success;
- evidence coverage;
- unresolved material contradictions;
- confidence calibration;
- branch efficiency;
- information gain per invocation;
- attractor escapes that improved the result;
- total cost per verified unit of work;
- operator interventions;
- stability across repetitions.

### 17.2 Comparison requirements

A new reasoning strategy must be compared against at least one simpler baseline
with the same:

- task fixture;
- model and provider when the strategy is isolated;
- tool and network limits;
- total budget;
- verification method;
- start state.

## 18. Learning and self-improvement

Cortxt must be able to improve from verified trajectories, but production must
not self-modify without control.

### 18.1 Two loops

```text
Inner loop:
the agent solves the current task within a locked policy and budget

Outer loop:
the eval system analyzes several verified trajectories and creates a candidate
for a changed strategy, operator, prompt, memory rule, or agent profile
```

### 18.2 Promotion

Every improvement candidate must:

1. have provenance and rationale;
2. be a separate version-pinned artifact;
3. be tested against regression and safety fixtures;
4. be compared against the active baseline;
5. be rollback-able;
6. be approved per policy before production.

### 18.3 When training becomes relevant

Model training is considered when there is enough quality-labeled data for a
bounded goal, e.g.:

- selection of the next reasoning operator;
- branch ranking;
- context selection;
- stop prediction;
- verification needs;
- attractor escape policy.

Training a general foundation model is not a dependency for RLM or
geometric reasoning v1.

## 19. Contracts

### 19.1 Extended dispatch request

The target contract will need to be extended over time with:

```yaml
agent_profile: coding-v1
reasoning_policy:
  allowed_strategies: [direct, recursive, geometric]
  max_reasoning_steps: 30
  max_depth: 2
  max_branches_per_node: 3
  max_total_children: 6
  max_model_invocations: 20
  max_context_reads: 30
verification_policy: tests-plus-adversarial-v1
memory_policy: run-scoped-v1
```

The existing dispatch contract is not changed until schema, compatibility, and
migration have been approved separately.

### 19.2 Extended result envelope

See §7.4 for the mapping between the Supervisor's internal state machine and
the status fields below.

```yaml
agent:
  platform_version: cortxt-agent-v0.1
  profile: coding-v1
reasoning:
  strategy_versions: [recursive-v1, geometric-v1]
  steps_used: 18
  branches_explored: 4
  max_depth_reached: 2
  model_invocations: 11
  contradictions_found: 3
  contradictions_resolved: 2
  termination_reason: acceptance_criteria_verified
  trajectory_ref: artifact://run/trajectory.json
children:
  - child_run_id: child-01
    status: succeeded
verification:
  policy: tests-plus-adversarial-v1
  verdict: passed
```

ADR-034 (MCP run lifecycle tools, Accepted 2026-08-22) additively extends
the real dispatch-contract envelope with `session_id` (resume), a
`review` object (submit_for_review), `cost_status`
(measured|estimated|unknown) on lifecycle responses, and structured
artifacts `{ref, sha256}`. See cortxt_mcp/run_lifecycle.py.

## 20. Security model

### 20.1 Ground rules

- The model is never a policy authority.
- The Reasoning Kernel must not grant itself a larger budget.
- The Supervisor must not create children outside the root run's mandate.
- The Tool Gateway rejects actions outside tool and data-class policy.
- The Execution Runtime uses the least privilege possible.
- A reviewer must not merge, deploy, or set Done.
- The learning loop must not silently change active production configuration.
- Private chain-of-thought, credentials, and customer content must not end up
  in the evidence registry.
- Tier-1+ MCP tool calls require a signed, nonce-bound mandate envelope,
  verified inside `call_tool` before any handler side effect (ADR-032);
  key identity and rotation are versioned per ADR-033 (Proposed).

### 20.2 Prompt injection and foreign instructions

External text, repositories, web pages, and documents are treated as data. They
cannot change system policy or grant new permissions. Tool actions require
separate admission even when the instruction comes from material the agent is
analyzing.

### 20.3 Recursion risk

Recursion must never be the only stop mechanism. Hard ceilings are enforced
outside the model and apply to the root and all children combined as the
target.

The mechanism differs from the goal: in v0.1 (detached processes, Phase 4)
this is enforced through a disjoint pre-allocated sub-budget per child plus
post-hoc rollover at integration, not through real-time aggregation of
cost/tokens across process boundaries. Real-time aggregation across detached
children is an open decision (§27).

## 21. Observability and evidence

Every run must be followable without exposing private reasoning:

- root and child run identity;
- state transitions;
- reasoning strategy and operator names;
- model invocation metadata;
- tool actions and result status;
- budget consumption;
- artifacts and hashes;
- verification outcomes;
- termination reason;
- operator gates and decisions.

Telemetry and product/customer payloads must be kept separate.

## 22. Migration from today's system

The migration follows a strangler pattern. Old and new execution paths can
coexist behind the control plane's route selection.

```text
Approved Dispatch
       |
       v
Routing policy
  |                              |
  v                              v
Hermes/Pi                     Cortxt Agent Platform
coding: permanent routing       target path
choice (ADR-019); coordination: migrated (§24.1)
  |                              |
  +-------> common result envelope and evaluation
```

### 22.1 What is retained

- the control plane and operator gates;
- the core principles of the dispatch and result contracts;
- run identity and claims;
- runtime/sandbox requirements;
- the evaluation harness;
- vertical packages;
- provider-neutral routing;
- the evidence registry;
- existing fixtures and verified working practices.

### 22.2 What is replaced incrementally

| Current responsibility | Target component |
| --- | --- |
| Hermes coordination | Cortxt Supervisor |
| Hermes agent profiles | Cortxt Agent Profiles |
| External agent memory | Cortxt Problem State and Memory |
| Ad hoc agent decomposition | Cortxt RLM Engine |
| Model-bound tool loop | Cortxt Agent Runtime + Tool Gateway |

Pi coding harness previously stood in this table as a replacement row. Per
ADR-019 (2026-08-16) that is no longer correct: the Cortxt Agent Runtime +
Coding Profile is an **addition** to Pi, not a replacement for it. See 22.3.

Engine selection and resume use the EngineAdapter/EngineContext
service-broker layer (ADR-026/027) with opaque per-engine `session_id`
resume (ADR-028) — see runtime/engine_registry.py,
runtime/engine_adapter.py, runtime/adapters/.

### 22.3 Transitional and permanent roles

Hermes's coordinating role, Prime Agent, and other non-coding engines can
during the migration be used as:

- benchmark;
- fallback;
- compatibility adapter;
- inspiration or reference implementation;
- an experimental path for testing hypotheses before Cortxt's own
  implementation is ready.

**Coding engines (Pi, Hermes, Codex, future GitHub Copilot) are exempt
from this migration pattern per ADR-019.** They are permanent routing choices in
Cortxt's coding policy, alongside Cortxt's own Coding Agent (Phase 3 and
onward). The replacement criteria in 24.2 no longer apply to coding engines.

No external agent runtime must be a hidden dependency in Cortxt Agent Core.

## 23. Implementation ladder

The ladder's numbering is a planning order, not a proven build sequence.
Per ADR-017, parts of the Reasoning Kernel, RLM Engine, and Geometric
Engine landed in `main` already before Phase 2 (PR #113, 2026-08-14), with
stubbed inference. This does not change the target state, but the reader
should not assume that the phase number reflects the actual landing order
in the code.

From Phase 4 onward: an exit criterion counts as met only after at least
three (N=3) consecutive green runs of its proof, not a one-off proof.
This does not apply retroactively to Phases 0–3.

### Phase 0 — Architecture and baseline

Deliverables:

- approved conceptual model;
- decision on package boundary;
- a fixture corpus sized against a strategy×metric coverage matrix (not
  a fixed interval) — a minimum per cell or a justified empty-cell policy
  must be evident from the matrix, not assumed from "10–20 fixtures";
- baseline from today's Hermes/Pi path;
- initial schemas for Agent State and Model Invocation.

Exit:

- we can measure quality, cost, lead time, and review findings for today's path;
- the target architecture does not contradict normative security contracts;
- the strategy×metric coverage matrix exists and is approved.

### Phase 1 — Inference Gateway

Deliverables:

- internal `InferencePort`;
- one external provider adapter;
- structured output;
- usage, cost, and timeout;
- fixtures and contract tests.

Exit:

- the same agent code can switch between at least two approved endpoints
  without change in the reasoning core.

### Phase 2 — Agent Runtime v0.1

Deliverables:

- session state;
- simple agent loop;
- tool admission;
- persistence and resume;
- result envelope;
- read-only research profile.

Exit:

- a research fixture can be solved without Hermes.

### Phase 3 — Coding Agent v0.1

Deliverables:

- repository discovery;
- read/search/patch/test/diff tools;
- Tool Gateway v0.1: schema, permission, and effect-class validation (§32.1)
  before each tool call — replacing direct function calls (e.g. today's
  `apply_patch` calls directly from the Supervisor);
- execution sandbox;
- bounded write policy;
- coding-specific operators.

Exit:

- a simple coding fixture can be solved and verified without Pi or Hermes;
- workspace, network, and budget ceilings are machine-proven;
- no tool execution happens without passing through the Tool Gateway.

This exit criterion proves capability, not an intention to make Pi or
Hermes unnecessary — they remain permanent routing choices per ADR-019.

### Phase 4 — Supervisor v0.1

Deliverables:

- root and child sessions;
- queryable status;
- heartbeat;
- cancellation;
- budget allocation;
- recovery;
- dependency joins.

Exit:

- two bounded child runs can be executed and integrated without Hermes.

v0.1 exposes status and control via CLI/query (operator CLI, queryable
status); integration with the operator's actual surfaces (Hermes desktop
primarily, Buzz as complement, per the current operating model) is not proven
and is required before the Supervisor can take primary-path responsibility
(cf. §24.1). Live heartbeat to a human operator in UI/dashboard form is
explicitly out of scope for v0.1.

### Phase 5 — RLM v1

Deliverables:

- external context store;
- bounded recursion;
- context slicing;
- branch budget;
- structured synthesis;
- RLM-specific evals;
- scaling the Supervisor from Phase 4's v0.1 ceiling (2 children, depth 1,
  see §25) to the depth and branch budget RLM requires (cf. §19.1:
  max_depth 2, max_total_children 6) — this is a deliverable of its own,
  not an assumption.

Exit:

- RLM beats a simpler baseline with a predefined margin on at least one
  long-context class within approved total cost.
- If this is not achieved after three (N=3) independent evaluation rounds:
  the RLM track is downgraded, by operator decision, to an
  experimental/diagnostic strategy behind the Reasoning Kernel with a simpler
  baseline as default. See "De-escalation paths" below for the consequence
  for Phase 6.

### Phase 6 — Geometric Reasoning v1

Deliverables:

- Problem State schema;
- reasoning graph;
- embeddings (source: see §27, open and blocking decision);
- first operator set;
- contradiction and attractor detection;
- path scoring;
- trajectory viewer or report.

Exit:

- which metric(s) in §12.2 are decisive (as opposed to
  diagnostic) is decided before this exit criterion is evaluated (§27 #8);
- the strategy yields measurable improvement on the decisive metric(s)
  without regression across safety fixtures;
- if Phase 5 has been de-escalated as above: `recursive_geometric` (§10.1) may
  continue to be developed but does not become the default strategy until the
  RLM track is re-established.

### Phase 7 — Self-hosted inference

Deliverables:

- an open model on a local or rented GPU;
- liveness and capacity metrics;
- the same InferencePort;
- comparable cost/quality telemetry.

Exit:

- at least one approved task class can run without an external inference
  provider.

### Phase 8 — Controlled learning loop

Deliverables:

- versioned improvement candidates;
- offline eval and promotion flow;
- rollback;
- possibly a trained operator or routing policy;
- Skill Platform promotion (§31) and Tool Platform evolution (§32.3) as a
  working built pipeline, not just a described model.

Exit:

- no automatic change can reach production without verified promotion.

### De-escalation paths

This section describes the consequence if a phase experiment does not deliver
measurable benefit — the §28 invariant ("a failed experiment must not destroy
the verified operational path") protects production but says nothing about
the fate of the phase itself or its dependent phases. Concretely:

- Phase 5 (RLM): see the de-escalation condition in the Phase 5 exit above.
- Phase 6 (Geometric Reasoning): if Phase 6's own exit criterion is not met
  after three independent evaluation rounds, the operator decides whether
  Geometric Reasoning is downgraded to a diagnostic layer (metrics are
  logged but do not affect routing) or paused entirely. §2's thesis about
  reasoning as transformations in a problem space remains as product vision
  regardless of the outcome — the platform's other layers (Supervisor, Agent
  Runtime, RLM, Inference Gateway) do not depend on Geometric Reasoning
  succeeding.
- De-escalation is always an operator decision, never automation — in line
  with §28 ("The model proposes; authoritative code validates and enforces").

## 24. Replacement criteria

### 24.1 Hermes can leave the primary path when

- the Supervisor can create, pause, resume, and cancel sessions;
- child runs have queryable status and heartbeat;
- budget, timeout, and recursion ceilings are enforced;
- dependencies and integration work after a process restart;
- operator gates and the result envelope are complete;
- eval results are at least equivalent for migrated task classes.

### 24.2 Historical: Pi as primary path (overridden by ADR-019)

This section previously described conditions for Pi to leave the primary path.
Per ADR-019 (2026-08-16), Pi is not replaced — Pi, Hermes, and Codex are
permanent routing choices alongside Cortxt's own Coding Agent. The conditions
below remain as a quality floor for when Cortxt's Coding Agent is a **valid
routing choice** for a task class, not as replacement criteria:

- Coding Agent can navigate the repository;
- the Execution Runtime enforces write and network limits;
- patch, test, and diff work reproducibly;
- scope expansion is detected and stops the run;
- artifacts, cost, and cleanup are verified;
- safety and coding fixtures pass.

### 24.3 External inference can leave a task class when

- a self-hosted model meets its quality floor;
- latency, availability, and total cost are accepted;
- data protection and operations are verified;
- a fallback still exists for controlled recovery.

## 25. First product increment

The Cortxt Agent Platform v0.1 should be deliberately small:

```text
A user sends a bounded research or coding task
  -> Control Plane creates an approved dispatch
  -> Cortxt Agent Runtime creates Problem State
  -> Reasoning Kernel chooses direct or bounded recursive
  -> The agent uses approved read/search/tool operations
  -> The coding profile can make a bounded patch and run tests
  -> Verification creates a verdict
  -> Result envelope and trajectory reference are returned
  -> the operator decides on any merge/Done
```

Limitations:

- at most recursion depth 1 (the v0.1 target; the recursive RLM Supervisor
  on main already exceeds this — depth-2 decomposition with full subtree
  projection, `supervisor/coordinator.py`);
- at most two child runs;
- one writable workspace;
- no deployments or publications;
- one external inference adapter;
- one simple persistent database;
- no automatic harness refinement.

## 26. Initial package boundary

**Historical:** This package boundary was replaced by §33 (ADR-016, Decision 1).
It is retained here for traceability, not as current authority.

The new code is introduced without an immediate move of existing files:

```text
agent-platform/
|- supervisor/
|- runtime/
|- reasoning/
|  |- kernel/
|  |- recursive/
|  `- geometric/
|- state/
|- memory/
|- tools/
|- inference/
`- profiles/

adapters/
|- inference/
|- hermes/
|- pi/
`- prime-agent/

harness/
|- execution/
`- evaluation/
```

The package boundary must be exercised in a vertical implementation before any
larger repository restructuring is decided.

## 27. Open decisions

The following must be decided before the respective implementation:

1. Implementation language for the Supervisor and Agent Runtime.
2. Process model for root and child sessions.
3. First persistence format for Problem State and trajectories.
4. ~~First execution sandbox on Windows and Linux.~~ Partially resolved
   (verified 2026-08-16, Kimi K2.7 code review of Phase 3 against `main`: the
   entire `docker_required` suite ran live on Windows with Docker Desktop, all
   8 boundary tests green, including the network-isolation/DNS/timeout probes).
   The Docker-based execution sandbox
   (`agent-platform/runtime/execution/subprocess_sandbox.py`)
   works on Windows and Linux and is CI-gated (the `docker_required` job in
   `.github/workflows/ci.yml`) — the OS-isolation question A4 concerned is
   resolved. Remains open: no subprocess-only fallback exists when Docker is
   missing (Phase 4's `sandbox_degraded` field presupposes such a path, but it
   must be built from scratch), and portable memory/CPU limits for the sandbox
   are still out of scope (assumption A10 in the Phase 3 spec).
5. Which external provider adapter is used as bootstrap.
6. Which fixtures constitute the quality floor for (a) the Hermes coordinating
   role that the Supervisor replaces (§24.1), and (b) the Cortxt Coding Agent
   as a valid routing choice alongside Pi/Hermes/Codex (§24.2) — Pi, Hermes,
   and Codex as coding engines are not replaced per ADR-019, so "replacement"
   applies only to (a).
7. Whether the Agent Platform initially lives in this repo or in a separate
   package with its own release cycle.
8. ~~Which geometric metrics are decisive versus diagnostic only.~~
   Resolved (ADR-025, `docs/adr/025-geometric-reasoning-decisive-vs-diagnostic-
   metrics.md`, 2026-08-19): five metrics are decisive (already consumed by
   `score_path`/`guidance`/`AttractorDetector` — graph distance to goal,
   evidence coverage, contradiction degree, novelty, stability); five remain
   diagnostic (semantic_closeness, centrality, revisit_ratio,
   path_diversity, information_gain) until a new, explicitly versioned
   policy promotes them. `information_gain` got a real call site
   (`reasoning.geometric.apply_confidence_update`) for the first time.
9. When self-hosted inference has business value compared with rented capacity.
10. Embeddings provider for Phase 6 (§12.2 semantic closeness). The
    InferencePort (§14.1) does not currently normalize embeddings, and no
    phase delivers it. Blocking for Phase 6 start.
11. Real-time aggregation of cost/token budget across detached
    process boundaries (§20.3) — v0.1 enforces only via disjoint
    pre-allocation plus post-hoc rollover, not continuous aggregation.

## 28. Architectural invariants

The following must remain true throughout the migration:

- The Control Plane owns the mandate; the agent does not own its own scope.
- Problem State and trajectories are owned by Cortxt and are portable.
- Agent Core does not import Hermes, Pi, Prime Agent, or a specific provider.
- External implementations depend on Cortxt's ports and contracts, not the reverse.
- Reasoning and execution are separate trust boundaries.
- The model proposes; authoritative code validates and enforces.
- Every run and child run has stable identity and budget.
- Verification is separate from production, and self-approval is forbidden.
- Learning happens through versioned candidates and verified promotion.
- A failed experiment must not destroy the verified operational path.

## 29. Decisions this target architecture proposes

The following are proposals until approved through the repository's decision
process:

1. Cortxt builds its own Agent Platform within the existing control plane.
2. The Cortxt Agent Runtime becomes the primary agent harness over time.
3. The Cortxt Supervisor will over time replace Hermes's coordinating primary role.
4. The Cortxt Coding Agent is a permanent addition to the routing policy for
   coding tasks, not a replacement for Pi/Hermes/Codex (overridden and
   replaced by ADR-019, 2026-08-16 — see §22.3/§24.2).
5. RLM and geometric reasoning are owned by Cortxt Agent Core.
6. Inference is a replaceable port; self-hosted inference is introduced incrementally.
7. Hermes's coordinating role and Prime Agent are used during the migration as
   adapters, fallback, or benchmark and are replaced incrementally, never as
   hidden core dependencies. Hermes, Pi, and Codex as coding engines are
   permanent routing choices (ADR-019) and are not migrated away.
8. Today's control, security, and eval foundation is retained.

## 30. Next planning steps

Done (verified against the ADR registry and the code):

- ADR for the Agent Platform as a new bounded context (ADR-016);
- ADR for the `InferencePort` and provider-independent model boundary (ADR-016);
- a first vertical slice (ADR-017);
- the real contract schemas that exist: `contracts/dispatch-request
  .schema.json` and `contracts/result-envelope.schema.json`;
- `agent-platform/state/` ledger CLI (run/session state events, not an
  Agent State schema);
- `reasoning/geometric/trajectory.py` (trajectory report module, not a
  committed Trajectory Event schema).

Still open before the next major decision packet:

- a fixture matrix with today's Hermes/Pi baseline (fixtures are scattered
  across the repo, but no consolidated matrix exists);
- threat model for Agent Runtime, Tool Gateway, and Execution Runtime (no
  such document exists in `docs/` yet);
- decision on which existing backlog items should be replaced or
  reformulated;
- ADR-016's open Validation item about `docs/authority-map` (see the note
  under "The document's role" above) is still undone.

Implementation should start with a vertical, runnable flow and not with an
extensive repository move or complete platform infrastructure — it already
has (ADR-017).

## 31. Skill Platform

Skills are first-class objects in the Cortxt Agent Platform. They describe
reusable work patterns and can compose reasoning operators and tools.

Skills and profiles carry the engine-agnostic capability manifest shape
per ADR-022 (`routing/engine_manifest.py`); the machine-readable
`schemas/skill-manifest.schema.json` and `schemas/profile-manifest
.schema.json` exist, and evolution/promotion is implemented in
`learning/skill_candidate.py` and `portability/skills/registry.py`.

A skill must be able to contain:

- manifest, identity, and semantic version;
- instructions and examples;
- input and output schemas;
- dependencies and compatible agent profiles;
- fixtures, tests, and evals;
- declared tools and the highest allowed effect class;
- provenance, changelog, and rollback information;
- optional reviewed executable helpers.

### 31.1 Skill Evolution

The agent may identify recurring successes, failures, and review corrections in
verified trajectories. The system can then create a new skill candidate or
propose a bounded improvement.

```text
trajectory observation
  -> pattern detection
  -> skill candidate
  -> sandboxed evaluation
  -> regression and safety comparison
  -> promotion decision
  -> canary/active or rejected
```

Self-improvement does not mean the agent may grant the candidate new
permissions itself or silently activate it. Promotion is governed by the
change's risk, fixtures, verified improvement, and rollback ability.

| Change | Minimum promotion rule |
| --- | --- |
| Instruction, example, or source | Eval against fixtures and regressions. |
| Workflow or reasoning operator | Comparison against baseline and safety fixtures. |
| Executable helper | Sandbox, dependency review, and contract tests. If the helper is agent-authored, a named human operator gate is additionally required before promotion. |
| New tool or new permission | Separate tool review and operator decision. |
| Credential, external effect, or policy | Always an operator gate. |

## 32. Tool Platform

Tools are typed, version-controlled operations that observe or affect an
environment. The Agent Runtime invokes them through the Tool Gateway; it does
not call shell, MCP, providers, or external APIs directly.

### 32.1 Tool contract

A tool must at least declare:

```yaml
id: repository.run_tests
version: 1.0.0
input_schema: contract-ref
output_schema: contract-ref
effect_class: bounded_execution
filesystem: current-run-workspace
network: none
credentials: []
timeout_seconds: 600
idempotency: repeatable
artifact_policy: result-and-summary
```

The Tool Gateway validates schema, profile permission, data class, declared
effects, budget, and runtime eligibility before execution.

### 32.2 Effect classes

| Class | Example | Control |
| --- | --- | --- |
| `observe` | Read a file or search code. | Read scope and data class. |
| `local_mutation` | Apply a patch in the run workspace. | Writable scope and diff control. |
| `bounded_execution` | Run a test or build in the sandbox. | Allowlist, resources, and timeout. |
| `external_mutation` | Create an issue or send a message. | Explicit mandate and read-back. |
| `irreversible` | Merge, deploy, or delete. | Operator gate. |
| `credential` | Create or rotate a secret. | Separate trust-boundary decision. |

### 32.3 Tool Evolution

The agent may create tool candidates with implementation, manifest, schemas,
documentation, tests, and fixtures. The candidate runs in isolation and must
demonstrate:

- correct schema and error behavior;
- permission denial for disallowed actions;
- timeout and cancellation;
- credential and network isolation;
- output sanitization;
- deterministic cleanup;
- dependency and security review;
- regression against the active tool version.

A candidate can never grant itself new rights. New network targets,
credentials, external mutations, and irreversible effects require explicit
promotion per Control Plane policy.

### 32.4 Transport neutrality

MCP, CLI, REST, and browser automation are tool adapters. Skills and reasoning
should depend on Cortxt's stable tool IDs and schemas, not on the transport's
or vendor's own names.

MCP is the chosen external integration surface (ADR-024); Tier-1+ MCP
tools carry the signed mandate envelope (ADR-032) and lifecycle tools
(ADR-034). The transport-neutral principle here applies to internal tool
IDs and schemas, not to the external surface decision.

## 33. Initial repository structure

The current directory set (verified against the tree) is:

```text
agent-platform/
|- adapters/           (inference/ only)
|- cli/
|- context_store/
|- cortxt_mcp/         (MCP server; ADR-024/032/034)
|- daemon/
|- harness/
|  |- eval/            (built: runner, baseline_direct, citation_match,
|  |                    cost, selfhosted_task_class)
|  `- fixtures/        (coding_longcontext/, research_longcontext/)
|- inference/
|- learning/
|- portability/
|- reasoning/          (kernel/, recursive/, geometric/)
|- routing/
|- runtime/            (adapters/, coding/, execution/, tools/ + ports)
|- security/
|- state/              (ledger CLI)
|- supervisor/
`- tests/
```

Repo-root `skills/` and `tools/` do not exist; today's tool inventory lives
in `agent-platform/runtime/tools/`. No existing execution path is moved into
a scaffold until a vertical slice and its contracts are verified.

Runtime candidates are promoted into the tracked runtime path
(`agent-platform/runtime/`) once their interfaces, isolation, cleanup,
observability, and failure behavior are stable — see
`runtime-and-evaluation-harness.md`; the evaluation side is tracked at
`agent-platform/harness/eval/`.
