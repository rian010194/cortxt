---
title: CLI and MCP quick start
description: Run the repository-native Cortxt CLI and its MCP server.
---

The `cortxt` CLI is Cortxt's local, automation, bootstrap, diagnostic, and
power-user interface, and today the most complete verified way to exercise
the platform (see [current product vs. direction](/docs/product-status/) for
what Cortxt OS / Work adds under ADR-042/044). The MCP server is the
external integration surface selected by ADR-024. This quick start proves
these current local interfaces; it does not launch a finished Cortxt OS.

## Install from the repository

Use Python 3.11 or later from a repository checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ./agent-platform
cortxt --help
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Start the MCP server

```bash
cortxt mcp serve
```

The server uses standard input/output transport and exposes the read-only MCP tool slice by default. An MCP client starts this command as its server process.

:::caution[Mandate required for mutations]
Per ADR-032, every Tier-1 or higher MCP tool call requires a signed, nonce-bound mandate envelope that is verified before execution. Keep mutation tiers locked unless your environment is configured to issue and verify these envelopes.
:::

The mandate carries scoped authority such as the issue reference, allowed tools, data-class ceiling, budget, runtime limit, expiry, and scope fingerprint. Private signing keys stay on the operator side; the server receives public keys only.

## Next steps

- Read the [current operating model](/docs/operating-model/) before choosing an execution path.
- Review the [dispatch contract](/docs/architecture/dispatch-contract/) for required identity, lifecycle, and result evidence.
- See [ADR-032 in the repository](https://github.com/rian010194/cortxt/blob/main/docs/adr/032-mcp-mandate-envelope.md) for the mandate-envelope decision and its acceptance record.
