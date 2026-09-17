"""Wire-order classification of inbound ACP messages (B1.5a).

Every message an ACP agent sends is turned into a plain, JSON-serializable
event dict that is already classified as `live`, `replay` or `out_of_turn`
before anything downstream sees it (ADR-049 D3: a surface consuming session
updates must be able to tell replayed history from live updates).

The classification depends only on *wire order* and on which outgoing
request is outstanding -- never on a clock, and never on the order in which
the SDK happens to run its per-notification callback tasks. The caller feeds
this class from the SDK's synchronous stream observer, which sees incoming
messages in receive order before they are dispatched.

`session/load` replays the prior conversation as ordinary notifications and
then responds; the response closes the replay window at that exact wire
position. Anything the agent sends for that session after the response
(hermes schedules available-commands/usage updates there) is `out_of_turn`,
not replay and not live.

Identity: the ACP sessionId is issued by the agent (ADR-049 D1) and is
copied from the wire as an opaque string. `turn_id` is supplied by the
caller. This module issues no identity of its own.

Stdlib only by design: no SDK, no store, no widget contract.

Event shape (consumed as plain data by later units):

    wire_seq        int, strictly increasing per connection, receive order
    origin          "live" | "replay" | "out_of_turn"
    kind            one of EVENT_KINDS
    acp_session_id  str | None, opaque, copied from the wire
    turn_id         str | None, as supplied to begin_prompt
    update_type     str | None, raw params.update.sessionUpdate
    payload         dict: the raw notification/request params; for a
                    response, {"result": ...} or {"error": ...} keyed as on
                    the wire, so a null result stays distinguishable from {}
    decision        "denied" | None, set on permission_request only
    stop_reason     str | None, set on turn_end only
"""
from __future__ import annotations

import copy

ORIGIN_LIVE = "live"
ORIGIN_REPLAY = "replay"
ORIGIN_OUT_OF_TURN = "out_of_turn"

KIND_SESSION_UPDATE = "session_update"
KIND_PERMISSION_REQUEST = "permission_request"
KIND_TURN_END = "turn_end"
KIND_TURN_FAILED = "turn_failed"
KIND_LOAD_COMPLETE = "load_complete"
KIND_PROTOCOL_ERROR = "protocol_error"

EVENT_KINDS = (
    KIND_SESSION_UPDATE,
    KIND_PERMISSION_REQUEST,
    KIND_TURN_END,
    KIND_TURN_FAILED,
    KIND_LOAD_COMPLETE,
    KIND_PROTOCOL_ERROR,
)

DECISION_DENIED = "denied"

_METHOD_SESSION_UPDATE = "session/update"
_METHOD_REQUEST_PERMISSION = "session/request_permission"

_LOAD = "load"
_PROMPT = "prompt"


class ConcurrentRequestRefused(RuntimeError):
    """Raised when a second outgoing request is begun while one is outstanding.

    At most one outgoing request may be outstanding per connection; otherwise
    a response could not be attributed to a load or a prompt by wire position
    alone. `session/cancel` is a notification and is not affected.
    """


class WireClassifier:
    def __init__(self) -> None:
        self._next_seq = 0
        self._outstanding: str | None = None
        self._session_id: str | None = None
        self._turn_id: str | None = None

    # -- outgoing side: called before the request is sent -----------------

    def begin_load(self, acp_session_id: str) -> None:
        self._begin(_LOAD, acp_session_id, None)

    def begin_prompt(self, acp_session_id: str, turn_id: str | None) -> None:
        self._begin(_PROMPT, acp_session_id, turn_id)

    def _begin(self, which: str, acp_session_id: str, turn_id: str | None) -> None:
        if self._outstanding is not None:
            raise ConcurrentRequestRefused(
                f"cannot begin {which}: a {self._outstanding} request is still outstanding"
            )
        self._outstanding = which
        self._session_id = acp_session_id
        self._turn_id = turn_id

    def _close_window(self) -> None:
        self._outstanding = None
        self._session_id = None
        self._turn_id = None

    # -- incoming side: called synchronously, in receive order -------------

    def observe_incoming(self, message: dict) -> dict | None:
        seq = self._take_seq()
        method = message.get("method")
        has_id = "id" in message

        if method is None:
            if not has_id:
                return self._event(seq, ORIGIN_OUT_OF_TURN, KIND_PROTOCOL_ERROR, None, None,
                                   {"reason": "unrecognised_message", "message": message})
            return self._on_response(seq, message)

        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        session_id = params.get("sessionId")
        session_id = session_id if isinstance(session_id, str) else None

        if method == _METHOD_SESSION_UPDATE and not has_id:
            update = params.get("update")
            update_type = update.get("sessionUpdate") if isinstance(update, dict) else None
            if self._outstanding == _LOAD and session_id is not None and session_id == self._session_id:
                origin, turn_id = ORIGIN_REPLAY, None
            elif self._outstanding == _PROMPT and session_id is not None and session_id == self._session_id:
                origin, turn_id = ORIGIN_LIVE, self._turn_id
            else:
                origin, turn_id = ORIGIN_OUT_OF_TURN, None
            return self._event(seq, origin, KIND_SESSION_UPDATE, session_id, turn_id, params,
                               update_type=update_type)

        if method == _METHOD_REQUEST_PERMISSION and has_id:
            if self._outstanding == _PROMPT and session_id is not None and session_id == self._session_id:
                origin, turn_id = ORIGIN_LIVE, self._turn_id
            else:
                origin, turn_id = ORIGIN_OUT_OF_TURN, None
            return self._event(seq, origin, KIND_PERMISSION_REQUEST, session_id, turn_id, params,
                               decision=DECISION_DENIED)

        return self._event(seq, ORIGIN_OUT_OF_TURN, KIND_PROTOCOL_ERROR, session_id, None,
                           {"reason": "unsupported_method", "method": method, "params": params})

    def _on_response(self, seq: int, message: dict) -> dict | None:
        if "error" in message:
            payload = {"error": message.get("error")}
        else:
            payload = {"result": message.get("result")}

        if self._outstanding == _LOAD:
            event = self._event(seq, ORIGIN_OUT_OF_TURN, KIND_LOAD_COMPLETE, self._session_id, None, payload)
            self._close_window()
            return event

        if self._outstanding == _PROMPT:
            if "error" in message:
                event = self._event(seq, ORIGIN_LIVE, KIND_TURN_FAILED, self._session_id, self._turn_id, payload)
            else:
                result = message.get("result")
                stop_reason = result.get("stopReason") if isinstance(result, dict) else None
                event = self._event(seq, ORIGIN_LIVE, KIND_TURN_END, self._session_id, self._turn_id, payload,
                                    stop_reason=stop_reason)
            self._close_window()
            return event

        # A response to a request this classifier does not bracket
        # (initialize, session/new): not a session event.
        return None

    def connection_lost(self) -> dict | None:
        """The transport ended. Never reports a completed turn."""
        if self._outstanding == _PROMPT:
            event = self._event(self._take_seq(), ORIGIN_LIVE, KIND_TURN_FAILED, self._session_id,
                                self._turn_id, {"reason": "connection_lost"})
        elif self._outstanding == _LOAD:
            event = self._event(self._take_seq(), ORIGIN_OUT_OF_TURN, KIND_PROTOCOL_ERROR, self._session_id,
                                None, {"reason": "connection_lost_during_load"})
        else:
            return None
        self._close_window()
        return event

    def local_protocol_error(self, reason: str, detail: dict | None = None) -> dict:
        """A client-side failure placed at the current wire position.

        Used when the event pipeline itself fails (the classifier or the sink
        raised), so the failure is recorded in the same sequence as the wire
        events instead of disappearing into a log.
        """
        payload = {"reason": reason}
        if detail:
            payload.update(detail)
        return self._event(self._take_seq(), ORIGIN_OUT_OF_TURN, KIND_PROTOCOL_ERROR, None, None, payload)

    # -- helpers -----------------------------------------------------------

    def _take_seq(self) -> int:
        seq = self._next_seq
        self._next_seq += 1
        return seq

    @staticmethod
    def _event(seq, origin, kind, acp_session_id, turn_id, payload, *,
               update_type=None, decision=None, stop_reason=None) -> dict:
        return {
            "wire_seq": seq,
            "origin": origin,
            "kind": kind,
            "acp_session_id": acp_session_id,
            "turn_id": turn_id,
            "update_type": update_type,
            "payload": copy.deepcopy(payload),
            "decision": decision,
            "stop_reason": stop_reason,
        }
