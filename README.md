# Cortxt

### An operating layer for durable AI work

Define the work once. Keep its mandate, state, evidence, and human decisions
when execution changes.

[Website](https://cortxt.io) ·
[Documentation](https://cortxt.io/docs/) ·
[Quick start](https://cortxt.io/docs/quick-start/) ·
[Architecture](https://cortxt.io/docs/architecture/) ·
[Roadmap](https://cortxt.io/docs/roadmap/)

> **Durable authority. Replaceable execution.**

AI work is often trapped inside one conversation, agent workspace, provider,
or runtime session. Cortxt keeps the durable identity and authority of the work
outside any individual execution attempt.

```text
Workstream
├── desired outcome and acceptance criteria
├── mandate, limits, budget, and provider policy
├── Run 1 · executor interrupted
├── accepted evidence remains attributable
├── Run 2 · compatible executor continues
└── consequential decision returns to a human
```

Runs, models, providers, engines, sessions, and workspaces can change. The
Workstream does not have to be reconstructed around each replacement.

## What Cortxt provides

- **Workstreams** for durable outcomes, state, and continuity.
- **Mandates** for explicit authority, limits, expiry, and reserved decisions.
- **Dispatch and Run identity** across compatible execution engines.
- **Provider and data policy** with deterministic, fail-closed decisions.
- **Evidence and independent review** before final human acceptance.
- **CLI and MCP interfaces** over Cortxt-owned contracts.
- **Declarative views and actions** with explicit authorization boundaries.

The emerging Cortxt OS brings these contracts together through Work Console,
Decisions, Evidence, Policies, Execution Inspector, Connections, and Studio.
Its purpose is to make durable work understandable—not to turn agent activity
into another terminal cockpit.

## Current state

Cortxt is open-source work in active development, built solo and in the open.
Today the repository includes working CLI, MCP, mandate, provider-policy,
dispatch, evidence, engine-adapter, state, and declarative widget foundations.
GitHub Issues and `workflow:*` labels currently carry durable workflow authority.

The broader Cortxt OS product experience and hosted capabilities are under
active development. Compatibility is adapter-specific; Cortxt does not claim
that every model, provider, or agent engine is supported.

See the [roadmap](https://cortxt.io/docs/roadmap/) and
[Architecture Decision Records](docs/adr/README.md) for the verified boundary
between the current baseline and product direction.

## Architecture at a glance

```text
Cortxt-owned work authority
  Workstream · mandate · policy · evidence · decisions
                         │
             dispatch and Run identity
                         │
       compatible engines, providers, and runtimes
                         │
             attributable results and evidence
```

Cortxt sits above execution. Agent workspaces help an agent perform work;
secure runtimes isolate execution; Cortxt preserves the work's authority and
continuity across those replaceable resources.

## Explore the repository

| Path | Purpose |
| --- | --- |
| [`agent-platform/`](agent-platform/) | CLI, MCP, mandates, dispatch, state, policies, adapters, evidence, and UI contracts |
| [`docs/`](docs/) | Architecture, operating model, security boundaries, and ADRs |
| [`verticals/`](verticals/README.md) | Domain packages and evaluated workflow profiles |
| [`contracts/`](contracts/README.md) | Shared interface contracts and schemas |
| [`scripts/`](scripts/) | Repository automation, verification, and operational tooling |

Start with:

1. [Quick start](https://cortxt.io/docs/quick-start/)
2. [Current operating model](docs/agents/current-operating-model.md)
3. [Dispatch contract](docs/architecture/dispatch-contract.md)
4. [Accepted ADRs](docs/adr/README.md)

## Open source and collaboration

Cortxt is licensed under [Apache-2.0](LICENSE). Contributions, technical
criticism, and concrete workflow discussions are welcome.

- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Open an issue](https://github.com/rian010194/cortxt/issues)
- [Discuss a design-partner workflow](https://cortxt.io)

Built by [Rikard Andersson](https://github.com/rian010194) in Malmö, Sweden.
