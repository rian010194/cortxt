"""A fake ACP agent for the AcpAdapter tests (B1.5a).

Not named test_*: pytest never collects it. It is spawned as
`sys.executable acp_fake_agent.py <state_dir> [options]` and speaks ACP over
stdio through the SDK's own agent side (acp.run_agent). It makes no network
call and no model call.

Behaviour by prompt text:
  default         stream 3 agent_message_chunk updates (the first echoes the
                  sessionId the agent holds), then end_turn
  ASK-PERMISSION  request permission with [allow_once, deny(reject_once)],
                  stream one chunk echoing the selected optionId (or
                  "cancelled"), then end_turn
  EXIT-MIDTURN    stream one chunk, then os._exit(3)
  WAIT-CANCEL     stream one chunk, wait for session/cancel, stop "cancelled"
  ECHO-CAPS       stream one chunk with the JSON of the client capabilities
                  received at initialize, then end_turn
  ECHO-ENV        stream one chunk with the JSON list of this process's
                  environment variable names, then end_turn
  ECHO-CWD        stream one chunk with the JSON of this process's working
                  directory and its entry count ({"cwd": ..., "entries": ...}),
                  then end_turn

session/load of a known id sends --replay N updates before responding, then
one available_commands_update after responding (mirrors hermes-agent
acp_adapter/server.py); an unknown id is answered like hermes answers it
(the handler returns None, which the SDK's agent side normalizes to the empty
result object {} on the wire) with no replay updates. Known ids live
in a JSON file under <state_dir>, so they survive into a second process.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import acp
from acp.schema import (
    AgentCapabilities,
    AllowedOutcome,
    AvailableCommand,
    AvailableCommandsUpdate,
    Implementation,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PermissionOption,
    PromptResponse,
    ToolCallUpdate,
)


class FakeAgent:
    def __init__(self, state_dir: Path, replay_count: int, replay_line_bytes: int) -> None:
        self._state_file = state_dir / "sessions.json"
        self._replay_count = replay_count
        self._replay_line_bytes = replay_line_bytes
        self._client_capabilities: dict = {}
        self._cancelled: dict[str, asyncio.Event] = {}
        self._conn = None

    def on_connect(self, conn) -> None:
        self._conn = conn

    def _known(self) -> list[str]:
        if not self._state_file.exists():
            return []
        return json.loads(self._state_file.read_text(encoding="utf-8"))

    async def _chunk(self, session_id: str, text: str) -> None:
        await self._conn.session_update(session_id, acp.update_agent_message_text(text))

    async def initialize(self, protocol_version, client_capabilities=None, client_info=None, **kwargs):
        if client_capabilities is not None:
            self._client_capabilities = client_capabilities.model_dump(mode="json", by_alias=True, exclude_none=True)
        return InitializeResponse(
            protocol_version=acp.PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(load_session=True),
            agent_info=Implementation(name="acp-fake-agent", version="0.0.1"),
        )

    async def new_session(self, cwd, mcp_servers=None, **kwargs):
        session_id = str(uuid.uuid4())
        self._state_file.write_text(json.dumps(self._known() + [session_id]), encoding="utf-8")
        return NewSessionResponse(session_id=session_id)

    async def load_session(self, cwd, session_id, mcp_servers=None, **kwargs):
        if session_id not in self._known():
            # hermes returns None here; SDK 0.9.0 sends it as {}.
            return None
        for i in range(self._replay_count):
            text = f"replay {i}"
            if self._replay_line_bytes:
                text = text + " " + "x" * self._replay_line_bytes
            await self._chunk(session_id, text)

        async def after_response() -> None:
            await asyncio.sleep(0)
            await self._conn.session_update(
                session_id,
                AvailableCommandsUpdate(
                    session_update="available_commands_update",
                    available_commands=[AvailableCommand(name="help", description="fake")],
                ),
            )

        asyncio.get_running_loop().create_task(after_response())
        return LoadSessionResponse()

    async def cancel(self, session_id, **kwargs):
        self._cancelled.setdefault(session_id, asyncio.Event()).set()

    async def prompt(self, prompt, session_id, message_id=None, **kwargs):
        text = "".join(getattr(block, "text", "") for block in prompt).strip()

        if text == "ASK-PERMISSION":
            response = await self._conn.request_permission(
                options=[
                    PermissionOption(option_id="allow_once", name="Allow once", kind="allow_once"),
                    PermissionOption(option_id="deny", name="Deny", kind="reject_once"),
                ],
                session_id=session_id,
                tool_call=ToolCallUpdate(tool_call_id="call-1", title="write a file"),
            )
            outcome = response.outcome
            chosen = outcome.option_id if isinstance(outcome, AllowedOutcome) else "cancelled"
            await self._chunk(session_id, chosen)
            return PromptResponse(stop_reason="end_turn")

        if text == "EXIT-MIDTURN":
            await self._chunk(session_id, "about to exit")
            os._exit(3)

        if text == "WAIT-CANCEL":
            event = self._cancelled.setdefault(session_id, asyncio.Event())
            await self._chunk(session_id, "waiting for cancel")
            await event.wait()
            return PromptResponse(stop_reason="cancelled")

        if text == "ECHO-CAPS":
            await self._chunk(session_id, json.dumps(self._client_capabilities, sort_keys=True))
            return PromptResponse(stop_reason="end_turn")

        if text == "ECHO-ENV":
            await self._chunk(session_id, json.dumps(sorted(os.environ)))
            return PromptResponse(stop_reason="end_turn")

        if text == "ECHO-CWD":
            await self._chunk(session_id, json.dumps(
                {"cwd": os.getcwd(), "entries": len(os.listdir(os.getcwd()))}))
            return PromptResponse(stop_reason="end_turn")

        await self._chunk(session_id, f"session {session_id}")
        await self._chunk(session_id, "second chunk")
        await self._chunk(session_id, "third chunk")
        return PromptResponse(stop_reason="end_turn")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("state_dir", type=Path)
    parser.add_argument("--replay", type=int, default=50)
    parser.add_argument("--replay-line-bytes", type=int, default=0)
    parser.add_argument("--stderr-bytes", type=int, default=0)
    args = parser.parse_args()

    if args.stderr_bytes:
        # Written before anything is answered: a parent that pipes stderr
        # without draining it blocks this write and never sees initialize.
        chunk = b"e" * 65536
        remaining = args.stderr_bytes
        while remaining > 0:
            n = min(remaining, len(chunk))
            sys.stderr.buffer.write(chunk[:n])
            remaining -= n
        sys.stderr.buffer.flush()

    args.state_dir.mkdir(parents=True, exist_ok=True)
    agent = FakeAgent(args.state_dir, args.replay, args.replay_line_bytes)
    asyncio.run(acp.run_agent(agent))


if __name__ == "__main__":
    main()
