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


# --- regression tests from Checkpoint 1.1 findings ---

def test_cyclic_list_does_not_hang_flatten():
    """P1 (Kimi fynd): _flatten/_flatten_scalars must not loop forever on a
    self-referencing list. Tests the flatten guards directly (the engine's
    decompose on cyclic content is out of scope for this DM1 slice)."""
    from reasoning.kernel.operators import _flatten
    from reasoning.kernel.engine import _flatten_scalars

    a = []
    a.append(a)   # cyclic self-reference
    a.append(1)   # a = [a, 1]
    assert _flatten(a) == [1]
    assert _flatten_scalars(a) == [1]


def test_geometric_requires_dict_content():
    """P2: geometric strategy on non-dict content fails in a controlled way."""
    from reasoning.kernel import new_problem
    from reasoning.kernel.engine import _solve_geometric
    state = new_problem([1, 2, 3])  # a flat list, not a dict
    try:
        _solve_geometric(state, expected=6)
    except TypeError:
        return
    raise AssertionError("expected TypeError for geometric with non-dict content")
