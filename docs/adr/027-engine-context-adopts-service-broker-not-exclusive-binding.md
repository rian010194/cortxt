# ADR-027: `EngineContext` adopts the service-broker pattern (Cordis §6.2), not exclusive binding

**Status:** Accepted
**Date:** 2026-08-19
**Deciders:** Rikard (operator), Claude Code (draft)
**Technical Story:** Amends ADR-026 after reading the Cordis v4 paper "A Programming
Paradigm for Spatiotemporal Composability" (Shi, Zhang, Cui — Peking University /
DeepSeek-AI), downloaded 2026-08-19 (`~/Downloads/paper.pdf`)

## Context

ADR-026 decided that a new `EngineAdapter`/`EngineContext` layer should replace
`unified_cli.py`'s hardcoded if/elif dispatch (lines 338–359), while `route()`/
`engine_manifest.py` remains untouched. The sketch in ADR-026 described the registry
informally: one `engine_id` maps to exactly one registered adapter, and switching
implementation means unregistering the old one and registering a new one.

The Cordis paper (§6.2, "Service Multiplexing") names and formalizes exactly the
intersection ADR-026 sketched — a coeffect key (for us: `engine_id`) that one or
more components (adapters) can bind to — and describes **two** patterns for it, not
one:

1. **Exclusive binding** — at most one implementation bound at a time; switching
   requires unload+load of the provider, which momentarily disrupts every consumer
   of the key. That is the pattern ADR-026 sketched implicitly.
2. **Service broker** — a central broker is injected by both providers *and*
   consumers. Multiple providers coexist behind the same key; the broker routes each
   call between them. The consumer never sees a binding switch, only the broker, so
   provider switches do not disrupt the consumer. The paper names three capabilities
   the broker gives "for free": load balancing (multiple providers, one routing
   policy), rolling updates (a new provider loads in parallel, traffic moves
   gradually, old ones unload when no in-flight calls remain) and cross-process
   invocation (each process its own context, an RPC bridge links them).

The difference is not cosmetic for our case. `hermes_invoker.py`'s docstring already
says that "route() picks 'hermes' as an engine_id, but picking isn't invoking" — and
`DEFAULT_MANIFESTS` (ADR-022) explicitly expects more entries per engine *family*
over time: multiple Deepseek profiles (e.g. one fast/cheap and one verified/more
expensive), or a primary engine with an explicit fallback when the former is
`degraded`. With exclusive binding, every such addition becomes a rebinding of the
same `engine_id` key — the consumer (`unified_cli.py` or later the `route()` caller)
notices a hiccup every time. With a broker, multiple adapters register under the same
key without the consumer ever seeing the seam.

## Decision

`EngineContext` (ADR-026) is implemented according to the broker pattern, not
exclusive binding — but **v1 builds only the broker's skeleton, not its policy
layer**:

1. **`engine_id` is a broker key, not a directly-bound slot.** `EngineContext.get
   (engine_id)` always returns a broker reference (`EngineBroker`), never an adapter
   directly. Consumer code (`unified_cli.py`) calls
   `engine_context.get(choice.engine_id).invoke(...)` — the same call surface ADR-026
   already sketched, no difference for the consumer.

2. **v1 policy: exactly one provider per broker, passthrough.** In v1 the broker
   implements no routing policy (no round-robin, no weighting) — that would be
   building speculatively for providers that do not exist yet, the same rule
   ADR-022's Alternatives section already applied to learned routing. A broker with a
   single registered provider degrades to pure passthrough: `invoke()` calls the
   single provider's `invoke()` directly. This is functionally identical to
   exclusive binding for today's two adapters (`claude-direct`, `hermes`) — the
   difference is only where the interface sits.

3. **Multiple-provider policy is built when a real need arises** — e.g. a second
   Deepseek profile, or an explicit fallback provider for a `degraded`-flagged
   engine (ADR-022's `reliability_class` field). That date, not today, is when the
   load balancing/rolling-updates policy is actually written.

4. **Cross-process invocation (the RPC bridge in §6.2) is explicitly not part of
   this decision.** `hermes_invoker.py`'s subprocess model covers today's needs (one
   process calls another engine's CLI and waits for the result); a distributed
   broker across multiple Cortxt processes is an entirely different scale question
   with no known need today.

**What this changes in ADR-026:** only where the interface between "one `engine_id`"
and "one adapter instance" sits (via the broker instead of directly), and that the
registry from the start allows multiple providers per key without redesign. The
`EngineAdapter` protocol, the `HermesAdapter` repackaging, and
`route()`/`engine_manifest.py` remaining untouched all stand unchanged.

## Consequences

### Positive
- Adding a second provider for an existing `engine_id` (new Deepseek profile,
  fallback engine) becomes one more registration, not a rebinding that disrupts
  consumers — exactly the property ADR-026 lacked.
- The v1 implementation is trivial (broker with one provider = passthrough), so no
  complexity is added for cases that do not exist yet — the broker's *skeleton*
  buys the future, not its policy logic.
- The terminology (`broker`, `provider`, `exclusive binding` vs `service broker`) is
  now shared with the Cordis paper, which makes future comparisons and any further
  borrowing of patterns (rolling updates, load balancing) cheaper to reason about.

### Negative
- One extra indirection layer (`EngineBroker` between `EngineContext` and
  `EngineAdapter`) compared to ADR-026's simpler sketch, for a problem (one provider
  per key) that does not require it today.
- The broker abstraction is, exactly as the paper itself flags (§5.3 "Threats to
  validity"), validated in a TypeScript/Koishi context over four years of production
  operation — no corresponding evidence exists for a Python port in this codebase.
  The pattern is borrowed as design vocabulary, not as a proven implementation.

### Risks
- If no second provider is ever registered per key, the indirection was wasted
  complexity — mitigated by the fact that the v1 policy (passthrough) keeps the
  cost to one extra method call, not a new subsystem class.
- The broker pattern may be tempted to grow routing policy (weighting,
  latency-based balancing) before data exists to justify it — the same
  speculative-building trap ADR-022 and ADR-026 already flagged. The explicit
  non-goal above (point 3) is intended to prevent that.

## Alternatives Considered
1. **Keep exclusive binding as ADR-026 sketched** — rejected: does not solve the
   concrete scenario (multiple Deepseek profiles, fallback engine for `degraded`)
   without the consumer noticing a provider switch; the broker skeleton costs almost
   nothing extra in v1 to avoid that.
2. **Build the entire broker policy layer now (load balancing, rolling updates)** —
   rejected: neither of today's two providers (`claude-direct`, `hermes`) has more
   than one instance; the same don't-build-speculatively rule that already governs
   `route()`'s scope (ADR-022).
3. **Cross-process/RPC broker from the start** — rejected: `hermes_invoker.py`'s
   subprocess model suffices for today's single-process daemon; no known
   multi-process scale question exists to solve for.

## Validation
- [ ] `EngineContext.get(engine_id)` returns an `EngineBroker`, not an adapter directly
- [ ] A broker with one registered provider behaves identically to a direct call (no
      extra side effects, no measurable overhead beyond one method hop)
- [ ] `unified_cli.py`'s call surface (`engine_context.get(...).invoke(...)`)
      unchanged from ADR-026's sketch
- [ ] No routing policy (round-robin/weighting) implemented until a second provider
      is actually registered under the same key

## Expiry/Review Trigger
- Review by: 2026-09-19 (same horizon as ADR-026)
- Trigger: a second provider is registered under the same `engine_id` (e.g. a second
  Deepseek profile or a fallback engine for a `degraded`-flagged engine) and requires
  the routing policy to actually be written, OR a cross-process need arises (the
  Supervisor Daemon is split across multiple processes) and §6.2's RPC bridge becomes
  relevant, OR ADR-026's own review trigger (RLM takes over `route()`'s role, or the
  registry turns out to be the wrong format) occurs first and carries this decision
  along in the reconsideration.
