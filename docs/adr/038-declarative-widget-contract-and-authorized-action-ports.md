# ADR-038: Declarative Widget Contract and Authorized Action Ports

**Status:** Accepted
**Date:** 2026-08-22
**Deciders:** Rikard Andersson (operator acceptance 2026-08-22)
**Technical Story:** issue #251 (widget platform design), issue #265 (materialization); source: `lab/widget-platform/track-a-widget-contract.md` + `synthesis.md` §5

## Context

ADR-015 and ADR-021 establish CLI-primary with a thin widget as an
administrative mirror of CLI state. The widget platform design (issue
#251) extends this into a composable surface: the operator wants to see
all open candidates and run several in parallel, and to be able to
prototype widgets quickly — including LLM-generated widgets via a clear
contract. Today `agent-platform/widget/` is a loopback static-file server
(`serve.py`, `snapshot.json`, `index.html`) with no action endpoint and no
generic contract: each new view would be bespoke code.

A widget must remain a thin, declarative surface over existing platform
authority. It must not acquire independent product or workflow logic, must
not widen the authority of the surface it mirrors, and must not become an
arbitrary-execution escape hatch. This ADR locks the widget contract
boundary and the action-port authority model, leaving concrete operations
and host evolution to reviewed builds (issue #259).

## Decision

### 1. A widget is a declarative pipeline

A widget is exactly:

```text
named data source -> typed view model -> primitive render tree -> named action request
```

Its spec has six top-level fields: `contract_version`, `widget`, `data`,
`render`, `actions`, and `capabilities`. Unknown top-level or nested
fields fail validation. There is no extension bag, embedded script,
template program, callback, URL fetch, shell string, or implicit
capability.

- `data.reads[]`: `id`, `source` (`store` | `cli` | `github`),
  `operation` (a registered read-registry ID, never a command line or
  URL), `input` (validated literal object), `select` (allow-listed
  projection), `refresh` (manual/on_load/bounded poll), `output_type`
  (registered type+version), `on_error` (empty/stale/static error state).
  Reads resolve only against platform-owned stores/snapshots, fixed
  registry-owned CLI argument arrays, or a configured repository with a
  fixed API operation and bounded result set.
- `render`: a pure tree of registered primitives (layout, text/status,
  collections, operational views, inputs) with typed JSON Pointer
  bindings and declared empty/error states. No widget-supplied HTML/CSS/
  JS/Markdown/SVG/event handlers. `when` is an optional reference to a
  typed boolean output — no expression language.
- `actions[]`: `id`, `port` (`cli` | `mcp` | `github-transition`),
  `operation` (registered action ID), `input`, `authorization` (explicit
  mode + required reference), `confirm` (summary + effect class +
  requirement), `result_type`, `idempotency_key` (required for retryable
  mutations). An action is a typed request to an existing authorized
  surface; the platform-owned adapter constructs and executes the real
  operation.

### 2. Three controlled action ports, each preserving its authorization surface

- `cli`: one allow-listed CLI command adapter, fixed executable + fixed
  argument schema; operator approval reference required for any mutation;
  the CLI's own guards are preserved. No raw command text from the widget.
- `mcp`: one registered MCP tool. Tier 0 follows its existing policy;
  Tier 1+ requires the exact signed, scoped, expiring, nonce-bound mandate
  envelope and fail-closed pre-handler verification locked by ADR-032. A
  widget may bind a mandate reference supplied by the authorized session;
  it cannot create, sign, widen, refresh, or edit a mandate.
- `github-transition`: one registered workflow-transition adapter behind
  operator authorization or an already accepted mechanical mandate for
  that exact transition; enforces the state/evidence rules of the dispatch
  contract; not a general label editor or GitHub API client.

Each action is authorization-checked again at action time against current
scope and state. Spec validation is necessary but never sufficient
authorization to execute.

### 3. Strict validation before any read, render, or action

The loader completes, in order: parse with strict resource limits +
canonicalize; validate exact contract version + full JSON Schema with
unknown fields forbidden; validate IDs/versions/reference integrity/
acyclic bindings; resolve all reads/primitives/transforms/actions/types
against installed registries; prove declarations are a subset of the
explicit `capabilities` manifest and the host/operator allow-list;
validate operation inputs, projections, output types, refresh minimums,
result limits, data classes; validate render bindings, primitive
properties, accessibility, static fallbacks; validate action port,
schema, effect class, confirmation, authorization mode + required
reference; reject forbidden fields/values (commands, executable paths,
arbitrary URLs, headers, env references, code, prompt text, credentials,
raw GitHub queries, unregistered extensions); produce a capability and
effect summary for operator review before installation/enablement.

### 4. Typed composition with no capability widening

A dashboard composition spec is a primitive layout tree referencing
widget IDs + exact versions. Each widget has an isolated ID namespace and
render subtree. Published outputs are typed; a consuming widget must
declare an input port with the same type or a registry-approved adapter.
Connections are declared by the composition spec; a missing, cyclic,
type-incompatible, or above-data-class connection fails before rendering.
Composition never rewrites a child widget's capabilities, data bindings,
or actions, and never aggregates weaker grants into a stronger grant.
Multi-step operations go through separately registered platform
workflows; a composition may bind one action's result status to another's
enabled state only through typed result status, never as an automatic
follow-up mutation.

### 5. LLM-generability within the inert contract

An LLM may emit a small inert YAML document (contract_version, widget id/
version/title, explicit capabilities, reads, render tree, actions). The
platform parses YAML into the same canonical JSON model used for schema
validation and hashing; YAML aliases, custom tags, duplicate keys,
non-string map keys, and implementation-specific coercions are rejected.
The loaded identity is the canonical document hash + widget ID + version.
If the LLM cannot name every requested capability and provide every safe
schema-required literal, generation stops with validation errors. The
platform never infers a data source, capability, action, authorization
reference, mandate, type conversion, workflow state, or completion from
labels, titles, primitives, bindings, or UI state.

### 6. Safety boundaries

Forbidden in widget specs, data, action requests, results, logs, and
composition documents: secrets/credentials/keys/mandate material;
customer/private documents, full prompts, model reasoning, unrestricted
logs, production run output content; unrestricted subprocess, shell
strings, executable selection, arbitrary arguments, env access,
filesystem traversal, host mounts, Docker socket access, eval, dynamic
code, arbitrary network access; general GitHub API access, arbitrary label
editing, merge/close authority, transitions outside a named adapter and
the operator gate; creating/signing/editing/replaying/widening an ADR-032
mandate or bypassing its checks; self-approval, approval of another
agent's work without operator authority, self-merge, self-close, marking
work `workflow:done`; automatic mutation triggered by load, poll, render,
selection, another widget's event, or an LLM suggestion. Denial, stale
state, authorization expiry, version mismatch, conflict, and indeterminate
results are first-class states; failures remain visible and fail closed.

## Consequences

### Positive

- Every widget is validated, versioned, capability-declared, and inert —
  including LLM-emitted specs — so new views can be prototyped quickly
  without bespoke code or new authority.
- Each action port preserves the existing authorization surface (CLI
  guards, ADR-032 mandate, dispatch-contract operator gate), so the
  widget cannot widen authority.
- The candidates view and future map views share one contract; the
  existing `agent-platform/widget/` stays as a compatibility surface.

### Negative

- A generic contract host (registry, loader, renderer, adapters) is new
  platform code that must be built and reviewed before the first widget
  (issue #259).
- Read-only-first means mutation ports are disabled until their adapters
  and gates are separately accepted.
- Strict validation adds latency and rejects ad-hoc widgets that rely on
  implicit behavior.

### Risks

- The generic contract could be over-generalized before real validated
  examples exist (the vertical-package-contract caution applies).
- A composition or action bug could present state as authority if
  action-time re-authorization is skipped — this ADR makes that re-check
  mandatory.
- The loopback host is not an execution boundary; an action endpoint must
  not be added to `serve.py` without a separately reviewed host boundary.

## Alternatives Considered

1. **Bespoke per-view widget code** (status quo) — rejected: does not give
   the operator quick prototyping or LLM-generability, and each view adds
   bespoke surface.
2. **Widgets as general scripts / URL-fetch / raw-command surfaces** —
   rejected: violates the no-arbitrary-execution boundary and would
   recreate the authority-widening this ADR prevents.
3. **Widgets with implicit capabilities and untyped composition** —
   rejected: capability inference and implicit connections are exactly the
   failure modes (label/title as authority, silent cross-widget mutation)
   the contract forbids.
4. **Mutation-first surface** — rejected: read-only-first keeps version
   0.1 safe; mutation ports ship only with their accepted adapters and
   gates (synthesis open question 1).

## Validation

- [ ] Implementation matches decision (build issue #259 after acceptance).
- [ ] Tests cover decision boundaries: unknown-field/duplicate-key/
      forbidden-value rejection before I/O; registry resolution; typed
      bindings; composition no-widening; action-port authorization
      re-check (build #259 AC).
- [ ] Documentation updated (this ADR; index; review log).

## Open Questions

- Which mutation ports, if any, ship in contract version 0.1 (synthesis
  Q1)? Recommended default: read-only data/render first; mark-ready and
  claim/run as disabled explanatory handoffs.
- Which initial operations and composition authors are allowed (synthesis
  Q2)?
- What refresh and result bounds become platform defaults (synthesis Q3)?
- When may an authorized mutation omit a second UI confirmation
  (synthesis Q7)?

## Expiry/Review Trigger

- Review by: 2026-11-22, or on first real use of a mutation port in a
  dispatched build, whichever comes first.
- Trigger: a widget needs an action the registered ports cannot express
  without widening authority; or the contract must accept a new source
  kind, primitive family, or composition rule.
