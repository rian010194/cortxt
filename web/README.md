# Operator cockpit web application

Status: current implementation
Authority: implementation entry point
Last verified: 2026-08-13

This React and TypeScript application is the repository's current operator
cockpit prototype. Its screens visualize repository fixtures and control-plane
concepts; they are not evidence that every displayed backend operation is live.

## Local verification

Run from this directory:

```text
npm run lint
npm run build
```

`npm run dev` starts the Vite development server. Package scripts and locked
dependencies in `package.json` and `package-lock.json` are authoritative for
the current implementation.
