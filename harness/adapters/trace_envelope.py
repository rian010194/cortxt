"""Minimal trace envelope for cross-profile observability.

Every profile (Hermes, Pi, Codex) appends one line to .trace/runs.jsonl per phase transition.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Profile(str, Enum):
    COORDINATOR = "coordinator"
    RESEARCHER = "researcher"
    BUILDER = "builder"
    CODEX = "codex"
    PI = "pi"


class PhaseStatus(str, Enum):
    START = "start"
    SUCCESS = "success"
    FAIL = "fail"
    RETRY = "retry"


class TraceEnvelope(BaseModel):
    """One line in the trace log. Append-only, JSONL."""
    ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    run_id: str
    profile: Profile
    phase: str
    status: PhaseStatus
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    artifacts: list[str] = Field(default_factory=list)
    gates_passed: list[str] = Field(default_factory=list)
    error: Optional[str] = None

    def to_jsonl(self) -> str:
        return self.model_dump_json(exclude_none=True)


# --- Simple logger -----------------------------------------------------------

TRACE_DIR = Path(".trace")
TRACE_FILE = TRACE_DIR / "runs.jsonl"


def ensure_trace_dir() -> None:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)


def log_event(env: TraceEnvelope) -> None:
    """Append one envelope to the trace file."""
    ensure_trace_dir()
    with TRACE_FILE.open("a", encoding="utf-8") as f:
        f.write(env.to_jsonl() + "\n")


def log_phase_start(
    run_id: str,
    profile: Profile,
    phase: str,
    model: str = "",
) -> TraceEnvelope:
    env = TraceEnvelope(
        run_id=run_id,
        profile=profile,
        phase=phase,
        status=PhaseStatus.START,
        model=model,
    )
    log_event(env)
    return env


def log_phase_end(
    run_id: str,
    profile: Profile,
    phase: str,
    status: PhaseStatus,
    model: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    artifacts: list[str] | None = None,
    gates_passed: list[str] | None = None,
    error: str | None = None,
) -> TraceEnvelope:
    env = TraceEnvelope(
        run_id=run_id,
        profile=profile,
        phase=phase,
        status=status,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        artifacts=artifacts or [],
        gates_passed=gates_passed or [],
        error=error,
    )
    log_event(env)
    return env