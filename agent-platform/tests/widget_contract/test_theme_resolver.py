import json
from pathlib import Path

import pytest

from widget_contract.tokens import DEFAULT_PRESET_ID
from widget_contract.theme_resolver import (
    ThemeResolverError,
    clear_persisted_theme,
    load_persisted_theme,
    resolve_theme,
    save_persisted_theme,
)

# Known preset ids shipped in widget/presets/visual-tokens.v2.json (issue #373).
OTHER_PRESET_ID = "graphite-ink"
THIRD_PRESET_ID = "soft-dusk"


@pytest.fixture
def pref_path(tmp_path: Path) -> Path:
    return tmp_path / "theme.json"


def test_default_when_nothing_set(pref_path: Path):
    assert resolve_theme(path=pref_path) == DEFAULT_PRESET_ID == "quiet-slate"


def test_persisted_preference_beats_default(pref_path: Path):
    save_persisted_theme(OTHER_PRESET_ID, path=pref_path)
    assert resolve_theme(path=pref_path) == OTHER_PRESET_ID


def test_session_override_beats_persisted_and_default(pref_path: Path):
    save_persisted_theme(OTHER_PRESET_ID, path=pref_path)
    assert resolve_theme(THIRD_PRESET_ID, path=pref_path) == THIRD_PRESET_ID


def test_session_override_beats_default_with_no_persisted_preference(pref_path: Path):
    assert resolve_theme(OTHER_PRESET_ID, path=pref_path) == OTHER_PRESET_ID


def test_empty_session_override_falls_through_to_persisted(pref_path: Path):
    save_persisted_theme(OTHER_PRESET_ID, path=pref_path)
    assert resolve_theme(None, path=pref_path) == OTHER_PRESET_ID
    assert resolve_theme("", path=pref_path) == OTHER_PRESET_ID


def test_session_override_unknown_preset_raises(pref_path: Path):
    with pytest.raises(ThemeResolverError):
        resolve_theme("not-a-real-preset", path=pref_path)


def test_save_unknown_preset_raises(pref_path: Path):
    with pytest.raises(ThemeResolverError):
        save_persisted_theme("not-a-real-preset", path=pref_path)
    # A failed save must not create a preference file.
    assert not pref_path.exists()


def test_persisted_preference_survives_across_invocations(pref_path: Path):
    # Simulates two separate CLI invocations sharing the same preference file:
    # the first saves, a fresh resolve_theme() call (no in-memory state) in a
    # "second invocation" reads it back.
    save_persisted_theme(OTHER_PRESET_ID, path=pref_path)

    resolved_first_invocation = resolve_theme(path=pref_path)
    resolved_second_invocation = resolve_theme(path=pref_path)

    assert resolved_first_invocation == OTHER_PRESET_ID
    assert resolved_second_invocation == OTHER_PRESET_ID


def test_session_override_does_not_leak_into_persisted_state(pref_path: Path):
    save_persisted_theme(OTHER_PRESET_ID, path=pref_path)

    # A session override changes what this call resolves to...
    assert resolve_theme(THIRD_PRESET_ID, path=pref_path) == THIRD_PRESET_ID

    # ...but the persisted preference on disk, and what a later call without
    # an override resolves to, are unchanged.
    assert load_persisted_theme(pref_path) == OTHER_PRESET_ID
    assert resolve_theme(path=pref_path) == OTHER_PRESET_ID


def test_explicit_save_after_session_override_does_persist(pref_path: Path):
    resolved = resolve_theme(THIRD_PRESET_ID, path=pref_path)
    save_persisted_theme(resolved, path=pref_path)

    assert load_persisted_theme(pref_path) == THIRD_PRESET_ID
    assert resolve_theme(path=pref_path) == THIRD_PRESET_ID


def test_load_persisted_theme_missing_file_returns_none(pref_path: Path):
    assert load_persisted_theme(pref_path) is None


def test_load_persisted_theme_corrupt_file_returns_none(pref_path: Path):
    pref_path.write_text("not json", encoding="utf-8")
    assert load_persisted_theme(pref_path) is None
    # A corrupt file falls through to default rather than raising.
    assert resolve_theme(path=pref_path) == DEFAULT_PRESET_ID


def test_load_persisted_theme_unknown_preset_falls_back_to_default(pref_path: Path):
    pref_path.parent.mkdir(parents=True, exist_ok=True)
    pref_path.write_text(json.dumps({"preset": "stale-preset-id"}), encoding="utf-8")
    # A directly-written (not via save_persisted_theme) stale preference id
    # must not blow up resolution.
    assert resolve_theme(path=pref_path) == DEFAULT_PRESET_ID


def test_save_persisted_theme_creates_parent_directories(tmp_path: Path):
    nested_path = tmp_path / "nested" / "does" / "not" / "exist" / "theme.json"
    save_persisted_theme(OTHER_PRESET_ID, path=nested_path)
    assert nested_path.is_file()
    assert load_persisted_theme(nested_path) == OTHER_PRESET_ID


def test_save_persisted_theme_overwrites_prior_value(pref_path: Path):
    save_persisted_theme(OTHER_PRESET_ID, path=pref_path)
    save_persisted_theme(THIRD_PRESET_ID, path=pref_path)
    assert load_persisted_theme(pref_path) == THIRD_PRESET_ID


def test_clear_persisted_theme_removes_preference(pref_path: Path):
    save_persisted_theme(OTHER_PRESET_ID, path=pref_path)
    clear_persisted_theme(pref_path)
    assert load_persisted_theme(pref_path) is None
    assert resolve_theme(path=pref_path) == DEFAULT_PRESET_ID


def test_clear_persisted_theme_missing_file_is_noop(pref_path: Path):
    clear_persisted_theme(pref_path)  # must not raise
    assert load_persisted_theme(pref_path) is None


def test_persisted_file_shape(pref_path: Path):
    save_persisted_theme(OTHER_PRESET_ID, path=pref_path)
    data = json.loads(pref_path.read_text(encoding="utf-8"))
    assert data == {"preset": OTHER_PRESET_ID}


def test_default_preference_path_is_under_dot_cortxt():
    from widget_contract.theme_resolver import DEFAULT_THEME_PREFERENCE_PATH

    assert DEFAULT_THEME_PREFERENCE_PATH.parent.name == ".cortxt"
    assert DEFAULT_THEME_PREFERENCE_PATH.name == "theme.json"
