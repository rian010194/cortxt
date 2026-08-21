"""Cortxt-owned, format-neutral portability and state package (ADR-012 complement).

Cortxt owns the neutral contract; Hermes is an adapter/provider behind the port
(same pattern as adapters/inference in Phase 2A). The core depends only on the neutral
artifacts and never imports the Hermes runtime.
"""
