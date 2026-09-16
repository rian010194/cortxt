"""The invocation contract every engine adapter implements (ADR-026).

route() (routing/engine_manifest.py) decides *which* engine_id wins for a
task -- picking isn't invoking, per hermes_invoker.py's own docstring. This
Protocol is the "invoking" half: whatever object a broker holds for a given
engine_id, it can call .invoke(...) on it without knowing which concrete
engine it's talking to.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class EngineAdapter(Protocol):
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
    ) -> dict:
        """session_id, when given, resumes an existing engine-native
        conversation instead of starting fresh -- opaque to every caller
        above the adapter (never parsed, compared, or assumed to mean the
        same thing across different engine_ids). The returned dict should
        include a `session_id` key: the engine-native id of the session
        that was just used (fresh or resumed), or None if the call failed
        before a session was established.
        """
        ...


# Event capability (ADR-047 D3). Deliberately NOT a member of EngineAdapter:
# a data member on a runtime_checkable Protocol is part of the isinstance
# check, so every existing adapter (and every conformance fake that defines
# only invoke) would stop being an EngineAdapter. An adapter opts in by
# declaring the class attribute `supports_events = True`; callers that need
# streamed events call require_event_support() and get an error, never a
# silent fallback to one-shot behaviour.


class EventsNotSupported(RuntimeError):
    """Raised when a caller needs events from an adapter that does not emit them."""


def supports_events(adapter: object) -> bool:
    """True only when the adapter declares `supports_events = True` (identity check, not truthiness)."""
    return getattr(adapter, "supports_events", False) is True


def require_event_support(adapter: object) -> None:
    """Raise EventsNotSupported naming type(adapter).__name__ unless supports_events(adapter)."""
    if not supports_events(adapter):
        raise EventsNotSupported(
            f"{type(adapter).__name__} does not declare supports_events = True; "
            "it cannot deliver streamed events"
        )
