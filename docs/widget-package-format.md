# Cortxt Widget Package Format (.cw)

This document specifies the format, security invariants, and standalone rendering contract for self-contained Cortxt widget packages (Issue #346).

## 1. Overview

A Cortxt widget package (`.cw`) is a single, self-contained JSON document that bundles:
1. Manifest metadata (format version, widget identity, timestamp, token version).
2. The declarative widget specification in YAML format.
3. The shared visual design tokens (`visual-tokens.v1`).
4. The standalone client-side renderer (`maker.js`).
5. An optional fixture / example render artifact.

The package enables an operator to export any widget from one Cortxt control plane and import it into another, or render it in an isolated standalone consumer without requiring the platform runtime or network access.

## 2. Package Schema & Fields

A valid `.cw` package is UTF-8 encoded JSON with the following structure:

```json
{
  "package_format": "1",
  "manifest": {
    "package_format_version": "1",
    "widget_id": "session-pulse",
    "widget_version": "0.1",
    "title": "Session Pulse",
    "exported_at": "2026-08-23T20:00:00Z",
    "tokens_version": "visual-tokens.v1"
  },
  "widget": "contract_version: \"0.1\"\nwidget:\n  id: session-pulse\n  version: \"0.1\"\n  title: Session Pulse\n...",
  "tokens": {
    "schema_version": 1,
    "colors": {
      "background": "#080b14",
      "surface": "#101522",
      "layer": "#ffffff0d",
      "hover": "#ffffff15",
      "stroke": "#29324a",
      "strong": "#3a4562",
      "text": "#f4f7ff",
      "muted": "#aab3c5",
      "dim": "#8792a8",
      "accent": "#4d6bfe",
      "blue": "#3151d8",
      "ok": "#68d391",
      "warn": "#f6c85f",
      "bad": "#ff7a90"
    },
    "typography": {
      "sans": [
        "Inter",
        "Segoe UI Variable",
        "Segoe UI",
        "sans-serif"
      ],
      "mono": [
        "Cascadia Code",
        "Cascadia Mono",
        "Consolas",
        "monospace"
      ],
      "size_base": "12px",
      "size_small": "10px",
      "size_heading": "14px",
      "weight_normal": 400,
      "weight_bold": 600
    },
    "spacing": {
      "unit": "4px",
      "gap_small": "4px",
      "gap_medium": "8px",
      "gap_large": "16px",
      "padding_small": "6px",
      "padding_medium": "12px"
    },
    "radius": {
      "small": "4px",
      "medium": "6px",
      "large": "12px"
    },
    "density": {
      "row_height": "28px",
      "card_max_height": "520px",
      "grid_min_card_width": "280px"
    }
  },
  "renderer": "/** Cortxt Widget Maker - Shared Client-Side Renderer ... */",
  "fixture": {
    "contract_version": "0.1",
    "widget": {
      "id": "session-pulse",
      "version": "0.1"
    },
    "render": {
      "primitive": "stack",
      "props": {},
      "children": [...]
    }
  }
}
```

### Field Definitions

- `package_format` (string, required): Format specification version. Currently `"1"`.
- `manifest` (object, required):
  - `package_format_version` (string, required): Format version (`"1"`).
  - `widget_id` (string, required): Identifier matching `^[a-z][a-z0-9.-]{0,63}$`.
  - `widget_version` (string, required): Semantic version string of the widget.
  - `title` (string, required): Human-readable title of the widget.
  - `exported_at` (string, required): ISO-8601 UTC timestamp of export.
  - `tokens_version` (string, required): Visual tokens schema identifier (`"visual-tokens.v1"`).
- `widget` (string, required): Complete YAML widget contract specification compliant with ADR-038.
- `tokens` (object, required): Visual design tokens dictionary validated against `visual-tokens.v1`.
- `renderer` (string, required): Embedded JavaScript source of `maker.js` for standalone rendering.
- `fixture` (object, optional): Example rendered artifact or fixture JSON for offline rendering.

## 3. Security & Fail-Closed Boundaries

Widget packages adhere to strict control-plane invariants:

1. **Content-Free Packages**:
   - The exporter scans all contents (spec, tokens, fixture, manifest) and refuses to export if secret-shaped markers (`sk-`, `cfat_`, `ghp_`, `github_pat_`, `-----BEGIN ... KEY-----`) are present.
   - The importer rejects any package carrying secret-shaped content before writing any file to disk.

2. **Fail-Closed Loading**:
   - Every package is validated completely (JSON syntax, format version, required fields, contract validation via `load_widget`, token schema validation via `visual-tokens.v1`) prior to performing any filesystem mutation.
   - Any validation error results in a stable failure error code with zero files written and no changes to `widgets.json`.

3. **No Arbitrary Code Execution**:
   - Widget specifications are strictly declarative contracts defining typed reads, bindings, and layout primitives.
   - The package format does not execute untrusted scripts.

## 4. Standalone Consumer Rendering

A standalone consumer (browser or Node.js) can render the widget directly from the package without installing Cortxt:

### In the Browser

```javascript
// 1. Fetch or read package JSON
const pkg = JSON.parse(packageJsonString);

// 2. Evaluate or include the embedded renderer
const script = document.createElement("script");
script.textContent = pkg.renderer;
document.head.append(script);

// 3. Apply visual tokens
window.WidgetMaker.applyTokens(pkg.tokens);

// 4. Render the fixture tree to a DOM container
const container = document.getElementById("widget-mount");
const renderTree = pkg.fixture ? (pkg.fixture.render || pkg.fixture) : null;
if (renderTree) {
  window.WidgetMaker.renderNodeToDom(renderTree, container);
} else {
  const parsed = window.WidgetMaker.parseYamlSubset(pkg.widget);
  if (parsed.ok) {
    const rendered = window.WidgetMaker.renderSpec(parsed.data, {});
    window.WidgetMaker.renderNodeToDom(rendered.render, container);
  }
}
```

### In Node.js

```javascript
const fs = require("fs");
const vm = require("vm");

const pkg = JSON.parse(fs.readFileSync("session-pulse.cw", "utf8"));

// Evaluate renderer in sandboxed module context
const exportsObj = {};
const sandbox = { module: { exports: exportsObj }, exports: exportsObj };
vm.createContext(sandbox);
vm.runInContext(pkg.renderer, sandbox);
const maker = sandbox.module.exports;

// Parse YAML and render with mock data
const parsed = maker.parseYamlSubset(pkg.widget);
const result = maker.renderSpec(parsed.data, {
  /* read data */
});
console.log(JSON.stringify(result.render, null, 2));
```

## 5. CLI Reference

### Exporting a Widget

```bash
# Export built-in widget by ID
cortxt widget export pulse --out pulse.cw

# Export with custom visual tokens
cortxt widget export pulse --out pulse.cw --tokens custom-tokens.json
```

### Loading and Installing a Widget Package

```bash
# Install package into default agent-platform/widget directory
cortxt widget load --package pulse.cw

# Install package into a custom directory
cortxt widget load --package pulse.cw --dir /path/to/widgets
```
