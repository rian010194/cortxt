from __future__ import annotations

import pytest

from routing.engine_manifest import (
    DEFAULT_FALLBACK_ENGINE,
    DEFAULT_MANIFESTS,
    EngineManifest,
    InvalidManifestError,
    route,
)


def _manifest(**overrides):
    fields = dict(
        engine_id="test-engine",
        task_shapes=("tdd",),
        cost_class="cheap",
        reliability_class="verified",
        notes="",
    )
    fields.update(overrides)
    return EngineManifest(**fields)


# --- EngineManifest validation ---


def test_manifest_defaults_to_checkpoint_required():
    manifest = EngineManifest(
        engine_id="test-engine",
        task_shapes=("general",),
        cost_class="cheap",
        reliability_class="unverified",
    )
    assert manifest.checkpoint_required is True


def test_default_manifests_require_checkpoint():
    for manifest in DEFAULT_MANIFESTS:
        assert manifest.checkpoint_required is True, (
            f"{manifest.engine_id} should default to checkpoint_required=True; "
            "no engine has cleared evidence to be exempted yet"
        )


def test_route_result_carries_checkpoint_policy():
    manifests = (
        EngineManifest(
            engine_id="engine-a",
            task_shapes=("research",),
            cost_class="cheap",
            reliability_class="unverified",
            checkpoint_required=False,
        ),
    )
    choice = route(["research"], manifests)
    assert choice.checkpoint_required is False


def test_manifest_rejects_empty_engine_id():
    with pytest.raises(InvalidManifestError):
        _manifest(engine_id="")


def test_manifest_rejects_invalid_cost_class():
    with pytest.raises(InvalidManifestError):
        _manifest(cost_class="expensive")


def test_manifest_rejects_invalid_reliability_class():
    with pytest.raises(InvalidManifestError):
        _manifest(reliability_class="great")


# --- route() ---


def test_route_matches_engine_by_task_shape():
    manifests = [_manifest(engine_id="a", task_shapes=("research",))]
    choice = route(["research"], manifests)
    assert choice.engine_id == "a"
    assert choice.matched_tag == "research"


def test_route_prefers_cheaper_cost_class_among_matches():
    manifests = [
        _manifest(engine_id="pricey", task_shapes=("tdd",), cost_class="metered"),
        _manifest(engine_id="cheap-one", task_shapes=("tdd",), cost_class="cheap"),
        _manifest(engine_id="free-one", task_shapes=("tdd",), cost_class="free"),
    ]
    choice = route(["tdd"], manifests)
    assert choice.engine_id == "free-one"


def test_route_excludes_degraded_engine_and_reports_why():
    manifests = [
        _manifest(engine_id="flaky", task_shapes=("research",), reliability_class="degraded"),
        _manifest(engine_id="solid", task_shapes=("research",), reliability_class="verified", cost_class="metered"),
    ]
    choice = route(["research"], manifests)
    assert choice.engine_id == "solid"
    assert any(engine_id == "flaky" for engine_id, _reason in choice.excluded)
    excluded_reason = dict(choice.excluded)["flaky"]
    assert "degraded" in excluded_reason


def test_route_falls_back_when_no_engine_matches():
    manifests = [_manifest(engine_id="a", task_shapes=("research",))]
    choice = route(["completely-unmatched-tag"], manifests)
    assert choice.engine_id == DEFAULT_FALLBACK_ENGINE
    assert "no engine" in choice.reason.lower() or "fallback" in choice.reason.lower()
    assert choice.matched_tag is None


def test_route_fallback_is_checkpoint_required_even_if_engine_default_were_relaxed():
    """Review finding: the fallback branch's `checkpoint_required=True` in
    route() is currently unverified as an intentional policy choice rather
    than incidental -- True also happens to be EngineChoice's own dataclass
    default, so a test that only asserted the field's value without ruling
    out that coincidence wouldn't catch a future flip of the dataclass
    default to False. Route with a matching-but-not-checkpoint-required
    candidate absent (no candidate at all) so the fallback path is the only
    thing that can produce this choice, and note the candidate engine below
    is itself declared checkpoint_required=False -- proving the fallback's
    True doesn't come from some ambient always-True default in this test's
    own setup."""
    manifests = [
        _manifest(engine_id="a", task_shapes=("research",), checkpoint_required=False),
    ]
    choice = route(["completely-unmatched-tag"], manifests)
    assert choice.engine_id == DEFAULT_FALLBACK_ENGINE
    assert choice.checkpoint_required is True


def test_route_falls_back_when_only_matching_engine_is_degraded():
    manifests = [_manifest(engine_id="a", task_shapes=("research",), reliability_class="degraded")]
    choice = route(["research"], manifests)
    assert choice.engine_id == DEFAULT_FALLBACK_ENGINE
    assert any(engine_id == "a" for engine_id, _reason in choice.excluded)


def test_route_is_deterministic_when_cost_class_ties():
    manifests = [
        _manifest(engine_id="zzz", task_shapes=("tdd",), cost_class="cheap"),
        _manifest(engine_id="aaa", task_shapes=("tdd",), cost_class="cheap"),
    ]
    choice = route(["tdd"], manifests)
    assert choice.engine_id == "aaa"


def test_route_rejects_empty_task_tags():
    with pytest.raises(ValueError):
        route([], [_manifest()])


# --- default v0.1 registry (ADR-022) ---


def test_default_manifests_register_claude_hermes_hermes_free_and_dsh():
    ids = {m.engine_id for m in DEFAULT_MANIFESTS}
    assert ids == {"claude", "hermes", "hermes-free", "dsh"}


def test_hermes_default_manifest_notes_cite_tonights_incidents():
    hermes = next(m for m in DEFAULT_MANIFESTS if m.engine_id == "hermes")
    assert "165" in hermes.notes or "166" in hermes.notes


def test_dsh_default_manifest_is_cheap_unverified_and_takes_research():
    # DSH-integration experiment: dsh is a live-proved, cheap headless engine
    # (lab/dsh-integration live-proof 2026-08-21). It competes with hermes on
    # research/background-task and wins the cheap tie-break ("dsh" < "hermes"
    # lexicographically), while hermes keeps parallel-dispatch. This is a
    # deliberate operator decision, not a default flip.
    dsh = next(m for m in DEFAULT_MANIFESTS if m.engine_id == "dsh")
    assert set(dsh.task_shapes) == {"research", "background-task"}
    assert dsh.cost_class == "cheap"
    assert dsh.reliability_class == "unverified"
    assert dsh.checkpoint_required is True


def test_route_over_default_manifests_takes_hermes_free_for_research():
    choice = route(["research"], DEFAULT_MANIFESTS)
    assert choice.engine_id == "hermes-free"


def test_route_over_default_manifests_takes_hermes_free_for_background_task():
    choice = route(["background-task"], DEFAULT_MANIFESTS)
    assert choice.engine_id == "hermes-free"


def test_route_over_default_manifests_keeps_hermes_for_parallel_dispatch():
    choice = route(["parallel-dispatch"], DEFAULT_MANIFESTS)
    assert choice.engine_id == "hermes"


def test_route_over_default_manifests_keeps_claude_for_general():
    choice = route(["general"], DEFAULT_MANIFESTS)
    assert choice.engine_id == "claude"


def test_route_over_default_manifests_falls_back_to_claude_for_unknown_shape():
    choice = route(["some-shape-nobody-declared"], DEFAULT_MANIFESTS)
    assert choice.engine_id == "claude"
