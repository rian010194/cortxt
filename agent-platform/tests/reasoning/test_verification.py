"""verify updates confidence: high contradiction lowers it, full coverage raises it."""

from reasoning.pipeline import _combine, _verified_confidence


def test_mismatch_lowers_verified_confidence():
    conf = _verified_confidence(6, 4, expected=99, geo_conf=0.0, recursive_conf=0.5)
    assert conf < 0.6  # expected mismatch dominates


def test_full_coverage_raises_verified_confidence():
    conf = _verified_confidence(6, 4, expected=10, geo_conf=1.0, recursive_conf=1.0)
    assert conf > 0.6
    assert conf <= 1.0


def test_combine_merges_scalars():
    assert _combine(6, 4) == 10
    assert _combine("a", "b") == ("a", "b")


def test_verified_confidence_without_expected_averages_phases():
    """No expected: confidence = 0.5 + 0.5*mean(recursive_conf, geo_conf)."""
    c = _verified_confidence(1, 1, expected=None, geo_conf=0.8, recursive_conf=0.6)
    assert c == 0.5 + 0.5 * ((0.6 + 0.8) / 2.0)
