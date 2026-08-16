"""Bounded execution sandbox (design spec decision 3, operator decision A4).

Two boundaries, defence in depth per §15 — the second does not replace the first:

1. **Launch discipline, enforced here before anything starts.** The command is
   chosen from a static allowlist of argv LISTS, never a string; ``shell=False``
   unconditionally; the workspace root must resolve to a real directory; the
   child env is built from an allowlist, never ``os.environ.copy()``; wall-clock
   timeout with kill-on-expiry; output truncated at a byte ceiling with the
   truncation recorded as a flag rather than silently applied.
2. **A real container boundary.** The validated command runs inside
   ``docker run --network none --rm`` against a digest-pinned image. The
   container has no network namespace access at all — not an allowlist a future
   command could bypass. The fixture's test suite needs zero network access, so
   full denial is both the simplest and the strongest option.

The agent runs OUTSIDE this boundary and only a single validated command crosses
into it — the opposite of Pi Builder's topology, which put the agent inside the
container. §15: "Reasoning och exekvering ska vara separata failure domains."

NOT claimed: memory and CPU ceilings are out of scope for v0.1 (assumption A10).
``docker run --memory``/``--cpus`` become load-bearing the first time a fixture
runs genuinely untrusted or resource-hungry code.

``runner`` injection exists solely so the launch-discipline tests never need a
Docker daemon. Production callers leave it None and get ``subprocess.run``.
"""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Resolved with:
#   docker pull python:3.12-slim
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim
BASE_IMAGE = "python@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65"

SANDBOX_IMAGE_TAG = "cortxt-sandbox:v0.1"
DOCKERFILE = Path(__file__).resolve().with_name("sandbox.Dockerfile")

ALLOWED_COMMANDS: dict[str, list[str]] = {
    "run_pytest": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "/workspace"],
}

_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "COMSPEC", "HOME", "USERPROFILE", "DOCKER_HOST")


class ExecutionError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class ExecutionResult:
    command_id: str
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool
    elapsed_ms: int


def child_env() -> dict[str, str]:
    """Allowlist-built env for the docker client process.

    This is the credential boundary. CORTXT_INFERENCE_API_KEY, KIMI_API_KEY,
    GH_TOKEN and anything else in the operator's shell are structurally absent
    because they are never copied in — not filtered out afterwards.
    DOCKER_HOST is kept because the client needs it to reach the daemon; it is
    not forwarded into the container.
    """
    env = {name: os.environ[name] for name in _ENV_ALLOWLIST if name in os.environ}
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def docker_available(runner: Callable[..., subprocess.CompletedProcess] | None = None) -> bool:
    """Fast, bounded reachability probe. Returns False rather than raising."""
    run = runner or subprocess.run
    try:
        proc = run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=15, check=False,
            shell=False, env=child_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def build_image(tag: str = SANDBOX_IMAGE_TAG, dockerfile: Path = DOCKERFILE,
                runner: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
    run = runner or subprocess.run
    try:
        proc = run(
            ["docker", "build", "--pull", "-t", tag, "-f", str(dockerfile), str(dockerfile.parent)],
            capture_output=True, text=True, timeout=900, check=False,
            shell=False, env=child_env(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ExecutionError("docker_unavailable", f"could not run docker build: {error}") from error
    if proc.returncode != 0:
        raise ExecutionError("image_build_failed", f"docker build failed:\n{proc.stderr}")


class ExecutionSandbox:
    def __init__(self, image: str = SANDBOX_IMAGE_TAG, timeout_seconds: int = 60,
                 max_output_bytes: int = 65536, max_executions: int = 4,
                 runner: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
        self._image = image
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes
        self._max_executions = max_executions
        self._runner = runner or subprocess.run
        self._used = 0

    @property
    def executions_used(self) -> int:
        return self._used

    def build_argv(self, command_id: str, workspace: Path) -> list[str]:
        command = ALLOWED_COMMANDS.get(command_id) if isinstance(command_id, str) else None
        if command is None:
            raise ExecutionError("unknown_command", f"command not on the allowlist: {command_id!r}")
        if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
            raise ExecutionError("command_not_a_list", f"allowlist entry is not argv: {command!r}")
        root = Path(workspace)
        if not root.is_dir():
            raise ExecutionError("workspace_invalid", f"workspace is not a directory: {workspace}")
        return [
            "docker", "run", "--rm",
            "--network", "none",
            "--workdir", "/workspace",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "PYTHONHASHSEED=0",
            "-v", f"{root.resolve()}:/workspace",
            "--name", f"cortxt-sandbox-{uuid.uuid4().hex[:12]}",
            self._image,
            *command,
        ]

    def run(self, command_id: str, workspace: Path) -> ExecutionResult:
        if self._used >= self._max_executions:
            raise ExecutionError(
                "cap_max_executions",
                f"sandbox executions used {self._used}, cap is {self._max_executions}",
            )
        argv = self.build_argv(command_id, workspace)
        container_name = argv[argv.index("--name") + 1]

        # Count the slot BEFORE launching: a run that times out or crashes still
        # consumed a sandbox slot, so the cap cannot be bypassed by failing.
        self._used += 1
        started = time.monotonic()
        try:
            proc = self._runner(
                argv, capture_output=True, text=True, errors="replace",
                timeout=self._timeout, check=False, shell=False,
                env=child_env(), cwd=None,
            )
            stdout, stderr, exit_code, timed_out = proc.stdout or "", proc.stderr or "", proc.returncode, False
        except subprocess.TimeoutExpired as expired:
            self._force_remove(container_name)
            stdout = expired.stdout.decode("utf-8", "replace") if isinstance(expired.stdout, bytes) else (expired.stdout or "")
            stderr = expired.stderr.decode("utf-8", "replace") if isinstance(expired.stderr, bytes) else (expired.stderr or "")
            exit_code, timed_out = -1, True
        except OSError as error:
            raise ExecutionError("docker_unavailable", f"could not launch docker: {error}") from error

        elapsed_ms = int((time.monotonic() - started) * 1000)
        truncated = len(stdout) > self._max_output or len(stderr) > self._max_output
        return ExecutionResult(
            command_id=command_id,
            exit_code=exit_code,
            stdout=stdout[: self._max_output],
            stderr=stderr[: self._max_output],
            truncated=truncated,
            timed_out=timed_out,
            elapsed_ms=elapsed_ms,
        )

    def _force_remove(self, container_name: str) -> None:
        """Kill the container after a client-side timeout. Killing the docker
        client alone would leave the container running past the ceiling."""
        try:
            self._runner(["docker", "rm", "-f", container_name], capture_output=True, text=True,
                         timeout=30, check=False, shell=False, env=child_env())
        except (OSError, subprocess.SubprocessError):
            pass
