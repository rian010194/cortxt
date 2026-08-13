"""Engine fixture tests — three strategy variants of the same "compute total" problem.

Requirement (DM1 AC): 0 model calls, deterministic, each fixture forces the
intended strategy.
"""

from reasoning.kernel import Engine, Strategy

# Flat, no constraints -> direct
FLAT = [1, 2, 3, 4, 5]

# Nested (list-in-list) -> recursive
NESTED = [[1, 2], [3, [4, 5]]]

# Flat values but with explicit constraint-dependencies -> geometric
CONSTRAINED = {"values": [1, 2, 3, 4, 5], "constraints": ["all positive", "sequential"]}


def test_direct_flat_sums_and_chooses_direct():
    eng = Engine(expected=15)
    r = eng.solve(FLAT)
    assert r["value"] == 15
    assert r["strategy"] == Strategy.DIRECT.value
    assert r["confidence"] == 1.0
    assert "verify" in " ".join(r["steps"])


def test_recursive_nested_sums_and_chooses_recursive():
    eng = Engine(expected=15)
    r = eng.solve(NESTED)
    assert r["value"] == 15
    assert r["strategy"] == Strategy.RECURSIVE.value
    assert r["confidence"] == 1.0
    joined = " ".join(r["steps"])
    assert "decompose" in joined and "integrate" in joined


def test_geometric_constrained_sums_and_chooses_geometric():
    eng = Engine(expected=15)
    r = eng.solve(CONSTRAINED)
    assert r["value"] == 15
    assert r["strategy"] == Strategy.GEOMETRIC.value
    assert r["confidence"] == 1.0


def test_wrong_expected_lowers_confidence():
    eng = Engine(expected=999)
    r = eng.solve(FLAT)
    assert r["value"] == 15
    assert r["confidence"] == 0.0  # expected mismatch -> verify fails
