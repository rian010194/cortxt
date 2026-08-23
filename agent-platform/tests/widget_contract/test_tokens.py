import json
from pathlib import Path

import pytest

from widget_contract.registry import TYPES, VISUAL_TOKENS_SCHEMA
from widget_contract.tokens import TokensError, ansi_map, load_tokens
from widget_contract.validation import ValidationError, validate

TOKENS_PATH = Path(__file__).resolve().parents[2] / "widget" / "tokens.json"


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
