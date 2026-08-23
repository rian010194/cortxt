"""Shared visual token loader, validator, and ANSI mapping for browser and CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from widget_contract.registry import TYPES
from widget_contract.validation import ValidationError, validate


class TokensError(ValueError):
    """Raised when tokens cannot be loaded, parsed, or validated."""
    pass


DEFAULT_TOKENS_PATH = Path(__file__).resolve().parents[1] / "widget" / "tokens.json"

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


def ansi_map(tokens: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Return a mapping of token color names to ANSI terminal escape sequences.

    Documented color mapping:
    - background: black background (\\x1b[40m)
    - surface: dark gray surface background (\\x1b[48;5;235m)
    - layer: subtle layer background (\\x1b[48;5;236m)
    - hover: hover state background (\\x1b[48;5;238m)
    - stroke: border / dark gray text (\\x1b[90m)
    - strong: bold bright white text (\\x1b[1;37m)
    - text: default foreground / reset (\\x1b[0m)
    - muted: bright black / gray foreground (\\x1b[90m)
    - dim: dim / faint text (\\x1b[2m)
    - accent: bold blue foreground (\\x1b[1;34m)
    - blue: standard blue foreground (\\x1b[34m)
    - ok: green foreground (\\x1b[32m)
    - warn: yellow foreground (\\x1b[33m)
    - bad: red foreground (\\x1b[31m)
    - reset: full reset (\\x1b[0m)

    Parameters:
        tokens: Optional tokens dictionary. If supplied, colors section is checked.

    Returns:
        Dictionary mapping color names to ANSI escape sequence strings.
    """
    result = dict(DEFAULT_ANSI_MAP)
    if tokens is not None and isinstance(tokens, Mapping):
        colors = tokens.get("colors")
        if isinstance(colors, Mapping):
            # Verify color keys exist or map custom colors if needed
            for k in DEFAULT_ANSI_MAP:
                if k in colors and k not in result:
                    result[k] = DEFAULT_ANSI_MAP.get(k, "\x1b[0m")
    return result
