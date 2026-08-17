import pytest
from context_store.slicer import slice_for_children, SliceBudgetExhausted
from context_store.store import ContextReference


def test_splits_range_into_n_contiguous_non_overlapping_slices():
    ref = ContextReference(source="repo", locator="big.py", range=(0, 300),
                            data_class="internal")
    slices = slice_for_children(ref, 3)
    assert len(slices) == 3
    assert slices[0].range == (0, 100)
    assert slices[1].range == (100, 200)
    assert slices[2].range == (200, 300)
    for s in slices:
        assert s.locator == "big.py"
        assert s.data_class == "internal"


def test_raises_when_n_exceeds_range_granularity():
    ref = ContextReference(source="repo", locator="tiny.py", range=(0, 2),
                            data_class="internal")
    with pytest.raises(SliceBudgetExhausted):
        slice_for_children(ref, 5)


def test_n_must_be_positive():
    ref = ContextReference(source="repo", locator="x.py", range=(0, 100),
                            data_class="internal")
    with pytest.raises(ValueError):
        slice_for_children(ref, 0)
