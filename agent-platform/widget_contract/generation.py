"""Prompt -> candidate widget spec -> strict-validated outcome.

The only place prompt-to-spec logic runs (design spec SS1). Every candidate
spec goes through the exact same `load_widget` strict loader used for
hand-authored and package-installed specs -- no parallel validation path.
Nothing here writes a spec to disk or installs it; callers (CLI commands)
own the explicit-confirmation step (ADR-038 SS6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .llm_client import LLMCallError, generate_text
from .loader import ContractError, load_widget
from .scaffold import find_missing_operations, write_operation_scaffold

_SYSTEM_PROMPT = (
    "You emit ONLY a widget spec YAML document per the Cortxt widget "
    "contract (contract_version, widget, data, render, actions, "
    "capabilities). No prose, no markdown fences, no explanation -- just "
    "the YAML document."
)


@dataclass(frozen=True)
class GenerationOutcome:
    status: str  # "ok" | "missing_operation" | "invalid"
    spec_text: str | None = None
    widget_id: str | None = None
    widget_version: str | None = None
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    document_hash: str | None = None
    missing_operations: tuple[str, ...] = field(default_factory=tuple)
    scaffold_paths: tuple[str, ...] = field(default_factory=tuple)
    error_message: str | None = None


def _build_prompt(prompt: str, existing_spec: str | None) -> str:
    if existing_spec:
        return (
            f"Here is the existing widget spec:\n\n{existing_spec}\n\n"
            f"Apply this edit and re-emit the complete updated spec:\n\n{prompt}"
        )
    return f"Emit a widget spec for: {prompt}"


def generate_widget_spec(
    prompt: str,
    *,
    existing_spec: str | None = None,
    scaffold_dir: Path | None = None,
) -> GenerationOutcome:
    try:
        candidate = generate_text(_build_prompt(prompt, existing_spec), system=_SYSTEM_PROMPT)
    except LLMCallError as exc:
        return GenerationOutcome(status="invalid", error_message=str(exc))

    try:
        widget = load_widget(candidate)
        return GenerationOutcome(
            status="ok",
            spec_text=candidate,
            widget_id=widget.id,
            widget_version=widget.version,
            capabilities=widget.capabilities,
            document_hash=widget.document_hash,
        )
    except ContractError as exc:
        raw = _lenient_parse(candidate)
        missing = tuple(find_missing_operations(raw)) if raw is not None else ()
        if missing:
            out_dir = scaffold_dir or Path.cwd()
            paths = tuple(str(write_operation_scaffold(op, out_dir)) for op in missing)
            return GenerationOutcome(
                status="missing_operation",
                spec_text=candidate,
                missing_operations=missing,
                scaffold_paths=paths,
            )
        return GenerationOutcome(status="invalid", spec_text=candidate, error_message=str(exc))


def _lenient_parse(text: str) -> dict | None:
    """Best-effort diagnostic parse only -- never used to decide validity.

    load_widget() (via loader._parse) remains the sole authority on whether
    a spec is valid; this just helps classify *why* it failed.
    """
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return doc if isinstance(doc, dict) else None
