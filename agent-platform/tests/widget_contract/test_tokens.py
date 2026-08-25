import copy
import json
from pathlib import Path

import pytest

from widget_contract.registry import TYPES, VISUAL_TOKENS_PRESET_IDS, VISUAL_TOKENS_SCHEMA
from widget_contract.tokens import (
    DEFAULT_PRESET_ID,
    DEFAULT_PRESETS_PATH,
    TokensError,
    ansi_map,
    contrast_ratio,
    load_preset_tokens,
    load_presets,
    load_tokens,
    truecolor_ansi_map,
)
from widget_contract.validation import ValidationError, validate

TOKENS_PATH = Path(__file__).resolve().parents[2] / "widget" / "tokens.json"
PRESETS_PATH = Path(__file__).resolve().parents[2] / "widget" / "presets" / "visual-tokens.v2.json"


def test_visual_tokens_type_registered():
    assert "visual-tokens.v1" in TYPES
    entry = TYPES["visual-tokens.v1"]
    assert entry.data_class == "public-metadata"
    assert entry.schema == VISUAL_TOKENS_SCHEMA


def test_tokens_json_exists_and_validates():
    assert TOKENS_PATH.is_file()
    data = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    validate(data, VISUAL_TOKENS_SCHEMA)
    assert "colors" in data
    assert "typography" in data
    assert "spacing" in data
    assert "radius" in data
    assert "density" in data


def test_visual_tokens_schema_rejection_modes():
    data = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))

    # 1. Unknown top-level key
    with pytest.raises(ValidationError):
        validate({**data, "unknown_field": 123}, VISUAL_TOKENS_SCHEMA)

    # 2. Missing required section
    for section in ("colors", "typography", "spacing", "radius", "density"):
        corrupted = {k: v for k, v in data.items() if k != section}
        with pytest.raises(ValidationError):
            validate(corrupted, VISUAL_TOKENS_SCHEMA)

    # 3. Unknown key inside colors
    bad_colors = {**data["colors"], "extra_color": "#ffffff"}
    with pytest.raises(ValidationError):
        validate({**data, "colors": bad_colors}, VISUAL_TOKENS_SCHEMA)

    # 4. Wrong type inside colors
    bad_type_colors = {**data["colors"], "accent": 12345}
    with pytest.raises(ValidationError):
        validate({**data, "colors": bad_type_colors}, VISUAL_TOKENS_SCHEMA)

    # 5. Missing key inside typography
    bad_typo = {k: v for k, v in data["typography"].items() if k != "sans"}
    with pytest.raises(ValidationError):
        validate({**data, "typography": bad_typo}, VISUAL_TOKENS_SCHEMA)

    # 6. Wrong type for typography sans (must be array)
    bad_typo_type = {**data["typography"], "sans": "Inter"}
    with pytest.raises(ValidationError):
        validate({**data, "typography": bad_typo_type}, VISUAL_TOKENS_SCHEMA)


def test_load_tokens_success_and_failures(tmp_path):
    # Default load
    tokens = load_tokens()
    assert isinstance(tokens, dict)
    assert tokens["colors"]["accent"] == "#4d6bfe"

    # Custom valid path
    custom = tmp_path / "custom_tokens.json"
    custom.write_text(json.dumps(tokens), encoding="utf-8")
    loaded_custom = load_tokens(custom)
    assert loaded_custom == tokens

    # Missing file
    missing = tmp_path / "nonexistent.json"
    with pytest.raises(TokensError, match="not found"):
        load_tokens(missing)

    # Malformed JSON
    malformed = tmp_path / "bad.json"
    malformed.write_text("{ broken json", encoding="utf-8")
    with pytest.raises(TokensError, match="Malformed JSON"):
        load_tokens(malformed)

    # Non-dict JSON
    not_dict = tmp_path / "array.json"
    not_dict.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(TokensError, match="must contain a top-level JSON object"):
        load_tokens(not_dict)

    # Schema invalid
    invalid_schema = tmp_path / "invalid_schema.json"
    invalid_schema.write_text(json.dumps({"colors": {}}), encoding="utf-8")
    with pytest.raises(TokensError, match="validation error"):
        load_tokens(invalid_schema)


def test_ansi_map_contains_required_keys():
    mapping = ansi_map()
    expected_keys = {
        "background", "surface", "layer", "hover", "stroke", "strong",
        "text", "muted", "dim", "accent", "blue", "ok", "warn", "bad", "reset"
    }
    assert expected_keys <= set(mapping.keys())
    assert mapping["accent"] == "\x1b[1;34m"
    assert mapping["ok"] == "\x1b[32m"
    assert mapping["warn"] == "\x1b[33m"
    assert mapping["bad"] == "\x1b[31m"
    assert mapping["text"] == "\x1b[0m"

    # Also test passing tokens dict
    tokens = load_tokens()
    mapping_with_tokens = ansi_map(tokens)
    assert expected_keys <= set(mapping_with_tokens.keys())


def test_ansi_map_keeps_classic_codes_stable():
    """ansi_map() must keep classic 16-color ANSI codes stable for pipes/tests."""
    tokens = load_tokens()
    mapping = ansi_map(tokens)
    assert mapping["accent"] == "\x1b[1;34m"
    assert mapping["ok"] == "\x1b[32m"
    assert mapping["warn"] == "\x1b[33m"
    assert mapping["bad"] == "\x1b[31m"
    assert mapping["text"] == "\x1b[0m"


def test_truecolor_ansi_map_matches_token_hex():
    """24-bit ANSI codes must be derived from the actual token hex values."""
    tokens = load_tokens()
    mapping = truecolor_ansi_map(tokens)
    # accent #4d6bfe -> truecolor foreground escape
    assert mapping["accent"] == "\x1b[38;2;77;107;254m"
    # ok #68d391 -> truecolor foreground escape
    assert mapping["ok"] == "\x1b[38;2;104;211;145m"
    assert mapping["reset"] == "\x1b[0m"


def test_truecolor_ansi_map_falls_back_without_tokens():
    mapping = truecolor_ansi_map()
    assert mapping["accent"] == "\x1b[1;34m"
    assert mapping["ok"] == "\x1b[32m"


def test_ansi_map_256_color_fallback_for_custom_colors():
    """Non-registered color keys resolve to a 256-color approximation."""
    from widget_contract.tokens import _parse_hex

    assert _parse_hex("#4d6bfe") == (77, 107, 254)
    assert _parse_hex("#abc") == (170, 187, 204)
    assert _parse_hex("not-a-color") is None
    assert _parse_hex("#12345") is None


def test_new_token_sections_valid():
    """The extended tokens file (effects/motion/backdrop) must still validate."""
    tokens = load_tokens()
    assert "effects" in tokens
    assert "motion" in tokens
    assert "backdrop" in tokens
    assert tokens["effects"]["glow_ok"] == "rgba(104, 211, 145, 0.55)"
    assert "duration_live" in tokens["motion"]
    assert "grid" in tokens["backdrop"]


# --- visual-tokens.v2 preset collection (issue #373) ------------------------


def test_visual_tokens_v2_type_registered():
    assert "visual-tokens.v2" in TYPES
    entry = TYPES["visual-tokens.v2"]
    assert entry.data_class == "public-metadata"


def test_preset_ids_are_the_three_fixed_names():
    assert VISUAL_TOKENS_PRESET_IDS == ("quiet-slate", "graphite-ink", "soft-dusk")
    assert DEFAULT_PRESET_ID == "quiet-slate"


def test_presets_file_exists_and_validates():
    assert PRESETS_PATH.is_file()
    envelope = load_presets()
    assert envelope["schema_version"] == 2
    assert envelope["default_preset"] == "quiet-slate"
    assert set(envelope["presets"]) == set(VISUAL_TOKENS_PRESET_IDS)


def test_each_preset_is_a_valid_v1_shaped_document():
    """Every preset document must independently satisfy VISUAL_TOKENS_SCHEMA,
    the same schema the pre-existing single-document tokens.json uses."""
    envelope = load_presets()
    for preset_id in VISUAL_TOKENS_PRESET_IDS:
        doc = envelope["presets"][preset_id]
        validate(doc, VISUAL_TOKENS_SCHEMA)
        assert set(doc["colors"]) == set(load_tokens()["colors"])


def test_presets_change_values_never_role_names():
    """Role names (color keys) are identical across presets; only values differ."""
    envelope = load_presets()
    role_sets = {
        preset_id: set(doc["colors"])
        for preset_id, doc in envelope["presets"].items()
    }
    assert len(set(map(frozenset, role_sets.values()))) == 1

    # And presets are not accidentally identical to each other.
    colors_by_preset = {
        preset_id: doc["colors"] for preset_id, doc in envelope["presets"].items()
    }
    assert colors_by_preset["quiet-slate"] != colors_by_preset["graphite-ink"]
    assert colors_by_preset["quiet-slate"] != colors_by_preset["soft-dusk"]
    assert colors_by_preset["graphite-ink"] != colors_by_preset["soft-dusk"]


@pytest.mark.parametrize("preset_id", VISUAL_TOKENS_PRESET_IDS)
def test_load_preset_tokens_returns_flat_v1_shape(preset_id):
    doc = load_preset_tokens(preset_id)
    assert isinstance(doc, dict)
    validate(doc, VISUAL_TOKENS_SCHEMA)
    assert doc["colors"] == load_presets()["presets"][preset_id]["colors"]


def test_load_preset_tokens_defaults_to_quiet_slate():
    default_doc = load_preset_tokens()
    explicit_doc = load_preset_tokens("quiet-slate")
    assert default_doc == explicit_doc
    assert default_doc["colors"] == load_presets()["presets"]["quiet-slate"]["colors"]


def test_load_preset_tokens_rejects_unknown_preset():
    with pytest.raises(TokensError, match="Unknown preset"):
        load_preset_tokens("midnight-neon")


def test_load_tokens_v1_back_compat_unaffected_by_presets():
    """load_tokens() (no args) must keep serving the original v1 document,
    unchanged, for any caller that has not adopted presets."""
    tokens = load_tokens()
    assert tokens["colors"]["accent"] == "#4d6bfe"
    # Not equal to any preset's colors: the original file is independent of
    # the new preset collection.
    envelope = load_presets()
    for preset_id in VISUAL_TOKENS_PRESET_IDS:
        assert tokens["colors"] != envelope["presets"][preset_id]["colors"]


def test_contrast_ratio_known_values():
    # Black vs white is the maximum possible WCAG contrast ratio (21:1).
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, rel=1e-3)
    # A color against itself is always 1:1.
    assert contrast_ratio("#5b6471", "#5b6471") == pytest.approx(1.0, rel=1e-6)
    assert contrast_ratio("not-a-color", "#ffffff") is None


@pytest.mark.parametrize("preset_id", VISUAL_TOKENS_PRESET_IDS)
def test_every_preset_stroke_meets_minimum_contrast(preset_id):
    """Acceptance criteria: stroke must reach >=3:1 contrast against
    background in every preset."""
    colors = load_presets()["presets"][preset_id]["colors"]
    ratio = contrast_ratio(colors["stroke"], colors["background"])
    assert ratio is not None
    assert ratio >= 3.0


def test_load_presets_rejects_low_contrast_preset(tmp_path):
    """The validator must fail the build if a preset's stroke/background
    contrast drops below 3:1."""
    envelope = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    rigged = copy.deepcopy(envelope)
    # Near-identical stroke and background colors: contrast ~1:1.
    rigged["presets"]["quiet-slate"]["colors"]["stroke"] = rigged["presets"]["quiet-slate"]["colors"]["background"]

    rigged_path = tmp_path / "rigged-visual-tokens.v2.json"
    rigged_path.write_text(json.dumps(rigged), encoding="utf-8")

    with pytest.raises(TokensError, match="contrast"):
        load_presets(rigged_path)


def test_load_presets_missing_file(tmp_path):
    missing = tmp_path / "nonexistent-presets.json"
    with pytest.raises(TokensError, match="not found"):
        load_presets(missing)


def test_load_presets_malformed_json(tmp_path):
    malformed = tmp_path / "bad-presets.json"
    malformed.write_text("{ broken json", encoding="utf-8")
    with pytest.raises(TokensError, match="Malformed JSON"):
        load_presets(malformed)


def test_load_presets_schema_rejects_missing_preset(tmp_path):
    envelope = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    corrupted = copy.deepcopy(envelope)
    del corrupted["presets"]["soft-dusk"]

    corrupted_path = tmp_path / "corrupted-presets.json"
    corrupted_path.write_text(json.dumps(corrupted), encoding="utf-8")

    with pytest.raises(TokensError, match="validation error"):
        load_presets(corrupted_path)


def test_default_presets_path_points_at_platform_owned_source():
    assert DEFAULT_PRESETS_PATH == PRESETS_PATH
    assert DEFAULT_PRESETS_PATH.is_file()


def test_load_preset_tokens_honors_envelope_default_preset(tmp_path):
    """load_preset_tokens() must read `default_preset` from the loaded
    envelope, not hardcode DEFAULT_PRESET_ID. A caller-supplied `path` whose
    envelope declares a different default_preset must get that preset, not
    silently fall back to quiet-slate."""
    envelope = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    custom = copy.deepcopy(envelope)
    custom["default_preset"] = "graphite-ink"

    custom_path = tmp_path / "custom-presets.json"
    custom_path.write_text(json.dumps(custom), encoding="utf-8")

    doc = load_preset_tokens(path=custom_path)
    assert doc["colors"] == custom["presets"]["graphite-ink"]["colors"]
    assert doc["colors"] != custom["presets"]["quiet-slate"]["colors"]
