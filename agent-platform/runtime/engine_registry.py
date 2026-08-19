"""EngineBroker/EngineContext (ADR-026, ADR-027).

Service-broker pattern, not exclusive binding (ADR-027): engine_id is a
broker key, never a directly-bound adapter slot. v1 policy is exactly one
provider per broker, pure passthrough -- no routing policy (round-robin,
weighting) is built until a second provider is actually registered under
the same engine_id (ADR-027 non-goal, explicit).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from runtime.engine_adapter import EngineAdapter


class NoProviderRegisteredError(RuntimeError):
    """No adapter is registered for this engine_id yet."""


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
    ) -> dict:
        if not self._providers:
            raise NoProviderRegisteredError(
                "no adapter registered for this broker's engine_id"
            )
        # v1: exactly one provider, pure passthrough (ADR-027 point 2).
        return self._providers[0].invoke(
            profile, prompt, timeout_seconds=timeout_seconds, model=model, provider=provider
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
