# Cortxt visual identity

Cortxt is a dark-first operator tool. Every surface should feel like a view onto the same control plane: quiet, precise, and native to a terminal without imitating a retro terminal. Indigo identifies the product; semantic colors communicate state.

## Color tokens

| Token | Hex | CLI | Widget and web |
| --- | --- | --- | --- |
| `ink` | `#F4F7FF` | Default bright text | Primary text |
| `muted` | `#8792A8` | Waiting, stale, abandoned, idle | Secondary text |
| `canvas` | `#080B14` | Terminal reference background | Page background |
| `surface` | `#101522` | Not applicable | Primary panels |
| `surface-raised` | `#171D2E` | Not applicable | Raised and interactive panels |
| `stroke` | `#29324A` | Not applicable | Borders and separators |
| `accent` | `#4D6BFE` | Links and product emphasis | Brand, focus, selected state |
| `accent-bright` | `#7C8FFF` | Optional bright emphasis | Accent text on dark surfaces |
| `info` | `#5ED3F3` | Running, working, info | Live and in-flight state |
| `success` | `#68D391` | Succeeded, ok, done | Successful state |
| `warning` | `#F6C85F` | Blocked, warn, attention | Needs attention |
| `danger` | `#FF7A90` | Failed, timed out, error | Failed or offline state |

Use color sparingly. Product accent is not a status. Status colors retain their semantic meaning across all surfaces and must always be paired with text, an icon, or shape.

### Previous-to-current mapping

| Surface | Previous | Current |
| --- | --- | --- |
| Landing accent | `#087F5B` | `#4D6BFE` |
| Landing accent highlight | `#7CF6C8` | `#7C8FFF` |
| Landing background | `#F8F6EF` | `#080B14` |
| Widget accent | `#60CDFF` | `#4D6BFE` |
| Widget deep blue | `#0F6CBD` | `#3151D8` |
| CLI white | `#F2F2F2` | `#F4F7FF` |
| CLI grey | `#767676` | `#8792A8` |
| CLI blue | `#3B78FF` | `#4D6BFE` |
| CLI green | `#16C60C` | `#68D391` |
| CLI yellow | `#C19C00` | `#F6C85F` |
| CLI red | `#C50F1F` | `#FF7A90` |
| CLI cyan | `#3A96DD` | `#5ED3F3` |

## Typography

- UI: `Inter`, then the platform sans-serif stack. Use 400 for body text, 600 for controls, and 700 for headings.
- Mono: `ui-monospace`, `SFMono-Regular`, `Cascadia Code`, `Roboto Mono`, `Consolas`, monospace. Use it for commands, identifiers, timestamps, telemetry, tabs, labels, and short operator signals.
- Base UI size: 16 px on the web, 12-13 px in the compact widget. Body line height is 1.6 on the web and 1.4 in dense tools.
- Display headings use restrained tracking and a maximum of 56 px. Cortxt should not use oversized marketing typography.

## Spacing and radius

The spacing scale is `4, 8, 12, 16, 24, 32, 48, 64, 96` px. Prefer 8 px for tight control spacing, 16-24 px inside panels, and 64-96 px between web sections.

Use a 6 px radius for chips and compact controls, 10 px for cards, 14 px for windows and large panels, and a pill radius only for status indicators. Borders are one pixel and low contrast. Shadows should be broad and subtle; glass effects are reserved for floating windows and top bars.

## Surface guidance

- CLI: lead with the command or result. Keep decoration minimal, preserve plain output when color is unavailable, and never make color the only status signal.
- Widget: dense, glanceable, and alive. Preserve window chrome, tabs, lanes, chips, feed, fleet rows, and gauges. Use translucency for hierarchy, not ornament.
- Web: share the same canvas, header height, typography, strokes, and indigo focus treatment across landing and docs. Product demonstrations should resemble real Cortxt surfaces.

## Tone and voice

Write direct English for operators. Prefer concrete nouns and active verbs: `Run`, `Inspect`, `Resume`, `Evidence`, `Mandate`. Avoid hype, exclamation marks, vague claims, and decorative jargon. Short mono labels may be lowercase when they represent machine state; navigation and prose use sentence case.
