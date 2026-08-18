"""Read-only agent runtime discovery.

This module answers exactly one question: "Is runtime X present on the
system PATH?" It performs presence detection ONLY, by asking the injected
``which`` callable whether an executable name resolves to a path.

HARD BOUNDARY -- read-only, no credentials:
    * This module NEVER reads environment variables for credentials.
    * This module NEVER reads any config file contents.
    * This module NEVER imports anything related to credentials, secrets,
      or tokens.
    * It is explicitly NOT the credential broker. Credential handling is a
      separate, security-sensitive module that must not live here.

All runtime state is returned through frozen, immutable :class:`RuntimeStatus`
records; nothing here mutates the host system.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RuntimeStatus:
    """Presence status of a single known agent runtime.

    Attributes:
        runtime_id: Dash-cased canonical id of the runtime.
        installed: Whether the runtime's executable resolves on PATH.
        path: The resolved executable path, or ``None`` if not installed.
    """

    runtime_id: str
    installed: bool
    path: str | None


#: Known agent runtimes: runtime_id -> executable name on PATH.
KNOWN_RUNTIMES: dict[str, str] = {
    "hermes": "hermes",
    "buzz": "buzz",
    "claude-code": "claude",
    "codex": "codex",
    "pi": "pi",
}


def discover_installed_runtimes(
    which: Callable[[str], str | None] = shutil.which,
) -> list[RuntimeStatus]:
    """Detect which known runtimes are on PATH.

    For each known runtime, the injected ``which`` callable is invoked with
    the runtime's executable name. If it returns a path, the runtime is
    reported as installed with that path; otherwise it is reported as not
    installed with ``path=None``.

    Args:
        which: Callable mapping an executable name to its resolved path
            (or ``None`` if not found). Defaults to :func:`shutil.which`.

    Returns:
        One :class:`RuntimeStatus` per known runtime, keyed by canonical
        dash-cased runtime id.
    """
    statuses: list[RuntimeStatus] = []
    for runtime_id, executable in KNOWN_RUNTIMES.items():
        path = which(executable)
        statuses.append(
            RuntimeStatus(
                runtime_id=runtime_id,
                installed=path is not None,
                path=path,
            )
        )
    return statuses
