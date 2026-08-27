# ADR-043: Global design-system source and consumer contract

Status: Accepted (2026-08-27, operator approval)

## Context

Landing, documentation, Cortxt OS, Work Console, Atlas, the Widget Host, and embedded widgets share portions of the visual-token model but consume it through different runtime paths and local aliases. Shared colors alone do not preserve typography, density, focus, status, surfaces, navigation, window chrome, motion, or the distinction between durable authority and replaceable execution.

ADR-042 decides the product hierarchy. This ADR decides how that hierarchy is expressed consistently without forcing identical layouts.

## Decision

1. `agent-platform/widget/presets/visual-tokens.v2.json` is the canonical authored preset collection. `agent-platform/widget/tokens.json` remains the v1 compatibility document.
2. `site/public/widgets/tokens.json` is generated from the platform-owned v1 document by `scripts/generate_widget_tokens.py`; it is never hand-edited.
3. Runtime and web adapters may expose framework-appropriate CSS properties, but must preserve canonical semantic roles and may not define a private Cortxt palette.
4. Landing may be narrative, docs reading-oriented, and OS/app surfaces denser. State meanings, typography family, focus behavior, authority/execution hierarchy, and preset behavior remain shared.
5. Durable authority objects—Workstreams, mandates, decisions, policies, approvals, and evidence—receive stable primary treatment. Runs, engines, providers, runtimes, and model invocations receive subordinate treatment.
6. Status is never communicated by color alone. Focus is visible. Reduced-motion and reduced-transparency preferences are respected where relevant.
7. New semantic roles are added first to the canonical model and validation, then propagated through generated artifacts and adapters. Local roles require a documented exception and migration owner.
8. CI enforces source/generated equality and the consumer bootstrap contract through `scripts/design_system_conformance.py`.

## Ownership

| File | Ownership |
| --- | --- |
| `agent-platform/widget/presets/visual-tokens.v2.json` | Authored canonical preset collection |
| `agent-platform/widget/tokens.json` | Authored v1 compatibility document |
| `site/public/widgets/tokens.json` | Generated web artifact |
| `site/public/theme-tokens.js`, `site/public/landing-theme.js` | Web adapters |
| `agent-platform/widget/index.html` | Widget Host / OS adapter and consumer |
| `site/src/styles/landing.css`, `custom.css`, `atlas.css` | Consumer layout and aliases, not theme sources |

## Compatibility

Quiet Slate, Graphite Ink, and Soft Dusk remain supported. V1 consumers continue receiving the flat document. Web fallbacks remain explicit so a failed fetch stays legible; fallback values must be quiet-slate-shaped and must not establish a fourth theme.

## Rejected alternatives

- Independent per-surface themes recreate drift.
- One global layout stylesheet removes legitimate surface differences.
- A large shared component library is premature while Work Console and Atlas evolve.
- Treating the generated web copy as canonical reverses the platform-to-consumer dependency.

## Consequences

One implementation owner controls shared source/generator files. Consumers evolve independently inside the contract. Atlas and future apps must demonstrate authority/execution hierarchy, preset coverage, focus, reduced motion, and representative desktop/narrow evidence.

