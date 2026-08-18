# agent-platform/tests/harness/fixtures/test_coding_longcontext.py
from harness.fixtures.coding_longcontext.generator import generate_variant


def test_three_seeds_produce_three_distinct_variants():
    v1 = generate_variant(seed=1)
    v2 = generate_variant(seed=2)
    v3 = generate_variant(seed=3)
    assert v1.repo_files != v2.repo_files != v3.repo_files
    # the fix touches exactly ONE file (check.py) but is only DERIVABLE by
    # reading constants.py too (the correct THRESHOLD value lives there, not
    # in check.py) — so expected_patch_files is length 1 by design. The
    # long-context property is that constants.py must be READ, not that
    # multiple files must be PATCHED.
    for v in (v1, v2, v3):
        assert v.expected_patch_files == {"check.py"}
        assert "constants.py" in v.repo_files  # must be present to READ, even though not patched


def test_same_seed_is_deterministic():
    a = generate_variant(seed=42)
    b = generate_variant(seed=42)
    assert a.repo_files == b.repo_files
    assert a.expected_patch_files == b.expected_patch_files


def test_materialize_writes_a_real_readable_combined_file(tmp_path):
    from harness.fixtures.coding_longcontext.generator import materialize

    fixture = generate_variant(seed=1)
    ref = materialize(fixture, tmp_path / "repo-1")
    content = open(ref.locator, encoding="utf-8").read()
    assert len(content) == ref.range[1]
    assert (tmp_path / "repo-1" / "constants.py").is_file()
    assert (tmp_path / "repo-1" / "check.py").is_file()
