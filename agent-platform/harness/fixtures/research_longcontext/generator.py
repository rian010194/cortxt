from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from context_store.store import ContextReference
from harness.eval.citation_match import ExpectedFact


@dataclass(frozen=True)
class ResearchFixture:
    documents: dict[str, str]
    expected_facts: list[ExpectedFact]
    # no context_ref field — use materialize() below to write the documents to
    # disk and get a real ContextReference, symmetric with Task 10's
    # CodingFixture.materialize().


def generate_research_variant(seed: int) -> ResearchFixture:
    rng = random.Random(seed)
    deadline_day = rng.randint(1, 28)
    key_doc = f"doc-{rng.randint(2, 4)}.txt"

    documents = {
        "doc-1.txt": "This regulation covers general scope and definitions. "
                     "See doc-2.txt for specific compliance dates.",
        "doc-2.txt": f"Compliance deadline: article X requires action by day {deadline_day} "
                     "of the applicable quarter." if key_doc == "doc-2.txt" else
                     "This section covers exemptions and does not set any deadline.",
        "doc-3.txt": f"Compliance deadline: article X requires action by day {deadline_day} "
                     "of the applicable quarter." if key_doc == "doc-3.txt" else
                     "This section covers appeals procedure, unrelated to deadlines.",
        "doc-4.txt": f"Compliance deadline: article X requires action by day {deadline_day} "
                     "of the applicable quarter." if key_doc == "doc-4.txt" else
                     "This section lists definitions only, no dates.",
    }
    expected_facts = [ExpectedFact(fact=f"day {deadline_day}", required_locator=key_doc)]
    return ResearchFixture(documents=documents, expected_facts=expected_facts)


def materialize(fixture: ResearchFixture, dest_dir: Path) -> ContextReference:
    """Writes fixture.documents to real files under dest_dir AND a single
    concatenated _combined.txt so RLM's structural range-slicing has one
    real, readable locator — symmetric with Task 10's CodingFixture.materialize()."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    combined_parts = []
    for name, content in fixture.documents.items():
        (dest_dir / name).write_text(content, encoding="utf-8")
        combined_parts.append(content)
    combined_text = "".join(combined_parts)
    combined_path = dest_dir / "_combined.txt"
    combined_path.write_text(combined_text, encoding="utf-8")
    return ContextReference(source="document_set", locator=str(combined_path),
                             range=(0, len(combined_text)), data_class="internal")
