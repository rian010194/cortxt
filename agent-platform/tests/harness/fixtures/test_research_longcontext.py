# agent-platform/tests/harness/fixtures/test_research_longcontext.py
from harness.fixtures.research_longcontext.generator import generate_research_variant


def test_three_seeds_produce_three_distinct_variants():
    v1 = generate_research_variant(seed=1)
    v2 = generate_research_variant(seed=2)
    assert v1.documents != v2.documents
    assert len(v1.expected_facts) >= 1


def test_expected_fact_locator_points_to_a_real_document():
    v = generate_research_variant(seed=5)
    for fact in v.expected_facts:
        assert fact.required_locator in v.documents


def test_materialize_writes_a_real_readable_combined_file(tmp_path):
    from harness.fixtures.research_longcontext.generator import materialize

    fixture = generate_research_variant(seed=5)
    ref = materialize(fixture, tmp_path / "docs-1")
    content = open(ref.locator, encoding="utf-8").read()
    assert len(content) == ref.range[1]
    for name in fixture.documents:
        assert (tmp_path / "docs-1" / name).is_file()
