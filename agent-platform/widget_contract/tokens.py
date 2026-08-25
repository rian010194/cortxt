"""Shared visual token loader, validator, and ANSI mapping for browser and CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from widget_contract.registry import TYPES, VISUAL_TOKENS_PRESET_IDS
from widget_contract.validation import ValidationError, validate


class TokensError(ValueError):
    """Raised when tokens cannot be loaded, parsed, or validated."""
    pass


DEFAULT_TOKENS_PATH = Path(__file__).resolve().parents[1] / "widget" / "tokens.json"

# visual-tokens.v2 preset collection (issue #373). Kept separate from
# DEFAULT_TOKENS_PATH: load_tokens() above is untouched and keeps serving the
# original single-document v1 file for callers that have not adopted
# presets. load_preset_tokens() below is the new preset-aware entry point.
DEFAULT_PRESETS_PATH = (
    Path(__file__).resolve().parents[1] / "widget" / "presets" / "visual-tokens.v2.json"
)
DEFAULT_PRESET_ID = "quiet-slate"

# Minimum WCAG non-text contrast ratio required between a preset's `stroke`
# and `background` colors (issue #373 acceptance criteria).
MIN_STROKE_CONTRAST = 3.0

DEFAULT_ANSI_MAP: dict[str, str] = {
    "background": "\x1b[40m",
    "surface": "\x1b[48;5;235m",
    "layer": "\x1b[48;5;236m",
    "hover": "\x1b[48;5;238m",
    "stroke": "\x1b[90m",
    "strong": "\x1b[1;37m",
    "text": "\x1b[0m",
    "muted": "\x1b[90m",
    "dim": "\x1b[2m",
    "accent": "\x1b[1;34m",
    "blue": "\x1b[34m",
    "ok": "\x1b[32m",
    "warn": "\x1b[33m",
    "bad": "\x1b[31m",
    "reset": "\x1b[0m",
}

# Which token color keys are foreground text colors vs. background fills.
_FOREGROUND_COLORS: frozenset[str] = frozenset(
    {"text", "muted", "dim", "accent", "blue", "ok", "warn", "bad", "strong", "stroke"}
)
_BACKGROUND_COLORS: frozenset[str] = frozenset(
    {"background", "surface", "layer", "hover"}
)


def _parse_hex(color: str) -> tuple[int, int, int] | None:
    """Parse '#rrggbb', '#rgb', '#rrggbbaa' or '#rgba' into an (r, g, b) tuple.

    Alpha is intentionally ignored: token colors with alpha (e.g. layer/hover
    overlays) map to their RGB component for terminal backgrounds, since ANSI
    has no alpha channel.
    """
    value = color.strip()
    if value.startswith("#") and len(value) in (4, 5, 7, 9):
        digits = value[1:8] if len(value) in (5, 9) else value[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        try:
            return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            return None
    return None


def _hex_to_ansi_truecolor(color: str, *, foreground: bool) -> str:
    """Convert a hex color to an ANSI 24-bit escape sequence.

    Falls back to a 256-color approximation when truecolor is not requested
    via the CORTXT_TRUECOLOR=1 environment flag, keeping terminals that only
    support 256 colors readable.
    """
    rgb = _parse_hex(color)
    if rgb is None:
        return ""
    r, g, b = rgb
    if _env_truecolor():
        prefix = "38" if foreground else "48"
        return f"\x1b[{prefix};2;{r};{g};{b}m"
    # 256-color cube approximation: 16 + 36*r' + 6*g' + b'
    cube = tuple(round(component / 255 * 5) for component in (r, g, b))
    code = 16 + 36 * cube[0] + 6 * cube[1] + cube[2]
    prefix = "38" if foreground else "48"
    return f"\x1b[{prefix};5;{code}m"


def _env_truecolor() -> bool:
    """Whether the caller explicitly opted into 24-bit truecolor output."""
    import os

    return os.environ.get("CORTXT_TRUECOLOR", "").strip().lower() in ("1", "true", "yes")


def load_tokens(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate visual design tokens from a JSON file.

    Parameters:
        path: Optional path to tokens.json. Defaults to agent-platform/widget/tokens.json.

    Returns:
        Validated tokens dictionary.

    Raises:
        TokensError: If the file is missing, contains invalid JSON, or fails schema validation.
    """
    target_path = Path(path) if path is not None else DEFAULT_TOKENS_PATH
    if not target_path.is_file():
        raise TokensError(f"Tokens file not found: {target_path}")

    try:
        content = target_path.read_text(encoding="utf-8")
    except Exception as err:
        raise TokensError(f"Failed to read tokens file {target_path}: {err}") from err

    try:
        data = json.loads(content)
    except Exception as err:
        raise TokensError(f"Malformed JSON in tokens file {target_path}: {err}") from err

    if not isinstance(data, dict):
        raise TokensError(f"Tokens file {target_path} must contain a top-level JSON object.")

    schema = TYPES["visual-tokens.v1"].schema
    try:
        validate(data, schema)
    except ValidationError as err:
        raise TokensError(f"Visual tokens validation error: {err}") from err

    return data


def _srgb_channel_to_linear(channel: int) -> float:
    """Convert one 0-255 sRGB channel to its linear-light value (WCAG formula)."""
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(color: str) -> float | None:
    """WCAG relative luminance of a hex color, or None if it cannot be parsed."""
    rgb = _parse_hex(color)
    if rgb is None:
        return None
    r, g, b = rgb
    return 0.2126 * _srgb_channel_to_linear(r) + 0.7152 * _srgb_channel_to_linear(g) + 0.0722 * _srgb_channel_to_linear(b)


def contrast_ratio(color_a: str, color_b: str) -> float | None:
    """WCAG contrast ratio between two hex colors, or None if either is unparseable."""
    lum_a = _relative_luminance(color_a)
    lum_b = _relative_luminance(color_b)
    if lum_a is None or lum_b is None:
        return None
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def _validate_stroke_contrast(preset_id: str, colors: Mapping[str, Any]) -> None:
    """Enforce the >=3:1 WCAG non-text contrast between stroke and background.

    Raises TokensError if the ratio is missing or below MIN_STROKE_CONTRAST.
    """
    stroke = colors.get("stroke")
    background = colors.get("background")
    ratio = contrast_ratio(stroke, background) if isinstance(stroke, str) and isinstance(background, str) else None
    if ratio is None:
        raise TokensError(f"Preset '{preset_id}': cannot compute stroke/background contrast from hex colors")
    if ratio < MIN_STROKE_CONTRAST:
        raise TokensError(
            f"Preset '{preset_id}': stroke/background contrast {ratio:.2f}:1 is below the "
            f"required {MIN_STROKE_CONTRAST:.1f}:1 (WCAG non-text contrast)"
        )


def load_presets(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the visual-tokens.v2 preset envelope.

    Parameters:
        path: Optional path to the presets JSON file. Defaults to
            agent-platform/widget/presets/visual-tokens.v2.json.

    Returns:
        The validated envelope: {"schema_version": 2, "default_preset": ..., "presets": {...}}.

    Raises:
        TokensError: If the file is missing, contains invalid JSON, fails schema
            validation, or any preset fails the stroke/background contrast check.
    """
    target_path = Path(path) if path is not None else DEFAULT_PRESETS_PATH
    if not target_path.is_file():
        raise TokensError(f"Presets file not found: {target_path}")

    try:
        content = target_path.read_text(encoding="utf-8")
    except Exception as err:
        raise TokensError(f"Failed to read presets file {target_path}: {err}") from err

    try:
        data = json.loads(content)
    except Exception as err:
        raise TokensError(f"Malformed JSON in presets file {target_path}: {err}") from err

    if not isinstance(data, dict):
        raise TokensError(f"Presets file {target_path} must contain a top-level JSON object.")

    schema = TYPES["visual-tokens.v2"].schema
    try:
        validate(data, schema)
    except ValidationError as err:
        raise TokensError(f"Visual tokens presets validation error: {err}") from err

    for preset_id, preset_doc in data["presets"].items():
        _validate_stroke_contrast(preset_id, preset_doc["colors"])

    return data


def load_preset_tokens(
    preset: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load one preset from the visual-tokens.v2 collection as a flat v1-shaped document.

    This is the preset-aware loader: it always returns a single flat token
    document with the same shape load_tokens() returns, so any caller that
    has not been updated to be preset-aware can use it unchanged. Defaults to
    the quiet-slate preset when no preset is requested.

    Parameters:
        preset: Preset id (one of VISUAL_TOKENS_PRESET_IDS). Defaults to
            "quiet-slate" (DEFAULT_PRESET_ID) when None.
        path: Optional path to the presets JSON file. Defaults to
            agent-platform/widget/presets/visual-tokens.v2.json.

    Returns:
        The requested preset's tokens as a flat visual-tokens.v1-shaped dict.

    Raises:
        TokensError: If the presets file is invalid, or the preset id is unknown.
    """
    preset_id = preset or DEFAULT_PRESET_ID
    if preset_id not in VISUAL_TOKENS_PRESET_IDS:
        raise TokensError(
            f"Unknown preset '{preset_id}'; expected one of {', '.join(VISUAL_TOKENS_PRESET_IDS)}"
        )

    envelope = load_presets(path)
    return envelope["presets"][preset_id]


def ansi_map(tokens: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Return a mapping of token color names to ANSI terminal escape sequences.

    This is the stable, environment-agnostic fallback map (classic 16/256-color
    ANSI) that keeps output predictable for pipes, logs, and tests. For 24-bit
    colors derived live from the token hex values, use
    :func:`truecolor_ansi_map` (opt-in, e.g. ``cortxt widget --tui
    --tui-truecolor``).

    Parameters:
        tokens: Optional tokens dictionary. If supplied, colors section is checked.

    Returns:
        Dictionary mapping color names to ANSI escape sequence strings.
    """
    result = dict(DEFAULT_ANSI_MAP)
    if tokens is not None and isinstance(tokens, Mapping):
        colors = tokens.get("colors")
        if isinstance(colors, Mapping):
            # Keep the classic fallback codes stable; custom keys resolve to
            # their nearest registered fallback so colorize_status stays green.
            for name, value in colors.items():
                if name not in result and isinstance(value, str) and value.startswith("#"):
                    rgb = _parse_hex(value)
                    if rgb is not None:
                        result[name] = _hex_to_ansi_truecolor(value, foreground=True)
    return result


def _hex_to_truecolor(color: str, *, foreground: bool) -> str:
    """Convert a hex color to an unconditional 24-bit ANSI escape sequence."""
    rgb = _parse_hex(color)
    if rgb is None:
        return ""
    r, g, b = rgb
    prefix = "38" if foreground else "48"
    return f"\x1b[{prefix};2;{r};{g};{b}m"


def truecolor_ansi_map(tokens: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Derive 24-bit truecolor ANSI codes directly from tokens.json hex colors.

    Unlike :func:`ansi_map` (256-color approximation for broad terminal
    compatibility), this reflects live token edits made in the Widget Maker's
    Tokens tab: an operator changing ``accent`` there sees the same change in
    ``--tui --tui-truecolor`` output. Callers opt in explicitly.

    Parameters:
        tokens: Optional tokens dictionary. If supplied, colors section is used.

    Returns:
        Dictionary mapping color names to 24-bit foreground ANSI escapes.
    """
    result: dict[str, str] = {}
    if tokens is not None and isinstance(tokens, Mapping):
        colors = tokens.get("colors")
        if isinstance(colors, Mapping):
            for name, value in colors.items():
                if not isinstance(value, str) or name in _BACKGROUND_COLORS:
                    continue
                code = _hex_to_truecolor(value, foreground=True)
                if code:
                    result[name] = code
    result.setdefault("reset", "\x1b[0m")
    for key, fallback in DEFAULT_ANSI_MAP.items():
        result.setdefault(key, fallback)
    return result
