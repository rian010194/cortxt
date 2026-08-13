"""verify updates confidence: high contradiction lowers it, full coverage raises it."""

from reasoning.pipeline import _combine, _verified_confidence


def test_high_contradiction_lowers_verified_confidence():
    # geo_conf low AND expected mismatch -> clearly low confidence
    conf = _verified_confidence(6, 4, expected=99, geo_conf=0.0)
    assert conf == 0.0
    assert conf < 0.6


def test_full_coverage_raises_verified_confidence():
    conf = _verified_confidence(6, 4, expected=10, geo_conf=1.0)
    assert conf > 0.6
    assert conf <= 1.0


def test_combine_merges_scalars():
    assert _combine(6, 4) == 10
    assert _combine("a", "b") == ("a", "b")


def test_verified_confidence_without_expected_uses_geo():
    c = _verified_confidence(1, 1, expected=None, geo_conf=0.8)
    assert c == 0.9  # 0.5 + 0.4 = 0.9 (0.5 + 0.5*geo_conf)
