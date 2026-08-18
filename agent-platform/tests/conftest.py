"""Shared pytest fixtures for the reasoning kernel.

``inference_port`` resolves to a deterministic MOCK by default (0 model calls),
keeping the default suite fast and hermetic. The opt-in ``real_inference_port``
marker only resolves to a real provider when the test is explicitly marked
``@pytest.mark.real_inference`` AND the inference environment is configured.
"""

from __future__ import annotations

import pytest


class _MockInferencePort:
    """Deterministic stub matching ``InferencePort.invoke(content) -> int``.

    For DM1-4 fixtures the "computed value" is the sum of all scalar ints in
    content — pure, fast, and never hitting a provider.
    """

    def invoke(self, content):
        def _flatten(obj):
            out = []
            if isinstance(obj, dict):
                for v in obj.values():
                    out.extend(_flatten(v))
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    out.extend(_flatten(v))
            else:
                out.append(obj)
            return out

        return sum(x for x in _flatten(content) if isinstance(x, int))


@pytest.fixture
def inference_port():
    """Mock InferencePort — the default for all reasoning tests (0 model calls)."""
    return _MockInferencePort()


@pytest.fixture
def real_inference_port():
    """Opt-in real InferencePort. Only usable under -m real_inference with env set.

    Import is lazy so the default suite never needs cortxt-resilient-inference
    or any credentials.
    """
    pytest.importorskip("adapters.inference")
    from adapters.inference import ResilientInferencePort

    try:
        port = ResilientInferencePort()
    except RuntimeError:
        pytest.skip("cortxt-resilient-inference not installed")
    if not port.available():
        pytest.skip("real inference not configured (CORTXT_INFERENCE_* env) — using mock is fine")
    return port
