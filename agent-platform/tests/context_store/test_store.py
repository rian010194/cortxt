from context_store.store import ContextReference


def test_context_reference_carries_source_locator_range_dataclass():
    ref = ContextReference(source="repo", locator="src/app.py", range=(0, 200),
                            data_class="internal")
    assert ref.source == "repo"
    assert ref.locator == "src/app.py"
    assert ref.range == (0, 200)
    assert ref.data_class == "internal"


def test_child_ref_narrows_range_and_keeps_everything_else():
    ref = ContextReference(source="document_set", locator="doc-3.txt",
                            range=(0, 5000), data_class="confidential")
    child = ref.child_ref((100, 300))
    assert child.source == "document_set"
    assert child.locator == "doc-3.txt"
    assert child.range == (100, 300)
    assert child.data_class == "confidential"
    # original is unchanged (frozen dataclass discipline, matches ChildProcess/RLMConfig)
    assert ref.range == (0, 5000)


def test_range_must_be_ordered_and_nonnegative():
    import pytest
    with pytest.raises(ValueError):
        ContextReference(source="repo", locator="x.py", range=(50, 10), data_class="internal")
    with pytest.raises(ValueError):
        ContextReference(source="repo", locator="x.py", range=(-1, 10), data_class="internal")
