# Orchestrator multi-engine resume + CodexAdapter v1 — design

Status: draft (formalizes brainstorming from session 3, 2026-08-20; not yet
reviewed with operator)
Date: 2026-08-20
Authority: architectural proposal for one bounded slice ("del 1 / A" per
`.hermes/dispatch/handoff-20260820b.md`); does not override ADR-026/027.
Related: `docs/adr/026-engine-adapter-registry-separate-from-route-selection.md`
(`EngineAdapter` protocol, `HermesAdapter` repackaging pattern — this spec
extends the protocol that ADR established, does not replace it);
`docs/adr/027-engine-context-adopts-service-broker-not-exclusive-binding.md`
(`EngineBroker`/`EngineContext`, single-provider-passthrough v1 policy this
spec keeps unchanged); `agent-platform/routing/engine_manifest.py`
(`route()`/`EngineManifest` — untouched by this spec, see Non-goals);
`agent-platform/cli/orchestrator.py` and `agent-platform/cli/
unified_cli.py:_run_orchestrator_chat` (the REPL this spec's engine-choice
and resume feed into); `.hermes/dispatch/handoff-20260820b.md` (session
history, budget-usage caveat, Codex-usage-pattern note)

## Problem

`_run_orchestrator_chat` (`agent-platform/cli/unified_cli.py`) hardcodes
`context.get("hermes")` — there is no way for an operator to talk to any
other engine from the orchestrator REPL, and no adapter exists for Codex to
register under `EngineContext` even if the hardcoding were removed.

Separately, `EngineAdapter.invoke()` (`runtime/engine_adapter.py`) is a pure
one-shot call: profile + prompt in, `{status, stdout, stderr, ...}` out. Every
orchestrator chat turn today rebuilds a full sanitized state projection
(`orchestrator_cli.build_chat_prompt`) and sends it fresh — deliberately
stateless on the engine side, which is the right shape for Hermes-as-advisor
(a short status/next-steps question shouldn't depend on the engine
remembering the last five turns). It is the wrong shape for Codex-as-
implementer: a multi-step coding conversation (read files, propose a diff,
take feedback, revise) loses everything Codex's own agent loop accumulated
(files read, edits made, its own reasoning) the moment the subprocess exits,
forcing the operator to re-explain state every single `cortxt` invocation.

Both engines already have their own native resume mechanism, verified
against the installed CLIs on this machine (2026-08-20, `--help` output
only, no real invocation):

- **Codex**: `codex exec <prompt>` starts a session; `codex exec resume
  <session_id|--last> <prompt>` continues it. `--json` streams JSONL events
  to stdout; `-o/--output-last-message <file>` writes the final response to
  a file (avoids parsing conversational prose off stdout, same UTF-8/text-
  parsing-is-fragile lesson `routing/hermes_invoker.py`'s encoding fix
  already taught this codebase). The exact event name/shape that carries the
  new session's id in `--json` output is **not yet verified** — flagged as
  Open question / first proof step, not guessed here.
- **Hermes**: `hermes -z <prompt> --resume <session_id>` (or `-r`) continues
  a prior session; `hermes sessions list` reads the SQLite session store and
  can report the most recent session's id; `--pass-session-id` puts the
  session id into the *agent's own* system prompt (for the model's benefit,
  not guaranteed to be a reliable way for *us* to capture the id
  programmatically). Exactly how `invoke_hermes()`'s one-shot `-z` call
  should surface the new session id it just created is also **not yet
  verified** — same proof-step treatment as Codex's event shape.

This spec is the formalization the operator asked for before any of this is
built (per handoff §1) — it does not itself change code.

## Non-goals

- **`route()`/`engine_manifest.py`.** Selection-by-task-tag is unrelated to
  this spec's engine choice, which is an operator picking *who they are
  talking to in the chat REPL*, not a task-shape-driven dispatch decision.
  No manifest row, no `route()` change. (A `codex` manifest row belongs to
  whatever spec adds Codex to *dispatch*, not to this chat-resume spec.)
- **`ClaudeAdapter`.** Explicitly deferred per the handoff's priority order;
  `unified_cli.py`'s existing "'claude-direct' has no headless invocation
  here" gap is untouched.
- **Streaming token-level output in the REPL.** Both engines' native modes
  used here (`hermes -z`, `codex exec`) are already non-streaming,
  block-until-done calls; this spec does not add a streaming UI.
- **Daemon/dispatch-side session resume.** `daemon/loop.py`'s
  `Coordinator`-driven runs are a different lifecycle (root/child sessions,
  Evidence Gate, `checkpoint_required`) from an interactive chat turn; this
  spec touches only the orchestrator chat REPL's adapter usage. If a future
  daemon spec wants Codex resume for unattended multi-step runs, it should
  reuse `CodexAdapter.invoke(..., session_id=...)` from this spec, not
  redesign it.
- **Cross-process/RPC broker (Cordis §6.2).** Already a non-goal of
  ADR-027; unchanged here — `codex`/`hermes` subprocess invocation stays
  single-process, synchronous, blocking.
- **A second provider under the same `engine_id`.** `codex` gets exactly
  one adapter, same v1 passthrough policy ADR-027 already set for `hermes`.

## Architecture

### 1. `EngineAdapter` protocol gains an optional resume parameter

`runtime/engine_adapter.py`'s `invoke()` signature adds one new keyword-only
parameter with a default that preserves today's behavior exactly:

```python
def invoke(
    self,
    profile: str,
    prompt: str,
    *,
    timeout_seconds: int,
    model: str | None = None,
    provider: str | None = None,
    cwd: Path | None = None,
    session_id: str | None = None,   # NEW
) -> dict:
    ...
```

`session_id=None` (today's only call shape, everywhere) must behave
identically to the current unmodified code — this is strictly additive.
When a caller passes a non-`None` `session_id`, the adapter resumes that
engine-native session instead of starting fresh. The returned dict gains one
new optional key, `session_id`, carrying the engine-native id of the
session that was just used (fresh or resumed) — `None` when the underlying
engine call failed before a session was ever established, or when an
adapter genuinely has no resumable-session concept.

This mirrors, deliberately, the same "adapter-local, engine-specific
detail hidden behind one contract" shape ADR-026 already established for
`invoke()` itself — `session_id` is opaque to every caller above the
adapter (a Codex UUID and a Hermes session id are never compared,
converted, or assumed to mean the same thing).

### 2. `invoke_hermes()` and `HermesAdapter` gain resume support

`routing/hermes_invoker.py:invoke_hermes()` adds an optional `session_id`
parameter; when given, appends `--resume <session_id>` to `argv` before
existing `-m`/`--provider` overrides. `HermesAdapter.invoke()` passes
`session_id` through unchanged (same delegation-only shape as today).

Capturing the *new* session id after a one-shot `-z` call needs the proof
step called out above — candidate approaches to verify, not to guess-commit
to:
1. `--pass-session-id` and parse a recognizable marker out of `stdout`
   (fragile: depends on how/whether the model echoes it back verbatim).
2. Call `hermes sessions list` (need to check its output format —
   `--json`? plain table?) immediately after, take the newest entry,
   confirmed via its `updated_at`/creation-order rather than assumed to be
   "the one we just made" without a check.
3. Ask Hermes upstream (or check its existing docs/`--help` more deeply)
   whether `-z` has an existing flag to print the session id directly to
   stderr or a side file, avoiding both fragile options above.

Whichever mechanism wins the proof step is the *only* thing that changes in
`HermesAdapter`/`invoke_hermes()` beyond the additive `session_id` parameter
already specified above.

### 3. New `CodexAdapter`

`runtime/adapters/codex_adapter.py`, same shape as `HermesAdapter`
(construction-time injectable `run_subprocess` for testability, no
speculative generality beyond what Codex's CLI actually offers):

```python
class CodexAdapter:
    def __init__(self, run_subprocess: Callable | None = None) -> None: ...
    def invoke(self, profile, prompt, *, timeout_seconds, model=None,
               provider=None, cwd=None, session_id=None) -> dict: ...
```

Behavior:
- `session_id is None` → `codex exec --json -o <tmpfile> [-m MODEL] [-C cwd]
  <prompt>`.
- `session_id is not None` → `codex exec resume <session_id> --json -o
  <tmpfile> [-m MODEL] [-C cwd] <prompt>`.
- `profile` maps to Codex's `-p/--profile` (`$CODEX_HOME/<name>.config.toml`
  layering) — same "profile" vocabulary as Hermes's `-p`, different
  underlying mechanism per engine, which is exactly why this detail lives
  inside the adapter and not in a caller.
- `provider` has no direct Codex CLI equivalent found in `--help`; the
  adapter does not invent one — an unsupported `provider` value is a no-op
  today, flagged with a code comment, not silently mapped to something
  wrong. (Open question below: whether this needs a `NotImplementedError`
  instead of a silent no-op — operator call.)
- The `--json` JSONL stream is parsed for whatever event carries the new
  session id (proof step); `-o <tmpfile>` is read for the final assistant
  message, matching the "don't parse conversational prose off stdout"
  lesson. `timeout_seconds` maps to the subprocess call's own `timeout=`,
  same as `invoke_hermes`.
- Return shape matches `invoke_hermes()`'s dict: `status` (`succeeded` |
  `failed` | `timed_out`), `stdout`/`stderr` (raw captured text, kept for
  debugging even though the parsed message is authoritative), `elapsed_
  seconds`, and the new `session_id`.
- `subprocess.run(..., encoding="utf-8", errors="replace")` from the start
  — apply the Hermes UTF-8 lesson proactively instead of waiting to
  rediscover it.

`runtime/default_engine_context.py` registers it alongside Hermes:

```python
def build_default_engine_context() -> EngineContext:
    context = EngineContext()
    context.register("hermes", HermesAdapter())
    context.register("codex", CodexAdapter())
    return context
```

Nothing about `EngineContext`/`EngineBroker` (ADR-027) changes — `codex`
gets its own broker key with exactly one provider, same passthrough policy.

### 4. Engine choice in `_run_orchestrator_chat`

Two additive changes, no removal of existing behavior:

- New `--engine` CLI flag on the `orchestrator chat` subcommand, default
  `"hermes"` (today's only behavior, unchanged if omitted).
- New local slash command `/engine <id>` (handled the same way `/status`,
  `/workstreams` etc. already are — in `orchestrator_cli.render_chat_command`
  or a sibling function, never invoking an engine) that switches which
  broker the *next* turn talks to, and echoes the new active engine back to
  the operator. Switching engines mid-session does **not** carry the old
  engine's conversation into the new one — each engine's `session_id` (if
  any) is tracked independently per engine, not shared.
- `transcript_record`'s `engine` field (currently hardcoded `"hermes"` in
  two call sites in `_run_orchestrator_chat`) becomes the active engine id.
- The Cortxt-side `session_state` event payload gains one new optional
  field on `chat.assistant` events: `engine_session_id` — the adapter's
  returned native session id, stored so a *future* `cortxt orchestrator
  chat --resume <cortxt-session-id>` (not built by this spec, see Open
  questions) could look it up. This spec stores the field; it does not
  build the resume-a-past-Cortxt-session flow.
- Default resume behavior **within one live REPL run**: on the first turn to
  a given engine, `session_id=None` (fresh). On every subsequent turn to
  the *same* engine within the same REPL process, pass the `engine_session_
  id` captured from that engine's previous turn, so a live multi-turn
  conversation with Codex keeps its own accumulated context turn-to-turn —
  this is the actual fix for the "loses everything every subprocess exit"
  problem in the Problem section. Hermes keeps today's stateless
  full-projection-per-turn prompt *in addition to* passing `--resume`
  (both together, not either/or) — resume gives Hermes conversational
  continuity too, but `build_chat_prompt`'s sanitized projection stays the
  source of truth for *system state* Hermes shouldn't have to remember
  itself (workstreams, runtimes) since that state can change between turns
  regardless of what the engine recalls.

## Data flow

```text
operator turn (non-slash, non-greeting)
  -> active engine's broker = context.get(active_engine_id)
  -> prior engine_session_id for active_engine_id (None on first use)
  -> build_chat_prompt(value, projection)  [unchanged — sanitized, redacted]
  -> broker.invoke(profile, prompt, ..., session_id=prior_engine_session_id)
  -> adapter starts fresh OR resumes, per session_id
  -> result: {status, stdout, stderr, session_id: new_engine_session_id, ...}
  -> print answer
  -> session_state.append(..., "chat.assistant", {..., engine_session_id})
  -> remember new_engine_session_id for this engine_id, next turn
```

## Error handling & safety boundaries

- **Resume of a stale/expired/unknown session_id.** Both CLIs' own failure
  mode (Codex: presumably a non-zero exit or an error event; Hermes:
  presumably a non-zero exit) is treated as a normal `status="failed"`
  result, same as any other invocation failure — the adapter does not
  retry with `session_id=None` automatically (that would silently start a
  new, un-announced conversation the operator didn't ask for). The chat
  REPL surfaces the failure and lets the operator decide (retry, or start
  fresh explicitly).
- **`session_id` is adapter-opaque.** Never validated, parsed, or compared
  across engines above the adapter boundary — same "opaque token" discipline
  `EngineAdapter`'s other parameters already follow.
- **Secrets/redaction unchanged.** `sanitize_user_text`/`build_chat_prompt`
  already redact before any engine call; resume changes nothing about what
  crosses the process boundary — the same sanitized projection is sent
  every turn regardless of resume state.
- **Budget discipline.** Per the operator's 2026-08-20 correction
  (`.hermes/dispatch/handoff-20260820b.md`, and this session's Codex-usage
  clarification): this spec does not itself authorize any real Codex/Hermes
  invocation. Implementation and its proof steps require the same
  before-real-calls check this session already did.

## Testing strategy

- **`EngineAdapter` protocol change**: existing `HermesAdapter`/broker tests
  continue to pass unmodified with `session_id` omitted (regression check
  that the new parameter is truly additive).
- **`CodexAdapter`**: unit-tested against a fake `run_subprocess`, same
  pattern as `test_hermes_invoker.py` — assert the right argv is built for
  fresh vs. resume calls, assert JSONL/output-file parsing against fixture
  content (not a real `codex` call).
- **`invoke_hermes()` resume**: unit-tested the same way — assert `--resume
  <id>` appears in argv when `session_id` is given, absent otherwise.
- **`_run_orchestrator_chat` engine choice**: extend
  `test_orchestrator_chat.py`'s `FakeBroker`/`FakeContext` pattern with a
  second fake engine, assert `/engine codex` switches the broker used by
  the next turn and that `transcript_record`'s `engine` field follows.
- **Resume-across-turns**: a REPL-level test that queues two non-slash
  turns to the same `FakeBroker`, asserts the second call's `session_id`
  kwarg equals the first call's returned `session_id`.
- **Real end-to-end verification** (actual `codex exec`/`hermes -z` calls,
  confirming the JSONL event shape and the Hermes session-id-capture
  mechanism from the two Architecture sections above) is a **proof step**,
  run manually, gated on an explicit budget check with the operator first —
  not part of the default `pytest -m "not real_inference and not
  docker_required"` suite.

## Open questions

1. **Exact Codex `--json` event carrying the new session id** — proof step,
   not guessed here (Architecture §3).
2. **Exact Hermes mechanism for capturing a fresh `-z` call's new session
   id** — three candidates listed in Architecture §2, proof step decides.
3. **Should an unsupported `provider` argument to `CodexAdapter.invoke()`
   raise vs. silently no-op?** Leaning toward raising (fail loud beats
   silent wrong-behavior, matching this project's general discipline
   against silent fallbacks) but left for operator confirmation since it's
   a small API-shape decision, not an architectural one.
4. **Resuming a *past* Cortxt `session_state` session's engine-native
   conversation** (`cortxt orchestrator chat --resume <cortxt-session-id>`,
   reading back the stored `engine_session_id` from a previous REPL run) is
   explicitly not built by this spec (Architecture §4 storage-only) — worth
   a follow-on spec once this slice is proven, not designed in detail here.
5. **Cost/timeout defaults for Codex turns** — `orchestrator chat`'s
   existing `--timeout` (default 120s) was sized for Hermes advisory
   replies; a Codex coding turn (reading files, proposing edits) may
   legitimately need longer. Left to the implementation plan to decide
   whether `--timeout`'s default should vary per engine or stay a single
   operator-set value.

## Decomposition note

This is sub-project "del 1 / A" of the "one CLI, multiple engines" vision
discussed in session 3 (2026-08-20). Explicitly out of this slice, per the
handoff's own priority ordering:
- The Variant A/B/C CLI-surface decision (`cortxt pipeline --watch` vs.
  `cortxt status` vs. a chat-header) — independent of this spec, needs
  operator input on the three mockup variants.
- Sub-project 2 (unattended-daemon credential/security model) and
  `ClaudeAdapter` — unchanged, deferred per the handoff.
