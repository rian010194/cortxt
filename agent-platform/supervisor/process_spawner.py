"""ProcessSpawner: cross-platform detached-process lifecycle for Supervisor.

Hides Windows vs POSIX process-group and signal handling behind one API
(design spec decisions 2 and 8). A detached child must survive its parent's
death — Windows achieves that with CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS;
POSIX with start_new_session=True (setsid). Graceful termination is likewise
platform-specific: CTRL_BREAK_EVENT then TerminateProcess on Windows, SIGTERM
then SIGKILL to the whole process group on POSIX. Liveness is checked via PID
+ process start-time (not PID alone) so a PID reused by an unrelated process
after a long outage is never misread as the original child (decision 6).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

class ProcessSpawnError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class ChildProcess:
    pid: int
    pgid: int
    session_id: str
    start_time: float


def _build_pythonpath() -> str:
    """Build PYTHONPATH for child processes to find runtime/ and adapters/ modules."""
    agent_platform = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    worktree = os.path.abspath(os.path.join(agent_platform, ".."))
    paths = [worktree, agent_platform]
    if "PYTHONPATH" in os.environ:
        return os.pathsep.join(paths + [os.environ["PYTHONPATH"]])
    return os.pathsep.join(paths)


def _process_start_time(pid: int) -> float | None:
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wintypes

        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            # Check if process is still alive by checking exit code
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                if exit_code.value == STILL_ACTIVE:
                    # Process is still alive, check start time
                    creation = wintypes.FILETIME()
                    exit_time = wintypes.FILETIME()
                    kernel_time = wintypes.FILETIME()
                    user_time = wintypes.FILETIME()
                    ok = kernel32.GetProcessTimes(
                        handle, ctypes.byref(creation), ctypes.byref(exit_time),
                        ctypes.byref(kernel_time), ctypes.byref(user_time),
                    )
                    if not ok:
                        return None
                    value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                    return float(value)
                else:
                    # Process has terminated
                    return None
            return None
        finally:
            kernel32.CloseHandle(handle)
    else:
        stat_path = Path(f"/proc/{pid}/stat")
        if not stat_path.is_file():
            return None
        try:
            fields = stat_path.read_text(encoding="utf-8").split(")")[-1].split()
            return float(fields[19])  # starttime is field 22, 0-indexed after "comm"
        except (OSError, IndexError, ValueError):
            return None


class ProcessSpawner:
    def spawn(self, session_id: str, args: list[str]) -> ChildProcess:
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            env = os.environ.copy()
            env["PYTHONPATH"] = _build_pythonpath()
            process = subprocess.Popen(
                args, creationflags=creationflags, close_fds=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                env=env,
            )
            pgid = process.pid
        else:
            env = os.environ.copy()
            env["PYTHONPATH"] = _build_pythonpath()
            process = subprocess.Popen(
                args, start_new_session=True, close_fds=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                env=env,
            )
            pgid = os.getpgid(process.pid)

        start_time = _process_start_time(process.pid)
        if start_time is None:
            raise ProcessSpawnError("spawn_failed", f"could not read start time for pid {process.pid}")
        return ChildProcess(pid=process.pid, pgid=pgid, session_id=session_id, start_time=start_time)

    def is_alive(self, child: ChildProcess) -> bool:
        current = _process_start_time(child.pid)
        return current is not None and current == child.start_time

    def terminate_gracefully(self, child: ChildProcess, timeout: float = 5.0) -> bool:
        if not self.is_alive(child):
            return True
        if sys.platform == "win32":
            import ctypes

            try:
                ctypes.windll.kernel32.GenerateConsoleCtrlEvent(signal.CTRL_BREAK_EVENT, child.pgid)
            except OSError:
                pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not self.is_alive(child):
                    return True
                time.sleep(0.1)
            try:
                PROCESS_TERMINATE = 1
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, child.pid)
                if handle:
                    try:
                        ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    finally:
                        ctypes.windll.kernel32.CloseHandle(handle)
            except OSError:
                pass
        else:
            try:
                os.killpg(child.pgid, signal.SIGTERM)
            except ProcessLookupError:
                return True
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not self.is_alive(child):
                    return True
                time.sleep(0.1)
            try:
                os.killpg(child.pgid, signal.SIGKILL)
            except ProcessLookupError:
                return True
        return not self.is_alive(child)
