from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from context_store.store import ContextReference


@dataclass(frozen=True)
class CodingFixture:
    repo_files: dict[str, str]
    expected_patch_files: set[str]
    required_read_files: set[str]  # must be READ for a correct fix, even if
    # not itself patched — constants.py holds the correct THRESHOLD value
    # check.py's fix needs, so a baseline that never reads it cannot produce
    # a correct patch even if check.py itself is in its truncated context
    # NOTE: no context_ref field here — a ContextReference pointing at a real,
    # readable file only exists once materialize() (below) has actually
    # written the fixture to disk; generate_variant() itself stays a pure,
    # no-I/O function so its own tests need no filesystem.


def generate_variant(seed: int) -> CodingFixture:
    rng = random.Random(seed)
    correct_value = rng.randint(100, 999)
    decoy_values = [rng.randint(1, 99) for _ in range(3)]

    constants_py = f"THRESHOLD = {correct_value}\n"
    # the bug: check.py uses a hardcoded decoy instead of importing THRESHOLD
    check_py = (
        f"DECOY_THRESHOLD = {decoy_values[0]}\n\n"
        "def is_over_threshold(value):\n"
        "    return value > DECOY_THRESHOLD  # BUG: should use constants.THRESHOLD\n"
    )
    test_check_py = (
        "from check import is_over_threshold\n"
        f"from constants import THRESHOLD\n\n"
        "def test_is_over_threshold_uses_shared_constant():\n"
        f"    assert is_over_threshold(THRESHOLD + 1) is True\n"
        f"    assert is_over_threshold(THRESHOLD - 1) is False\n"
    )
    decoy_files = {
        f"decoys/module_{i}.py": f"NOISE_{i} = {v}\n"
        for i, v in enumerate(decoy_values[1:], start=1)
    }

    repo_files = {
        "constants.py": constants_py,
        "check.py": check_py,
        "test_check.py": test_check_py,
        **decoy_files,
    }
    return CodingFixture(repo_files=repo_files,
                          expected_patch_files={"check.py"},
                          required_read_files={"check.py", "constants.py"})


def materialize(fixture: CodingFixture, dest_dir: Path) -> ContextReference:
    """Writes fixture.repo_files to real files under dest_dir AND a single
    concatenated _combined.txt (same file order as repo_files' insertion
    order) so RLM's structural range-slicing (Coordinator.run_node,
    _read_context_content) has one real, readable locator to operate on.

    Individual repo_files are ALSO written as real files (not just the
    combined blob) so a future Coding-vertical-specific tool wiring
    (patch/test, out of scope for this task) can address them individually;
    RLM's generic slicing in this plan only ever reads the combined blob.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    combined_parts = []
    for path, content in fixture.repo_files.items():
        file_path = dest_dir / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        combined_parts.append(content)
    combined_text = "".join(combined_parts)
    combined_path = dest_dir / "_combined.txt"
    combined_path.write_text(combined_text, encoding="utf-8")
    return ContextReference(source="repo", locator=str(combined_path),
                             range=(0, len(combined_text)), data_class="internal")
