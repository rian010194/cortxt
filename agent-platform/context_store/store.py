"""ContextReference: a structural pointer into a large external context.

Never embeds the referenced content — RLM nodes read the source via this
reference at leaf-evaluation time (Task 6). data_class is copied from the
source's existing per-node/relation metadata (§9.3) and must accompany the
reference through every subsequent Tool Gateway admission check (§11.4).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextReference:
    source: str        # "repo" | "document_set"
    locator: str        # file path, or document id
    range: tuple[int, int]   # (start_line, end_line) or (start_offset, end_offset)
    data_class: str

    def __post_init__(self) -> None:
        start, end = self.range
        if start < 0 or end < 0:
            raise ValueError(f"range must be non-negative, got {self.range}")
        if start > end:
            raise ValueError(f"range start must be <= end, got {self.range}")

    def child_ref(self, new_range: tuple[int, int]) -> "ContextReference":
        return ContextReference(source=self.source, locator=self.locator,
                                 range=new_range, data_class=self.data_class)
