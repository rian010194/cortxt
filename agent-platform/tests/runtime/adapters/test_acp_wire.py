"""Pure tests for the ACP wire classifier (B1.5a). No subprocess, no SDK."""
from __future__ import annotations

import datetime
import json
import time

import pytest

from runtime.adapters.acp_wire import (
    ORIGIN_LIVE,
    ORIGIN_OUT_OF_TURN,
    ORIGIN_REPLAY,
    ConcurrentRequestRefused,
    WireClassifier,
)

SID = "agent-issued-1"
OTHER = "agent-issued-2"


def _update(session_id=SID, text="hi", kind="agent_message_chunk"):
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": kind, "content": {"type": "text", "text": text}},
        },
    }


def _response(result, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error_response(rid=1):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": "boom"}}


def _permission(session_id=SID, rid=7):
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "method": "session/request_permission",
        "params": {
            "sessionId": session_id,
            "toolCall": {"toolCallId": "t1"},
            "options": [
                {"optionId": "allow_once", "name": "Allow", "kind": "allow_once"},
                {"optionId": "deny", "name": "Deny", "kind": "reject_once"},
            ],
        },
    }


def test_updates_during_load_are_replay_and_during_prompt_are_live():
    c = WireClassifier()
    c.begin_load(SID)
    replay = [c.observe_incoming(_update()) for _ in range(3)]
    assert [e["origin"] for e in replay] == [ORIGIN_REPLAY] * 3
    c.observe_incoming(_response({}))

    c.begin_prompt(SID, "turn-a")
    live = [c.observe_incoming(_update()) for _ in range(3)]
    assert [e["origin"] for e in live] == [ORIGIN_LIVE] * 3
    assert all(e["kind"] == "session_update" for e in live)
    assert all(e["turn_id"] == "turn-a" for e in live)
    assert all(e["update_type"] == "agent_message_chunk" for e in live)
    assert all(e["acp_session_id"] == SID for e in live + replay)
    assert all(e["turn_id"] is None for e in replay)


def test_load_window_closes_at_the_response_wire_position():
    c = WireClassifier()
    c.begin_load(SID)
    events = [
        c.observe_incoming(_update()),
        c.observe_incoming(_update()),
        c.observe_incoming(_response({})),
        c.observe_incoming(_update(kind="available_commands_update")),
    ]
    assert [(e["origin"], e["kind"]) for e in events] == [
        (ORIGIN_REPLAY, "session_update"),
        (ORIGIN_REPLAY, "session_update"),
        (ORIGIN_OUT_OF_TURN, "load_complete"),
        (ORIGIN_OUT_OF_TURN, "session_update"),
    ]
    assert events[2]["acp_session_id"] == SID
    assert events[2]["payload"] == {"result": {}}


def test_null_load_result_is_preserved_in_the_payload():
    c = WireClassifier()
    c.begin_load(SID)
    event = c.observe_incoming(_response(None))
    assert event["kind"] == "load_complete"
    assert event["payload"] == {"result": None}


def test_update_for_another_session_during_prompt_is_out_of_turn():
    c = WireClassifier()
    c.begin_prompt(SID, None)
    assert c.observe_incoming(_update(session_id=OTHER))["origin"] == ORIGIN_OUT_OF_TURN
    assert c.observe_incoming(_update(session_id=SID))["origin"] == ORIGIN_LIVE


def test_update_for_another_session_during_load_is_out_of_turn():
    c = WireClassifier()
    c.begin_load(SID)
    assert c.observe_incoming(_update(session_id=OTHER))["origin"] == ORIGIN_OUT_OF_TURN


def test_update_with_nothing_outstanding_is_out_of_turn():
    c = WireClassifier()
    assert c.observe_incoming(_update())["origin"] == ORIGIN_OUT_OF_TURN


def test_begin_prompt_while_load_outstanding_is_refused():
    c = WireClassifier()
    c.begin_load(SID)
    with pytest.raises(ConcurrentRequestRefused):
        c.begin_prompt(SID, None)


@pytest.mark.parametrize("first,second", [("load", "load"), ("prompt", "prompt"), ("prompt", "load")])
def test_any_overlapping_outgoing_request_is_refused(first, second):
    c = WireClassifier()
    getattr(c, f"begin_{first}")(*([SID] if first == "load" else [SID, None]))
    with pytest.raises(ConcurrentRequestRefused):
        getattr(c, f"begin_{second}")(*([SID] if second == "load" else [SID, None]))


def test_a_new_request_may_begin_after_the_response():
    c = WireClassifier()
    c.begin_load(SID)
    c.observe_incoming(_response({}))
    c.begin_prompt(SID, None)
    c.observe_incoming(_response({"stopReason": "end_turn"}))
    c.begin_load(SID)


def test_wire_seq_strictly_increases_across_1000_mixed_messages():
    c = WireClassifier()
    seqs = []
    for i in range(1000):
        step = i % 10
        if step == 0:
            c.begin_load(SID) if i % 20 == 0 else c.begin_prompt(SID, f"t{i}")
            message = _update()
        elif step == 3:
            message = _permission()
        elif step == 5:
            message = _update(session_id=OTHER)
        elif step == 7:
            message = {"jsonrpc": "2.0", "id": i, "method": "fs/read_text_file", "params": {"sessionId": SID}}
        elif step == 9:
            message = _response({"stopReason": "end_turn"})
        else:
            message = _update()
        event = c.observe_incoming(message)
        assert event is not None
        seqs.append(event["wire_seq"])
    assert len(seqs) == 1000
    assert all(b > a for a, b in zip(seqs, seqs[1:]))
    assert seqs[0] >= 0


def test_classification_reads_no_clock(monkeypatch):
    def script():
        c = WireClassifier()
        out = []
        c.begin_load(SID)
        out.append(c.observe_incoming(_update()))
        out.append(c.observe_incoming(_response({})))
        out.append(c.observe_incoming(_update()))
        c.begin_prompt(SID, "t")
        out.append(c.observe_incoming(_update()))
        out.append(c.observe_incoming(_permission()))
        out.append(c.observe_incoming(_response({"stopReason": "end_turn"})))
        c.begin_prompt(SID, "u")
        out.append(c.connection_lost())
        return out

    expected = script()

    def boom(*_a, **_k):
        raise AssertionError("classifier read a clock")

    class _NoDatetime:
        def __getattr__(self, name):
            raise AssertionError("classifier read datetime")

        now = utcnow = today = staticmethod(boom)

    monkeypatch.setattr(time, "time", boom)
    monkeypatch.setattr(time, "monotonic", boom)
    monkeypatch.setattr(time, "perf_counter", boom)
    monkeypatch.setattr(datetime, "datetime", _NoDatetime())
    assert script() == expected


def test_permission_request_is_denied_live_during_prompt_and_denied_out_of_turn_otherwise():
    c = WireClassifier()
    c.begin_prompt(SID, "t")
    during = c.observe_incoming(_permission())
    assert during["kind"] == "permission_request"
    assert during["origin"] == ORIGIN_LIVE
    assert during["decision"] == "denied"
    assert during["turn_id"] == "t"
    c.observe_incoming(_response({"stopReason": "end_turn"}))

    outside = c.observe_incoming(_permission())
    assert outside["kind"] == "permission_request"
    assert outside["origin"] == ORIGIN_OUT_OF_TURN
    assert outside["decision"] == "denied"

    c.begin_prompt(SID, "t2")
    other_session = c.observe_incoming(_permission(session_id=OTHER))
    assert other_session["origin"] == ORIGIN_OUT_OF_TURN
    assert other_session["decision"] == "denied"


def test_decision_is_only_set_on_permission_requests():
    c = WireClassifier()
    c.begin_prompt(SID, None)
    assert c.observe_incoming(_update())["decision"] is None
    assert c.observe_incoming(_response({"stopReason": "end_turn"}))["decision"] is None


def test_connection_lost_during_prompt_is_turn_failed_never_turn_end():
    c = WireClassifier()
    c.begin_prompt(SID, "t")
    c.observe_incoming(_update())
    event = c.connection_lost()
    assert event["kind"] == "turn_failed"
    assert event["kind"] != "turn_end"
    assert event["payload"] == {"reason": "connection_lost"}
    assert event["stop_reason"] is None
    assert event["turn_id"] == "t"
    # the window is closed: nothing further outstanding
    assert c.connection_lost() is None


def test_connection_lost_during_load_is_protocol_error():
    c = WireClassifier()
    c.begin_load(SID)
    event = c.connection_lost()
    assert event["kind"] == "protocol_error"
    assert event["payload"] == {"reason": "connection_lost_during_load"}


def test_connection_lost_with_nothing_outstanding_emits_nothing():
    assert WireClassifier().connection_lost() is None


def test_payload_is_deep_copied_from_the_wire():
    c = WireClassifier()
    c.begin_prompt(SID, None)
    message = _update(text="original")
    event = c.observe_incoming(message)
    snapshot = json.dumps(event, sort_keys=True)
    message["params"]["update"]["content"]["text"] = "mutated"
    message["params"]["sessionId"] = "mutated"
    assert json.dumps(event, sort_keys=True) == snapshot


def test_error_response_during_prompt_is_turn_failed():
    c = WireClassifier()
    c.begin_prompt(SID, "t")
    event = c.observe_incoming(_error_response())
    assert event["kind"] == "turn_failed"
    assert event["stop_reason"] is None
    assert event["payload"] == {"error": {"code": -32603, "message": "boom"}}


def test_turn_end_carries_stop_reason():
    c = WireClassifier()
    c.begin_prompt(SID, "t")
    event = c.observe_incoming(_response({"stopReason": "cancelled"}))
    assert event["kind"] == "turn_end"
    assert event["origin"] == ORIGIN_LIVE
    assert event["stop_reason"] == "cancelled"


def test_other_client_methods_are_out_of_turn_protocol_errors():
    c = WireClassifier()
    c.begin_prompt(SID, "t")
    for method in ("fs/read_text_file", "fs/write_text_file", "terminal/create", "_ext/thing"):
        event = c.observe_incoming({"jsonrpc": "2.0", "id": 3, "method": method, "params": {"sessionId": SID}})
        assert (event["origin"], event["kind"]) == (ORIGIN_OUT_OF_TURN, "protocol_error")
        assert event["payload"]["method"] == method


def test_responses_to_unbracketed_requests_emit_nothing():
    c = WireClassifier()
    assert c.observe_incoming(_response({"protocolVersion": 1})) is None


def test_events_are_json_serializable_and_have_the_frozen_keys():
    c = WireClassifier()
    c.begin_prompt(SID, "t")
    events = [c.observe_incoming(_update()), c.observe_incoming(_permission()),
              c.observe_incoming(_response({"stopReason": "end_turn"})), c.local_protocol_error("sink_failed")]
    for event in events:
        assert set(event) == {"wire_seq", "origin", "kind", "acp_session_id", "turn_id",
                              "update_type", "payload", "decision", "stop_reason"}
        json.dumps(event)
