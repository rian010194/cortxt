"""Automated per-run gate (target: internal design archive, "Evidence Gate"). Replaces a
human's per-commit review with three checks: terminal status, presence of
real evidence, and artifact-scope match. A self-reported "succeeded" with no
evidence is a gate failure, not a pass (the #174/#175 false-completion
failure mode this exists to catch).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateOutcome:
    decision: str  # "proceed" | "pause" | "freeze"
    reason: str


def evaluate_gate(
    result_envelope: dict,
    *,
    checkpoint_required: bool,
    allowed_artifact_prefixes: tuple[str, ...] = (),
) -> GateOutcome:
    status = result_envelope.get("status")
    if status != "succeeded":
        return GateOutcome("freeze", f"terminal status was {status!r}, not 'succeeded'")

    evidence = result_envelope.get("evidence") or []
    if not evidence:
        return GateOutcome("freeze", "no evidence in result envelope (unverifiable completion)")

    if allowed_artifact_prefixes:
        artifacts = result_envelope.get("artifacts") or []
        for artifact in artifacts:
            if not artifact.startswith(allowed_artifact_prefixes):
                return GateOutcome("freeze", f"artifact outside allowed scope: {artifact}")

    if checkpoint_required:
        return GateOutcome("pause", "clean result, but this engine's checkpoint_required=True")
    return GateOutcome("proceed", "clean result, checkpoint not required")
