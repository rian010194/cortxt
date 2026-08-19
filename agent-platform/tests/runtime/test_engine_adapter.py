from __future__ import annotations

from runtime.engine_adapter import EngineAdapter


class _ConformingAdapter:
    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None):
        return {"status": "succeeded", "profile": profile}


class _NonConformingAdapter:
    def frobnicate(self):
        return None


def test_conforming_object_is_an_engine_adapter_instance():
    assert isinstance(_ConformingAdapter(), EngineAdapter)


def test_non_conforming_object_is_not_an_engine_adapter_instance():
    assert not isinstance(_NonConformingAdapter(), EngineAdapter)
