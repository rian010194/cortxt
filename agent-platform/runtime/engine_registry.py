"""EngineBroker/EngineContext (ADR-026, ADR-027).

Service-broker pattern, not exclusive binding (ADR-027): engine_id is a
broker key, never a directly-bound adapter slot. v1 policy is exactly one
provider per broker, pure passthrough -- no routing policy (round-robin,
weighting) is built until a second provider is actually registered under
the same engine_id (ADR-027 non-goal, explicit).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from runtime.engine_adapter import EngineAdapter


class NoProviderRegisteredError(RuntimeError):
    """No adapter is registered for this engine_id yet."""


# Per-engine advisory default for how long one turn is allowed to run when
# the caller doesn't pass an explicit timeout_seconds/--timeout override.
# Hermes's 120s is today's pre-existing global default (orchestrator chat's
# --timeout), preserved unchanged; Codex gets its own, larger default
# because a coding turn (read files, propose a diff) legitimately runs
# longer than a short Hermes advisory reply (spec Open question #5,
# 2026-08-20-orchestrator-engine-resume-and-codex-adapter-v1-design.md).
# Any engine_id not listed here falls back to Hermes's default rather than
# raising -- same "sane fallback, not a silent wrong guess" shape the rest
# of this registry already follows.
_DEFAULT_TIMEOUT_SECONDS_BY_ENGINE: dict[str, int] = {
    "hermes": 120,
    "codex": 300,
}


def default_timeout_seconds(engine_id: str) -> int:
    return _DEFAULT_TIMEOUT_SECONDS_BY_ENGINE.get(engine_id, _DEFAULT_TIMEOUT_SECONDS_BY_ENGINE["hermes"])


@dataclass
class EngineBroker:
    _providers: list[EngineAdapter] = field(default_factory=list)

    @property
    def has_provider(self) -> bool:
        return bool(self._providers)

    def register(self, adapter: EngineAdapter) -> None:
        self._providers.append(adapter)

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
        if not self._providers:
            raise NoProviderRegisteredError(
                "no adapter registered for this broker's engine_id"
            )
        # v1: exactly one provider, pure passthrough (ADR-027 point 2).
        return self._providers[0].invoke(
            profile, prompt, timeout_seconds=timeout_seconds, model=model, provider=provider,
            cwd=cwd, session_id=session_id,
        )


@dataclass
class EngineContext:
    _brokers: dict[str, EngineBroker] = field(default_factory=dict)

    def get(self, engine_id: str) -> EngineBroker:
        if engine_id not in self._brokers:
            self._brokers[engine_id] = EngineBroker()
        return self._brokers[engine_id]

    def register(self, engine_id: str, adapter: EngineAdapter) -> None:
        self.get(engine_id).register(adapter)
