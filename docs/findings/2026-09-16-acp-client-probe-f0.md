# Finding — F0 ACP client probe: transport, streaming, elicitation and resume on Windows

**Document type:** register. It records what was observed, once. Never edited; superseded by a
new file if wrong.

**Date:** 2026-09-16.
**Scope:** F0 of the dialogue-to-result series
(`docs/plans/2026-09-16-dialogue-to-result-series-handoff.md`).
**Mandate:** probe only. Throwaway code in a scratchpad outside every package tree. No product
code, no `AcpAdapter`, no ADR edit, no remote transport, no paid route, no repository touched.

---

## Why this probe existed

ADR-047 adopted the Agent Client Protocol as a client (D1) and specified an additive `on_event`
plus a `supports_events` capability (D3). It is **Accepted and entirely unimplemented**: at
`f6dba33` there is no `AcpAdapter`, and `agent-platform/runtime/engine_adapter.py:17` carries no
`on_event` or `supports_events`.

The series plan therefore put a probe first. Its largest open question was whether **any**
ACP-speaking agent could be run locally on Windows at all: a scan of all five Cortxt repositories
(`cortxt`, `cortxt-agents`, `cortxt-resilient-inference`, `cortxt-vault`,
`cortxt-state-portability`) returned **zero** matches for `agentclientprotocol`, `acp_`,
`jsonrpc` or `json-rpc`.

That question resolved before the probe ran: **Hermes itself ships an ACP agent mode.**

---

## Environment (verified, not assumed)

| Component | Value |
|---|---|
| Agent under test | `hermes acp` — *"Start Hermes Agent in ACP mode for editor integration"* |
| Hermes ACP version | `0.18.2` (`hermes acp --version`) |
| Dependency self-check | `hermes acp --check` → `Hermes ACP check OK` |
| Client SDK | `agent-client-protocol` **0.9.0** |
| SDK requires | `Requires-Python <3.15,>=3.10`; `Requires-Dist: pydantic>=2.7` |
| Python | 3.11.15, Windows |
| Negotiated protocol version | `1` |
| Route | default Hermes profile (free); four real model turns |
| Cost | unknown (not measured). Never 0 |

`cortxt-agent-platform` declares `requires-python >=3.11`, so the SDK's floor is satisfied.

---

## Results

| # | Question | Outcome |
|---|---|---|
| 1 | Installability on Windows | **PASS** |
| 2 | Transport: subprocess JSON-RPC over stdio, `session/new` + one prompt turn | **PASS** |
| 3a | Streaming session updates | **PASS** |
| 3b | Elicitation — structured question back to the operator | **PASS** |
| 4 | Session resume | **PASS, across a process restart** |
| 4b | Who issues the ACP `sessionId` | **The agent** |

### Q2 — transport

`spawn_agent_process` → `initialize` → `new_session` → `prompt` completed with
`stop_reason: end_turn`; turn duration 5.89 s; agent process exited with return code 0.

Agent capabilities reported at initialize:

```
load_session=True
prompt_capabilities: audio=False, embedded_context=False, image=True
mcp_capabilities: http=False, sse=False
session_capabilities: close, fork, list, resume
```

### Q3a — streaming

Updates arrive incrementally at token granularity, before the turn completes. Excerpt from the
recorded timeline (seconds from probe start):

```
15.44  AgentMessageChunk    I
15.44  AgentMessageChunk     attempted to write the file,
15.45  AgentMessageChunk     but the edit
15.49  AgentMessageChunk     was denied by the approval client
15.50  AgentMessageChunk    ,
```

Other update types observed: `AvailableCommandsUpdate`, `UsageUpdate`, `SessionInfoUpdate`,
`UserMessageChunk`, `ToolCallStart`, `ToolCallProgress`.

### Q3b — elicitation, and it fails closed

The probe asked the agent to write a file using its own tool. The agent did not proceed on its
own: `request_permission` reached the client.

```
14.44  ToolCallStart         write: probe_effect.txt
14.44  REQUEST_PERMISSION    "Approve edit: probe_effect.txt"  options=['allow_once', 'deny']
```

The probe answered `deny`. **The effect did not occur** — `probe_effect.txt` was not created
(checked on disk afterwards), and the agent reported the refusal honestly:

> "I attempted to write the file, but the edit was denied by the approval client, so the file was
> not created."

This is the missing half of field designation **F-6** (workers stall on interactive input,
undetected), demonstrated working and refusing in the safe direction.

### Q4 — resume across a process restart

Same-process resume passed in round 1. Round 2 tested the product requirement — *close Cortxt,
open it again*:

1. Process A (pid 19968) created session `d0298f9d-45cc-4a7e-aaba-beffdd5d6eda` and was told a
   codeword. Process A exited, return code 0.
2. Process B (pid 19448), a new process, called `load_session` with the same session id.
3. Asked to recall the codeword, process B answered it verbatim. `recall_ok: True`.

### Q4b — the `sessionId` issuer

`acp.NewSessionRequest` has fields `field_meta`, `cwd`, `mcp_servers` — **no session id**.
`acp.NewSessionResponse` carries `session_id`. Confirmed in both probe runs: the id is produced
by the agent in response to `session/new`.

---

## New finding not anticipated by ADR-047

**`load_session` replays the prior conversation as session updates.**

On resume, process B received the whole earlier exchange re-emitted as notifications —
`UserMessageChunk`, `AgentMessageChunk`, and even `ToolCallStart` — all at one timestamp, before
the new turn began:

```
27.38  B:UserMessageChunk    Remember this exactly: the codeword is ...
27.38  B:AgentMessageChunk   OK.
27.38  B:UserMessageChunk    Use your file-writing tool to create a file named probe_effect.txt ...
27.38  B:ToolCallStart       write: probe_effect.txt
27.38  B:ToolCallProgress
27.38  B:AgentMessageChunk   I attempted to write the file, but the edit was denied ...
29.53  B:AgentMessageChunk   OR
29.53  B:AgentMessageChunk   RESTAD
29.58  B:AgentMessageChunk   -41
```

**Consequence for the product:** the dialogue surface must distinguish replayed history from live
updates. Without that, resuming a conversation looks like the agent answering everything again.
This is a design requirement on the dialogue surface that ADR-047 does not state.

---

## Open decision this probe does not make

**ADR-047 §D4 is wrong as written.** It states:

> The ACP `sessionId` is **owned by Cortxt**, created via `session/new`.

`docs/561-acp-decision-packet.md` records the opposite under Criterion 4:

> sessionId issuer — CORRECTED in D4 (agent issues the ACP sessionId in response to `session/new`)

The observed behaviour matches the decision packet, not the ADR text.

**This register states the evidence and decides nothing.** An accepted ADR is not edited to
remove a contradiction; a new decision supersedes it. The correction is the operator's, and it
must be settled **before an `AcpAdapter` is built** — the session-resume design depends on which
side owns the identifier.

---

## Not tested, deliberately

- **Remote HTTP/WebSocket transport.** The decision packet marks it *"QUALIFIED (draft; do not
  implement now)"*. Local stdio is what a local web app needs.
- **Cortxt as an ACP agent.** ADR-047 D1 defers the agent role; it is not rejected.
- **Cancellation.** `CancelNotification` exists in the SDK surface but was not exercised.
- **Any adapter registration, `route()` or `engine_manifest.py` interaction.** Out of scope by
  the probe's own mandate.

---

## Recommendation

**ACP holds, with conditions.**

1. **`pydantic>=2.7` becomes a new platform dependency.** `cortxt-agent-platform` currently
   declares `pyyaml`, `jsonschema`, `cryptography` and `cortxt-resilient-inference`. This is a
   real addition and should be decided explicitly, not absorbed silently.
2. **The dialogue surface must separate replayed history from live updates** (see the new
   finding above).
3. **The ADR-047 D4 contradiction must be resolved before the adapter is built.**
4. Remote transport and the agent role stay out of scope.

**Effect on the plan:** B1.5 is unblocked and builds on ACP. The fallback path — extending
`on_event` over an existing adapter with `cortxt-resilient-inference` as the engine — is not
needed. ADR-047 D3 becomes concrete: `on_event` carries `SessionNotification`, and
`supports_events` separates the ACP adapter from the five existing adapters, which declare it
false and must error rather than silently ignore an `on_event` caller.

Probe code was throwaway and was not retained.
