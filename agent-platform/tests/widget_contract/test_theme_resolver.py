import json
from pathlib import Path

import pytest

from widget_contract import theme_resolver
from widget_contract.tokens import DEFAULT_PRESET_ID, load_preset_tokens
from widget_contract.theme_resolver import (
    ThemeResolverError,
    clear_persisted_theme,
    load_persisted_theme,
    resolve_theme,
    save_persisted_theme,
    sync_widget_tokens,
)

# Known preset ids shipped in widget/presets/visual-tokens.v2.json (issue #373).
OTHER_PRESET_ID = "graphite-ink"
THIRD_PRESET_ID = "soft-dusk"

# A stand-in path used to select the fake custom presets collection below.
# It is never touched as a real filesystem path -- _fake_load_presets()
# intercepts it before any file I/O happens.
CUSTOM_PRESETS_PATH = "sentinel://custom-presets-collection"

# A custom visual-tokens.v2-shaped collection with its own default_preset
# ("graphite-ink", not the shipped "quiet-slate") and its own preset id set
# (deliberately omits "quiet-slate" entirely). Used to prove resolve_theme()
# and save_persisted_theme() honor presets_path rather than falling back to
# the hardcoded DEFAULT_PRESET_ID constant or the shipped presets file.
CUSTOM_DEFAULT_PRESET_ID = "graphite-ink"
CUSTOM_ENVELOPE = {
    "schema_version": 2,
    "default_preset": CUSTOM_DEFAULT_PRESET_ID,
    "presets": {"graphite-ink": {}, "soft-dusk": {}},
}

_real_load_presets = theme_resolver.load_presets


def _fake_load_presets(path=None):
    """Return CUSTOM_ENVELOPE for CUSTOM_PRESETS_PATH, else load for real.

    theme_resolver only ever reads envelope["presets"] (for the known-id
    set) and envelope["default_preset"] (for the fallback), so a minimal
    fake envelope is sufficient -- no need to satisfy the full
    visual-tokens.v2 JSON schema (which fixes the preset id set and would
    make a collection lacking "quiet-slate" impossible to construct via a
    real file).
    """
    if path == CUSTOM_PRESETS_PATH:
        return CUSTOM_ENVELOPE
    return _real_load_presets(path)


@pytest.fixture
def custom_presets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make CUSTOM_PRESETS_PATH resolve to CUSTOM_ENVELOPE for this test."""
    monkeypatch.setattr(theme_resolver, "load_presets", _fake_load_presets)


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


# -- presets_path: custom presets collection ---------------------------------
#
# These exercise a presets_path pointing at a *different* presets collection
# than the shipped visual-tokens.v2.json -- one with its own default_preset
# and its own preset id set. Regression coverage for two review findings on
# PR #382 (issue #374): resolve_theme()'s no-override/no-persisted fallback
# was returning the hardcoded DEFAULT_PRESET_ID constant instead of the
# loaded envelope's own default_preset, and save_persisted_theme() had no
# presets_path parameter at all, so it always validated against the default
# shipped presets file regardless of which collection the caller was
# actually working against.


def test_resolve_theme_fallback_uses_custom_collection_default_preset(
    custom_presets, pref_path: Path
):
    resolved = resolve_theme(path=pref_path, presets_path=CUSTOM_PRESETS_PATH)
    assert resolved == CUSTOM_DEFAULT_PRESET_ID == "graphite-ink"
    # Must not be the hardcoded module constant -- the custom collection's
    # default differs from it, and the constant isn't even a valid preset id
    # in this collection.
    assert resolved != DEFAULT_PRESET_ID


def test_save_persisted_theme_validates_against_custom_presets_path(
    custom_presets, pref_path: Path
):
    # Success: "soft-dusk" is a valid preset id in the custom collection.
    save_persisted_theme("soft-dusk", path=pref_path, presets_path=CUSTOM_PRESETS_PATH)
    assert load_persisted_theme(pref_path) == "soft-dusk"

    # Rejection: DEFAULT_PRESET_ID ("quiet-slate") is valid in the *default*
    # shipped collection but is not a member of the custom collection --
    # save_persisted_theme must validate against presets_path, not silently
    # fall back to the default shipped presets file.
    with pytest.raises(ThemeResolverError):
        save_persisted_theme(DEFAULT_PRESET_ID, path=pref_path, presets_path=CUSTOM_PRESETS_PATH)

    # A rejected save must not clobber the previously-persisted valid value.
    assert load_persisted_theme(pref_path) == "soft-dusk"


def test_save_persisted_theme_without_presets_path_still_uses_default_collection(pref_path: Path):
    # No presets_path override: behavior must be unchanged from before this
    # fix -- validation is against the default shipped presets collection.
    save_persisted_theme(DEFAULT_PRESET_ID, path=pref_path)
    assert load_persisted_theme(pref_path) == DEFAULT_PRESET_ID


# -- session_override whitespace handling -------------------------------------


def test_whitespace_only_session_override_falls_through_to_persisted(pref_path: Path):
    save_persisted_theme(OTHER_PRESET_ID, path=pref_path)
    assert resolve_theme("   ", path=pref_path) == OTHER_PRESET_ID


def test_whitespace_only_session_override_falls_through_to_default(pref_path: Path):
    assert resolve_theme("   ", path=pref_path) == DEFAULT_PRESET_ID


def test_session_override_with_surrounding_whitespace_is_stripped(pref_path: Path):
    assert resolve_theme(f"  {OTHER_PRESET_ID}  ", path=pref_path) == OTHER_PRESET_ID


# -- sync_widget_tokens (issue #376 review finding 1) --------------------------
#
# `cortxt theme use <preset>` (agent-platform/cli/unified_cli.py's
# `_run_theme`) calls sync_widget_tokens() right after save_persisted_theme()
# so the widget host's live widget/tokens.json actually reflects the newly
# selected preset -- before this fix, sync_widget_tokens() existed but had
# zero callers, so the widget host / site kept rendering the old v1 default
# palette forever regardless of `theme use`.


@pytest.fixture
def widget_tokens_path(tmp_path: Path) -> Path:
    return tmp_path / "widget-tokens.json"


def test_sync_widget_tokens_writes_resolved_preset(pref_path: Path, widget_tokens_path: Path):
    assert not widget_tokens_path.exists()
    result = sync_widget_tokens(OTHER_PRESET_ID, path=pref_path, widget_tokens_path=widget_tokens_path)
    assert result.preset_id == OTHER_PRESET_ID
    assert result.written is True
    assert result.reason is None
    assert widget_tokens_path.is_file()
    written = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    assert written == load_preset_tokens(OTHER_PRESET_ID)


def test_sync_widget_tokens_marker_written_alongside_tokens_file(pref_path: Path, widget_tokens_path: Path):
    sync_widget_tokens(OTHER_PRESET_ID, path=pref_path, widget_tokens_path=widget_tokens_path)
    marker_path = widget_tokens_path.with_name(widget_tokens_path.name + ".sync-marker.json")
    assert marker_path.is_file()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["preset"] == OTHER_PRESET_ID
    assert isinstance(marker["hash"], str) and marker["hash"]


def test_sync_widget_tokens_resync_after_its_own_write_overwrites_cleanly(
    pref_path: Path, widget_tokens_path: Path
):
    # First sync (no marker yet) writes unconditionally.
    sync_widget_tokens(OTHER_PRESET_ID, path=pref_path, widget_tokens_path=widget_tokens_path)
    # A second sync to a different preset, with the file untouched since the
    # first sync, must also succeed (marker hash still matches what's on disk).
    result = sync_widget_tokens(THIRD_PRESET_ID, path=pref_path, widget_tokens_path=widget_tokens_path)
    assert result.written is True
    assert result.preset_id == THIRD_PRESET_ID
    written = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    assert written == load_preset_tokens(THIRD_PRESET_ID)


def test_sync_widget_tokens_does_not_clobber_hand_edited_file(pref_path: Path, widget_tokens_path: Path):
    # Establish a baseline sync + marker.
    sync_widget_tokens(OTHER_PRESET_ID, path=pref_path, widget_tokens_path=widget_tokens_path)

    # Simulate a human hand-editing widget/tokens.json directly (e.g. via the
    # Widget Maker's Tokens tab) after that sync -- the file no longer
    # matches what the marker recorded.
    hand_edited = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    hand_edited["colors"]["accent"] = "#123456"
    widget_tokens_path.write_text(json.dumps(hand_edited, indent=2) + "\n", encoding="utf-8")

    result = sync_widget_tokens(THIRD_PRESET_ID, path=pref_path, widget_tokens_path=widget_tokens_path)
    assert result.written is False
    assert result.preset_id == THIRD_PRESET_ID
    assert result.reason is not None and "hand-edited" in result.reason

    # The hand edit must survive untouched.
    still_on_disk = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    assert still_on_disk["colors"]["accent"] == "#123456"


def test_sync_widget_tokens_force_overrides_clobber_guard(pref_path: Path, widget_tokens_path: Path):
    sync_widget_tokens(OTHER_PRESET_ID, path=pref_path, widget_tokens_path=widget_tokens_path)
    hand_edited = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    hand_edited["colors"]["accent"] = "#123456"
    widget_tokens_path.write_text(json.dumps(hand_edited, indent=2) + "\n", encoding="utf-8")

    result = sync_widget_tokens(
        THIRD_PRESET_ID, path=pref_path, widget_tokens_path=widget_tokens_path, force=True
    )
    assert result.written is True
    written = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    assert written == load_preset_tokens(THIRD_PRESET_ID)


def test_sync_widget_tokens_first_sync_overwrites_preexisting_unmarked_file(
    pref_path: Path, widget_tokens_path: Path
):
    # A file that already exists but was never synced by us before (e.g. the
    # shipped default widget/tokens.json checked into the repo) has no
    # marker yet -- there is nothing "of ours" it could have diverged from,
    # so the first sync must proceed rather than treat it as a clobber.
    widget_tokens_path.write_text(json.dumps({"colors": {"accent": "#4d6bfe"}}) + "\n", encoding="utf-8")
    result = sync_widget_tokens(OTHER_PRESET_ID, path=pref_path, widget_tokens_path=widget_tokens_path)
    assert result.written is True
    written = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    assert written == load_preset_tokens(OTHER_PRESET_ID)
