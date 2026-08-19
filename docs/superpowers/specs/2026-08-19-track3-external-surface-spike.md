# Track 3 spike: external integration surface form (SDK vs. MCP server vs. REST API)

**Date:** 2026-08-19
**Feeds:** ADR-024 (`docs/adr/024-external-integration-surface-form.md`)
**Grounds in:** ADR-023 (`docs/adr/023-bottom-up-and-top-down-integration-model.md`),
ADR-022 (`docs/adr/022-fas3-capability-manifest-and-engine-selection-criteria.md`),
`docs/superpowers/specs/2026-08-19-v02-swarm-orchestration-model-design.md` §"Engine
expansion: Pi and the own coding agent"

## What this spike answers

ADR-023 decided Cortxt should be **bottom-up-consumable externally** — other
frameworks and agents call into Cortxt's control plane as a service, without
adopting Cortxt's own orchestration — but explicitly left the concrete *form*
open ("SDK language? MCP server? REST?"). This spike compares the three
candidate forms against what Cortxt's control plane actually contains today,
and against who the concretely-named external consumers are, and recommends
one.

## Who the consumers actually are (not hypothetical)

This matters more than it looks, because "polyglot" gets read as "which
programming languages" by default, and that's the wrong axis here. The two
external consumers named concretely in this swarm effort's own planning
(`docs/superpowers/specs/2026-08-19-v02-swarm-orchestration-model-design.md`,
"Engine expansion: Pi and the own coding agent") are:

- **Pi** — an external coding agent, invoked as a CLI/agent runtime, not
  imported as a library.
- **The operator's own coding agent** (this Claude Code CLI session, or a
  headless equivalent) — same shape: invoked, not linked in-process.

ADR-023's Context section also names the broader class: LangGraph/LangChain,
CrewAI, Vercel AI SDK, and "other coding-agents." None of these are consumed
by writing application code that calls a Cortxt Python import — they are
themselves agent/orchestration runtimes that call *out* to tools. The real
question isn't "what language is the consumer written in," it's **"what
protocol does an agent runtime already speak to call an external tool
surface, without Cortxt writing per-consumer glue."**

## What the control plane surface actually is today

Two existing pieces are the concrete substance any external form would wrap:

- `agent-platform/routing/engine_manifest.py` — `route(task_tags, manifests) ->
  EngineChoice`, plus `DEFAULT_MANIFESTS` (ADR-022's capability-manifest
  pattern: each engine self-declares `task_shapes`, `cost_class`,
  `reliability_class`). This is naturally shaped as **"list what you can do"
  + "pick one for this task"** — the same shape as an MCP tool list, or a
  REST `/capabilities` + `/route` pair.
- `agent-platform/cli/unified_cli.py` — the admin surface: `provider-policy`,
  `state`, `profile`, `supervisor`, `coding`, `rlm`, `sessions`, `widget`,
  `dispatch`, `runtimes`, `credentials` (`store`/`inject`), `addons`
  (`submit`). Each subcommand already returns a structured `ResultEnvelope`
  (`issue_id`, `run_id`, `status`, `usage`, `cost`, `artifacts`, `evidence`,
  `error` — see `unified_cli.py:31-65`). This envelope is already
  API-response-shaped; none of the three forms below need to invent a new
  result schema.

Also relevant to implementation cost: `agent-platform/pyproject.toml`
currently declares exactly two dependencies (`pyyaml`, `jsonschema`). There is
no HTTP framework in the codebase — the one existing network-facing piece,
`agent-platform/widget/serve.py`, is a loopback-only static-file server built
on stdlib `http.server`, not a general-purpose API server. Any form that
requires standing up a real web framework is a first for this codebase, not
an extension of an existing pattern.

## Option 1: SDK (language-specific client library)

**Concretely:** publish a Python package (and, to be genuinely polyglot,
TypeScript and/or Go packages) that wrap `engine_manifest.route()` and
`unified_cli`'s admin commands as typed function calls, executed in-process
or by shelling out to `cortxt` under the hood.

**Cost:** highest of the three. Each additional language is a separate
packaging/versioning/CI surface (build, publish, changelog, breaking-change
discipline) — not a one-time cost but a permanent one that scales with
however many languages get support. Python-only would satisfy neither Pi nor
a TypeScript-based LangGraph/Vercel AI SDK consumer without a shim.

**Fit against ADR-023's "service, not framework" framing:** poor. An SDK
means the consumer links Cortxt into *their* process and trusts *their*
runtime to invoke it correctly and consistently apply Cortxt's own mandate/
audit guarantees (ADR-019, ADR-022) — the opposite of "control plane as a
service" that ADR-023's Decision section describes ("ge mig
mandat-verifierad routing/audit för den här uppgiften"). A library call
inside someone else's process cannot itself enforce a boundary the way an
out-of-process service call can; the guarantee becomes "trust the consumer
called it right," not "the control plane enforced it."

**Fit against the named consumers:** Pi and the operator's own coding agent
are not going to `pip install`/`npm install` a library and write integration
code — they're agent runtimes that call tools by protocol, not by import.

## Option 2: REST API

**Concretely:** an HTTP service exposing something like
`GET /capabilities` (wrapping `DEFAULT_MANIFESTS`), `POST /route` (wrapping
`route()`), and admin endpoints mirroring `unified_cli`'s subcommands
(`POST /credentials/inject`, `POST /addons/submit`, etc.), each returning the
existing `ResultEnvelope` shape as JSON.

**Cost:** medium-high. Genuinely language-agnostic (any HTTP client works),
which is a real point in its favor. But it requires: a web framework
dependency the codebase doesn't currently have; a long-running server process
with its own deployment/hosting story (loopback-only, like the widget
server? bound to a real interface, which raises the credential-broker-shaped
threat-model question ADR-023's own Risks section flags as unaddressed);
authentication/session design for a network-reachable control plane; and a
hand-written OpenAPI/schema layer so consumers know what's callable, since
HTTP alone carries no tool-discovery convention the way MCP's tool-list
does.

**Fit against ADR-023's framing:** good in principle — "service" reads most
literally as "network service" — but the operational cost (auth, hosting, a
new dependency class) is real and not yet justified by a concrete deployment
target. ADR-023's own Risks section already flags that the external surface's
security model isn't specified; REST is the option that makes that gap most
urgent to close before anything ships, because it's the only one of the
three that's reachable over a network by default.

**Fit against the named consumers:** works, but requires Pi/LangGraph/CrewAI/
Vercel AI SDK to each write bespoke HTTP-calling code against a bespoke
schema — there's no shared discovery convention, so every consumer
integration is a small one-off, even though the protocol (HTTP) itself is
universal.

## Option 3: MCP server

**Concretely:** an MCP server (stdio transport, no new network-facing
process) exposing `engine_manifest.py`'s manifest/routing as MCP tools (e.g.
a `list_engine_capabilities` tool wrapping `DEFAULT_MANIFESTS`, a
`route_task` tool wrapping `route()`) and `unified_cli.py`'s admin surface as
further tools (`credentials_inject`, `addons_submit`, `list_runtimes`, etc.),
each tool's result being the existing `ResultEnvelope.to_dict()` — no new
response schema to invent.

**Cost:** lowest of the three. stdio-transport MCP needs no new web
framework dependency (compatible with the codebase's current two-dependency
posture) and no hosting/networking story — it launches as a subprocess the
same way `cortxt dispatch` already launches engine invocations. Tool
discovery is native to the protocol (an MCP client lists available tools),
so no bespoke schema/discovery layer needs to be hand-built the way REST
would need one. `EngineManifest`'s existing fields (`task_shapes`,
`cost_class`, `reliability_class`, `notes`) map close to directly onto MCP
tool metadata/descriptions.

**Fit against ADR-023's framing:** strong. "Control plane as a service" for
an *agent* consumer specifically means "a tool surface another agent runtime
can call into," which is exactly what MCP is designed for — it is the
protocol built for agent-to-tool-surface calls, not general-purpose
human/application HTTP APIs (REST) or in-process language linking (SDK).

**Fit against the named consumers:** this is the decisive point. Both
concretely-named consumers — Pi and the operator's own coding agent — are
MCP-capable agent runtimes already, by construction of what they are (coding
agents in the current MCP-centric tooling ecosystem). LangGraph, CrewAI, and
the Vercel AI SDK — the three frameworks ADR-023's Context section names —
all ship first-class MCP client support as of the current tooling landscape.
Choosing MCP means these consumers need **zero new protocol-adapter code** on
their side to call Cortxt; choosing SDK or REST means Cortxt (or the
consumer) writes bespoke integration code per consumer, every time.

## Recommendation

**MCP server**, with reasoning, not just as the "modern-sounding" choice:

1. **Lowest implementation cost**, concretely grounded in this codebase: no
   new dependency class (stdio MCP doesn't need a web framework), no new
   hosting/networking surface, tool discovery comes free with the protocol,
   and the two existing pieces that would be wrapped
   (`engine_manifest.route()`, `unified_cli`'s admin commands) already return
   structured results (`ResultEnvelope`) that map onto MCP tool results
   without redesign.
2. **Best fit to ADR-023's actual framing** — "control plane as a service"
   for agent consumers, not general HTTP clients — and to ADR-022's
   capability-manifest pattern, which already has the "declare what you can
   do" shape an MCP tool list needs.
3. **Zero-integration-cost for the consumers that are actually named**, not
   hypothetical ones: Pi and the operator's own coding agent already speak
   MCP as agent runtimes; the major external orchestration frameworks named
   in ADR-023 (LangGraph, CrewAI, Vercel AI SDK) already ship MCP clients.
   SDK would mean writing and maintaining N language-specific packages
   forever; REST would mean every consumer hand-rolling HTTP-calling glue
   against a bespoke schema. MCP is the one form where "polyglot" is solved
   by the protocol itself, not by Cortxt writing per-language or
   per-consumer adapter code.

This is not a rejection of REST forever — if a genuinely non-agent consumer
(a plain web dashboard, a CI system) needs to call the control plane later,
a thin REST facade over the same underlying functions is a small addition,
not a redesign. But it is not the form to build first, because no concrete
non-agent consumer exists yet, and the concrete agent consumers are better
served by MCP with less code.

**What is explicitly not decided here:** which specific tools the MCP server
exposes first (a full `unified_cli` mirror vs. a narrower slice starting with
`route()`/capabilities only), authentication/mandate-verification for the MCP
tool calls themselves (ADR-023's own flagged open risk), and packaging/
distribution of the server. Those are implementation-plan questions for
after ADR-024, not spike-doc questions.
