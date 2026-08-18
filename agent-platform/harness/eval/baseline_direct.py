from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from harness.fixtures.coding_longcontext.generator import CodingFixture


class InferencePort(Protocol):
    def invoke(self, prompt: str) -> str: ...
    def cost_of(self, prompt: str) -> float: ...


@dataclass(frozen=True)
class BaselineResult:
    success: bool
    cost: float
    output: str


def _build_truncated_prompt(fixture: CodingFixture, max_context_chars: int) -> tuple[str, set[str]]:
    included_files: set[str] = set()
    parts = []
    budget = max_context_chars
    for path, content in fixture.repo_files.items():
        if budget <= 0:
            break
        chunk = content[:budget]
        parts.append(f"# {path}\n{chunk}")
        included_files.add(path)
        budget -= len(chunk)
    return "\n\n".join(parts), included_files


def run_baseline(fixture: CodingFixture, inference: InferencePort,
                  max_context_chars: int) -> BaselineResult:
    prompt, included_files = _build_truncated_prompt(fixture, max_context_chars)
    output = inference.invoke(prompt)
    # structural success check: the baseline can only have produced a
    # CORRECT patch if every file the fix requires READING was actually
    # included in its truncated context — required_read_files, not just
    # expected_patch_files.
    success = fixture.required_read_files.issubset(included_files)
    cost = inference.cost_of(prompt)
    return BaselineResult(success=success, cost=cost, output=output)
