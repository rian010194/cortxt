"""Idle-stop + cold-start lifecycle for a self-hosted Vast.ai vLLM instance (Fas 7, Beslut 8).

Task 4: ``should_stop_for_idle`` -- the decision logic as a pure function (no I/O).
Task 5: ``_VastAiControlAdapter`` (Vast.ai REST boundary) + ``ensure_running()``
wrapper that makes a cold start transparent to the caller.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Protocol, runtime_checkable


def should_stop_for_idle(
    last_activity_ts: float, now_ts: float, idle_threshold_minutes: int
) -> bool:
    """True when idle longer than the threshold (pure arithmetic, fail-closed).

    Note the boundary: ``>=`` threshold means exactly-at-threshold stops too.
    Callers seed ``last_activity_ts`` with provisioning time so a brand-new
    instance is never treated as "idle forever".
    """
    return (now_ts - last_activity_ts) >= idle_threshold_minutes * 60


class SelfhostedLifecycleError(RuntimeError):
    """Raised when a self-hosted instance cannot be brought to healthy, fail-closed."""


@runtime_checkable
class InstanceControl(Protocol):
    """Minimal contract for starting/stopping/querying a Vast.ai instance."""

    def status(self) -> str:  # "running" | "stopped"
        ...

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...


class _VastAiControlAdapter:
    """Vast.ai REST boundary for one instance.

    Real HTTP implementation is exercised only against the live platform in
    Fas B; the deterministic TDD scope (this task) drives it via a FakeControl
    with the same ``InstanceControl`` shape. ``api_key_env`` names the environ
    variable holding the credential -- the value is never logged or stored.
    """

    def __init__(self, instance_id: str, api_key_env: str = "CORTXT_SELFHOSTED_API_KEY") -> None:
        self._instance_id = instance_id
        self._api_key_env = api_key_env

    def _api_key(self) -> str:
        key = os.environ.get(self._api_key_env) or ""
        if not key:
            raise SelfhostedLifecycleError(
                f"Vast.ai control missing credential in {self._api_key_env}"
            )
        return key

    def status(self) -> str:
        # Vast.ai GET /api/v0/instances/<id>/ returns the instance state
        # nested under a top-level "instances" key (verified live 2026-08-17
        # -- an earlier draft assumed flat fields and always returned
        # "stopped" for a genuinely running instance). Fail-closed to
        # "stopped" on any error so ensure_running prefers to (re)start
        # rather than assume healthy.
        try:
            key = self._api_key()
            req = urllib.request.Request(
                f"https://console.vast.ai/api/v0/instances/{self._instance_id}/",
                headers={"Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                state = (body.get("instances") or {}).get("actual_status")
                return "running" if state == "running" else "stopped"
        except Exception:
            return "stopped"

    def start(self) -> None:
        self._set_state("running")

    def stop(self) -> None:
        self._set_state("stopped")

    def _set_state(self, state: str) -> None:
        # Vast.ai's real control API (verified live 2026-08-17 via the
        # official `vastai` CLI's --explain) is a single PUT to the instance
        # resource with a JSON {"state": ...} body -- there is no separate
        # /start/ or /stop/ sub-route, which an earlier draft assumed.
        try:
            key = self._api_key()
            body = json.dumps({"state": state}).encode("utf-8")
            req = urllib.request.Request(
                f"https://console.vast.ai/api/v0/instances/{self._instance_id}/",
                data=body, method="PUT",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as exc:  # fail-closed on any control failure
            raise SelfhostedLifecycleError(
                f"Vast.ai control set-state({state!r}) failed: {exc}"
            ) from exc


def ensure_running(
    control: InstanceControl,
    probe,
    poll_interval_s: float = 5,
    max_wait_s: float = 120,
) -> None:
    """Bring an instance to healthy, starting it if needed (Beslut 8).

    If ``control.status()`` is not "running", start it, then poll the liveness
    ``probe`` until ``alive=True`` or ``max_wait_s`` elapses. On timeout raise
    ``SelfhostedLifecycleError`` (fail-closed -- better a clear error than a
    call against a not-ready server).
    """
    if control.status() != "running":
        control.start()
    deadline = time.monotonic() + max_wait_s
    while True:
        if probe.check().alive:
            return
        if time.monotonic() >= deadline:
            raise SelfhostedLifecycleError(
                "self-hosted instance did not become healthy within "
                f"{max_wait_s}s (max_wait_s)"
            )
        time.sleep(poll_interval_s)
