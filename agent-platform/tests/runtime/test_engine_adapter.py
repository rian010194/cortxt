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


class _OldStyleAdapter:
    """An adapter written before session_id existed -- must still conform."""

    def invoke(self, profile, prompt, *, timeout_seconds, model=None, provider=None, cwd=None):
        return {"status": "succeeded", "profile": profile}


def test_pre_existing_adapter_without_session_id_still_conforms():
    assert isinstance(_OldStyleAdapter(), EngineAdapter)


def test_adapter_with_session_id_parameter_conforms():
    class _NewStyleAdapter:
        def invoke(self, profile, prompt, *, timeout_seconds, model=None,
                    provider=None, cwd=None, session_id=None):
            return {"status": "succeeded", "profile": profile, "session_id": session_id}

    assert isinstance(_NewStyleAdapter(), EngineAdapter)
