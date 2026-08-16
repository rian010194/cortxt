from __future__ import annotations

from pathlib import Path

import yaml

VERTICAL = Path(__file__).resolve().parents[3] / "verticals" / "vertical-02-code-fixture"


def test_002_fixture_is_genuinely_broken_and_independent_of_001():
    fixture_dir = VERTICAL / "evals" / "synthetic" / "002-independent-strings"
    fixture = yaml.safe_load((fixture_dir / "fixture.yaml").read_text(encoding="utf-8"))
    assert fixture["declared_scope"] == ["strings_util.py"]

    source = (fixture_dir / "workspace" / "strings_util.py").read_text(encoding="utf-8")
    namespace: dict = {}
    exec(compile(source, "strings_util.py", "exec"), namespace)  # noqa: S102 - fixture is repo-owned
    assert namespace["last_word"]("the quick brown fox") != "fox"


def test_003_fixture_cannot_pass_without_the_ranges_handoff():
    """Proves the join is real: stats.py's own fix alone is not enough while
    ranges.py is still buggy (as shipped, matching 001's unfixed state)."""
    import sys
    from types import ModuleType

    fixture_dir = VERTICAL / "evals" / "synthetic" / "003-stats-depends-on-ranges"
    fixture = yaml.safe_load((fixture_dir / "fixture.yaml").read_text(encoding="utf-8"))
    assert fixture["declared_scope"] == ["stats.py"]

    # Execute ranges.py and add it to sys.modules so stats.py can import it
    namespace: dict = {"__name__": "ranges"}
    ranges_source = (fixture_dir / "workspace" / "ranges.py").read_text(encoding="utf-8")
    exec(compile(ranges_source, "ranges.py", "exec"), namespace)  # noqa: S102
    assert namespace["sum_to"](5) != 15, "ranges.py must ship broken, exactly like 001"

    # Add ranges module to sys.modules so stats.py can import from it
    ranges_module = ModuleType("ranges")
    ranges_module.__dict__.update(namespace)
    sys.modules["ranges"] = ranges_module

    try:
        stats_source = (fixture_dir / "workspace" / "stats.py").read_text(encoding="utf-8")
        stats_ns: dict = {}
        exec(compile(stats_source, "stats.py", "exec"), stats_ns)  # noqa: S102
        # Fixing only the n - 1 bug in stats.py, with ranges.py still broken, must
        # still fail -- this is the whole point of the dependency.
        def _average_to_if_stats_fixed(n):
            total = stats_ns["sum_to"](n)
            return total / n
        assert _average_to_if_stats_fixed(5) != 3.0
    finally:
        # Clean up sys.modules
        if "ranges" in sys.modules:
            del sys.modules["ranges"]
