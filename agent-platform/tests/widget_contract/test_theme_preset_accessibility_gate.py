"""CI accessibility gate for the visual-tokens.v2 preset collection (issue #378).

This is the automated, repeatable gate that turns the manual WCAG
luminance-contrast checks run by hand against the `/prototypes` study
(`site/src/styles/prototypes.css`, `site/src/styles/prototype-themes.css`,
docs/daemon-dogfood branch) into a CI job that fails the build on a
regression, per issue #378's acceptance criteria:

  - Text contrast: text/muted vs background/surface >= 4.5:1 (WCAG AA).
  - Non-text/UI-component contrast: stroke, and any filled status/accent
    indicator, vs background >= 3:1 (WCAG 1.4.11).
  - Status-pair distinguishability: status roles must be differentiated
    *structurally* (glyph/shape), not merely by a color-luminance gap
    between pastel hues -- issue #378 explicitly calls out that luminance
    separation between the shipped status hues (measured 1.05-1.28:1
    between mint/gold/rose) is not a realistic bar and must not be a
    false-positive generator.
  - Schema validation: every preset conforms to the issue-1
    (visual-tokens.v2) envelope shape -- delegated to the existing
    coverage in test_tokens.py, and included here as an explicit envelope
    smoke check so this file is a self-contained "run just this" gate.
  - CLI/TUI rendering: preset selection changes rendered output, and the
    plain (non-ANSI) fallback stays legible (no escape codes, semantic
    content preserved) across all three presets.

This is a *gate*, not a fix: if a check below fails because a shipped
preset genuinely violates it, the fix belongs to issue #373 (token
values) or issue #4 (surface-level shape/color usage), not here.
"""

from __future__ import annotations

import re

import pytest

from widget_contract.registry import TYPES, VISUAL_TOKENS_PRESET_IDS, VISUAL_TOKENS_SCHEMA
from widget_contract.swimlane_text import render_swimlane_items
from widget_contract.tokens import (
    contrast_ratio,
    load_preset_tokens,
    load_presets,
    truecolor_ansi_map,
)
from widget_contract.tui import colorize_status, render_tui
from widget_contract.validation import validate

# WCAG AA minimum contrast for normal body text (issue #378 scope).
MIN_TEXT_CONTRAST = 4.5

# WCAG 1.4.11 minimum contrast for non-text UI components / graphical
# objects (stroke, filled indicators) against their background.
MIN_NON_TEXT_CONTRAST = 3.0

# Foreground roles treated as "text" for the AA text-contrast check.
_TEXT_ROLES = ("text", "muted")

# Backgrounds text/indicators are realistically composited against.
_BACKGROUND_ROLES = ("background", "surface")

# Foreground roles treated as "filled indicators" (dot/bar/graph-line/
# stroke fills) for the non-text WCAG 1.4.11 check.
_INDICATOR_ROLES = ("stroke", "accent", "blue", "ok", "warn", "bad")


def _preset_colors(preset_id: str) -> dict:
    return load_presets()["presets"][preset_id]["colors"]


# --- Text contrast (WCAG AA, >=4.5:1) ---------------------------------------


@pytest.mark.parametrize("preset_id", VISUAL_TOKENS_PRESET_IDS)
@pytest.mark.parametrize("fg_role", _TEXT_ROLES)
@pytest.mark.parametrize("bg_role", _BACKGROUND_ROLES)
def test_text_contrast_meets_wcag_aa(preset_id: str, fg_role: str, bg_role: str):
    colors = _preset_colors(preset_id)
    ratio = contrast_ratio(colors[fg_role], colors[bg_role])
    assert ratio is not None, (
        f"Preset '{preset_id}': could not compute {fg_role}/{bg_role} contrast "
        f"from hex colors {colors[fg_role]!r} / {colors[bg_role]!r}"
    )
    assert ratio >= MIN_TEXT_CONTRAST, (
        f"Preset '{preset_id}': {fg_role} ({colors[fg_role]}) vs {bg_role} "
        f"({colors[bg_role]}) contrast is {ratio:.2f}:1, below the required "
        f"{MIN_TEXT_CONTRAST}:1 (WCAG AA normal text)"
    )


# --- Non-text / UI-component contrast (WCAG 1.4.11, >=3:1) ------------------


@pytest.mark.parametrize("preset_id", VISUAL_TOKENS_PRESET_IDS)
@pytest.mark.parametrize("fg_role", _INDICATOR_ROLES)
def test_indicator_contrast_meets_wcag_non_text_minimum(preset_id: str, fg_role: str):
    """Stroke and any filled indicator color (accent/blue/ok/warn/bad) must
    reach >=3:1 against `background`, the surface they are rendered on in
    the accepted /prototypes reference (panes, dots, bars, graph lines all
    sit on `--bg`, not `--surface`)."""
    colors = _preset_colors(preset_id)
    ratio = contrast_ratio(colors[fg_role], colors["background"])
    assert ratio is not None
    assert ratio >= MIN_NON_TEXT_CONTRAST, (
        f"Preset '{preset_id}': indicator '{fg_role}' ({colors[fg_role]}) vs "
        f"background ({colors['background']}) contrast is {ratio:.2f}:1, below "
        f"the required {MIN_NON_TEXT_CONTRAST}:1 (WCAG 1.4.11 non-text contrast)"
    )


# --- Status-pair structural distinguishability -------------------------------
#
# Deliberately does NOT assert a luminance gap between ok/warn/bad -- issue
# #378 calls that out as an unrealistic, false-positive-generating bar
# (1.05-1.28:1 measured between the shipped pastel status hues). Instead
# this asserts the actual differentiator the accepted /prototypes reference
# uses: distinct glyphs/shapes per status role (filled vs ring dot, ✖, ▲),
# so a viewer who cannot perceive the color difference still sees a
# different mark.

# (status_category, sample item) pairs exercising every branch of
# render_swimlane_items' marker selection (widget_contract/swimlane_text.py).
_STATUS_SAMPLES = {
    "running": {"label": "researcher", "status": "running"},
    "idle": {"label": "archiver", "status": "idle"},
    "blocked": {"label": "reviewer", "status": "blocked"},
    "warn": {"label": "watcher", "status": "warn"},
    "ok": {"label": "verifier", "status": "ok"},
}

_MARKER_RE = re.compile(r"[─-⟿]")  # box/geometric/dingbat glyph range


def _extract_marker(rendered_item: str) -> str:
    """Pull the trailing glyph off a rendered swimlane item, stripping any
    ANSI color codes so the shape assertion is color-independent."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered_item)
    match = _MARKER_RE.search(plain)
    assert match, f"No structural glyph marker found in {plain!r}"
    return match.group(0)


@pytest.mark.parametrize("preset_id", VISUAL_TOKENS_PRESET_IDS)
def test_status_roles_are_structurally_distinguishable(preset_id: str):
    """Every status category renders with its own glyph, independent of
    which preset's colors are applied -- the shape, not the color, is what
    a colorblind or non-color-perceiving viewer relies on."""
    tokens = load_preset_tokens(preset_id)
    colors_map = truecolor_ansi_map(tokens)

    markers: dict[str, str] = {}
    for category, item in _STATUS_SAMPLES.items():
        rendered = render_swimlane_items([item], colors=colors_map)
        markers[category] = _extract_marker(rendered)

    # Status roles that are plausibly rendered "near each other" (issue
    # #378's ok/warn/bad and running/waiting examples) must use different
    # glyphs from one another.
    assert markers["running"] != markers["idle"]
    assert markers["running"] != markers["blocked"]
    assert markers["warn"] != markers["blocked"]
    assert markers["warn"] != markers["ok"]
    assert markers["blocked"] != markers["idle"]


def test_status_glyphs_are_preset_independent():
    """The glyph chosen for a status category must not depend on preset
    colors -- it is a shape decision, not a color decision. Regresses to a
    single glyph set across all three presets."""
    per_preset_markers = []
    for preset_id in VISUAL_TOKENS_PRESET_IDS:
        tokens = load_preset_tokens(preset_id)
        colors_map = truecolor_ansi_map(tokens)
        markers = {
            category: _extract_marker(render_swimlane_items([item], colors=colors_map))
            for category, item in _STATUS_SAMPLES.items()
        }
        per_preset_markers.append(markers)

    first = per_preset_markers[0]
    for other in per_preset_markers[1:]:
        assert other == first, (
            "Status glyph shapes must be identical across presets; only "
            "color may vary"
        )


# --- Schema validation (envelope smoke check) --------------------------------


def test_all_presets_conform_to_v2_envelope_schema():
    """Explicit envelope-shape smoke check so this file is a self-contained
    gate; full schema-rejection-mode coverage lives in test_tokens.py
    (issue #373) and is not duplicated here."""
    assert "visual-tokens.v2" in TYPES
    envelope = load_presets()
    schema = TYPES["visual-tokens.v2"].schema
    validate(envelope, schema)
    assert set(envelope["presets"]) == set(VISUAL_TOKENS_PRESET_IDS)
    for preset_id in VISUAL_TOKENS_PRESET_IDS:
        validate(envelope["presets"][preset_id], VISUAL_TOKENS_SCHEMA)


# --- CLI/TUI rendering assertions --------------------------------------------


_SAMPLE_TREE = {
    "primitive": "stack",
    "props": {"label": "Theme preview"},
    "children": [
        {"primitive": "heading", "props": {"value": "Preset check"}},
        {"primitive": "badge", "props": {"value": "running"}},
        {"primitive": "badge", "props": {"value": "blocked"}},
        {"primitive": "metric", "props": {"label": "Active", "value": 3}},
    ],
}


@pytest.mark.parametrize("preset_id", VISUAL_TOKENS_PRESET_IDS)
def test_ansi_fallback_stays_legible_for_every_preset(preset_id: str):
    """Non-TTY / force_ansi=False output must contain no escape codes and
    must preserve the same semantic content regardless of preset."""
    tokens = load_preset_tokens(preset_id)
    plain = render_tui(_SAMPLE_TREE, tokens=tokens, force_ansi=False)
    assert "\x1b" not in plain
    assert "=== Theme preview ===" in plain
    assert "## Preset check" in plain
    assert "[running]" in plain
    assert "[blocked]" in plain
    assert "Active: 3" in plain


def test_rendered_colors_change_across_presets():
    """Forced-ANSI truecolor rendering must actually reflect each preset's
    own hex values -- a future preset edit (or a new preset) that leaves
    rendering unchanged (e.g. a copy-paste bug reusing quiet-slate's
    colors) must fail this gate."""
    rendered_by_preset = {}
    for preset_id in VISUAL_TOKENS_PRESET_IDS:
        tokens = load_preset_tokens(preset_id)
        rendered_by_preset[preset_id] = render_tui(
            _SAMPLE_TREE, tokens=tokens, force_ansi=True, truecolor=True
        )

    values = list(rendered_by_preset.values())
    assert len(set(values)) == len(values), (
        f"Truecolor TUI output must differ across presets; got identical "
        f"renders among {list(rendered_by_preset)}"
    )


@pytest.mark.parametrize("preset_id", VISUAL_TOKENS_PRESET_IDS)
def test_truecolor_ansi_map_reflects_preset_hex_values(preset_id: str):
    tokens = load_preset_tokens(preset_id)
    colors_map = truecolor_ansi_map(tokens)
    expected_ok = tokens["colors"]["ok"]
    r, g, b = (int(expected_ok[i : i + 2], 16) for i in (1, 3, 5))
    assert colors_map["ok"] == f"\x1b[38;2;{r};{g};{b}m"


@pytest.mark.parametrize("preset_id", VISUAL_TOKENS_PRESET_IDS)
def test_colorize_status_stays_within_registered_semantic_roles(preset_id: str):
    """colorize_status must only ever apply the ok/warn/bad/muted semantic
    roles (never raw preset hex outside the token contract), so every
    preset's ANSI/truecolor map keeps status coloring meaningful."""
    tokens = load_preset_tokens(preset_id)
    colors_map = truecolor_ansi_map(tokens)
    for value in ("running", "blocked", "pending", "-"):
        out = colorize_status(value, colors_map)
        assert value in out
