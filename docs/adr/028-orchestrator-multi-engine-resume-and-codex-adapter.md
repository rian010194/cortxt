# ADR-028: Orchestrator multi-engine resume via opaque per-adapter session_id, CodexAdapter added

**Status:** Accepted
**Date:** 2026-08-20
**Deciders:** Rikard Andersson (operator)
**Technical Story:** (internal design archive)

## Context

`_run_orchestrator_chat` (`agent-platform/cli/unified_cli.py`) hardcoded
`context.get("hermes")` — an operator could not talk to any engine but
Hermes from the orchestrator REPL, and no adapter existed for Codex.

Separately, `EngineAdapter.invoke()` was a pure one-shot call: profile +
prompt in, result out. That shape is right for Hermes-as-advisor (each
chat turn resends a fresh sanitized state projection deliberately, so the
engine never has to remember prior turns). It is wrong for Codex-as-
implementer: a multi-step coding conversation (read files, propose a
diff, take feedback, revise) lost everything Codex's own agent loop had
accumulated the moment the subprocess exited, forcing the operator to
re-explain state on every `cortxt` invocation.

Both engines already expose their own native resume mechanism (`codex
exec resume <session_id> <prompt>`, `hermes -z <prompt> --resume
<session_id>`), verified against the installed CLIs' `--help` output
before this was built.

This ADR extends the `EngineAdapter` protocol ADR-026 established and the
`EngineBroker`/`EngineContext` service-broker pattern ADR-027 established;
it does not replace either.

## Decision

1. `EngineAdapter.invoke()` gains one new keyword-only parameter,
   `session_id: str | None = None`, strictly additive — omitting it (every
   call site today) behaves identically to the pre-existing signature. The
   returned dict gains one new optional key, `session_id`, carrying the
   engine-native id of the session just used (fresh or resumed).
   `session_id` is treated as **opaque above the adapter boundary** — a
   Codex UUID and a Hermes session id are never compared, converted, or
   assumed to mean the same thing, mirroring the same "engine-specific
   detail hidden behind one contract" discipline ADR-026 already
   established for `invoke()` itself.
2. `invoke_hermes()` / `HermesAdapter` and the new `CodexAdapter`
   (`runtime/adapters/codex_adapter.py`) both implement resume by
   appending their engine's native resume flag (`--resume <id>` /
   `resume <id>`) to argv when `session_id` is given, and both capture the
   session id of a freshly-created session after a one-shot call
   (`hermes sessions list` for Hermes, parsing the `--json` event stream
   for Codex) rather than guessing at output shape.
3. `CodexAdapter` gets its own `EngineContext`/`EngineBroker` registration
   key (`"codex"`), single-provider passthrough, same v1 policy ADR-027
   already set for Hermes — no second provider under one `engine_id`.
4. The orchestrator chat REPL (`unified_cli.py`) gains a `--engine` flag
   (default `"hermes"`, today's only behavior unchanged if omitted) and a
   `/engine <id>` slash command that switches which broker the *next* turn
   talks to. Each engine's `session_id` is tracked independently per
   engine within one live REPL process — switching engines does not carry
   one engine's conversation into another. On the first turn to a given
   engine in a REPL run, `session_id=None` (fresh); on every subsequent
   turn to the *same* engine, the previously-captured `session_id` is
   passed so a live multi-turn conversation keeps its own accumulated
   context. Hermes keeps its existing stateless full-projection-per-turn
   prompt **in addition to** passing `--resume` (both together, not
   either/or) — resume adds conversational continuity, but the sanitized
   projection stays the source of truth for system state Hermes shouldn't
   have to remember itself.
5. `session_state`'s `chat.assistant` event payload gains one new optional
   field, `engine_session_id`, storing the adapter's returned native
   session id for future correlation. This ADR stores the field; it does
   not build a `cortxt orchestrator chat --resume <cortxt-session-id>`
   flow that reads it back (deferred, see Open Questions).
6. Resume of a stale/expired/unknown `session_id` is treated as a normal
   `status="failed"` result — the adapter never silently falls back to
   `session_id=None` and starts an un-announced new conversation. The
   operator sees the failure and decides whether to retry or start fresh
   explicitly.

## Consequences

### Positive
- An operator can talk to Codex from the same orchestrator REPL used for
  Hermes, without re-explaining accumulated state every turn.
- The opaque-session-id discipline keeps engine-specific resume mechanics
  fully contained inside each adapter — no caller above the adapter
  boundary needs to know Codex resume differs from Hermes resume.
- Strictly additive to `EngineAdapter.invoke()`: every existing call site
  and test continues to pass unmodified with `session_id` omitted.

### Negative
- Two independent session-id universes now exist per REPL run (per-engine
  `session_id`, plus Cortxt's own `session_state` id) with only a
  one-directional link (`chat.assistant.engine_session_id` points at the
  engine session, nothing points back yet) — a full round-trip resume of
  a past Cortxt session's engine-native conversation is not yet possible.

### Risks
- `CodexAdapter`'s `--json` event-stream parsing for the new session id
  depends on Codex's own event shape remaining stable across CLI versions
  — not covered by a compatibility contract, only by this session's live
  verification.

## Alternatives Considered
1. **Keep `EngineAdapter.invoke()` fully stateless, re-send full context
   every turn for every engine** — Rejected: this is what caused the
   original problem for Codex-as-implementer; Hermes-as-advisor's
   stateless shape is deliberately right for it, but forcing the same
   shape onto Codex loses everything its own agent loop accumulates.
2. **A cross-process/RPC broker unifying both engines' session state** —
   Rejected as out of scope; already a non-goal of ADR-027, unchanged
   here. Subprocess invocation stays single-process, synchronous,
   blocking.
3. **Automatic fallback to a fresh session on a stale `session_id`** —
   Rejected: would silently start a new, un-announced conversation the
   operator didn't ask for, violating this project's discipline against
   silent fallbacks.

## Validation
- [x] Implementation matches decision — `runtime/engine_adapter.py`,
      `runtime/adapters/codex_adapter.py`, `routing/hermes_invoker.py`,
      `cli/unified_cli.py` (`--engine` flag, `/engine` command) all landed
      2026-08-20, merged to `main`.
- [x] Tests cover decision boundaries — fake-`run_subprocess` unit tests
      for both adapters' fresh-vs-resume argv construction and JSONL/
      output-file parsing; `FakeBroker`/`FakeContext`-based REPL tests for
      `/engine` switching and per-engine session continuity.

## Open Questions (deferred, not blocking this ADR)
- Resuming a *past* Cortxt `session_state` session's engine-native
  conversation (`--resume <cortxt-session-id>` reading back the stored
  `engine_session_id`) — storage-only today, no read-back flow built.
- Whether an unsupported `provider` argument to `CodexAdapter.invoke()`
  should raise vs. silently no-op — currently a silent no-op with a code
  comment; leaning toward raising in a future revision.
- Per-engine `--timeout` defaults — Codex coding turns may legitimately
  need longer than Hermes's advisory-reply-sized default; left to a
  future implementation decision.
