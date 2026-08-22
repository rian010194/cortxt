"""Deterministic widget-spec emitter standing in for an LLM (dogfood, issue #286).

The contract's core value is "prompt yourself tools": an LLM emits a small
inert widget spec, and the strict loader + renderer turn it into a served
view. This module is the deterministic, network-free stand-in for that LLM:
it emits contract-valid spec YAML for registered reads. Real LLM output can
be routed through the exact same `cortxt widget load` intake; nothing here
depends on the emitter being an LLM.

Emitters only produce text; they never execute reads, render, or mutate
state. Safety comes from the loader (closed schema, forbidden values,
capability allow-list) which runs before any I/O.
"""
from __future__ import annotations

import textwrap


def emit_all_open_issues_spec(repo: str, *, title: str = "All Open Issues",
                              version: str = "0.1") -> str:
    """Emit a spec that reads all open issues and renders them in a table.

    Uses only registered primitives (heading, metric, table), the registered
    `issues.all-open.list.v1` read (capability `read:issues`), typed JSON
    Pointer bindings, and declared capabilities. Valid under the strict
    loader; the document hash is canonical across emitter runs.
    """
    return textwrap.dedent(f'''\
        contract_version: "0.1"
        widget:
          id: all-open-issues
          version: "{version}"
          title: {title}
        data:
          reads:
            - id: issues
              source: github
              operation: issues.all_open.list.v1
              input:
                repo: {repo}
              select: []
              refresh:
                mode: manual
              output_type: issues.all-open.list.v1
              on_error: stale
        render:
          primitive: stack
          props: {{label: {title}}}
          children:
            - primitive: heading
              props: {{value: {title}}}
              bindings: {{}}
            - primitive: table
              props: {{label: Issues, columns: [number, title, workflow]}}
              bindings:
                rows: {{read: issues, pointer: /issues, type: core.array.v1}}
        actions: []
        capabilities: [read:issues]
    ''')


def emit_session_pulse_spec(*, title: str = "Pulse", version: str = "0.1") -> str:
    """Emit a spec that reads the store snapshot and shows orchestrator state.

    Uses the registered `sessions.snapshot.v2` read (capability
    `read:sessions`) and only registered primitives. Valid under the strict
    loader.
    """
    return textwrap.dedent(f'''\
        contract_version: "0.1"
        widget:
          id: pulse
          version: "{version}"
          title: {title}
        data:
          reads:
            - id: snapshot
              source: store
              operation: sessions.snapshot.v2
              input: {{}}
              select: []
              refresh:
                mode: poll
                interval_seconds: 5
              output_type: sessions.snapshot.v2
              on_error: stale
        render:
          primitive: stack
          props: {{label: {title}}}
          children:
            - primitive: heading
              props: {{value: {title}}}
              bindings: {{}}
            - primitive: key-value
              bindings:
                value: {{read: snapshot, pointer: /orchestrator, type: core.object.v1}}
        actions: []
        capabilities: [read:sessions]
    ''')


def emit_unsafe_spec() -> str:
    """Emit a deliberately unsafe spec that the loader must reject.

    Contains a forbidden value (a raw URL in a title) and an undeclared
    capability so the strict loader fails closed before any read or render.
    """
    return textwrap.dedent('''\
        contract_version: "0.1"
        widget:
          id: unsafe
          version: "0.1"
          title: "https://evil.example/payload"
        data:
          reads: []
        render:
          primitive: stack
          children: []
        actions: []
        capabilities: [read:issues]
    ''')


def emit_variants() -> dict[str, str]:
    """Return all emitter variants keyed by stable id (for the dogfood proof)."""
    return {
        "all-open-issues": emit_all_open_issues_spec("owner/repo"),
        "pulse": emit_session_pulse_spec(),
        "unsafe": emit_unsafe_spec(),
    }
