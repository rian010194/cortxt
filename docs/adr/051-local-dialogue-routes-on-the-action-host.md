# ADR-051: Local dialogue routes on the action host (revision 2)

**Status:** Accepted (2026-09-17, operator)
**Date:** 2026-09-17 (rev2; original draft 2026-09-16)
**Deciders:** Rikard (operator, OD-1); draft by Claude, rev2 by Hermes coordinator
**Extends:** ADR-038 (adds a second, narrower route class to the reviewed host boundary it
requires; supersedes nothing in it). **Applies:** ADR-047 D1–D3 as amended by ADR-049 D1–D4;
ADR-044 (first-party app boundary).
**Technical Story:** B1.5c/B1.5d of the dialogue-to-result series; decision DEC-3
(`lab/dialogue-series/DECISIONS-pending-20260916.md`); slicing `lab/dialogue-series/b15-slicing.md`;
build-level form `lab/dialogue-series/b15c-order.md` §D2–§D8 (audited by the A3 swarm).

## Context

The series' first runnable web dialogue needs the browser to create a dialogue session, send a
turn, watch a streamed reply and its status, cancel a turn, and reopen a session. Those requests
must reach an ACP agent process (B1.5a) and a dialogue store (B1.5b) through the loopback host.

**What the host boundary is today (verified at `0f6113ba3ed2`, origin/main after #622 #624 #623
#625 #626 #627).**
- `agent-platform/widget/action_host.py` is "the separately reviewed boundary ADR-038 requires
  before any action endpoint" (`:1-15`): loopback `127.0.0.1`, same-origin with no CORS answer, a
  per-process session token echoed as `X-Cortxt-Token`, body bound `MAX_BODY_BYTES = 8 * 1024`,
  closed-schema validation, a sliding-window rate limit of 12 requests per minute (`_check_rate`)
  and an operator gate — approval reference plus `confirm` — before any side effect.
- It serves 20 `/api` routes (17 GET, 3 POST): session/token, widget generation, the authorized
  action, packaging action, plus the packaging/repository read routes merged from the series.
  None is for a session, a chat or ACP.
- `agent-platform/widget/serve.py` is static-only.
- The host resolves a data home; **unset is not an error** (FR1 correction, CHECKPOINT entry 8)
  and the packaging routes answer `503 store_unavailable`; set-but-invalid refuses before binding.

**What ADR-038 says that binds this.** Mutation ports stay disabled "until their adapters and
gates are separately accepted"; "automatic mutation triggered by load, poll, render, selection,
another widget's event, or an LLM suggestion" is forbidden; "an action endpoint must not be added
to `serve.py` without a separately reviewed host boundary".

**Why the existing action class does not fit a conversation.** A dialogue turn changes no GitHub,
label, Run or dispatch state. It does two things the host has never done: it **starts and drives
a local agent process**, which may itself run tools and call a model, and it **persists operator
and agent prose** under the data home. Requiring an approval reference and `confirm` per turn is
honest but makes conversation unusable; treating turns as reads is dishonest, because a turn has
effects. A separately named class is needed.

**What the agent can do regardless of Cortxt.** `hermes acp` asks the client for permission for
dangerous commands and edits, but its edit approval also consults an agent-side auto-approve
policy (`acp_adapter/server.py`, `make_acp_edit_approval_requester(..., auto_approve_getter=...)`),
and tools that do not ask are not visible to the client at all. A client-side deny covers only
what the agent chooses to ask.

## Decision

### D1 — A new route class: local dialogue routes

The action host gains a route class, **local dialogue routes**, distinct from authorized action
routes. It is mounted on the **existing** action host (same listener, same origin, same token), not
on `serve.py`, and not on a new listener or port.

### D2 — The route set is closed

| Method | Path | Effect | Body / query |
|---|---|---|---|
| GET | `/api/dialogue/sessions` | none | — |
| POST | `/api/dialogue/sessions` | creates a dialogue session record (no agent process) | `{}` |
| GET | `/api/dialogue/session` | none | `?id=<cortxt session id>&after=<sequence>` |
| POST | `/api/dialogue/connect` | starts the agent process for a session: `session/new` if unbound, `session/load` if bound | `{"session_id"}` |
| POST | `/api/dialogue/turn` | accepts one prompt for asynchronous execution | `{"session_id", "text", "client_request_id"}` |
| POST | `/api/dialogue/cancel` | cancels the open turn | `{"session_id", "turn_id"}` |

Nothing else is added by this ADR. In particular there is **no permission-answer route** (D5) and
no route that binds a dialogue to a work record (B1.5e decides that under its own gate).

Paths are exact matches with query parameters, following the host's existing routing style.
Identifiers in requests and responses are **Cortxt** identifiers (`session_<32hex>`); the
agent-issued ACP id appears in responses only as the opaque `acp_session_id` field and is never
accepted as a request key, file name or directory (ADR-049 D1/D2).

Turn acceptance is asynchronous: the POST answers `202` with a `turn_id` once the turn is
persisted, and the reply reaches the client only through the poll (D10). A `client_request_id`
de-duplicates a repeated turn POST within the host's lifetime.

### D3 — What the class may never reach

Handlers of this class and the module behind them (`widget/dialogue_service.py`) must have **no
code path** to: the action executor or action ports (`widget_contract.action_executor`,
`widget_contract.action_ports`), GitHub or CLI ports (`widget_contract.adapters.github_ports`,
`cli_ports`), the dispatcher or run registry (`scripts/dispatcher.py`, `.dispatch/runs.json`),
the packaging or work-record operations, labels, issues, or Runs. This is enforced by a test, not
by review alone (Validation).

### D4 — The gate for this class

Every request, **GET included**, requires the session token (transcripts are operator prose; the
existing GET routes are not changed by this ADR). Every request with an effect is a **POST from an
explicit operator act** in the first-party app: creating a session, pressing connect, sending a
turn, pressing cancel. **No approval reference and no `confirm` per turn.**

**No effect from load, poll or render** (ADR-038): GET routes never create a session, never start
or reconnect an agent, never call a model. Reopening a session in the browser shows its **history
from the store**; reconnecting the agent is a separate POST.

### D5 — Agent permission requests are denied; there is no allow path

Every `session/request_permission` from the agent is answered **deny** by the adapter (B1.5a) and
recorded as a denied event the app shows. No route lets the browser allow a request. Allowing agent
effects is a mandate question (ADR-042's execution boundary) and needs its own accepted decision.

### D6 — The agent runs in a dedicated, empty working directory with a trimmed environment

The agent process for a dialogue session runs with `cwd = <data_home>/dialogue/workspaces/<cortxt
session id>`, created empty — never a repository checkout, never a read area, never the data home
root. Its environment is the ACP SDK's inherited-variable allowlist plus explicitly configured
additions; the host never passes its full environment. The agent command is an explicit argv
configured at host start, never a shell string. Without a configured command the class answers
`503 agent_unavailable`. Agent stderr is appended to a per-session log file under
`<data-home>/dialogue/logs/` for diagnosability, never an undrained pipe.

### D7 — Unavailable and refused are explicit, never empty

| Condition | Answer |
|---|---|
| no data home configured | `503 {"error": {"kind": "dialogue_unavailable"}}` on every route of the class |
| token missing or wrong | `403 authorization_denied` on every route of the class |
| ACP SDK extra not installed | `503 acp_unavailable` on `connect`; reads still served |
| agent command not configured or not found | `503 agent_unavailable` on `connect` and `turn` |
| live-agent cap reached | `503 agent_capacity` on `connect` |
| session not connected | `409 not_connected` on `turn`/`cancel` |
| a turn is open | `409 turn_in_progress` on `turn` |
| wrong `turn_id` on cancel | `409 turn_not_open` |
| this host is not the dialogue writer | `409 dialogue_writer_busy` on every dialogue POST; reads still served |
| targeted session log unreadable (integrity, foreign) | `409 session_unreadable` with the store kind |
| cursor ahead of the store | `409 cursor_ahead` |
| concurrent writer detected by the log | `409 sequence_conflict` with the store kind |
| agent connection lost | `502 agent_connection_lost` |
| agent answered uninterpretably (incl. a null `session/load` result) | `502 agent_protocol_error` |

A route of this class never answers `200` with an empty list for a condition in this table.

**Unknown ACP id on load — DEC-8(a), replacing the draft's `agent_session_not_found` row.** With
ACP SDK 0.9.0, `session/load` of an id the agent does not know is **undetectable on the wire**: the
agent answers like a known id with no replay. This ADR does **not** invent a not-found error. The
`connect` response and the persisted `dialogue.session.loaded` event carry the zero-replay evidence
(`replayed_update_count == 0`, `zero_replay == true`), so the first-party app can show "started
fresh" both live and on a later reopen. A client-side `AcpSessionNotFound` from the SDK (wire-
unreachable in 0.9.0) is surfaced as `502 agent_protocol_error`, never as "session not found".

**Unreadable sessions are surfaced, never dropped (F1).** The session list comes from the store's
`list_sessions()` (which reports unreadable entries), never from a resolve that skips them. The
list response carries `status: "ok" | "partial"` plus an `unreadable` array with the store's kind
per entry; a request targeting an unreadable session answers `409 session_unreadable` with the
store kind.

**One dialogue writer per data home (F4 / U-B3).** A host holds an OS file lock on
`<data-home>/dialogue/writer.lock` for its lifetime. A second host on the same data home serves
dialogue **reads** and answers every dialogue **POST** `409 dialogue_writer_busy`. The store's
`sequence_conflict` remains the last-resort detection underneath and is surfaced whenever it fires;
the lock is the enforcement, not the log race.

**Read shape and cursor (F2a / N2).** Session reads return the store's raw log events verbatim
(each `dialogue.updates` payload event keeps its own `origin` and `wire_seq`), with the
response-level `origin` copied from the store's read result — never computed, never dropped. The
poll cursor is the store's `sequence`, never `wire_seq`: `next` is the `sequence` of the last event
returned, `has_more` is true exactly when the read was cut at the page bound. Gaps in `wire_seq`
do not affect the cursor (pinned by a test with a gap).

### D8 — Bounds

- A dialogue body bound of its own, larger than the action bound (`MAX_BODY_BYTES` is sized for
  action requests), enforced before JSON parsing — value set in the B1.5c order.
- A send limit in its **own** bucket, not the action bucket (`_check_rate`); reads are not limited
  by either bucket; cancel is never rate-limited (stopping a turn must never be blocked).
- At most one open turn per session; at most a small fixed number of live agent processes per host
  (value set in the B1.5c order); a request beyond it answers `503 agent_capacity`.
- One host per data home for dialogue writes (D7, F4/U-B3 above).

### D9 — Transport of the transcript — CONDITIONAL on DEC-2

The transcript is served as an **unregistered** JSON route payload, following the existing
precedent of content-bearing unregistered payloads (`/api/run-freshness`, the packaging GET
routes), and every event carries its `origin` (`live`, `replay`, `out_of_turn`, or `history`).
**This paragraph is conditional on DEC-2.** If the operator's D-5 decision requires a registered
widget-contract type or a data class for dialogue prose, D9 is superseded before the B1.5c order
freezes and D-5 moves onto the first-runnable-dialogue path. OD-2 gates only B1.5e (slicing C1).

### D10 — Polling, not a push channel

The app reads new events with `GET /api/dialogue/session?after=<sequence>`. No SSE, WebSocket or
long-poll is added. Token-level streaming therefore reaches the screen at the poll interval.

## Consequences

### Positive
- A conversation is possible without widening the authority of any existing route: no route in
  this class can touch GitHub, labels, Runs, dispatch, packaging or work records, and a test proves
  it.
- Load, poll and render stay effect-free, preserving ADR-038's strongest rule.
- One listener, one token, one origin: the review of ADR-038's boundary is extended, not duplicated.
- Every failure mode the first runnable dialogue can hit has a named, non-empty answer — including
  the second-writer and unreadable-log cases the review carry-forwards (F1, F4).
- DEC-8(a) is honoured exactly: no invented error for a wire-undetectable condition; the evidence
  is exposed instead.

### Negative
- Poll latency: streamed tokens appear in poll-sized steps.
- Without an allow path the agent cannot perform any effect that asks for permission; tasks that
  need one fail visibly. That is intended for this class, and it limits what a dialogue can do.
- Prompt and reply text is stored under the data home, in the session log format, with no
  retention rule yet.
- A second route class makes the host's route table longer and its guard order must be kept in
  parity for two classes.

### Risks
- **Agent-side effects the client never sees.** Deny-by-default covers only requests the agent
  sends. Tools that do not ask, and agent-side auto-approve policies (hermes `edit_approval`
  `auto_approve_getter`), run inside the agent. The empty working directory limits the blast radius
  of relative-path effects; it is **not** a sandbox. Which `hermes acp` tools run without asking was
  not established when this ADR was drafted.
- **Model calls cost money and send prose off-machine** through the agent's own provider
  configuration, which Cortxt does not control. The operator's route choice in Hermes applies.
- **The session token is not authentication against local software**; it prevents cross-origin
  pages from acting, as ADR-038's boundary already assumes.
- **Replay misclassification** if an agent version replays after answering `session/load`:
  replayed updates would render `out_of_turn`, visibly, not as live. The classification rule lives
  in B1.5a and is pinned by tests against a fake agent only.

## Alternatives Considered

1. **Each turn as an authorized action** (approval reference + `confirm`, through
   `/api/action`) — rejected: honest about effects, unusable for conversation, and it would route
   turns through the executor that D3 keeps them away from.
2. **A separate dialogue listener on its own port** — rejected: a second boundary to review, a
   second token, a second origin for the app to reach, and a new port on a machine where several
   ports are deliberately left alone.
3. **Mount on `serve.py`** — rejected by ADR-038.
4. **SSE or WebSocket streaming** — deferred, not rejected: `ThreadingHTTPServer` holds one thread
   per open stream and the host has no streaming precedent. Review trigger below.
5. **A permission-answer route with allow** — rejected for this class: allowing agent effects is a
   mandate decision, not a transport one.
6. **Connect-on-open (GET reopens and reloads the agent)** — rejected: an effect triggered by
   render, which ADR-038 forbids.
7. **Registering the transcript as a widget-contract type now** — not chosen: it requires a data
   class for prose that does not exist (DEC-2). Kept as the path D9 falls back to.
8. **`409 agent_session_not_found` on unknown ACP id** (the rev1 draft's D7 row) — removed in
   rev2: it contradicts the accepted DEC-8(a) (CHECKPOINT entries 13, 17). With SDK 0.9.0 the
   condition is undetectable on the wire; an error invented for it would fire on legitimate
   "started fresh" loads and hide the zero-replay evidence. The falsifier remains: an SDK upgrade
   that makes unknown ids wire-detectable re-opens this row.

## Validation

Each item names the mutation it catches. All are B1.5c/B1.5d order material; the frozen test map
lives in `b15c-order.md` (§TESTS, §ACCEPTANCE MAP) and `b15d-order.md`.

- [ ] Route-table test: the set of `/api/dialogue/*` paths equals D2's six, per method —
      *catches an added route (e.g. a permission-allow route) slipping in.*
- [ ] Token test: every D2 route, GET included, answers `403` without `X-Cortxt-Token` —
      *catches an unguarded transcript read.*
- [ ] No-reach test: a full create → connect → turn → cancel flow against a fake agent with the
      action executor, GitHub ports, CLI ports and the run registry replaced by sentinels that fail
      on any call — zero calls; plus an AST import check on `widget/dialogue_service.py` —
      *catches a code path from a dialogue route to any D3 target.*
- [ ] Effect-free reads: GET routes called repeatedly with no agent configured and no session
      connected start zero processes (spawn function replaced by a sentinel) and append zero
      events — *catches connect-on-render.*
- [ ] Deny test: a fake agent's permission request is answered with its reject option and appears
      as a denied event in the session read — *catches an allow path.*
- [ ] Unavailable table: each D7 row produces its status and kind, and none produces `200` —
      *catches 200-with-empty.*
- [ ] DEC-8(a) test: a session bound to a made-up ACP id connects without error, `mode == "load"`,
      `zero_replay` true, `replayed_update_count == 0`, and the persisted loaded event carries it —
      *catches an invented not-found error and a lost zero-replay evidence chain.*
- [ ] Unreadable test (F1): a corrupt session log makes the list answer `partial` with the entry
      and kind in `unreadable`, and a targeted request answers `409 session_unreadable` —
      *catches dropped or 500-ing unreadable sessions.*
- [ ] Second-writer test (F4/U-B3): a second host on the same data home answers every dialogue
      POST `409 dialogue_writer_busy` while its reads keep working — *catches a silent second
      writer.*
- [ ] Cursor/origin tests (F2a, N2): reads carry the store `origin` verbatim; polling
      `after=cursor.next` returns each store `sequence` exactly once; a planted gap in `wire_seq`
      does not move the cursor — *catches a wire_seq cursor and an origin flag dying at the
      transport.*
- [ ] Working-directory test: the fake agent reports its `cwd`; it equals the per-session empty
      directory under the data home and is not inside the repository — *catches running the agent
      in a checkout.*
- [ ] Environment test: a variable planted in the host environment is absent in the fake agent
      unless configured — *catches passing the full environment.*
- [ ] Bucket test: dialogue sends do not consume the action bucket; action requests do not block
      dialogue sends — *catches a shared limiter.*
- [ ] Operator live acceptance (FR, DEC-6c) through the browser against real `hermes acp`, with a
      session-bound sentinel.

## Expiry/Review Trigger

- Review when any of: DEC-2 is recorded (D9); an allow path for agent permissions is proposed (D5);
  a push channel is proposed (D10); Cortxt takes the ACP agent role (ADR-047 D1); a dialogue must
  bind to a work record (B1.5e); a remote ACP transport is proposed; an ACP SDK change makes an
  unknown session id wire-detectable (D7, DEC-8(a) row).
