# ADR-026: Engine adapter-registry (cordis-inspired DI) is kept separate from `route()`'s selection

**Status:** Accepted (amended 2026-08-19 for the service-broker pattern per ADR-027)
**Date:** 2026-08-19
**Deciders:** Rikard (operator), Claude Code (draft)
**Technical Story:** Follow-up on ADR-022 (capability manifest + `route()`), arising from a
discussion about adding Deepseek's harness as an additional engine and about whether
cordis (`cordiverse/cordis`, the Koishijs family's plugin/DI framework) ideas should
replace `agent-platform/routing/engine_manifest.py`

## Context

The operator looked at `cordiverse/cordis` (scoped `Context`/DI, plugin lifecycle,
isolated reload per plugin) and at Deepseek's agent harness as a candidate for an
additional engine in the loop (beyond Claude, Codex, Hermes). The question that arose:
should cordis-style DI/plugin model replace `engine_manifest.py` entirely?

A code inventory (2026-08-19) shows that `engine_manifest.py` and invocation are
already implicitly split in two, just not formalized:

- `routing/engine_manifest.py` — `route(task_tags, manifests) -> EngineChoice`, a pure
  function. Only **selection**: given tags, which `engine_id` wins. `DEFAULT_MANIFESTS`
  today has two entries (`claude-direct`, `hermes`); ADR-022's Alternatives section
  already intended more adapters (Pi, Codex, Copilot) to be added as manifest rows when
  they are wired in.
- `routing/hermes_invoker.py` — knows *how* hermes is actually run (subprocess
  wrapper). The file's own docstring says explicitly: "`route()` picks 'hermes' as an
  engine_id, but picking isn't invoking." Already a deliberate separation, just not a
  registered contract.
- `cli/unified_cli.py:338–359` — hardcoded `if choice.engine_id == "hermes": ... elif
  choice.engine_id == "claude-direct": ...`. It is **this branch**, not `route()`,
  that is the actual place where a DI/plugin layer would replace something.

ADR-022 already promises a successor to `route()`'s role: target-architecture.md §29
point 5 ("RLM and geometric reasoning are owned by Cortxt Agent Core") and the Phase
5/6 work in `agent-platform/reasoning/geometric/`. Quoting ADR-022: "when that engine
is ready, it replaces `route()`'s role; it does not extend it." The Supervisor Daemon
v1 spec ((internal design archive), Non-goals) repeats
the same thing and points out that the daemon inherits the handoff automatically
without its own code change.

Letting cordis DI replace `engine_manifest.py` entirely would thus introduce a **second,
competing successor** to the same bootstrap function — one that is not the already
planned RLM/Geometric Reasoning path. That would dissolve an architecture decision
(ADR-022) without formally superseding it, and without the evidence (Phase 6 exit
criterion) that ADR-022/025 already set as a condition for touching `route()`'s role.

## Decision

Cordis-inspired DI does **not** replace `route()`/`engine_manifest.py`. It is
introduced as a separate layer that replaces `unified_cli.py`'s hardcoded
if/elif dispatch:

1. **`route()` and `EngineManifest` are not touched.** The selection contract
   (ADR-022) stands unchanged; RLM/Geometric Reasoning remains the only intended
   successor to its role.

2. **New layer: `EngineAdapter` protocol + `EngineContext` registry**
   (`runtime/engine_adapter.py`, `runtime/engine_registry.py`). Each engine (Claude,
   Hermes, Codex, future Deepseek) becomes an adapter that registers itself in a root
   context at daemon start — cordis's idea of scoped `Context`/DI, ported as a
   pattern, not as a TS/Koishi dependency (Supervisor Daemon is Python).

3. **Existing invocation code is repackaged, not rewritten.**
   `hermes_invoker.invoke_hermes()` becomes the `invoke()` method on a `HermesAdapter`.
   The same pattern fills the documented gap at `unified_cli.py:299`
   ("'claude-direct' has no headless invocation here") with a `ClaudeAdapter` when/if
   it is built, and provides a clear registration point for a future `DeepseekAdapter`
   — one manifest row in `engine_manifest.py` plus one adapter file, nothing else.

4. **`unified_cli.py`'s if/elif chain (lines 338–359) is replaced** with
   `engine_context.get(choice.engine_id).invoke(...)`. That is the only place
   actually removed.

**Explicitly not part of this decision:**
- Building or registering a `DeepseekAdapter` now — happens as its own ADR-022
  manifest row when Deepseek is actually wired in and has run evidence (the same rule
  ADR-022 already set for Pi/Codex/Copilot).
- Touching `route()`'s selection algorithm or `reliability_class` semantics.
- Hot-reload/isolated crash recovery per adapter in v1 — the registry enables it
  later, but the Supervisor Daemon v1 spec does not build that functionality now.

## Consequences

### Positive
- `route()` remains untouched and inherits the RLM handoff exactly as ADR-022 already
  promised — no new dependency is introduced on the selection side.
- Adding an engine (Deepseek or other) becomes: one manifest row + one adapter file,
  no change in `unified_cli.py` or in the selection logic.
- `hermes_invoker.py`'s existing, already-tested subprocess logic is reused as is —
  no rewrite of working code.

### Negative
- A new small abstraction layer (`EngineAdapter`/`EngineContext`) is added that did
  not exist before — more code to maintain for a problem (four hardcoded lines in
  `unified_cli.py`) that is small today.
- The cordis pattern (scoped Context, DI) is ported conceptually from a TS/Koishi
  framework; no code or package is imported, which means details (fork semantics,
  service scoping) must be redesigned for Python, not copied.

### Risks
- If the registry is built with more generality than three-four adapters actually
  require (hot-reload, dependency graph between adapters), the same
  "don't build speculatively" trap that ADR-022's Alternatives section already warned
  about on the selection side arises.
- Two new architecture concepts (`route()`'s selection and `EngineContext`'s DI) must
  be kept apart in future documentation — risk that someone by mistake puts selection
  logic in an adapter or invocation logic in `route()`.

## Alternatives Considered
1. **Let cordis DI replace `engine_manifest.py` entirely** — rejected: it would
   introduce a competing successor to `route()`'s role alongside the already planned
   RLM/Geometric Reasoning path (ADR-022, target-architecture.md §29.5), without
   formally superseding ADR-022 and without the Phase 6 exit criterion's evidence.
2. **Do nothing — keep `unified_cli.py`'s if/elif** — rejected: does not scale beyond
   three-four engines without becoming a growing hardcoded chain; nor does it provide
   an isolation point for future per-adapter crash/reload.
3. **Import cordis (the TS package) directly via a Node sidecar layer** — rejected:
   the Supervisor Daemon and the entire agent-platform package are Python; a Node
   dependency for a pure architecture pattern is disproportionate complexity.

## Validation
- [ ] `EngineAdapter` protocol and `EngineContext` registry implemented and tested
- [ ] `HermesAdapter` repackages `invoke_hermes()` without changing its tested behavior
- [ ] `unified_cli.py:338–359`'s if/elif chain removed, replaced by
      `engine_context.get(...).invoke(...)`
- [ ] `route()`/`engine_manifest.py` unchanged (diff shows zero changes in that file)

## Expiry/Review Trigger
- Review by: 2026-09-19
- Trigger: a third/fourth adapter (Deepseek, Codex, or Pi) is registered and reveals
  that the protocol is the wrong format (e.g. needs streaming or multi-turn state the
  registry did not anticipate), OR RLM/Geometric Reasoning takes over `route()`'s role
  (the Phase 6 exit criterion, see ADR-025) and the interface between selection and
  registry needs reconsideration, OR Supervisor Daemon v1 actually implements
  per-adapter hot-reload and it shows that `EngineContext` was designed too narrowly.
