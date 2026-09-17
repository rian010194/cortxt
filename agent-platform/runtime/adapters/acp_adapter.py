"""ACP client for one agent over stdio, driven from ordinary threads (B1.5a).

AcpConnection starts one ACP agent process and runs the SDK's asyncio
connection on one dedicated daemon thread. Callers use blocking methods --
start, new_session, load_session, prompt, cancel, close -- and receive every
inbound message as an event dict already classified live / replay /
out_of_turn by runtime.adapters.acp_wire, in wire order, through the
injected event_sink.

Decisions this module encodes (ADR-047 D1-D3 as amended by ADR-049):

* The ACP sessionId is issued by the agent in response to session/new and
  is held here as an opaque string. This module issues no identity: turn_id
  is supplied by the caller, and the one-shot path passes none.
* Classification happens in the SDK's synchronous stream observer, which
  sees incoming messages in receive order. Client.session_update is a no-op:
  the SDK runs each notification as its own task, so by the time that
  callback runs the bracketing response may already have resolved.
* If the classifier or the sink raises, the failure is recorded as a
  protocol_error event and the connection is closed. The SDK would otherwise
  log and swallow the observer exception and keep going with a gap in the
  event stream.
* Permission requests are always answered with a reject option (reject_once,
  else reject_always) or, when the agent offers none, with the cancelled
  outcome. No allow_once / allow_always option is ever selected; there is no
  policy hook in this unit.
* Sessions are reopened with session/load only. session/resume is never
  sent: hermes-agent silently creates a new session for an unknown id on
  resume, which would look like success. A null session/load result is
  AcpSessionNotFound. This is a defensive client contract: an SDK 0.9.0
  agent normalizes a None load result to {} before it reaches the wire, and
  the SDK client coerces a raw null into an empty response, so against such
  agents an unknown id answers like a known one without replay updates.
  Both the returned result and the raw wire result are checked.
* A lost connection is never a completed turn: turn_failed and
  AcpConnectionLost, never turn_end.
* The agent's stderr goes to a file or DEVNULL, never an undrained PIPE (the
  SDK default, which deadlocks a chatty agent). The environment is the SDK's
  trimmed allowlist plus the explicit `env` additions; os.environ is never
  passed whole.
* subprocess_windows.no_window_kwargs() cannot be applied: the SDK transport
  accepts no creationflags, so on Windows the agent may open a console
  window.

The agent-client-protocol SDK is imported only inside function bodies, so
this module imports cleanly where the optional dependency is absent; start()
raises AcpUnavailable there.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.metadata
import logging
import platform
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from runtime.adapters.acp_wire import (
    KIND_LOAD_COMPLETE,
    KIND_SESSION_UPDATE,
    KIND_TURN_END,
    KIND_TURN_FAILED,
    ORIGIN_LIVE,
    ConcurrentRequestRefused,
    WireClassifier,
)

_log = logging.getLogger(__name__)

_SDK_DISTRIBUTION = "agent-client-protocol"
_CANCEL_GRACE_SECONDS = 5.0
_SHUTDOWN_WAIT_SECONDS = 15.0
_EXIT_DRAIN_POLLS = 500
_EXIT_DRAIN_POLL_SECONDS = 0.01


class AcpUnavailable(RuntimeError):
    """The agent-client-protocol SDK is not installed."""


class AcpSessionNotFound(LookupError):
    """session/load answered null: the agent does not know this session."""


class AcpConnectionLost(RuntimeError):
    """The agent connection ended (or was closed) before the request completed."""


class AcpProtocolError(RuntimeError):
    """The agent answered in a way this client cannot interpret."""


def _import_sdk():
    try:
        import acp
    except ImportError as exc:
        raise AcpUnavailable(
            f"the ACP client needs the {_SDK_DISTRIBUTION} package; install the agent-platform "
            f"'acp' extra (pip install -e 'agent-platform[acp]')"
        ) from exc
    return acp


class _DenyingClient:
    """The client half the SDK calls back into. Answers deny, implements nothing else."""

    async def request_permission(self, options, session_id, tool_call, **kwargs):
        from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

        for wanted in ("reject_once", "reject_always"):
            for option in options:
                if option.kind == wanted:
                    # AllowedOutcome is the SDK's "selected an option" shape;
                    # the option selected here is always a reject option.
                    return RequestPermissionResponse(
                        outcome=AllowedOutcome(outcome="selected", option_id=option.option_id)
                    )
        return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))

    async def session_update(self, session_id, update, **kwargs):
        # Events were already classified and delivered by the stream observer.
        return None

    async def _not_supported(self, method: str):
        from acp import RequestError

        raise RequestError.method_not_found(method)

    async def read_text_file(self, **kwargs):
        await self._not_supported("fs/read_text_file")

    async def write_text_file(self, **kwargs):
        await self._not_supported("fs/write_text_file")

    async def create_terminal(self, **kwargs):
        await self._not_supported("terminal/create")

    async def terminal_output(self, **kwargs):
        await self._not_supported("terminal/output")

    async def release_terminal(self, **kwargs):
        await self._not_supported("terminal/release")

    async def wait_for_terminal_exit(self, **kwargs):
        await self._not_supported("terminal/wait_for_exit")

    async def kill_terminal(self, **kwargs):
        await self._not_supported("terminal/kill")


class AcpConnection:
    def __init__(
        self,
        *,
        command: str,
        args: Sequence[str] = (),
        cwd: Path,
        env: Mapping[str, str] | None = None,
        event_sink: Callable[[dict], None],
        stderr_path: Path | None = None,
        line_limit_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self._command = command
        self._args = tuple(args)
        self._cwd = Path(cwd)
        self._env = dict(env) if env else {}
        self._sink = event_sink
        self._stderr_path = stderr_path
        self._line_limit_bytes = line_limit_bytes

        self._classifier = WireClassifier()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self._stderr_file = None

        # Loop-thread state.
        self._conn = None
        self._main_task: asyncio.Task | None = None
        self._lost: asyncio.Future | None = None
        self._stop: asyncio.Event | None = None
        self._busy = False
        self._last_terminal: dict | None = None

    # -- public, blocking API ---------------------------------------------------

    def start(self, timeout_seconds: float) -> dict:
        self._check_caller_thread()
        if self._loop is not None:
            raise RuntimeError("AcpConnection.start() was already called")
        if self._closed:
            raise AcpConnectionLost("connection is closed")
        acp = _import_sdk()

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, name="acp-connection", daemon=True)
        thread.start()
        self._loop, self._thread = loop, thread

        try:
            response = self._wait(self._open(acp), timeout_seconds, what="initialize")
        except BaseException:
            self.close()
            raise

        info = response.agent_info
        capabilities = response.agent_capabilities
        return {
            "protocol_version": response.protocol_version,
            "agent_name": info.name if info is not None else None,
            "agent_version": info.version if info is not None else None,
            "agent_capabilities": (
                capabilities.model_dump(mode="json", by_alias=True, exclude_none=True)
                if capabilities is not None else {}
            ),
            "sdk_version": importlib.metadata.version(_SDK_DISTRIBUTION),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        }

    def new_session(self, timeout_seconds: float) -> str:
        self._check_usable()
        return self._wait(self._new_session(), timeout_seconds, what="session/new")

    def load_session(self, acp_session_id: str, timeout_seconds: float) -> None:
        self._check_usable()
        self._wait(self._load_session(acp_session_id), timeout_seconds, what="session/load")

    def prompt(self, acp_session_id: str, text: str, *, turn_id: str | None, timeout_seconds: float) -> dict:
        self._check_usable()
        future = asyncio.run_coroutine_threadsafe(self._prompt(acp_session_id, text, turn_id), self._loop)
        try:
            return future.result(timeout_seconds)
        except concurrent.futures.TimeoutError:
            pass
        try:
            self.cancel(acp_session_id)
        except (AcpConnectionLost, RuntimeError):
            pass
        try:
            return future.result(_CANCEL_GRACE_SECONDS)
        except concurrent.futures.TimeoutError:
            self.close()
            raise AcpConnectionLost(
                f"session/prompt did not answer within {timeout_seconds}s "
                f"plus {_CANCEL_GRACE_SECONDS}s after session/cancel"
            ) from None

    def cancel(self, acp_session_id: str) -> None:
        self._check_usable()
        self._wait(self._cancel(acp_session_id), _CANCEL_GRACE_SECONDS, what="session/cancel")

    def close(self) -> None:
        self._check_caller_thread()
        if self._closed:
            return
        self._closed = True
        loop, thread = self._loop, self._thread
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), loop).result(_SHUTDOWN_WAIT_SECONDS)
        except Exception:
            _log.exception("ACP connection shutdown did not complete cleanly")
        loop.call_soon_threadsafe(loop.stop)
        thread.join(_SHUTDOWN_WAIT_SECONDS)
        if not thread.is_alive():
            loop.close()
        if self._stderr_file is not None:
            self._stderr_file.close()
            self._stderr_file = None

    # -- caller-thread helpers ------------------------------------------------------

    def _check_caller_thread(self) -> None:
        if self._thread is not None and threading.get_ident() == self._thread.ident:
            raise RuntimeError("AcpConnection methods must not be called from its own event-loop thread")

    def _check_usable(self) -> None:
        self._check_caller_thread()
        if self._loop is None:
            raise RuntimeError("AcpConnection.start() has not been called")
        if self._closed:
            raise AcpConnectionLost("connection is closed")

    def _wait(self, coro, timeout_seconds: float, *, what: str):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout_seconds)
        except concurrent.futures.TimeoutError:
            self.close()
            raise AcpConnectionLost(f"{what} did not answer within {timeout_seconds}s; connection closed") from None

    # -- loop thread ----------------------------------------------------------------

    async def _open(self, acp):
        loop = asyncio.get_running_loop()
        self._lost = loop.create_future()
        self._stop = asyncio.Event()
        started = loop.create_future()
        self._main_task = loop.create_task(self._main(acp, started))
        await started

        from acp.schema import ClientCapabilities, FileSystemCapabilities

        capabilities = ClientCapabilities(
            fs=FileSystemCapabilities(read_text_file=False, write_text_file=False),
            terminal=False,
        )
        self._begin_request()
        try:
            return await self._guarded(
                self._conn.initialize(protocol_version=acp.PROTOCOL_VERSION, client_capabilities=capabilities)
            )
        finally:
            self._busy = False

    async def _main(self, acp, started: asyncio.Future) -> None:
        if self._stderr_path is not None:
            self._stderr_file = open(self._stderr_path, "ab")
            stderr_target = self._stderr_file
        else:
            stderr_target = subprocess.DEVNULL
        try:
            async with acp.spawn_agent_process(
                _DenyingClient(),
                self._command,
                *self._args,
                env=self._env,
                cwd=str(self._cwd),
                transport_kwargs={"stderr": stderr_target, "limit": self._line_limit_bytes},
                observers=[self._observe],
            ) as (conn, process):
                self._conn = conn
                watcher = asyncio.get_running_loop().create_task(self._watch_exit(process))
                started.set_result(None)
                try:
                    await self._stop.wait()
                finally:
                    watcher.cancel()
        except BaseException as exc:
            if not started.done():
                if isinstance(exc, asyncio.CancelledError):
                    started.cancel()
                else:
                    started.set_exception(exc)
            else:
                _log.exception("ACP connection ended with an error")
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
        finally:
            self._mark_lost("connection_closed")

    async def _watch_exit(self, process) -> None:
        returncode = await process.wait()
        # The process is gone, but lines it wrote may still be buffered; let
        # the SDK's receive loop classify them before declaring the loss.
        reader = process.stdout
        for _ in range(_EXIT_DRAIN_POLLS):
            if reader is None or reader.at_eof() or self._lost.done():
                break
            await asyncio.sleep(_EXIT_DRAIN_POLL_SECONDS)
        self._mark_lost(f"agent_process_exited:{returncode}")

    async def _shutdown(self) -> None:
        if self._lost is not None:
            self._mark_lost("closed_by_caller")
        if self._main_task is not None:
            try:
                await self._main_task
            except BaseException:
                pass

    def _observe(self, stream_event) -> None:
        direction = getattr(stream_event.direction, "value", stream_event.direction)
        if direction != "incoming":
            return
        if self._lost is not None and self._lost.done():
            return
        try:
            event = self._classifier.observe_incoming(stream_event.message)
            if event is None:
                return
            if event["kind"] in (KIND_TURN_END, KIND_TURN_FAILED, KIND_LOAD_COMPLETE):
                self._last_terminal = event
            self._sink(event)
        except Exception as exc:
            failure = self._classifier.local_protocol_error(
                "event_pipeline_failed", {"error": f"{type(exc).__name__}: {exc}"}
            )
            self._deliver_quietly(failure)
            self._mark_lost("event_pipeline_failed")

    def _deliver_quietly(self, event: dict) -> None:
        try:
            self._sink(event)
        except Exception:
            _log.exception("ACP event sink raised while the connection was being closed")

    def _mark_lost(self, reason: str) -> None:
        if self._lost is None or self._lost.done():
            return
        event = self._classifier.connection_lost()
        if event is not None:
            self._deliver_quietly(event)
        self._lost.set_result(reason)
        self._stop.set()

    def _begin_request(self) -> None:
        if self._lost is not None and self._lost.done():
            raise AcpConnectionLost(f"connection lost: {self._lost.result()}")
        if self._busy:
            raise ConcurrentRequestRefused("another request is outstanding on this ACP connection")
        self._busy = True

    async def _guarded(self, coro):
        task = asyncio.ensure_future(coro)
        await asyncio.wait({task, self._lost}, return_when=asyncio.FIRST_COMPLETED)
        if self._lost.done():
            task.cancel()
            raise AcpConnectionLost(f"connection lost: {self._lost.result()}")
        return task.result()

    async def _new_session(self) -> str:
        self._begin_request()
        try:
            response = await self._guarded(self._conn.new_session(cwd=str(self._cwd), mcp_servers=[]))
        finally:
            self._busy = False
        return response.session_id

    async def _load_session(self, acp_session_id: str) -> None:
        from acp import RequestError

        self._begin_request()
        try:
            self._classifier.begin_load(acp_session_id)
            self._last_terminal = None
            try:
                result = await self._guarded(
                    self._conn.load_session(cwd=str(self._cwd), session_id=acp_session_id, mcp_servers=[])
                )
            except RequestError as exc:
                raise AcpProtocolError(f"session/load failed: {exc}") from exc
            if result is None:
                raise AcpSessionNotFound(acp_session_id)
            event = self._last_terminal
            if event is None or event["kind"] != KIND_LOAD_COMPLETE:
                raise AcpProtocolError("session/load returned without a classified load_complete event")
            if "result" in event["payload"] and event["payload"]["result"] is None:
                raise AcpSessionNotFound(acp_session_id)
        finally:
            self._busy = False

    async def _prompt(self, acp_session_id: str, text: str, turn_id: str | None) -> dict:
        from acp import RequestError, text_block

        self._begin_request()
        try:
            self._classifier.begin_prompt(acp_session_id, turn_id)
            self._last_terminal = None
            try:
                await self._guarded(self._conn.prompt(prompt=[text_block(text)], session_id=acp_session_id))
            except RequestError:
                pass  # the classifier recorded the error response as turn_failed
            except AcpConnectionLost:
                raise
            except Exception as exc:
                raise AcpProtocolError(f"session/prompt answer could not be read: {exc}") from exc
            event = self._last_terminal
            if event is None or event["kind"] not in (KIND_TURN_END, KIND_TURN_FAILED):
                raise AcpProtocolError("session/prompt returned without a classified terminal event")
            return event
        finally:
            self._busy = False

    async def _cancel(self, acp_session_id: str) -> None:
        if self._lost.done():
            raise AcpConnectionLost(f"connection lost: {self._lost.result()}")
        await self._guarded(self._conn.cancel(session_id=acp_session_id))


class AcpAdapter:
    """EngineAdapter for one-shot use of an ACP agent (ADR-047 D2).

    Each invoke starts the agent, opens a session (session/load of
    session_id when given, else session/new), sends one prompt, and closes.
    profile, model and provider are accepted for EngineAdapter-protocol
    symmetry and ignored: the ACP agent's own configuration decides them.
    timeout_seconds bounds each protocol step separately. The returned
    session_id is the id the agent issued (or the one it loaded); no turn
    identity is issued on this path.

    Not registered in the engine registry; registration is a later decision.
    """

    supports_events = True

    def __init__(
        self,
        *,
        command: str,
        args: Sequence[str] = (),
        cwd: Path,
        env: Mapping[str, str] | None = None,
        stderr_path: Path | None = None,
    ) -> None:
        self._command = command
        self._args = tuple(args)
        self._cwd = Path(cwd)
        self._env = dict(env) if env else None
        self._stderr_path = stderr_path

    def invoke(
        self,
        profile: str,
        prompt: str,
        *,
        timeout_seconds: int,
        model: str | None = None,
        provider: str | None = None,
        cwd: Path | None = None,
        session_id: str | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> dict:
        text_parts: list[str] = []

        def sink(event: dict) -> None:
            if (
                event["origin"] == ORIGIN_LIVE
                and event["kind"] == KIND_SESSION_UPDATE
                and event["update_type"] == "agent_message_chunk"
            ):
                update = event["payload"].get("update")
                content = update.get("content") if isinstance(update, dict) else None
                if isinstance(content, dict) and content.get("type") == "text":
                    text_parts.append(str(content.get("text", "")))
            if on_event is not None:
                on_event(event)

        connection = AcpConnection(
            command=self._command,
            args=self._args,
            cwd=Path(cwd) if cwd is not None else self._cwd,
            env=self._env,
            event_sink=sink,
            stderr_path=self._stderr_path,
        )
        try:
            connection.start(timeout_seconds)
            if session_id is not None:
                connection.load_session(session_id, timeout_seconds)
                acp_session_id = session_id
            else:
                acp_session_id = connection.new_session(timeout_seconds)
            terminal = connection.prompt(acp_session_id, prompt, turn_id=None, timeout_seconds=timeout_seconds)
        finally:
            connection.close()

        return {
            "status": "succeeded" if terminal["kind"] == KIND_TURN_END else "failed",
            "session_id": acp_session_id,
            "stop_reason": terminal["stop_reason"],
            "text": "".join(text_parts),
        }
