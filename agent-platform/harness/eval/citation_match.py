"""citation-match-v1: structural verification for the research/document
long-context class (spec decision 5) — not model-based grading, per the
runtime-and-evaluation-harness doc's requirement to distinguish the two.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectedFact:
    fact: str
    required_locator: str


def citation_match_v1(answer: str, cited_locators: set[str],
                       expected_facts: list[ExpectedFact]) -> bool:
    for expected in expected_facts:
        if expected.fact not in answer:
            return False
        if expected.required_locator not in cited_locators:
            return False
    return True
