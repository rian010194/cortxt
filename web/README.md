# Operator cockpit web application

Status: paused legacy prototype
Authority: historical entry point (superseded for product surface by ADR-015; see docs/adr/021)
Last verified: 2026-08-21

This React and TypeScript application is a historical operator cockpit
prototype. Per ADR-015 the web surface is **paused legacy**, and per
ADR-021 a widget UI is permitted only as a complement to the CLI-primary
surface, never a replacement. The CLI (`cortxt`) is the product surface and
source of truth; its `cortxt widget` subcommand is the sanctioned thin mirror
of operator state. The screens in this prototype visualize repository fixtures
and control-plane concepts; they are not evidence that every displayed backend
operation is live, and they are not the current implementation.

## Local verification

Run from this directory:

```text
npm run lint
npm run build
```

`npm run dev` starts the Vite development server. Package scripts and locked
dependencies in `package.json` and `package-lock.json` are authoritative for
the current implementation.
