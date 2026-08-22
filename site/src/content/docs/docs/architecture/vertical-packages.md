---
title: Vertical package contract
description: How domain behavior stays separate from platform infrastructure.
---

A vertical package declares what a generic harness should do and evaluate without embedding infrastructure. [Read the authoritative source](https://github.com/rian010194/cortxt/blob/main/docs/architecture/vertical-package-contract.md).

## A vertical may declare

- Versioned identity and supported workflows.
- Domain inputs, outputs, instructions, and templates.
- Required capabilities and domain schemas.
- Deterministic assertions and redistributable evaluation fixtures.
- Expected artifacts and review requirements.

## A vertical must not own

- Dispatchers or global task state.
- Sandbox implementation, host mounts, or cleanup.
- Provider credentials or customer data.
- Hard-coded provider selection where a capability declaration is enough.
- Platform-wide approval and review policy.

Unsupported capabilities or incompatible contracts fail before model execution.
