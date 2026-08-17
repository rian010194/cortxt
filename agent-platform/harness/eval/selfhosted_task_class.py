"""Self-hosted L0 task-class eval harness (Fas 7, Beslut 4) -- deterministic part.

Runs a named L0 fixture through any ``TextInferencePort``-like object and
reports binary success (+ error on failure, cost routed by the port's own
BudgetGate). This reuses the pattern from Fas 5's N=3 baseline (binary success,
cost, N rounds) but is purpose-built for a short, bounded L0 classification /
extraction task over synthetic text -- not ``CodingFixture`` (long-context code
repos, wrong task class for a bounded L0 proof).

0 GPU / network calls here: the harness is built and tested against a fake
port. The real N=3 run against a deployed model is Fas B.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from adapters.inference.budget_gate import BudgetExhausted
from runtime.text_inference_port import TextInferenceError


@dataclass(frozen=True)
class TaskClassFixture:
    id: str
    prompt: str
    output_schema: dict
    expected_answer: str


@dataclass(frozen=True)
class TaskClassResult:
    fixture_id: str
    success: bool
    output: Any
    error: str | None


def run_task_class_eval(fixture: TaskClassFixture, port) -> TaskClassResult:
    """Invoke ``port`` on the fixture and decide binary success (fail-closed).

    Success iff ``port.invoke(...)`` returns a mapping whose ``"answer"`` equals
    the fixture's ``expected_answer``. Any ``TextInferenceError`` or
    ``BudgetExhausted`` propagates as a failure result with the error string --
    never an uncontrolled exception out of an eval run.
    """
    try:
        output = port.invoke(fixture.prompt, output_schema=fixture.output_schema)
        answer = output.get("answer") if isinstance(output, dict) else None
        return TaskClassResult(
            fixture_id=fixture.id,
            success=answer == fixture.expected_answer,
            output=output,
            error=None,
        )
    except (TextInferenceError, BudgetExhausted) as exc:
        return TaskClassResult(
            fixture_id=fixture.id, success=False, output=None, error=str(exc)
        )
