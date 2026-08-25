# Widget visual tokens: preset collection (`visual-tokens.v2`)

Issue: #373 (1 of 7 in the theme-preset production rollout; see also
`docs/widget-package-format.md` for the single-document `visual-tokens.v1`
tokens dictionary this envelope wraps).

## Two documents, two jobs

- `agent-platform/widget/tokens.json` -- the original single-document
  `visual-tokens.v1` tokens dictionary. Unchanged by this issue: it keeps
  being what `widget_contract.tokens.load_tokens()` returns, and what
  `widget_contract.tui` and `widget_contract.package` consume, exactly as
  before. Existing callers that have not adopted presets are unaffected.
- `agent-platform/widget/presets/visual-tokens.v2.json` -- the new versioned
  preset collection added by this issue. Carries the three preset documents
  fixed by prior operator decision: `quiet-slate` (default), `graphite-ink`,
  `soft-dusk`. Loaded and validated by
  `widget_contract.tokens.load_presets()` / `load_preset_tokens()`.

Both files live under the platform-owned `agent-platform/widget/` source
tree; storing the presets in a directory (rather than folding them into
`tokens.json` itself) was the implementer's choice here, so that
`tokens.json` and its existing consumers/tests stay byte-for-byte unchanged.

## `visual-tokens.v2` schema

```json
{
  "schema_version": 2,
  "default_preset": "quiet-slate",
  "presets": {
    "quiet-slate": { "...": "a full visual-tokens.v1-shaped document" },
    "graphite-ink": { "...": "a full visual-tokens.v1-shaped document" },
    "soft-dusk": { "...": "a full visual-tokens.v1-shaped document" }
  }
}
```

Registered in `agent-platform/widget_contract/registry.py` as
`VISUAL_TOKENS_PRESETS_SCHEMA` / `TYPES["visual-tokens.v2"]`. `presets` is a
closed object requiring exactly the three fixed preset ids
(`VISUAL_TOKENS_PRESET_IDS` in `registry.py`) -- no custom/user-authored
presets are accepted (out of scope for this issue). Each preset value
validates against the same `VISUAL_TOKENS_SCHEMA` used for `tokens.json`, so
a single preset document can always be handed to a v1 caller unchanged.
Presets change color *values*; the `colors` role names (`background`,
`surface`, `layer`, `hover`, `stroke`, `strong`, `text`, `muted`, `dim`,
`accent`, `blue`, `ok`, `warn`, `bad`) and the `typography` block's keys
never vary between presets.

`layer` and `hover` are translucent white overlays (`#ffffff0d` /
`#ffffff15`) shared by all three presets, matching how `tokens.json` already
expresses them -- an alpha wash reads correctly over any preset's `surface`
color, so it does not need to be preset-tuned. Every other color role, plus
the `effects.glow_*` colors and `backdrop.vignette`, is tuned per preset.

## Loading

- `load_tokens(path=None)` -- unchanged. Still reads `tokens.json` and
  returns its flat v1-shaped dict.
- `load_presets(path=None)` -- loads and validates the `visual-tokens.v2`
  envelope (schema plus the stroke/background contrast check below). Raises
  `TokensError` on any failure.
- `load_preset_tokens(preset=None, path=None)` -- the preset-aware loader.
  Returns one preset as a flat `visual-tokens.v1`-shaped dict, so any caller
  that only knows the v1 shape can use it unchanged. Defaults to the
  `quiet-slate` preset (`DEFAULT_PRESET_ID`) when `preset` is omitted.

Picking which preset actually applies at runtime (env var, CLI flag,
per-workspace state, etc.) is issue #374's job, not this one.

## Contrast validation

`load_presets()` enforces, for every preset, that `stroke` reaches at least
3:1 WCAG non-text contrast against `background`
(`widget_contract.tokens.MIN_STROKE_CONTRAST`, computed by
`contrast_ratio()`). A preset that fails this check raises `TokensError` and
the envelope does not load. All three shipped presets currently clear the
bar by a small margin (~3.1:1).

Status roles (`ok` / `warn` / `bad`) are not shape-differentiated at this
layer -- this issue only enforces color contrast; enforcing shape (so status
is never carried by color alone) in a consuming UI is issue #374's job. The
`/prototypes` study (`site/src/pages/prototypes.astro`,
`site/src/styles/prototype-themes.css`, not on `main` at the time of this
issue) is the accepted reference for the intended visual result and for that
shape-plus-color accessibility pattern.

## Regenerating the web-consumer artifact

`site/public/widgets/tokens.json` must be a mechanically generated copy of
`agent-platform/widget/tokens.json`, never hand-edited:

```
python scripts/generate_widget_tokens.py          # regenerate the copy
python scripts/generate_widget_tokens.py --check  # verify without writing (exit 1 if stale)
```

This copies the existing `visual-tokens.v1` document only -- applying any
`visual-tokens.v2` preset to the widget host or any other consuming surface
is out of scope for this issue (issue #374's job).
