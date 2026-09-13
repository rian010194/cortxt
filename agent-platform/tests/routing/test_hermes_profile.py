"""Tests for the shared Hermes profile resolver (M1 of explicit profile selection, #555/#594).

Behavioural tests at the module seam: ``resolve_profile`` and
``hermes_profile_revision``. Every fixture builds its own temporary profiles
root -- no live Hermes profile config is read, and no network/model call is
made.

Bound fields under test: ``model``, ``provider``, ``base_url``, ``api_mode``,
``fallback``. Deliberately unbound: skills, delegation, display, kanban,
personality, secrets.
"""
from __future__ import annotations

import json

import pytest
import yaml

from routing.execution_profile import (
    EXECUTION_PROFILE_FIELDS,
    canonical_json,
    sha256_digest,
)
from routing.hermes_profile import (
    PROFILE_BOUND_FIELDS,
    HermesProfileError,
    hermes_profile_revision,
    resolve_profile,
)

# The execution fields as declared in a Hermes profile config.yaml. The
# routing fields live under the top-level ``model:`` block; the fallback chain
# is a top-level ``fallback_providers`` list (legacy key: ``fallback_model``).
DECLARED = {
    "model": {
        "default": "deepseek-v4.1-flash",
        "provider": "custom",
        "base_url": "https://model.inferx.net/endpoints/v1",
        "api_mode": "chat_completions",
    },
    "fallback_providers": [
        {"provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
    ],
    # Deliberately unbound: must never reach the revision.
    "skills": ["code-review"],
    "delegation": {"max_concurrent_children": 2, "max_spawn_depth": 1},
    "display": {"show_cost": True},
    "kanban": {"orchestrator_profile": "coordinator"},
    "personality": "terse",
}

EXPECTED_PROFILE = {
    "model": "deepseek-v4.1-flash",
    "provider": "custom",
    "base_url": "https://model.inferx.net/endpoints/v1",
    "api_mode": "chat_completions",
    "fallback": [{"provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"}],
}

# Independently derived from the spec's canonicalisation rule
# (json.dumps(sort_keys=True, separators=(",", ":"), default=str) over exactly
# the bound fields, sha256, "sha256:" prefix) -- NOT recomputed by the module.
EXPECTED_REVISION = "sha256:9ba71beae9380438fb5515f27639d7a03d2fb650683e0e0415b275362fe60e88"


def _write_profile(root, name, config, *, raw_text=None):
    """Materialise ``profiles/<name>/config.yaml`` under a temp profiles root."""
    profile_dir = root / name
    profile_dir.mkdir(parents=True, exist_ok=True)
    config_path = profile_dir / "config.yaml"
    text = raw_text if raw_text is not None else yaml.safe_dump(config)
    config_path.write_text(text, encoding="utf-8")
    return config_path


@pytest.fixture
def profiles_root(tmp_path):
    root = tmp_path / "profiles"
    root.mkdir()
    return root


# --------------------------------------------------------------------------
# AC1 -- resolve_profile reads the named profile's declared execution fields.
# --------------------------------------------------------------------------


def test_resolve_profile_returns_only_the_declared_execution_fields(profiles_root):
    _write_profile(profiles_root, "builder", DECLARED)
    result = resolve_profile("builder", profiles_root=profiles_root)
    assert result == EXPECTED_PROFILE
    assert set(result) == set(PROFILE_BOUND_FIELDS)


def test_resolve_profile_accepts_model_name_under_model_key(profiles_root):
    """Hermes accepts both ``model.default`` and ``model.model`` for the name."""
    declared = {"model": {**DECLARED["model"]}}
    declared["model"].pop("default")
    declared["model"]["model"] = "deepseek-v4.1-flash"
    _write_profile(profiles_root, "builder", declared)
    assert resolve_profile("builder", profiles_root=profiles_root)["model"] == "deepseek-v4.1-flash"


def test_resolve_profile_accepts_legacy_fallback_model_key(profiles_root):
    declared = {"model": {**DECLARED["model"]}}
    declared["fallback_model"] = {"provider": "inferx", "model": "deepseek-v4-flash-0731"}
    _write_profile(profiles_root, "builder", declared)
    result = resolve_profile("builder", profiles_root=profiles_root)
    assert result["fallback"] == [{"provider": "inferx", "model": "deepseek-v4-flash-0731"}]


def test_resolve_profile_treats_undeclared_fallback_as_an_empty_chain(profiles_root):
    declared = {"model": {**DECLARED["model"]}}
    _write_profile(profiles_root, "builder", declared)
    assert resolve_profile("builder", profiles_root=profiles_root)["fallback"] == []


def test_resolve_profile_reads_the_named_profile_not_another(profiles_root):
    _write_profile(profiles_root, "builder", DECLARED)
    other = {"model": {**DECLARED["model"], "default": "other-model"}}
    _write_profile(profiles_root, "reviewer", other)
    assert resolve_profile("builder", profiles_root=profiles_root)["model"] == "deepseek-v4.1-flash"
    assert resolve_profile("reviewer", profiles_root=profiles_root)["model"] == "other-model"


@pytest.mark.parametrize("name", ["does-not-exist", "default"])
def test_resolve_profile_unknown_profile_raises_and_never_falls_back(profiles_root, name):
    _write_profile(profiles_root, "builder", DECLARED)
    with pytest.raises(HermesProfileError):
        resolve_profile(name, profiles_root=profiles_root)


@pytest.mark.parametrize("name", ["", "   ", None, 7])
def test_resolve_profile_empty_or_non_string_name_raises(profiles_root, name):
    with pytest.raises(HermesProfileError):
        resolve_profile(name, profiles_root=profiles_root)


@pytest.mark.parametrize("name", ["", "   "])
def test_resolve_profile_empty_name_never_resolves_a_root_level_config(profiles_root, name):
    """An empty name fails closed even when the profiles root itself has a config.

    Guards the fail-closed rule specifically: without the explicit name check,
    ``root / ""`` is the profiles root, so a root-level ``config.yaml`` would
    resolve as if it were a named profile.
    """
    (profiles_root / "config.yaml").write_text(yaml.safe_dump(DECLARED), encoding="utf-8")
    with pytest.raises(HermesProfileError):
        resolve_profile(name, profiles_root=profiles_root)


@pytest.mark.parametrize("name", ["../builder", "sub/builder", "sub\\builder", ".."])
def test_resolve_profile_rejects_a_name_escaping_the_profiles_root(profiles_root, name):
    _write_profile(profiles_root, "builder", DECLARED)
    with pytest.raises(HermesProfileError):
        resolve_profile(name, profiles_root=profiles_root)


def test_resolve_profile_missing_config_file_raises(profiles_root):
    (profiles_root / "builder").mkdir()
    with pytest.raises(HermesProfileError):
        resolve_profile("builder", profiles_root=profiles_root)


@pytest.mark.parametrize("field", ["model", "provider", "base_url", "api_mode"])
def test_resolve_profile_missing_bound_field_raises(profiles_root, field):
    key = "default" if field == "model" else field
    declared = {"model": {k: v for k, v in DECLARED["model"].items() if k != key}}
    _write_profile(profiles_root, "builder", declared)
    with pytest.raises(HermesProfileError):
        resolve_profile("builder", profiles_root=profiles_root)


def test_resolve_profile_absent_model_block_raises(profiles_root):
    _write_profile(profiles_root, "builder", {"skills": ["code-review"]})
    with pytest.raises(HermesProfileError):
        resolve_profile("builder", profiles_root=profiles_root)


@pytest.mark.parametrize("field", ["model", "provider", "base_url", "api_mode"])
@pytest.mark.parametrize("value", ["", "   "])
def test_resolve_profile_empty_bound_field_raises(profiles_root, field, value):
    declared = {"model": {**DECLARED["model"]}}
    key = "default" if field == "model" else field
    declared["model"][key] = value
    _write_profile(profiles_root, "builder", declared)
    with pytest.raises(HermesProfileError):
        resolve_profile("builder", profiles_root=profiles_root)


def test_resolve_profile_empty_config_file_raises(profiles_root):
    _write_profile(profiles_root, "builder", None, raw_text="")
    with pytest.raises(HermesProfileError):
        resolve_profile("builder", profiles_root=profiles_root)


def test_resolve_profile_unparseable_config_file_raises(profiles_root):
    _write_profile(profiles_root, "builder", None, raw_text="model: [unclosed\n")
    with pytest.raises(HermesProfileError):
        resolve_profile("builder", profiles_root=profiles_root)


def test_resolve_profile_malformed_fallback_raises(profiles_root):
    declared = {"model": {**DECLARED["model"]}, "fallback_providers": "openrouter"}
    _write_profile(profiles_root, "builder", declared)
    with pytest.raises(HermesProfileError):
        resolve_profile("builder", profiles_root=profiles_root)


# --------------------------------------------------------------------------
# AC2/AC3 -- revision changes on bound changes, is stable on unbound changes.
# --------------------------------------------------------------------------


def test_revision_matches_the_canonical_bound_form():
    """AC4: the revision is the shared canonical_json/sha256_digest pair."""
    assert hermes_profile_revision(EXPECTED_PROFILE) == EXPECTED_REVISION
    assert hermes_profile_revision(EXPECTED_PROFILE) == sha256_digest(
        canonical_json(EXPECTED_PROFILE, PROFILE_BOUND_FIELDS)
    )


def test_revision_is_sha256_prefixed():
    assert hermes_profile_revision(EXPECTED_PROFILE).startswith("sha256:")
    assert len(hermes_profile_revision(EXPECTED_PROFILE)) == len("sha256:") + 64


@pytest.mark.parametrize(
    "field, new_value",
    [
        ("model", "other-model"),
        ("provider", "openrouter"),
        ("base_url", "https://openrouter.ai/api/v1"),
        ("api_mode", "responses"),
        ("fallback", [{"provider": "inferx", "model": "deepseek-v4-flash-0731"}]),
    ],
)
def test_revision_changes_when_a_bound_field_changes(field, new_value):
    changed = {**EXPECTED_PROFILE, field: new_value}
    assert hermes_profile_revision(changed) != EXPECTED_REVISION


def test_revision_changes_when_the_fallback_chain_order_changes():
    two = [
        {"provider": "openrouter", "model": "a"},
        {"provider": "inferx", "model": "b"},
    ]
    assert hermes_profile_revision({**EXPECTED_PROFILE, "fallback": two}) != hermes_profile_revision(
        {**EXPECTED_PROFILE, "fallback": list(reversed(two))}
    )


def test_revision_stable_for_reordered_keys_in_the_config_file(profiles_root):
    _write_profile(profiles_root, "builder", DECLARED)
    reordered = {
        "kanban": DECLARED["kanban"],
        "fallback_providers": DECLARED["fallback_providers"],
        "model": {
            "api_mode": DECLARED["model"]["api_mode"],
            "base_url": DECLARED["model"]["base_url"],
            "provider": DECLARED["model"]["provider"],
            "default": DECLARED["model"]["default"],
        },
        "skills": DECLARED["skills"],
    }
    _write_profile(profiles_root, "contributor", reordered)
    assert hermes_profile_revision(
        resolve_profile("builder", profiles_root=profiles_root)
    ) == hermes_profile_revision(resolve_profile("contributor", profiles_root=profiles_root))


@pytest.mark.parametrize(
    "key, value",
    [
        ("skills", ["other-skill", "another-skill"]),
        ("delegation", {"max_concurrent_children": 9, "max_spawn_depth": 4}),
        ("display", {"show_cost": False, "tool_progress": "none"}),
        ("kanban", {"orchestrator_profile": "builder", "max_spawn": 8}),
        ("personality", "verbose"),
    ],
)
def test_revision_unchanged_when_an_unbound_field_changes(profiles_root, key, value):
    """AC3: unbound policy/display/skill/delegation changes never move the revision."""
    _write_profile(profiles_root, "builder", DECLARED)
    changed = {**DECLARED, key: value}
    _write_profile(profiles_root, "changed", changed)
    base_rev = hermes_profile_revision(resolve_profile("builder", profiles_root=profiles_root))
    changed_rev = hermes_profile_revision(resolve_profile("changed", profiles_root=profiles_root))
    assert changed_rev == base_rev


def test_resolve_profile_ignores_secrets_in_the_config(profiles_root):
    """AC3 (secrets): an api_key change is not bound and never returned."""
    with_key = {
        **DECLARED,
        "model": {**DECLARED["model"], "api_key": "ix_secret_one"},
        "custom_providers": [{"name": "inferx", "api_key": "ix_secret_two"}],
    }
    with_other_key = {
        **DECLARED,
        "model": {**DECLARED["model"], "api_key": "ix_secret_three"},
    }
    _write_profile(profiles_root, "builder", with_key)
    _write_profile(profiles_root, "other", with_other_key)
    resolved = resolve_profile("builder", profiles_root=profiles_root)
    assert resolved == EXPECTED_PROFILE
    assert "secret" not in json.dumps(resolved)
    assert hermes_profile_revision(resolved) == hermes_profile_revision(
        resolve_profile("other", profiles_root=profiles_root)
    )


# --------------------------------------------------------------------------
# Binding surface -- the bound tuple is additive, the shared tuple is intact.
# --------------------------------------------------------------------------


def test_profile_bound_fields_are_exactly_the_approved_five():
    assert PROFILE_BOUND_FIELDS == ("model", "provider", "base_url", "api_mode", "fallback")


def test_execution_profile_fields_are_untouched():
    assert EXECUTION_PROFILE_FIELDS == ("engine_id", "worker_role", "provider", "model", "isolation")
    assert PROFILE_BOUND_FIELDS != EXECUTION_PROFILE_FIELDS
