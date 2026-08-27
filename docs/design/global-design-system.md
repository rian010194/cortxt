# Cortxt global design system

## Product character

Cortxt should feel calm, precise, durable, trustworthy, and operational without becoming militaristic or terminal-centric. Typography and spacing create hierarchy before borders and color. Motion explains state transitions rather than decorating them.

The governing principle is **durable authority, replaceable execution**.

## Visual grammar

| Meaning | Treatment |
| --- | --- |
| Workstream, mandate, policy, decision, approval, evidence | Stable surface, persistent identity, clear ownership and state; primary hierarchy |
| Run, engine, provider, runtime, model invocation | Denser subordinate treatment; revealed in context |
| Required attention | Explicit action and label plus restrained warning color |
| Evidence / accepted completion | Durable record treatment; success color supports text and shape |
| Blocked work | Clear reason and recovery path plus icon, label, or structure |
| Navigation / interactive accent | One restrained accent and visible keyboard focus |

## Consumers

The canonical preset source is `agent-platform/widget/presets/visual-tokens.v2.json`. The flat `agent-platform/widget/tokens.json` is the compatibility contract; `site/public/widgets/tokens.json` is generated.

| Consumer | Adapter | Permitted variation |
| --- | --- | --- |
| Landing | `landing-theme.js`, `landing.css` | Narrative scale, composition, marketing density |
| Docs | `theme-tokens.js`, `custom.css` | Reading widths, docs navigation, code presentation |
| OS / Work Console | Widget Host loader and host CSS | App/window chrome, interaction density, canvas behavior |
| Embedded widgets | Host inheritance and fallback | Domain layout inside the widget contract |
| Atlas | `theme-tokens.js`, `atlas.css` | Graph layout, edges, progressive disclosure |
| Execution Inspector | OS/Widget Host adapter | Dense execution detail subordinate to its Workstream |

## Required workflow

1. Read ADR-043 and this document.
2. Identify the consumer and adapter.
3. Use canonical roles before adding aliases or literals.
4. Change canonical sources/generators instead of synchronizing copies manually.
5. Run `python scripts/design_system_conformance.py` and relevant tests/builds.
6. Review desktop and narrow widths, keyboard focus, supported presets, and reduced motion.
7. Document intentional deviations with an owner and migration condition.

## Atlas onboarding

Atlas is a derived relationship view, never a second backlog or generic graph dashboard. Workstreams and mandates are stable anchors; dependencies connect durable work; evidence attaches to what it proves. Runs and execution resources expand on demand and remain visually subordinate.

